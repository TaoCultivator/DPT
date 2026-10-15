import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import assert from 'node:assert/strict';import {Readable} from 'node:stream';
import {classify,claim,routeFailure,ACCEPTANCE_FAILURE_PATTERN,isAcceptanceFailureCode} from './candidate-11/lib/scheduler-core.mjs';
import {createAdapter,normalizeFailure} from './candidate-11/lib/host-adapter.mjs';
import {apply} from './candidate-11/lib/index.js';
let passed=0,tests=[];function test(n,f){f();passed++;tests.push(n);console.log('通过：'+n)}
const running=(id,p=5)=>({id,status:'in_progress',priority:p,basePriority:p,blockedBy:[],title:'任务'+id,description:'原任务约束：不得改口径',run:{attemptId:'t',status:'running'}});
const failure=(code,extra={})=>({failure:{code,message:'验收缺证据：未附回归命令输出与哈希核对结果',target:'a',scope:'w',evidenceKey:'acc-ev-1',...extra}});

// ---- ① 任何 ACCEPTANCE_* 前缀码都归“修复”类 ----
test('任何 ACCEPTANCE_* 失败码都归修复类（不再退回未知原因）',()=>{
  for(const code of ['ACCEPTANCE_EVIDENCE_MISSING','ACCEPTANCE_CRITERIA_UNMET','ACCEPTANCE_EVIDENCE_MISSING_2','ACCEPTANCE_REPORT_MISSING','ACCEPTANCE_X9','ACCEPTANCE_'])
    assert.equal(classify({code}),code==='ACCEPTANCE_'?'unknown':'repair','分类错误：'+code);
  assert.equal(ACCEPTANCE_FAILURE_PATTERN.test('ACCEPTANCE_EVIDENCE_MISSING'),true);
  for(const bad of ['acceptance_evidence_missing','X_ACCEPTANCE_EVIDENCE_MISSING','ACCEPTANCE-1','ACCEPTANCE_证据缺失','ACCEPTANCE','ACCEPTANCE_x','',undefined,null,42,{}])
    assert.equal(isAcceptanceFailureCode(bad),false,'不得误判：'+JSON.stringify(bad));
});
test('ACCEPTANCE_EVIDENCE_MISSING 走 repair：自动建修复前置、原任务挂 blockedBy、描述含验收原文',()=>{
  const f=normalizeFailure(failure('ACCEPTANCE_EVIDENCE_MISSING'));
  assert.equal(f.code,'ACCEPTANCE_EVIDENCE_MISSING');
  assert.equal(f.rawEvidence.code,'ACCEPTANCE_EVIDENCE_MISSING');
  const r=routeFailure({issues:[running('a',7)]},'a','t',f);
  assert.equal(r.action,'awaiting-repair');
  assert.equal(!r.state.issues.some(x=>x.diagnosisForFingerprint),true,'不得开诊断卡');
  const rep=r.state.issues.find(x=>x.repairForFingerprint);
  assert(rep,'应生成修复前置');
  assert.equal(rep.id,'repair-'+r.state.issues[0].failureControl.fingerprint);
  assert.equal(rep.status,'backlog');assert.equal(rep.priority,7);assert.equal(rep.acceptanceRequired,true);
  assert.equal(rep.evidence.code,'ACCEPTANCE_EVIDENCE_MISSING');
  assert.equal(rep.title,'修复前置：ACCEPTANCE_EVIDENCE_MISSING / a');
  assert(rep.description.includes('验收缺证据：未附回归命令输出与哈希核对结果'));
  assert(rep.description.includes('原任务约束：不得改口径'));
  assert.equal(rep.description.includes('UNKNOWN'),false);
  const orig=r.state.issues.find(x=>x.id==='a');
  assert.deepEqual(orig.blockedBy,[rep.id]);assert.equal(orig.status,'blocked');
  assert.equal(orig.failureControl.category,'repair');assert.equal(orig.failureControl.action,'awaiting-repair');
});
// ---- ② ACCEPTANCE_CRITERIA_UNMET 行为不变 ----
test('ACCEPTANCE_CRITERIA_UNMET 行为不变',()=>{
  assert.equal(classify({code:'ACCEPTANCE_CRITERIA_UNMET'}),'repair');
  const f=normalizeFailure({failure:{code:'ACCEPTANCE_CRITERIA_UNMET',message:'三条判据未达成：pytest 仍 10 failed',target:'a',scope:'w',evidenceKey:'rep'}});
  assert.equal(f.code,'ACCEPTANCE_CRITERIA_UNMET');assert.equal(f.target,'a');assert.equal(f.scope,'w');
  assert.equal(f.message,'三条判据未达成：pytest 仍 10 failed');
  const r=routeFailure({issues:[running('a')]},'a','t',f);
  assert.equal(r.action,'awaiting-repair');
  const rep=r.state.issues.find(x=>x.repairForFingerprint);
  assert.equal(rep.title,'修复前置：ACCEPTANCE_CRITERIA_UNMET / a');
  assert(rep.description.includes('三条判据未达成：pytest 仍 10 failed'));
});
// ---- ③ 非 ACCEPTANCE_ 前缀未知码仍走 UNKNOWN/诊断 ----
test('非 ACCEPTANCE_ 前缀的未知码仍归一为 UNKNOWN 并走诊断',()=>{
  assert.equal(classify({code:'WIDGET_FLUX_9'}),'unknown');
  const f=normalizeFailure({failure:{code:'WIDGET_FLUX_9',message:'未知受控失败',target:'module-y',scope:'w',evidenceKey:'u-1'}});
  assert.equal(f.code,'UNKNOWN');assert.equal(f.rawEvidence.code,'WIDGET_FLUX_9');
  const r=routeFailure({issues:[running('a')]},'a','t',f);
  assert.equal(r.action,'diagnose');
  assert.equal(r.state.issues.some(x=>x.repairForFingerprint),false,'不得误开修复卡');
});
// ---- ④ 白名单原有码行为不变 ----
test('白名单原有码行为不变（TEST_REGRESSION / HTTP_429 / 无代码文本）',()=>{
  assert.equal(classify({code:'TEST_REGRESSION'}),'repair');
  assert.equal(classify({code:'PERMISSION_DENIED'}),'repair');
  assert.equal(normalizeFailure({failure:{code:'TEST_REGRESSION',message:'回归挂了',target:'t',scope:'w',evidenceKey:'r-1'}}).code,'TEST_REGRESSION');
  assert.equal(normalizeFailure({failure:{code:'RATE_LIMITED',message:'限流',target:'t',scope:'w',evidenceKey:'r-2'}}).code,'RATE_LIMITED');
  assert.equal(normalizeFailure({error:{code:'HTTP_429',message:'limited'}}).code,'HTTP_429');
  assert.equal(normalizeFailure({reason:'maybe rate limit'}).code,'UNKNOWN');
  assert.equal(normalizeFailure({failure:{code:'ACCEPTANCE_EVIDENCE_MISSING',message:'x'}}).evidenceKey!==undefined,true);
  const r=routeFailure({issues:[running('a')]},'a','t',normalizeFailure({failure:{code:'TEST_REGRESSION',message:'回归挂了',target:'t',scope:'w',evidenceKey:'r-3'}}));
  assert.equal(r.action,'awaiting-repair');
});
// ---- Host 适配层生产入口（review 打回）不得把验收码降级 ----
const fixture=(issues)=>{let state={version:1,issues,autoExec:{enabled:true},autoAccept:true};let chain=Promise.resolve(),n=0;
  const adapter=createAdapter({mutate:fn=>{const p=chain.then(()=>{const r=fn(state);state=r.state;return r});chain=p.catch(()=>{});return p},now:()=>1000000,token:()=>String(++n)});
  return {api:adapter,get:()=>structuredClone(state)}};
