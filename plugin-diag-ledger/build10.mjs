import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url)),snapDir=path.join(dir,'source-snapshot-10'),out=path.join(dir,'candidate-10');

/* 整段插入 scheduler-core.mjs 末尾；String.raw 保证 \n 与 Windows 路径转义原样落盘。 */
const DIAGNOSIS_BLOCK = String.raw`
/* ---------------- 看板诊断处置卡（用户 2026-10-15 规则：受阻先查台账，命中即处理） ----------------
   诊断类失败不再停在“受阻 + 等人给证据”：复用修复前置机制自动开一张阻塞处置卡
   —— blockedBy 挂住原任务、状态 backlog、按 promoteBacklog 开关正常领取、独立验收后由看板自动解锁。
   卡内内置执行须知：第一步先查 decision-ledger 台账，命中 accepted/experience 直接按结论实施，
   命中 rejected 写明规避条件，只有 proposed 或未命中才返回 USER_APPROVAL_REQUIRED 请用户授权。 */
export const DIAGNOSIS_LEDGER = Object.freeze({
  skill: 'decision-ledger',
  index: 'E:\\Works\\DPT\\docs\\decision-ledger\\index.jsonl',
  script: 'C:\\Users\\songzhenxi\\.dsh\\skills\\decision-ledger\\scripts\\ledger_search.py',
});

export function diagnosisDispositionDescription(issue, failure, options = {}) {
  const ledgerIndex = options.ledgerIndex ?? DIAGNOSIS_LEDGER.index;
  const ledgerScript = options.ledgerScript ?? DIAGNOSIS_LEDGER.script;
  const raw = failure.rawEvidence ? JSON.stringify(failure.rawEvidence) : (failure.message ?? '');
  return [
    '## 处置来源',
    '受阻任务：' + issue.id + '；' + (issue.title ?? ''),
    '失败代码：' + failure.code + '；目标：' + failure.target + '；作用域：' + failure.scope,
    '证据指纹：' + failure.evidenceKey,
    '涉及模块/文件：' + failure.target + '（照抄失败证据里的原始目标与作用域，不另行推断）',
    '原始失败说明：' + (failure.message ?? '请先核对原始失败证据，不凭标题猜原因'),
    '原始失败原文：' + raw,
    '## 第一步：先查决策台账（decision-ledger），不要先问用户',
    '用 decision-ledger 技能检索本项目历史决策，命中即处理：',
    '1. 台账索引：' + ledgerIndex,
    '2. 检索脚本：' + ledgerScript,
    '3. 调用检索脚本必须带 PYTHONIOENCODING=utf-8（否则中文输出乱码并可能报错），形如 ledger_search.py --index <索引> --query "<关键词>" --top 3。',
    '4. 检索锚点取本次失败原文、失败码与错误文本、涉及模块/文件/命令/指标；至少换 2-3 组关键词，不得只查一次就下结论。',
    '## 命中后按台账条目 status 分流',
    '- accepted / experience：结论已被验证过，直接按结论实施；完成后按 decision-ledger 的记录维护流程回写台账，不要只在评论里写。',
    '- rejected：该方案已被否决，不得重走；必须在交付说明里写明规避条件与重新考虑的边界。',
    '- proposed 或未命中任何条目：视同未命中，不得凭猜测实施；结束本次执行并返回 failure.code = USER_APPROVAL_REQUIRED，并附上「查过的关键词清单 + 未命中的事实」。',
    '## 执行边界',
    '- 不得改动用户手动设置的开关、权限、模型或既有验收口径；不得自行重启 DSH，不得对外发布或上传。',
    '- 台账命中也不能替代必须当次授权的红线：对外发布与上传、删除或覆盖数据、花钱、以及 DPT 参数数值口径的实质变更。',
    '## 验收要求',
    '- 交付必须给出：查台账用过的关键词与命中条目 id/路径、按结论实施的差异、验证命令与结果；未命中时必须给出 USER_APPROVAL_REQUIRED 的完整证据。',
    '- 依赖是否满足由看板自行解析，本卡不要执行任何看板依赖或解锁操作。',
    '## 原任务约束（仅供引用，不是要求重做原业务）',
    issue.description ?? '（原任务无说明，先按失败证据定位）',
  ].join('\n');
}

export function openDiagnosisDisposition(state, id, failure, options = {}) {
  const i = state.issues.find(x => x.id === id);
  if (!i) return { created: false, reused: false, id: null, reason: 'issue-missing' };
  const f = failure ?? i.lastFailure;
  if (!f || !f.code || !f.target || !f.scope || !f.evidenceKey) return { created: false, reused: false, id: null, reason: 'failure-incomplete' };
  const key = fingerprint(f);
  const now = options.now ?? Date.now();
  const opened = state.issues.find(x => x.diagnosisForFingerprint === key && !x.archivedAt && x.status !== 'canceled');
  if (opened) {
    // 同一失败指纹只开一张：受影响任务直接挂到既有卡上，不重复立项。
    if (!(i.blockedBy ?? []).includes(opened.id)) {
      opened.affectedIssues = [...new Set([...(opened.affectedIssues ?? []), i.id])];
      opened.affectedContexts = [...(opened.affectedContexts ?? []), { issueId: i.id, title: i.title ?? '', constraints: i.description ?? '', evidence: copy(f) }];
      opened.description = (opened.description ?? '') + '\n\n## 新增受影响任务约束引用：' + i.id + '\n' + (i.title ?? '') + '\n' + (i.description ?? '无额外约束') + '\n原始失败：' + (f.message ?? f.code);
      opened.version = (opened.version ?? 1) + 1;
      opened.updatedAt = new Date(now).toISOString();
      opened.scopeRevision = (opened.scopeRevision ?? 1) + 1;
      invalidate(opened);
      if (opened.run && opened.run.status !== 'failed') opened.run.status = 'interrupted';
    }
    i.blockedBy = [...new Set([...(i.blockedBy ?? []), opened.id])];
    i.status = 'blocked';
    return { created: false, reused: true, id: opened.id, reason: 'diagnosis-issue-exists' };
  }
  const cardId = 'diagnose-' + key;
  if (state.issues.some(x => x.id === cardId)) return { created: false, reused: false, id: cardId, reason: 'diagnosis-issue-closed' };
  const repairRoot = i.repairRoot ?? i.id;
  const repairDepth = (i.repairDepth ?? 0) + 1;
  const repairCount = state.issues.filter(x => x.repairRoot === repairRoot).length;
  if (repairDepth > POLICY.maxRepairDepth || repairCount >= POLICY.maxRepairsPerRoot)
    return { created: false, reused: false, id: null, reason: 'diagnosis-budget-exhausted' };
  const requested = priority(i.basePriority ?? i.priority);
  const card = { id: cardId, diagnosisForFingerprint: key, repairRoot, repairDepth,
    title: '诊断处置：' + f.code + ' / ' + f.target, priority: requested, basePriority: requested,
    status: 'backlog', blockedBy: [], affectedIssues: [i.id], createdAt: new Date(now).toISOString(),
    evidence: copy(f), acceptanceRequired: true, scopeRevision: 1,
    affectedContexts: [{ issueId: i.id, title: i.title ?? '', constraints: i.description ?? '', evidence: copy(f) }],
    description: diagnosisDispositionDescription(i, f, options),
    comments: [], activity: [], retries: 0, version: 1, updatedAt: new Date(now).toISOString() };
  state.issues.push(card);
  i.blockedBy = [...new Set([...(i.blockedBy ?? []), card.id])];
  i.status = 'blocked';
  return { created: true, reused: false, id: card.id, reason: null };
}
`;

