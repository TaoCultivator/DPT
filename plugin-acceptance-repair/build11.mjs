import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url)),snapDir=path.join(dir,'source-snapshot-11'),out=path.join(dir,'candidate-11');

/* 候选11：任何 ACCEPTANCE_* 失败码都归“修复”类。
   事故：k-mv8wjxd7-14 被独立验收打回，失败码 ACCEPTANCE_EVIDENCE_MISSING，
   原本 classif 只认写死的 ACCEPTANCE_CRITERIA_UNMET，于是掉进 UNKNOWN → “未知原因等人工诊断”。
   本次两处改动（不动 index.js 的验收回写兜底逻辑）：
   1) scheduler-core.mjs：新增 ACCEPTANCE_FAILURE_PATTERN / isAcceptanceFailureCode，classify 增加前缀分支（保留原数组）。
   2) host-adapter.mjs：normalizeFailure 的码白名单放行“白名单命中 或 ACCEPTANCE_* 前缀”，其余仍归一为 UNKNOWN。 */

fs.mkdirSync(path.join(out,'lib'),{recursive:true});
const names=['index.js','client.js','scheduler-core.mjs','host-adapter.mjs','failure-resolution.mjs','bounded-write.mjs','review-interruption.mjs','restart-recovery.mjs'];
const live=p=>path.join('C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/dsh-task-board/lib',p);
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
// 0) 基线核对：在线 8 个模块必须仍等于候选10的安装哈希；基线漂移就拒绝构建（本工作区出过构建把补丁覆盖回快照的事故）
const prev=JSON.parse(fs.readFileSync(path.join(dir,'deployment-manifest-10.json'),'utf8'));
for(const f of prev.files){const rel=f.relative.replace(/^lib\//,'');if(hash(live(rel))!==f.candidateSha256)throw new Error('在线基线已漂移，拒绝构建：'+f.relative)}
fs.mkdirSync(snapDir,{recursive:true});
for(const n of names){const bytes=fs.readFileSync(live(n)),prior=path.join(snapDir,'lib-'+n);
  if(fs.existsSync(prior)&&!fs.readFileSync(prior).equals(bytes))throw new Error('在线文件已变化，拒绝构建：'+n);
  if(!fs.existsSync(prior))fs.writeFileSync(prior,bytes);
  fs.copyFileSync(prior,path.join(out,'lib',n));}
const read=n=>fs.readFileSync(path.join(out,'lib',n),'utf8').replaceAll('\r\n','\n').replace(/\n+$/,'\n');
const write=(n,s)=>fs.writeFileSync(path.join(out,'lib',n),s);
function one(text,anchor,replacement,label){const n=text.split(anchor).length-1;if(n!==1)throw new Error('唯一锚点失败('+label+')='+n);return text.replace(anchor,replacement)}

// 1) scheduler-core.mjs：ACCEPTANCE_* 前缀判定（助手 + classify 分支），写死数组原样保留
let sc=read('scheduler-core.mjs');
sc=one(sc,
`// 仅信任机器代码/明确类别，不凭含糊文字猜测瞬时失败。
export function classify(f) {`,
`// 验收侧给出的失败码统一以 ACCEPTANCE_ 开头（如 ACCEPTANCE_CRITERIA_UNMET、ACCEPTANCE_EVIDENCE_MISSING）。
// 前缀判定只放行这一族的机器码，不做任何模糊文字猜测；非字符串一律不认。
export const ACCEPTANCE_FAILURE_PATTERN = /^ACCEPTANCE_[A-Z0-9_]+$/;
export function isAcceptanceFailureCode(code) {
  return typeof code === 'string' && ACCEPTANCE_FAILURE_PATTERN.test(code);
}
// 仅信任机器代码/明确类别，不凭含糊文字猜测瞬时失败。
export function classify(f) {`,'scheduler-core.helper');
sc=one(sc,
`  if (['TEST_REGRESSION', 'CODE_DEFECT', 'DELIVERABLE_MISSING', 'ENVIRONMENT_MISSING', 'PERMISSION_DENIED', 'ACCEPTANCE_CRITERIA_UNMET'].includes(f.code)) return 'repair';
  return 'unknown';
}`,
`  if (['TEST_REGRESSION', 'CODE_DEFECT', 'DELIVERABLE_MISSING', 'ENVIRONMENT_MISSING', 'PERMISSION_DENIED', 'ACCEPTANCE_CRITERIA_UNMET'].includes(f.code)) return 'repair';
  // 任何 ACCEPTANCE_* 前缀的验收失败码一律归修复类：验收侧换个同样合理的码名（如 ACCEPTANCE_EVIDENCE_MISSING）
  // 不得再退回“未知原因、等人工给诊断证据”。写死数组保留，前缀匹配只作补充判据。
  if (isAcceptanceFailureCode(f.code)) return 'repair';
  return 'unknown';
}`,'scheduler-core.classify');
write('scheduler-core.mjs',sc);

// 2) host-adapter.mjs：normalizeFailure 不再把 ACCEPTANCE_* 降级成 UNKNOWN
let ad=read('host-adapter.mjs');
ad=one(ad,
`  const code=supportedCodes.has(machine.code)?machine.code:'UNKNOWN';`,
`  // 白名单命中，或验收侧给出的 ACCEPTANCE_* 前缀码（与 scheduler-core.classify 的修复类判据同源）都保留原码；
  // 其余不明码仍是 UNKNOWN，不凭含糊文字把未知错误判成可自动处理的故障。
  const code=(supportedCodes.has(machine.code)||core.isAcceptanceFailureCode(machine.code))?machine.code:'UNKNOWN';`,'host-adapter.normalizeFailure');
write('host-adapter.mjs',ad);

const changed=names.filter(n=>hash(path.join(snapDir,'lib-'+n))!==hash(path.join(out,'lib',n)));
if(changed.sort().join(',')!=='host-adapter.mjs,scheduler-core.mjs')throw new Error('改动集合异常：'+changed.join('、'));
// 3) index.js 的验收回写兜底逻辑必须原样保留（仅在验收没给 structured.failure 时用 ACCEPTANCE_CRITERIA_UNMET）
const idx=read('index.js');
one(idx,`          const acceptFailure = (structured && structured.failure) || {
            code: 'ACCEPTANCE_CRITERIA_UNMET',`,'index.acceptanceFallback-keep');
fs.writeFileSync(path.join(dir,'patch-manifest-11.json'),JSON.stringify({purpose:'任何 ACCEPTANCE_* 失败码都归修复类（不再退回未知原因等人工诊断）',baseline:names.map(n=>({relative:'lib/'+n,originalSha256:hash(path.join(snapDir,'lib-'+n)),candidateSha256:hash(path.join(out,'lib',n))})),createdAt:new Date().toISOString()},null,2));
fs.writeFileSync(path.join(dir,'deployment-manifest-11.json'),JSON.stringify({files:names.map(n=>({relative:'lib/'+n,originalSha256:hash(live(n)),candidateSha256:hash(path.join(out,'lib',n))})),status:'候选11：ACCEPTANCE_* 前缀码一律归修复类'},null,2));
console.log('候选11已生成：ACCEPTANCE_* 一律归修复类（改动集合='+changed.join('、')+'）。');
