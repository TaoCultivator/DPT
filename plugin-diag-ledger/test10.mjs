import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import assert from 'node:assert/strict';import {Readable} from 'node:stream';
import {openDiagnosisDisposition,DIAGNOSIS_LEDGER} from './candidate-10/lib/scheduler-core.mjs';
import {apply} from './candidate-10/lib/index.js';
let passed=0,tests=[];const test=(n,f)=>{f();passed++;tests.push(n);console.log('通过：'+n)};
const failure={code:'UNKNOWN',target:'module-x',scope:'w',evidenceKey:'diag-e2e-1'};
// ---- 纯规则核心：诊断处置卡 ----
await test('诊断处置卡内置 decision-ledger 检索须知与授权兜底',()=>{
  const st={issues:[{id:'a',status:'blocked',priority:5,basePriority:5,blockedBy:[],title:'未知原因受阻',description:'原任务约束：不得改数值口径',lastFailure:failure}]};
  const r=openDiagnosisDisposition(st,'a');assert.equal(r.created,true);
  const d=st.issues.find(x=>x.id===r.id).description;
  for(const need of ['decision-ledger','E:\\Works\\DPT\\docs\\decision-ledger\\index.jsonl','ledger_search.py','PYTHONIOENCODING=utf-8','accepted / experience','rejected','proposed','USER_APPROVAL_REQUIRED','证据指纹：diag-e2e-1','module-x','原任务约束：不得改数值口径','看板自行解析'])assert(d.includes(need),'缺须知：'+need);
  assert.equal(DIAGNOSIS_LEDGER.index,'E:\\Works\\DPT\\docs\\decision-ledger\\index.jsonl');
});
await test('同一失败指纹只开一张卡并共享受影响任务',()=>{
  const st={issues:[{id:'a',status:'blocked',priority:9,basePriority:9,blockedBy:[],lastFailure:failure},{id:'b',status:'blocked',priority:5,basePriority:5,blockedBy:[],lastFailure:failure}]};
  const r1=openDiagnosisDisposition(st,'a');assert.equal(r1.created,true);
  const r2=openDiagnosisDisposition(st,'b');assert.equal(r2.created,false);assert.equal(r2.reused,true);assert.equal(r2.id,r1.id);assert.equal(r2.reason,'diagnosis-issue-exists');
  assert.equal(st.issues.filter(x=>x.diagnosisForFingerprint).length,1);
  assert.deepEqual(st.issues.find(x=>x.id==='a').blockedBy,[r1.id]);
  assert.deepEqual(st.issues.find(x=>x.id==='b').blockedBy,[r1.id]);
  const card=st.issues.find(x=>x.id===r1.id);assert.deepEqual(card.affectedIssues,['a','b']);assert.equal(card.scopeRevision,2);assert(card.description.includes('b'));
});
await test('诊断开卡同样受链深≤3与单根≤8限额约束',()=>{
  const many=Array.from({length:8},(_,n)=>({id:'r'+n,repairRoot:'root',status:'done',blockedBy:[]}));
  const full={issues:[{id:'root',status:'blocked',priority:5,basePriority:5,blockedBy:[],lastFailure:{...failure,evidenceKey:'e-full'}},...many]};
  const a=openDiagnosisDisposition(full,'root');assert.equal(a.created,false);assert.equal(a.reason,'diagnosis-budget-exhausted');assert.equal(full.issues.length,9);
  const deep={issues:[{id:'c',status:'blocked',priority:5,basePriority:5,blockedBy:[],repairDepth:3,repairRoot:'root',lastFailure:{...failure,evidenceKey:'e-deep'}}]};
  assert.equal(openDiagnosisDisposition(deep,'c').reason,'diagnosis-budget-exhausted');assert.equal(deep.issues.length,1);
  const okState={issues:[{id:'c2',status:'blocked',priority:5,basePriority:5,blockedBy:[],repairDepth:2,repairRoot:'root',lastFailure:{...failure,evidenceKey:'e-ok'}}]};
  const ok=openDiagnosisDisposition(okState,'c2');assert.equal(ok.created,true);
  const card=okState.issues.find(x=>x.id===ok.id);assert.equal(card.repairDepth,3);assert.equal(card.repairRoot,'root');assert.equal(card.status,'backlog');assert.equal(card.acceptanceRequired,true);assert.deepEqual(okState.issues[0].blockedBy,[card.id]);
});
// ---- 完整插件端到端：诊断类分流 → 自动开卡 → 按开关领取 → 未命中授权 ----
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-c10-'));const timers=[],intervals=[],calls=[],pending=[],errors=[];
const parent={id:'parent',session:{header:{cwd:root}}};const ws={id:'w',path:root,sessionIds:['parent'],title:'诊断自动立项'};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
let route,seq=0;
const ctx={fs:{resolve:async(p,o={})=>path.resolve(o.cwd??root,p),readText:async p=>fs.readFileSync(p,'utf8'),writeText:async(p,t)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,t)}},
 timer:{timeout:f=>{timers.push(f);return()=>{}},interval:f=>{intervals.push(f);return()=>{}}},tools:{register:()=>{}},webServer:{register:r=>route=r.handler},
 workspaceRegistry:{get:i=>i==='w'?ws:null},agents:{currentInitiator:()=>parent,get:i=>i==='parent'?parent:null,list:()=>[parent]},agentDefaultModel:{currentSelection:()=>null},llm:{},
 subagents:{start:async(_,spec)=>{calls.push(spec.label);const d=deferred();pending.push({label:spec.label,...d});return {id:'s'+(++seq),result:d.promise,dispose:async()=>{}}}},
 shell:{resolve:r=>r,execute:async()=>({result:async()=>({exitCode:1,stdout:{text:''},stderr:{text:''}})})},effect:(fn)=>{try{fn()}catch{}}};