await (async()=>{
  const f=fixture([{id:'a',status:'todo',priority:5,basePriority:5,blockedBy:[]}]);
  const c=(await f.api.claimNext()).claim;
  await f.api.succeed('a',c.attemptId,'done');
  const review=(await f.api.claimReview('a')).claim;
  const out=await f.api.review('a',review.attemptId,review.executionAttemptId,{passed:false,report:'交付缺证据',failure:{code:'ACCEPTANCE_EVIDENCE_MISSING',message:'交付缺证据：未附哈希核对',target:'a',scope:'w',evidenceKey:'acc-adapter-1'}});
  test('Host 适配层验收打回保留 ACCEPTANCE_EVIDENCE_MISSING 并立修复前置',()=>{
    assert.equal(out.action,'awaiting-repair');
    const s=f.get();const orig=s.issues.find(x=>x.id==='a');const rep=s.issues.find(x=>x.repairForFingerprint);
    assert.equal(orig.lastFailure.code,'ACCEPTANCE_EVIDENCE_MISSING');
    assert.equal(orig.status,'blocked');assert.deepEqual(orig.blockedBy,[rep.id]);
    assert.equal(rep.evidence.code,'ACCEPTANCE_EVIDENCE_MISSING');
    assert.equal(s.issues.some(x=>x.diagnosisForFingerprint),false);
  });
})();
// ---- 完整插件端到端（隔离 RPC，零真实模型调用） ----
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-c11-'));const timers=[],intervals=[],calls=[],pending=[],errors=[];
let route,seq=0;
const parent={id:'parent',session:{header:{cwd:root}}};const ws={id:'w',path:root,sessionIds:['parent'],title:'验收失败码分流'};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const ctx={fs:{resolve:async(p,o={})=>path.resolve(o.cwd??root,p),readText:async p=>fs.readFileSync(p,'utf8'),writeText:async(p,t)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,t)}},
 timer:{timeout:f=>{timers.push(f);return()=>{}},interval:f=>{intervals.push(f);return()=>{}}},tools:{register:()=>{}},webServer:{register:r=>route=r.handler},
 workspaceRegistry:{get:i=>i==='w'?ws:null},agents:{currentInitiator:()=>parent,get:i=>i==='parent'?parent:null,list:()=>[parent]},agentDefaultModel:{currentSelection:()=>null},llm:{},
 subagents:{start:async(_,spec)=>{calls.push(spec.label);const d=deferred();pending.push({label:spec.label,...d});return {id:'s'+(++seq),result:d.promise,dispose:async()=>{}}}},
 shell:{resolve:r=>r,execute:async()=>({result:async()=>({exitCode:1,stdout:{text:''},stderr:{text:''}})})},effect:(fn)=>{try{fn()}catch{}}};