fs.mkdirSync(path.join(out,'lib'),{recursive:true});
const names=['index.js','client.js','scheduler-core.mjs','host-adapter.mjs','failure-resolution.mjs','bounded-write.mjs','review-interruption.mjs','restart-recovery.mjs'];
const live=p=>path.join('C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/dsh-task-board/lib',p);
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
// 0) 基线核对：在线 8 个模块必须仍等于候选9的安装哈希；基线漂移就拒绝构建（本工作区出过构建把补丁覆盖回快照的事故）
const prev=JSON.parse(fs.readFileSync(path.join(dir,'deployment-manifest-9.json'),'utf8'));
for(const f of prev.files)if(hash(live(f.relative.replace('lib/','')))!==f.candidateSha256)throw new Error('在线基线已漂移，拒绝构建：'+f.relative);
fs.mkdirSync(snapDir,{recursive:true});
for(const n of names){const bytes=fs.readFileSync(live(n)),prior=path.join(snapDir,'lib-'+n);
  if(fs.existsSync(prior)&&!fs.readFileSync(prior).equals(bytes))throw new Error('在线文件已变化，拒绝构建：'+n);
  if(!fs.existsSync(prior))fs.writeFileSync(prior,bytes);
  fs.copyFileSync(prior,path.join(out,'lib',n));}
