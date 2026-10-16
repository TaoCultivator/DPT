import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url)),snapDir=path.join(dir,'source-snapshot-14'),out=path.join(dir,'candidate-14');

/* 候选14：授权类挂起在“用户已授权”后必须有解锁通道（k-mvae3o8m-29）。

   事故（2026-10-16，k-mv8yxm2n-15）：任务被授权类挂起（failureControl.action='hold'、
   category='authorization'）后，用户已经按要求完成了人工动作，但看板没有任何入口能把它放回队列：
     · moveIssue → todo：被 retryGuard 以“失败原因尚未解除，禁止原地重试”拦下；
     · kanban.resolveFailure（唯一正规恢复通道）：显式拒绝 category==='authorization'
       （“授权问题需专门的授权验证流程，诊断证据不等于授权”）—— 这条拒绝本身是对的；
     · 界面上的「解除阻塞」走的是同一个 moveIssue，同样被拒；
     · 超时/重启自动恢复不适用于 authorization 类。
   结果只能靠“取消 + 另立承接卡”绕过，属流程性损失。缺的不是“放宽诊断”，而是**“用户已授权”这条路径**。

   本候选新增（三处改动，不动验收回写兜底、不动用户开关）：
   1) failure-resolution.mjs：新增纯规则 grantAuthorization(state, id, input, now) —— 只处理
      「action==='hold' 且 category==='authorization'」的挂起；必须带与挂起对象一致的 failureToken；
      必须 confirmed===true 且写明人工动作；同一 failureToken 只放行一次（authorizationGrants 记账）。
   2) index.js：新增 RPC 方法 kanban.grantAuthorization，且**只有看板界面的人工点击能调**：
      来源凭证 CLIENT_ORIGIN 是插件内部的冻结对象，由本插件的 HTTP RPC 路由在
      「请求带 x-kanban-client: board 交互标记」时注入；agent 的动态工具调用形态是
      handlers[...](args) 单参数，拿不到凭证 → 一律拒绝。另有 issueView 暴露 authorizationGrants 供界面判断。
      resolveFailure / retryGuard 的既有拦截一条都不放宽。
   3) client.js：call() 每次 RPC 带交互标记；新增 AuthorizationGrantView（勾选“我已完成所需的人工动作/批准”
      + 授权说明 + 确认按钮）；详情页与「受阻」列表的「解除阻塞」按钮对 authorization 类改为调出该确认，
      不再复用 moveIssue。 */