const rpc=async(m,a={})=>{let response;const req=Readable.from([Buffer.from(JSON.stringify({method:'kanban.'+m,args:{workspaceId:'w',...a}}))]);req.method='POST';await route(req,{setHeader(){},writeHead(){},end:t=>response=JSON.parse(t)});return response};
const state=async()=>(await rpc('getState')).state;
const settle=()=>new Promise(r=>setImmediate(r));
const drain=async()=>{for(let n=0;n<40;n++){const queued=timers.splice(0,timers.length);if(!queued.length)return;for(const f of queued)await f();await settle()}};
const waitFor=async fn=>{for(let n=0;n<400;n++){if(await fn())return;await new Promise(r=>setTimeout(r,5))}throw new Error('等待超时')};
const take=label=>{const p=pending.find(x=>x.label===label);assert(p,'缺少待派发的子代理：'+label);pending.splice(pending.indexOf(p),1);return p};
const oldErr=console.error;console.error=(...a)=>{errors.push(a.map(String).join(' '));oldErr(...a)};
try{
 apply(ctx);
 await rpc('setAutoAccept',{enabled:true});await rpc('setAutoExec',{patch:{enabled:true,promoteBacklog:false}});
 // A：验收自己给出 ACCEPTANCE_EVIDENCE_MISSING
 const idA=(await rpc('createIssue',{title:'验收缺证据的任务',priority:7})).issueId;
 await rpc('moveIssue',{id:idA,to:'todo'});await drain();await waitFor(()=>pending.some(p=>p.label==='executor-'+idA));
 take('executor-'+idA).resolve({structured:{status:'done',summary:'done'},stopReason:'completed'});
 await waitFor(async()=>((await state()).issues.find(x=>x.id===idA)||{}).status==='in_review');
 await drain();await waitFor(()=>pending.some(p=>p.label==='acceptance-'+idA));
 take('acceptance-'+idA).resolve({structured:{verdict:'fail',report:'## 结论：不通过。交付缺证据：未附回归命令输出与哈希核对结果。',
   failure:{code:'ACCEPTANCE_EVIDENCE_MISSING',message:'交付缺证据：未附回归命令输出与哈希核对结果',target:idA,scope:'w',evidenceKey:'acc-ev-e2e-1'}}});
 await waitFor(async()=>(await state()).issues.some(x=>x.repairForFingerprint));
 const s1=await state();const rep1=s1.issues.find(x=>x.repairForFingerprint);const orig1=s1.issues.find(x=>x.id===idA);
 test('端到端：验收打回 ACCEPTANCE_EVIDENCE_MISSING 自动开修复前置并挂住原任务',()=>{
   assert.equal(orig1.status,'blocked');assert.deepEqual(orig1.blockedBy,[rep1.id]);
   assert.equal(orig1.lastFailure.code,'ACCEPTANCE_EVIDENCE_MISSING');
   assert.equal(orig1.failureControl.category,'repair');assert.equal(orig1.failureControl.action,'awaiting-repair');
   assert.equal(rep1.status,'backlog');assert.equal(rep1.repairForFingerprint,orig1.failureControl.fingerprint);
   assert(rep1.id.startsWith('repair-'));
   assert.equal(s1.issues.some(x=>x.diagnosisForFingerprint),false,'不得退回未知原因等人工诊断');
   assert(orig1.comments.some(c=>String(c.text).includes('awaiting-repair')));
 });
 test('端到端：修复卡标题与描述保留验收原文与证据指纹，未被降级成 UNKNOWN',()=>{
   assert.equal(rep1.title,'修复前置：ACCEPTANCE_EVIDENCE_MISSING / '+idA);
   assert(rep1.description.includes('交付缺证据：未附回归命令输出与哈希核对结果'));
   assert(rep1.description.includes('失败代码：ACCEPTANCE_EVIDENCE_MISSING；目标：'+idA+'；作用域：w'));
   assert(rep1.description.includes('证据指纹：acc-ev-e2e-1'));
   assert.equal(rep1.description.includes('UNKNOWN'),false);
 });
 // B：验收没给 structured.failure —— 兜底码与兜底文案必须与改动前一致
 const idB=(await rpc('createIssue',{title:'验收没给结构化失败的任务',priority:5})).issueId;
 await rpc('moveIssue',{id:idB,to:'todo'});await drain();await waitFor(()=>pending.some(p=>p.label==='executor-'+idB));
 take('executor-'+idB).resolve({structured:{status:'done',summary:'done'},stopReason:'completed'});
 await waitFor(async()=>((await state()).issues.find(x=>x.id===idB)||{}).status==='in_review');
 await drain();await waitFor(()=>pending.some(p=>p.label==='acceptance-'+idB));
 take('acceptance-'+idB).resolve({structured:{verdict:'fail',report:'## 结论：不通过。判据未达成。'}});
 await waitFor(async()=>{const x=(await state()).issues.find(i=>i.id===idB);return x&&(x.blockedBy||[]).length>0});
 const s2=await state();const orig2=s2.issues.find(x=>x.id===idB);const rep2=s2.issues.find(x=>x.id===(orig2.blockedBy||[])[0]);
 test('端到端：验收未给 failure 时仍用兜底码 ACCEPTANCE_CRITERIA_UNMET（文案不变）',()=>{
   assert.equal(orig2.lastFailure.code,'ACCEPTANCE_CRITERIA_UNMET');
   assert.equal(orig2.failureControl.category,'repair');
   assert.equal(rep2.title,'修复前置：ACCEPTANCE_CRITERIA_UNMET / '+idB);
   assert(rep2.description.includes('不通过。判据未达成。'));
   assert.equal(orig2.status,'blocked');
 });
 // C：执行侧非 ACCEPTANCE_ 前缀未知码仍走诊断处置卡
 const idC=(await rpc('createIssue',{title:'未知原因受阻的任务',priority:5})).issueId;
 await rpc('moveIssue',{id:idC,to:'todo'});await drain();await waitFor(()=>pending.some(p=>p.label==='executor-'+idC));
 take('executor-'+idC).resolve({structured:{status:'failed',failure:{code:'WIDGET_FLUX_9',message:'未知受控失败：请先查决策台账',target:'module-y',scope:'w',evidenceKey:'u-e2e-1'}}});
 await waitFor(async()=>(await state()).issues.some(x=>x.diagnosisForFingerprint));
 const s3=await state();const orig3=s3.issues.find(x=>x.id===idC);const diag=s3.issues.find(x=>x.diagnosisForFingerprint);
 test('端到端：非 ACCEPTANCE_ 前缀未知码仍走诊断处置卡、不误开修复卡',()=>{
   assert.equal(orig3.lastFailure.code,'UNKNOWN');assert.equal(orig3.failureControl.category,'unknown');
   assert.equal(orig3.failureControl.action,'diagnose');
   assert(diag.id.startsWith('diagnose-'));assert.deepEqual(orig3.blockedBy,[diag.id]);
   assert.equal(s3.issues.some(x=>x.repairForFingerprint&&(x.affectedIssues||[]).includes(idC)),false,'未知码不得误开修复卡');
 });
 test('全程无宿主错误日志',()=>assert.deepEqual(errors,[]));
}finally{fs.rmSync(root,{recursive:true,force:true,maxRetries:5,retryDelay:100});console.error=oldErr}
fs.writeFileSync(new URL('./test11-results.json',import.meta.url),JSON.stringify({passed,tests,scope:'候选11：任何 ACCEPTANCE_* 失败码都归修复类（纯规则核心 + Host 适配层 + 完整插件隔离RPC，零真实模型调用）'},null,2));
console.log('合计通过：'+passed);