const read=n=>fs.readFileSync(path.join(out,'lib',n),'utf8').replaceAll('\r\n','\n');
const write=(n,s)=>fs.writeFileSync(path.join(out,'lib',n),s);
function one(text,anchor,replacement,label){const n=text.split(anchor).length-1;if(n!==1)throw new Error('唯一锚点失败('+label+')='+n);return text.replace(anchor,replacement)}

// 1) scheduler-core.mjs：新增诊断处置卡（复用修复前置机制）+ decision-ledger 执行须知
write('scheduler-core.mjs',read('scheduler-core.mjs').replace(/\n+$/,'\n')+DIAGNOSIS_BLOCK);

// 2) host-adapter.mjs：候选 Host 事务入口与生产入口保持一致（否则适配层会回落成“挂起等人”）
let ad=read('host-adapter.mjs');
ad=one(ad,
`    fail:(id,attemptId,result)=>commit(state=>{
      const r=core.routeFailure(state,id,attemptId,normalizeFailure(result),now());
      return {state:r.state,changed:r.applied,action:r.action};
    }),`,
`    fail:(id,attemptId,result)=>commit(state=>{
      const r=core.routeFailure(state,id,attemptId,normalizeFailure(result),now());
      if(!r.applied)return {state:r.state,changed:false,action:r.action};
      // 诊断类分流不再停在“受阻 + 等人给证据”：自动开一张阻塞处置卡（先查 decision-ledger 台账）。
      if(r.action==='diagnose'){const opened=core.openDiagnosisDisposition(r.state,id);return {state:r.state,changed:true,action:(opened.created||opened.reused)?r.action:'hold'}}
      return {state:r.state,changed:true,action:r.action};
    }),`,'host-adapter.fail');
write('host-adapter.mjs',ad);

// 3) failure-resolution.mjs：修复前置仍必须走验收闭环；自动开的诊断处置卡不阻止人工补充新证据后的一次恢复
let fr=read('failure-resolution.mjs');
fr=one(fr,
`  if((i.blockedBy??[]).length)throw new Error('有修复前置，必须走前置验收闭环');`,
`  // 修复前置必须走验收闭环；只有“全部依赖都是自动开的诊断处置卡”时才允许人工补充新证据后的一次恢复。
  const deps=(i.blockedBy??[]).map(did=>out.issues.find(x=>x.id===did));
  const diagnosisOnly=(i.blockedBy??[]).length>0&&deps.every(d=>d&&!d.archivedAt&&d.status!=='canceled'&&d.diagnosisForFingerprint&&!d.repairForFingerprint);
  if((i.blockedBy??[]).length&&!diagnosisOnly)throw new Error('有修复前置，必须走前置验收闭环');`,'failure-resolution.guard');
fr=one(fr,
`  invalidate(i);i.run=completedRun;i.status=resumeReview?'in_review':'todo';i.manualHold=false;f.action='recovered';delete f.nextRetryAt;`,
`  // 人工已提供新证据：诊断处置卡已无意义，解除依赖并作废，避免继续消耗算力。
  if(diagnosisOnly)for(const d of deps){d.status='canceled';d.canceledReason='人工已提供新证据并单次恢复：'+id;d.updatedAt=new Date(now).toISOString()}
  if(diagnosisOnly)i.blockedBy=[];
  invalidate(i);i.run=completedRun;i.status=resumeReview?'in_review':'todo';i.manualHold=false;f.action='recovered';delete f.nextRetryAt;`,'failure-resolution.release');
write('failure-resolution.mjs',fr);