const names=['index.js','client.js','scheduler-core.mjs','host-adapter.mjs','failure-resolution.mjs','bounded-write.mjs','review-interruption.mjs','restart-recovery.mjs'];
const live=p=>path.join('C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/dsh-task-board/lib',p);
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
// 0) 基线核对：在线 8 个模块必须仍等于候选13的安装哈希；基线漂移就拒绝构建（本工作区出过构建把补丁覆盖回快照的事故）
const prev=JSON.parse(fs.readFileSync(path.join(dir,'deployment-manifest-13.json'),'utf8'));
for(const f of prev.files){const rel=f.relative.replace(/^lib\//,'');if(hash(live(rel))!==f.candidateSha256)throw new Error('在线基线已漂移，拒绝构建：'+f.relative)}
// 命名先探路：候选14/快照14 要么不存在（首次构建），要么带本次构建的 .build14.json 标记（幂等重建）；
// 目录里出现别人的同名候选时直接拒绝，绝不覆盖。
const stampOut=path.join(out,'.build14.json'),stampSnap=path.join(snapDir,'.build14.json');
if(fs.existsSync(out)&&!fs.existsSync(stampOut))throw new Error('候选目录已被占用（非本次构建产物），拒绝覆盖：candidate-14');
if(fs.existsSync(snapDir)&&!fs.existsSync(stampSnap))throw new Error('快照目录已被占用（非本次构建产物），拒绝覆盖：source-snapshot-14');
fs.mkdirSync(path.join(out,'lib'),{recursive:true});
fs.mkdirSync(snapDir,{recursive:true});
// 快照一旦建立就不再改写：在线文件与快照不一致 = 基线漂移，必须停下来人工确认
for(const n of names){const bytes=fs.readFileSync(live(n)),prior=path.join(snapDir,'lib-'+n);
  if(fs.existsSync(prior)&&!fs.readFileSync(prior).equals(bytes))throw new Error('在线文件已变化，拒绝构建：'+n);
  if(!fs.existsSync(prior))fs.writeFileSync(prior,bytes);
  fs.copyFileSync(prior,path.join(out,'lib',n));}
const read=n=>fs.readFileSync(path.join(out,'lib',n),'utf8').replaceAll('\r\n','\n').replace(/\n+$/,'\n');
const write=(n,s)=>fs.writeFileSync(path.join(out,'lib',n),s);
function one(text,anchor,replacement,label){const n=text.split(anchor).length-1;if(n!==1)throw new Error('唯一锚点失败('+label+')='+n);return text.replace(anchor,replacement)}
// 按“行包含”定位，避免把带引号/反引号的大段代码原样抄进本脚本
function insertBefore(text,needle,block,label){const lines=text.split('\n');const hits=lines.map((l,i)=>l.includes(needle)?i:-1).filter(i=>i>=0);if(hits.length!==1)throw new Error('插入锚点不唯一('+label+')='+hits.length);const i=hits[0];return [...lines.slice(0,i),...block.split('\n'),...lines.slice(i)].join('\n')}
function insertAfter(text,needle,block,label){const lines=text.split('\n');const hits=lines.map((l,i)=>l.includes(needle)?i:-1).filter(i=>i>=0);if(hits.length!==1)throw new Error('插入锚点不唯一('+label+')='+hits.length);const i=hits[0];return [...lines.slice(0,i+1),...block.split('\n'),...lines.slice(i+1)].join('\n')}
// 同一段代码在文件里被复制过（如 Board 内的历史死代码）：用“窗口内的上下文”消歧后替换整行
function replaceLineInContext(text,needle,contextNeedle,windowLines,replacement,label){
  const lines=text.split('\n');
  const hits=lines.map((l,i)=>l.includes(needle)&&lines.slice(i,i+windowLines).some(x=>x.includes(contextNeedle))?i:-1).filter(i=>i>=0);
  if(hits.length!==1)throw new Error('上下文锚点不唯一('+label+')='+hits.length);
  return [...lines.slice(0,hits[0]),replacement,...lines.slice(hits[0]+1)].join('\n');
}
// 在锚点行之后找到第一条“仅含闭括号逗号”的行（= 该子元素的闭合行），把新行插到它后面（即同级兄弟）
function insertAfterClosingLine(text,anchorNeedle,contextNeedle,windowLines,replacement,label){
  const lines=text.split('\n');
  const hits=lines.map((l,i)=>l.includes(anchorNeedle)&&lines.slice(i,i+windowLines).some(x=>x.includes(contextNeedle))?i:-1).filter(i=>i>=0);
  if(hits.length!==1)throw new Error('上下文锚点不唯一('+label+')='+hits.length);
  let j=-1;for(let k=hits[0]+1;k<lines.length;k++){if(lines[k].trim()==='),'){j=k;break}}
  if(j<0)throw new Error('找不到闭合行('+label+')');
  return [...lines.slice(0,j+1),replacement,...lines.slice(j+1)].join('\n');
}

// ============ 1) failure-resolution.mjs：用户授权确认的纯规则 ============
let fr=read('failure-resolution.mjs');
fr=fr+`
// ---- 用户授权确认通道（k-mvae3o8m-29；纯规则、可单测）----
// 事故（2026-10-16，k-mv8yxm2n-15）：授权类挂起（action='hold'、category='authorization'）后，用户已经
// 完成所需的人工动作，但看板没有任何入口能把它放回队列 —— moveIssue→todo 被 retryGuard 拦下，
// 唯一正规恢复通道 resolveFailure 又显式拒绝授权类（“授权问题需专门的授权验证流程”）。这句拒绝是对的：
// 诊断证据不等于授权。缺的是“用户已授权”这条路径，本函数补的就是它：**只有用户点了确认才算授权**。
// 语义边界（不得放宽，也不得变成通用后门）：
//   · 只处理「action==='hold' 且 category==='authorization'」的挂起，诊断类/修复类/配置类一律不走；
//   · 必须携带与当前挂起对象一致的 failureToken（fingerprint ?? holdReason），否则拒绝过期授权；
//   · 必须 confirmed===true 且写明人工动作（note 至少 4 字），避免被程序化调用冒充人工确认；
//   · 同一 failureToken 只放行一次（authorizationGrants 记账）；再次受阻必须由用户重新授权。
export function grantAuthorization(state, id, input, now = Date.now()) {
  const out = structuredClone(state), i = out.issues.find(x => x.id === id);
  if (!i || i.archivedAt || i.status !== 'blocked') throw new Error('仅可处理当前受阻任务');
  if ((i.blockedBy ?? []).length) throw new Error('有修复前置，必须走前置验收闭环');
  const f = i.failureControl;
  if (!f || f.action !== 'hold') throw new Error('当前失败不是挂起状态，不需要授权解锁');
  if (f.category !== 'authorization') throw new Error('只有授权类挂起可以走用户授权确认通道');
  const failureToken = f.fingerprint ?? f.holdReason;
  if (!failureToken || input.failureToken !== failureToken) throw new Error('失败已变化或缺失，拒绝过期授权');
  if (input.confirmed !== true) throw new Error('必须由看板界面上的用户确认才算授权');
  const note = typeof input.note === 'string' ? input.note.trim() : '';
  if (note.length < 4) throw new Error('必须写明用户完成的人工动作或批准内容');
  const history = i.authorizationGrants ?? [];
  if (history.some(x => x.failureToken === failureToken)) throw new Error('同一失败已授权一次，禁止反复放行，再次受阻需新的授权');
  const evidenceKey = typeof input.evidenceKey === 'string' && input.evidenceKey.trim() ? input.evidenceKey.trim() : 'grant-' + failureToken;
  i.authorizationGrants = [...history, { failureToken, evidenceKey, note, at: new Date(now).toISOString(), by: 'user' }];
  invalidate(i); i.run = null; i.status = 'todo'; i.manualHold = false;
  i.enqueuedAt = new Date(now).toISOString();
  f.action = 'recovered'; delete f.nextRetryAt;
  return { state: out, released: id, failureToken };
}
`;
write('failure-resolution.mjs',fr);

// ============ 2) index.js：只给界面人工点击用的 RPC 通道 ============
let idx=read('index.js');
idx=one(idx,"import { resolveFailure } from './failure-resolution.mjs'","import { resolveFailure, grantAuthorization } from './failure-resolution.mjs'",'index.import');
idx=insertBefore(idx,'    const handlers = {',`    // ---- 客户端交互凭证（k-mvae3o8m-29）----
    // 只有本插件的 HTTP RPC 路由（下方 webServer.register）能在“请求带界面交互标记”时造出并注入它。
    // agent 的调用形态是动态工具 → handlers[...](args) 的单参数调用，拿不到这个凭证，
    // 所以 kanban.grantAuthorization（授权类唯一解锁通道）对 agent 一律拒绝：
    // 诊断证据、脚本、HTTP 直连都不能代替用户本人在界面上的确认。
    const CLIENT_ORIGIN = Object.freeze({ source: 'kanban-web-client', version: 1 })
    const CLIENT_HEADER = 'x-kanban-client'
    const CLIENT_HEADER_VALUE = 'board'
`,'index.clientOrigin');
idx=one(idx,'failureControl: i.failureControl || null, diagnosticRecoveryHistory: i.diagnosticRecoveryHistory || [],','failureControl: i.failureControl || null, diagnosticRecoveryHistory: i.diagnosticRecoveryHistory || [], authorizationGrants: i.authorizationGrants || [],','index.issueView');
idx=insertBefore(idx,"      'kanban.retryIssue': async (args) => {",`      // 用户授权确认（k-mvae3o8m-29）：授权类挂起唯一的解锁通道。
      // 语义固定：只有“看板界面上的人工点击”可以调用 —— 调用必须由 HTTP RPC 路由注入 CLIENT_ORIGIN 凭证。
      // agent 没有这个工具入口，直接调用也拿不到凭证；resolveFailure 仍拒绝授权类（诊断证据不等于授权）。
      'kanban.grantAuthorization': async (args, origin) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        if (origin !== CLIENT_ORIGIN) return { ok: false, message: '授权确认只能由看板界面的人工点击发起：agent 不得解锁授权类挂起' }
        const out = await mutate(store, (state) => {
          const cur = findIssue(state, args.id)
          if (!cur) return { ok: false, message: '议题不存在' }
          if (typeof args.version !== 'number' || cur.version !== args.version) return { ok: false, conflict: true, message: '请刷新失败记录后再确认授权' }
          try {
            const granted = grantAuthorization(state, args.id, args, Date.now())
            Object.assign(state, granted.state)
            const changed = findIssue(state, args.id)
            addComment(changed, 'user', '用户确认授权：' + String(args.note || '').trim() + '（授权指纹 ' + granted.failureToken + '，同一失败仅放行一次）')
            logActivity(changed, 'status', 'user', 'blocked', changed.status, { authorizationToken: granted.failureToken })
            return { commit: true, ok: true, released: granted.released, version: changed.version, message: '授权已确认，任务回到待执行队列（同一失败只放行一次）' }
          } catch (e) { return { ok: false, message: e.message } }
        })
        if (out.ok) scheduleBatch(store)
        return out
      },
`,'index.grantHandler');
idx=one(idx,'const out = await handler(payload.args)',`// 交互标记由本插件的前端 bundle（client.js 的 call()）在每次 RPC 上携带；没有它的调用不是看板界面
          // 发起的（例如 agent 直接打 HTTP 或进程内直调），授权类解锁必须依赖这个凭证。
          const fromBoardClient = !!(req && req.headers && req.headers[CLIENT_HEADER] === CLIENT_HEADER_VALUE)
          const out = await handler(payload.args, fromBoardClient ? CLIENT_ORIGIN : null)`,'index.rpcOrigin');
write('index.js',idx);

// ============ 3) client.js：界面入口（详情页 + 受阻列表） ============
let cl=read('client.js');
cl=one(cl,"headers: { 'Content-Type': 'application/json' },","headers: { 'Content-Type': 'application/json', 'X-Kanban-Client': 'board' },",'client.header');
cl=one(cl,"'.kb-other-item .act { display: flex; gap: 4px; margin-top: 6px; }',","'.kb-other-item .act { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }',",'client.css');
// 位置要求：必须落在 DiagnosticRecoveryView 与 DetailView 之间 —— 既有用例
// priority-components.test.mjs 按 `function DiagnosticRecoveryView(`→`function DetailView(` 切片再在 vm 里执行，
// DetailView 引用到的组件必须在这个切片内定义（放到切片外会让既有回归直接判负）。
cl=insertBefore(cl,'        function DetailView({ detail, state, issues, issueById, statusLabel, selWs, act, closeDetail, openDetail, addLabel, deleteLabel }) {',`		    // ---- 授权类挂起的用户确认通道（k-mvae3o8m-29）----
	    // 事故：授权类挂起（action='hold' + category='authorization'）此前没有任何解锁入口 ——
	    // moveIssue→todo 被 retryGuard 拦下、resolveFailure 又显式拒绝授权类，只能靠“取消 + 另立承接卡”绕过。
	    // 这里补的就是“用户本人在界面上点确认”这条路径：勾选 + 写明人工动作，才发 grantAuthorization。
	    const AUTH_NOTE_DEFAULT = '我已完成所需的人工动作/批准'
	    function AuthorizationGrantView({ detail, selWs, act }) {
	      const control = detail.failureControl
	      const token = control ? (control.fingerprint || control.holdReason || '') : ''
	      const isAuthHold = detail.status === 'blocked' && !(detail.blockedBy || []).length && !!control && control.action === 'hold' && control.category === 'authorization'
	      const [checked, setChecked] = React.useState(false)
	      const [note, setNote] = React.useState(AUTH_NOTE_DEFAULT)
	      const [message, setMessage] = React.useState('')
	      const [submitting, setSubmitting] = React.useState(false)
	      if (!isAuthHold) return null
	      const granted = (detail.authorizationGrants || []).some(g => g.failureToken === token)
	      const submit = async () => {
	        if (submitting || !checked || note.trim().length < 4) return
	        setSubmitting(true)
	        setMessage('正在记录授权…')
	        try {
	          const args = { workspaceId: selWs.id, id: detail.id, version: detail.version, failureToken: token, note: note.trim(), evidenceKey: 'ui-grant-' + Date.now().toString(36), confirmed: true }
	          let result
	          await act(async () => { result = await call('grantAuthorization', args); return result })
	          setMessage(result && result.ok ? '授权已确认，任务回到待执行队列（同一失败只放行一次）。' : ((result && result.message) || '提交未确认成功，请刷新核对。'))
	        } catch (error) {
	          setMessage('提交失败：' + String(error))
	        } finally {
	          setSubmitting(false)
	        }
	      }
	      return el('div', { className: 'kb-field', style: { flexBasis: '100%' } },
	        el('h4', null, '授权确认（仅本人可点）'),
	        granted ? el('p', null, '该失败已授权过一次；若再次因同一失败受阻，需要新的授权，不能重复放行。')
	          : el('p', null, '这条任务因授权问题挂起（需要人工动作或批准）。诊断证据不能代替授权，请完成所需动作后由本人在此确认。'),
	        granted ? null : el('div', null,
	          el('label', null, el('input', { type: 'checkbox', checked: checked, onChange: (e) => setChecked(e.target.checked) }), ' 我已完成所需的人工动作/批准'),
	          el('label', null, '授权说明'),
	          el('input', { value: note, onChange: (e) => setNote(e.target.value), placeholder: AUTH_NOTE_DEFAULT }),
	          el('button', { className: 'kb-btn', disabled: submitting || !checked || note.trim().length < 4, onClick: submit }, submitting ? '正在提交…' : '确认授权并放回队列'),
	        ),
	        message ? el('p', { role: 'status' }, message) : null,
	      )
	    }
`, 'client.grantView');
cl=one(cl,"el('p',null,canResolve?'提交新的可复核证据后，仅允许恢复一次。':'任务仍受阻，请先完成修复前置或取得所需授权。'),","el('p',null,canResolve?'提交新的可复核证据后，仅允许恢复一次。':(control.category==='authorization'?'这是授权类挂起：只能由本人在下方「授权确认」中确认后放回队列，诊断证据不能代替授权。':'任务仍受阻，请先完成修复前置或取得所需授权。')),",'client.diagHint');
cl=one(cl,'                    el(DiagnosticRecoveryView, { detail, selWs, act }),','                    el(DiagnosticRecoveryView, { detail, selWs, act }),\n                    el(AuthorizationGrantView, { detail, selWs, act }),','client.detailView');
cl=insertAfter(cl,'function OtherPanelView({ otherOpen, otherTab, setOtherTab, issues, openDetail, moveIssue, act, selWs }) {',`	      // 授权类挂起在「解除阻塞」上不能复用 moveIssue（必被 retryGuard 拦下），改为就地调出确认面板。
	      const [authFor, setAuthFor] = React.useState(null)
	      const isAuthHold = (i) => !!(i && i.status === 'blocked' && i.failureControl && i.failureControl.action === 'hold' && i.failureControl.category === 'authorization')`,'client.otherPanelState');
cl=replaceLineInContext(cl,"otherTab === 'blocked' ? el('button', { className: 'kb-mini ok', onClick: () => moveIssue(i.id, 'todo') }, '解除阻塞') : null,","openDetail(i.id)",12,"\t\t              otherTab === 'blocked' ? el('button', { className: 'kb-mini ok', onClick: () => { if (isAuthHold(i)) setAuthFor(authFor === i.id ? null : i.id); else moveIssue(i.id, 'todo') } }, isAuthHold(i) ? (authFor === i.id ? '收起授权确认' : '确认授权…') : '解除阻塞') : null,",'client.unblock');
cl=insertAfterClosingLine(cl,"el('button', { className: 'kb-mini', onClick: () => openDetail(i.id) }, '查看'),","openDetail(i.id)",12,"\t\t            (isAuthHold(i) && authFor === i.id) ? el(AuthorizationGrantView, { key: i.id + '-grant', detail: i, selWs, act }) : null,",'client.otherPanelGrant');
write('client.js',cl);

const changed=names.filter(n=>hash(path.join(snapDir,'lib-'+n))!==hash(path.join(out,'lib',n)));
if(changed.sort().join(',')!=='client.js,failure-resolution.mjs,index.js')throw new Error('改动集合异常：'+changed.join('、'));
fs.writeFileSync(path.join(dir,'patch-manifest-14.json'),JSON.stringify({purpose:'授权类挂起新增“用户授权确认”通道（grantAuthorization：界面人工点击专用 + 同一失败指纹只放行一次；详情页与受阻列表的解锁入口改为调出确认）',baseline:names.map(n=>({relative:'lib/'+n,originalSha256:hash(path.join(snapDir,'lib-'+n)),candidateSha256:hash(path.join(out,'lib',n))})),createdAt:new Date().toISOString()},null,2));
fs.writeFileSync(path.join(dir,'deployment-manifest-14.json'),JSON.stringify({files:names.map(n=>({relative:'lib/'+n,originalSha256:hash(live(n)),candidateSha256:hash(path.join(out,'lib',n))})),status:'候选14：授权类挂起在用户确认后可放回队列（agent 不得调用；同一 failureToken 只放行一次）'},null,2));
fs.writeFileSync(stampOut,JSON.stringify({candidate:'candidate-14',by:'build14.mjs',purpose:'授权类挂起必须有“用户已授权”这条解锁路径',createdAt:new Date().toISOString()},null,2));
fs.writeFileSync(stampSnap,JSON.stringify({snapshot:'source-snapshot-14',by:'build14.mjs',createdAt:new Date().toISOString()},null,2));
console.log('候选14已生成：用户授权确认通道 + 界面入口（改动集合='+changed.join('、')+'）。');