const rpc=async(m,a={})=>{let response;const req=Readable.from([Buffer.from(JSON.stringify({method:'kanban.'+m,args:{workspaceId:'w',...a}}))]);req.method='POST';await route(req,{setHeader(){},writeHead(){},end:t=>response=JSON.parse(t)});return response};
const state=async()=>(await rpc('getState')).state;
const settle=()=>new Promise(r=>setImmediate(r));
const drain=async()=>{for(let n=0;n<40;n++){const queued=timers.splice(0,timers.length);if(!queued.length)return;for(const f of queued)await f();await settle()}};
const intervalPass=async()=>{for(const f of intervals)await f();await drain()};
const waitFor=async fn=>{for(let n=0;n<400;n++){if(await fn())return;await new Promise(r=>setTimeout(r,5))}throw new Error('等待超时')};
const oldErr=console.error;console.error=(...a)=>{errors.push(a.map(String).join(' '));oldErr(...a)};
try{
 apply(ctx);
 await rpc('setAutoExec',{patch:{enabled:true,promoteBacklog:false}});
 const id=(await rpc('createIssue',{title:'未知原因受阻任务',priority:7})).issueId;
 await rpc('moveIssue',{id,to:'todo'});await drain();await waitFor(()=>pending.length===1);
 pending.shift().resolve({structured:{status:'failed',failure:{...failure,message:'未知受控失败：请先查决策台账'}}});
 await waitFor(async()=>(await state()).issues.some(x=>x.diagnosisForFingerprint));
 const s1=await state();const card1=s1.issues.find(x=>x.diagnosisForFingerprint);const orig1=s1.issues.find(x=>x.id===id);
 await test('诊断类分流自动立项处置卡并挂住原任务',()=>{
  assert.equal(orig1.status,'blocked');assert.deepEqual(orig1.blockedBy,[card1.id]);
  assert.equal(card1.status,'backlog');assert.equal(card1.priority,7);
  assert(card1.id.startsWith('diagnose-'));assert.equal(card1.repairRoot,id);assert.equal(card1.diagnosisForFingerprint,orig1.failureControl.fingerprint);
  assert.equal(orig1.failureControl.action,'diagnose');
  assert(orig1.comments.some(c=>String(c.text).includes('诊断类失败已自动立项处置卡')));
 });
 await test('处置卡描述自带台账检索步骤与命中分流规则',()=>{
  const d=card1.description;
  for(const need of ['## 第一步：先查决策台账','decision-ledger','E:\\Works\\DPT\\docs\\decision-ledger\\index.jsonl','ledger_search.py','PYTHONIOENCODING=utf-8','accepted / experience','rejected','proposed','USER_APPROVAL_REQUIRED','未知受控失败：请先查决策台账','证据指纹：diag-e2e-1','module-x'])assert(d.includes(need),'卡里缺：'+need);
 });
 await rpc('setAutoExec',{patch:{enabled:true,promoteBacklog:true}});await drain();
 await waitFor(()=>pending.some(p=>p.label.includes('diagnose-')));
 const claimed=await state();
 await test('诊断处置卡按 promoteBacklog 开关正常领取',()=>{
  assert(pending.some(p=>p.label.includes('diagnose-')));
  assert(['todo','in_progress'].includes(claimed.issues.find(x=>x.diagnosisForFingerprint).status));
 });
 pending.find(p=>p.label.includes('diagnose-')).resolve({structured:{status:'failed',failure:{code:'USER_APPROVAL_REQUIRED',message:'台账未命中：查过「未知受控失败」「module-x」「diag-e2e-1」三组关键词，无相关条目',target:'decision-ledger',scope:'w',evidenceKey:'diag-miss-1'}}});
 await waitFor(async()=>{const c=(await state()).issues.find(x=>x.diagnosisForFingerprint);return c&&c.failureControl&&c.failureControl.action==='hold'});
 const s2=await state();const card2=s2.issues.find(x=>x.diagnosisForFingerprint);const orig2=s2.issues.find(x=>x.id===id);
 await test('台账未命中即转授权类失败挂起，不再自动重跑',()=>{
  assert.equal(card2.status,'blocked');assert.equal(card2.failureControl.action,'hold');assert.equal(card2.lastFailure.code,'USER_APPROVAL_REQUIRED');
  assert(card2.comments.some(c=>String(c.text).includes('台账未命中')));
  assert.equal(orig2.status,'blocked');assert.deepEqual(orig2.blockedBy,[card2.id]);
 });
 const id2=(await rpc('createIssue',{title:'同一指纹再来一次',priority:5})).issueId;
 await intervalPass();await intervalPass();
 await waitFor(()=>pending.some(p=>p.label.includes(id2)));
 pending.find(p=>p.label.includes(id2)).resolve({structured:{status:'failed',failure:{...failure,message:'未知受控失败：请先查决策台账'}}});
 await waitFor(async()=>((await state()).issues.find(x=>x.id===id2)??{}).status==='blocked');
 const s3=await state();
 await test('同一失败指纹不重复开卡，第二个任务挂到同一张卡',()=>{
  const cards=s3.issues.filter(x=>x.diagnosisForFingerprint);assert.equal(cards.length,1);assert.equal(s3.issues.length,3);
  assert.deepEqual(s3.issues.find(x=>x.id===id2).blockedBy,[cards[0].id]);
  assert(cards[0].affectedIssues.includes(id2));assert(cards[0].description.includes(id2));
 });
 await test('全程无宿主错误日志',()=>assert.deepEqual(errors,[]));
}finally{fs.rmSync(root,{recursive:true,force:true,maxRetries:5,retryDelay:100});console.error=oldErr}
fs.writeFileSync(new URL('./test10-results.json',import.meta.url),JSON.stringify({passed,tests,scope:'候选10：诊断类分流自动立项（纯规则核心 + 完整插件隔离RPC，零真实模型调用）'},null,2));
console.log('合计通过：'+passed);