// 4) index.js：失败分流应用处自动立项；待立项领取注释区分诊断处置卡
let s=read('index.js');
s=one(s,`import { migrate, effectivePriority, eligible, queue as schedulerQueue, routeFailure, releaseAfterRepair, hasCycle }  from './scheduler-core.mjs'`,
  `import { migrate, effectivePriority, eligible, queue as schedulerQueue, routeFailure, releaseAfterRepair, hasCycle, openDiagnosisDisposition }  from './scheduler-core.mjs'`,'index.import');
s=one(s,
`      addComment(cur, 'system', '失败分流: ' + routed.action + '；' + (cur.lastFailure.message || '原因待诊断'))
      logActivity(cur, 'status', 'system', 'in_progress', cur.status)
      return { commit: true, action: routed.action }`,
`      addComment(cur, 'system', '失败分流: ' + routed.action + '；' + (cur.lastFailure.message || '原因待诊断'))
      logActivity(cur, 'status', 'system', 'in_progress', cur.status)
      // 用户 2026-10-15 规则：诊断类不再停在“受阻 + 等人给证据”，自动开一张阻塞处置卡；
      // 卡里已内置执行须知：先查 decision-ledger，命中即处理，未命中才返回 USER_APPROVAL_REQUIRED 请用户授权。
      if (routed.action === 'diagnose') {
        const opened = openDiagnosisDisposition(state, id)
        if (opened.created) addComment(cur, 'system', '诊断类失败已自动立项处置卡：' + opened.id + '（先查决策台账，命中即处理，未命中才请用户授权）')
        else if (opened.reused) addComment(cur, 'system', '同一失败指纹已有诊断处置卡，直接挂载：' + opened.id)
        else {
          cur.failureControl = { ...(cur.failureControl || {}), action: 'hold', holdReason: opened.reason || 'diagnosis-issue-unavailable' }
          addComment(cur, 'system', '诊断处置卡未自动立项（' + (opened.reason || 'unknown') + '），本轮不再重复开卡，等待人工授权')
        }
      }
      return { commit: true, action: routed.action }`,'index.applyRoutedFailure');
s=one(s,
`          addComment(i, 'system', i.repairForFingerprint ? '自动领取：修复前置转入等待认领' : '自动领取：待立项已按开关转入等待认领')`,
`          addComment(i, 'system', i.repairForFingerprint ? '自动领取：修复前置转入等待认领' : (i.diagnosisForFingerprint ? '自动领取：诊断处置卡转入等待认领（先查决策台账，命中即处理）' : '自动领取：待立项已按开关转入等待认领'))`,'index.promoteComment');
s=one(s,
`        lastFailure: i.lastFailure || null, acceptedAt: i.acceptedAt || null, repairForFingerprint: i.repairForFingerprint || null, repairRoot: i.repairRoot || null, affectedIssues: i.affectedIssues || [],`,
`        lastFailure: i.lastFailure || null, acceptedAt: i.acceptedAt || null, repairForFingerprint: i.repairForFingerprint || null, diagnosisForFingerprint: i.diagnosisForFingerprint || null, repairRoot: i.repairRoot || null, affectedIssues: i.affectedIssues || [],`,'index.issueView');
write('index.js',s);

const changed=names.filter(n=>hash(path.join(snapDir,'lib-'+n))!==hash(path.join(out,'lib',n)));
if(changed.sort().join(',')!=='failure-resolution.mjs,host-adapter.mjs,index.js,scheduler-core.mjs')throw new Error('改动集合异常：'+changed.join('、'));
fs.writeFileSync(path.join(dir,'patch-manifest-10.json'),JSON.stringify({purpose:'诊断类分流改为自动立项：先查 decision-ledger，命中即处理，未命中才请用户授权',baseline:names.map(n=>({relative:'lib/'+n,originalSha256:hash(path.join(snapDir,'lib-'+n)),candidateSha256:hash(path.join(out,'lib',n))})),createdAt:new Date().toISOString()},null,2));
fs.writeFileSync(path.join(dir,'deployment-manifest-10.json'),JSON.stringify({files:names.map(n=>({relative:'lib/'+n,originalSha256:hash(live(n)),candidateSha256:hash(path.join(out,'lib',n))})),status:'候选10：诊断类分流自动立项（decision-ledger 优先）'},null,2));
console.log('候选10已生成：诊断类分流→自动开卡（改动集合='+changed.join('、')+'）。');
