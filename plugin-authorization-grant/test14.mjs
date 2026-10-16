import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import assert from 'node:assert/strict';import {Readable} from 'node:stream';import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
import {fingerprint,queue} from './candidate-14/lib/scheduler-core.mjs';
import {normalizeFailure} from './candidate-14/lib/host-adapter.mjs';
import {resolveFailure,grantAuthorization} from './candidate-14/lib/failure-resolution.mjs';
import {apply} from './candidate-14/lib/index.js';
const dir=path.dirname(fileURLToPath(import.meta.url));
let passed=0,tests=[];const pendingTests=[];
function test(n,f){const r=f();passed++;tests.push(n);
  if(r&&typeof r.then==='function')pendingTests.push(Promise.resolve(r).then(()=>console.log('通过：'+n)));
  else console.log('通过：'+n);}

/* 候选14 用例：授权类挂起在“用户已授权”后必须有解锁通道（k-mvae3o8m-29）。
   事故：k-mv8yxm2n-15 被授权类挂起（action='hold'、category='authorization'）后，用户已按要求完成人工动作，
   但看板没有任何入口能把它放回队列 —— moveIssue→todo 被 retryGuard 拦下、唯一正规通道 resolveFailure 又显式
   拒绝 authorization 类（拒绝本身是对的：诊断证据不等于授权）。结果只能“取消 + 另立承接卡”绕过。

   用例覆盖议题的五条判据：
   ① agent 调 grantAuthorization 被拒（来源校验）—— agent 没有入口，无界面交互标记的调用一律拒绝；
   ② 客户端确认后卡回 todo，且有审计记录（评论 + 活动流 + 授权记账 + 落盘 + 可被调度）；
   ③ failureToken 不匹配被拒；
   ④ 同一 failureToken 第二次确认被拒（换新指纹可再次授权，不是死路）；
   ⑤ 既有 moveIssue / resolveFailure / retryIssue 的拦截行为不变，且不新增越权后门。 */

// ============================== 一、纯规则 ==============================
const AUTH_FP=fingerprint({code:'AUTH_REQUIRED',target:'dsh-auth',scope:'w',evidenceKey:'auth-e2e-1'});
const mkState=(over={})=>({version:5,issues:[{id:'k-x',status:'blocked',blockedBy:[],basePriority:5,priority:5,
  failureControl:{action:'hold',category:'authorization',fingerprint:AUTH_FP,holdReason:'需要用户授权'},
  authorizationGrants:[],...(over.fc?{}:{}),...over}]});
const input=(over={})=>({failureToken:AUTH_FP,note:'我已完成所需的人工动作/批准',evidenceKey:'ui-grant-1',confirmed:true,...over});

test('①-纯规则：grantAuthorization 只认授权类挂起，放行一次并留下授权记账',()=>{
  const out=grantAuthorization(mkState(),'k-x',input(),1780000000000);
  const i=out.state.issues[0];
  assert.equal(out.released,'k-x');assert.equal(out.failureToken,AUTH_FP);
  assert.equal(i.status,'todo','授权后必须回到待执行队列');
  assert.equal(i.failureControl.action,'recovered','必须解除 hold，否则调度器仍然不认（eligible 会排除 hold）');
  assert.equal(i.manualHold,false);assert.equal(i.run,null);
  assert.equal(i.authorizationGrants.length,1);
  assert.equal(i.authorizationGrants[0].failureToken,AUTH_FP);
  assert.equal(i.authorizationGrants[0].note,'我已完成所需的人工动作/批准');
  assert.equal(i.authorizationGrants[0].evidenceKey,'ui-grant-1');
  assert.equal(i.authorizationGrants[0].by,'user');
  assert.equal(i.authorizationGrants[0].at,new Date(1780000000000).toISOString());
  assert.equal(i.lastFailure,undefined,'授权不是失败诊断：不得改写失败证据');
  assert.equal(queue(out.state,1780000000000).includes('k-x'),true,'放回队列后必须能被调度器领取');
  // 原状态不得被就地改写（纯函数）
  const before=mkState();
  grantAuthorization(before,'k-x',input());
  assert.equal(before.issues[0].status,'blocked');
});
test('②-纯规则：令牌/确认/说明/依赖缺一不可，且不得成为其他失败类别的后门',()=>{
  const fc=(x)=>({failureControl:{action:'hold',category:'authorization',fingerprint:AUTH_FP,holdReason:'需要用户授权',...x}});
  assert.throws(()=>grantAuthorization(mkState(),'k-x',input({failureToken:'别的 token'})),/拒绝过期授权/);
  assert.throws(()=>grantAuthorization(mkState(),'k-x',input({failureToken:undefined})),/拒绝过期授权/);
  assert.throws(()=>grantAuthorization(mkState(),'k-x',input({confirmed:false})),/用户确认才算授权/);
  assert.throws(()=>grantAuthorization(mkState(),'k-x',input({confirmed:undefined})),/用户确认才算授权/);
  assert.throws(()=>grantAuthorization(mkState(),'k-x',input({note:'太短'})),/人工动作或批准内容/);
  assert.throws(()=>grantAuthorization(mkState({blockedBy:['repair-x']}),'k-x',input()),/有修复前置/);
  assert.throws(()=>grantAuthorization(mkState({status:'todo'}),'k-x',input()),/仅可处理当前受阻任务/);
  assert.throws(()=>grantAuthorization(mkState({archivedAt:'2026-01-01'}),'k-x',input()),/仅可处理当前受阻任务/);
  assert.throws(()=>grantAuthorization(mkState(),'不存在',input()),/仅可处理当前受阻任务/);
  // 诊断类（unknown→diagnose）不得走授权通道，也不能用授权给“明确的缺陷”放行
  assert.throws(()=>grantAuthorization(mkState(fc({action:'diagnose',category:'unknown'})),'k-x',input()),/不是挂起状态/);
  assert.throws(()=>grantAuthorization(mkState(fc({category:'repair'})),'k-x',input()),/只有授权类挂起/);
  assert.throws(()=>grantAuthorization(mkState(fc({category:'configuration'})),'k-x',input()),/只有授权类挂起/);
  assert.throws(()=>grantAuthorization(mkState(fc({category:'unknown'})),'k-x',input()),/只有授权类挂起/);
  // 诊断放行仍拒绝授权类（既保留的防线，不得被本轮改动放宽）
  assert.throws(()=>resolveFailure(mkState(),'k-x',{failureToken:AUTH_FP,evidence:'已核实：授权已由用户补充，允许继续一次',evidenceKey:'k14-rec-1'}),/授权问题需专门的授权验证流程/);
});
test('③-纯规则：同一 failureToken 只放行一次，换新指纹可以再次授权',()=>{
  const granted=grantAuthorization(mkState(),'k-x',input());
  const again=granted.state.issues[0];
  assert.equal(again.authorizationGrants.length,1);
  // 同一指纹再次受阻（同一失败再现）后再确认：换说明、换证据标识都不行
  again.status='blocked';
  again.failureControl={action:'hold',category:'authorization',fingerprint:AUTH_FP,holdReason:'需要用户授权'};
  assert.throws(()=>grantAuthorization(granted.state,'k-x',input({note:'再次确认',evidenceKey:'ui-grant-2'})),/同一失败已授权一次/);
  assert.equal(granted.state.issues[0].authorizationGrants.length,1,'被拒的重复确认不得记账');
  // 新的失败指纹 = 新的授权，不是死路
  const FP2=fingerprint({code:'AUTH_REQUIRED',target:'dsh-auth',scope:'w',evidenceKey:'auth-e2e-2'});
  const next=granted.state.issues[0];
  next.status='blocked';next.failureControl={action:'hold',category:'authorization',fingerprint:FP2,holdReason:'再次需要用户授权'};
  const out2=grantAuthorization(granted.state,'k-x',input({failureToken:FP2,evidenceKey:'ui-grant-3'}));
  assert.equal(out2.state.issues[0].authorizationGrants.length,2);
  assert.equal(out2.state.issues[0].status,'todo');
});

// ============================== 二、完整插件端到端 ==============================
const roots=[];
function harness(label){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-c14-'));roots.push(root);
  const timers=[],intervals=[],pending=[],tools=[];
  const liveAgents=new Map(),parent={id:'parent',session:{header:{cwd:root}}};
  const ws={id:'w',path:root,sessionIds:['parent'],title:label};
  const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
  let route=null,seq=0;
  const ctx={fs:{resolve:async(p,o={})=>path.resolve(o.cwd??root,p),readText:async p=>fs.readFileSync(p,'utf8'),writeText:async(p,t)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,t)}},
   timer:{timeout:f=>{timers.push(f);return()=>{}},interval:f=>{intervals.push(f);return()=>{}}},tools:{register:t=>tools.push(t)},
   webServer:{register:r=>route=r.handler},workspaceRegistry:{get:i=>i==='w'?ws:null},
   agents:{currentInitiator:()=>parent,get:i=>(liveAgents.get(i)||(i==='parent'?parent:null)),list:()=>[parent]},
   agentDefaultModel:{currentSelection:()=>null},llm:{},
   subagents:{start:async(_,spec)=>{const d=deferred();pending.push({label:spec.label,...d});return {id:'s'+(++seq),result:d.promise,dispose:async()=>{}}}},
   shell:{resolve:r=>r,execute:async()=>({result:async()=>({exitCode:1,stdout:{text:''},stderr:{text:''}})})},effect:fn=>{try{fn()}catch{}}};
  apply(ctx);
  assert(intervals.length>=1,'健康扫描的 interval 应已在 apply 时注册');
  const healthTick=intervals[0];
  // opts.client===false 模拟“不是看板界面发起的调用”（agent 直连 HTTP / 进程内直调）：不带交互标记
  const rpc=async(m,a={},opts={})=>{let response;const req=Readable.from([Buffer.from(JSON.stringify({method:'kanban.'+m,args:{workspaceId:'w',...a}}))]);req.method='POST';
    if(opts.client!==false)req.headers={'x-kanban-client':'board'};
    await route(req,{setHeader(){},writeHead(){},end:t=>response=JSON.parse(t)});return response};
  const state=async()=>(await rpc('getState')).state;
  const settle=()=>new Promise(r=>setImmediate(r));
  const settleMany=async(n=30)=>{for(let i=0;i<n;i++)await settle()};
  const drain=async()=>{for(let n=0;n<40;n++){const queued=timers.splice(0,timers.length);if(!queued.length)return;for(const f of queued)await f();await settle()}};
  const waitFor=async fn=>{for(let n=0;n<400;n++){if(await fn())return;await new Promise(r=>setTimeout(r,5))}throw new Error('等待超时')};
  const take=label=>{const p=pending.find(x=>x.label===label);assert(p,'缺少待派发的子代理：'+label);pending.splice(pending.indexOf(p),1);return p};
  const rawState=()=>JSON.parse(fs.readFileSync(path.join(root,'.dsh','kanban-state.json'),'utf8'));
  const rawIssue=id=>{try{return rawState().issues.find(x=>x.id===id)||null}catch(e){return null}};
  return {root,pending,tools,intervals,liveAgents,rpc,state,drain,settle,settleMany,waitFor,take,rawState,rawIssue,healthTick,
    scan:async()=>{healthTick();await settle()},
    view:async id=>(await state()).issues.find(x=>x.id===id)};
}
async function dispatchHeld(h,title,priority){
  const id=(await h.rpc('createIssue',{title,priority})).issueId;
  await h.rpc('moveIssue',{id,to:'todo'});
  await h.drain();
  await h.waitFor(()=>h.pending.some(p=>p.label==='executor-'+id));
  const held=h.take('executor-'+id);
  await h.waitFor(async()=>{const it=await h.view(id);return !!(it&&it.run&&it.run.subagentId)});
  return {id,held,run:(await h.view(id)).run};
}
const oldErr=console.error;const hostErrors=[];
console.error=(...a)=>{hostErrors.push(a.map(String).join(' '));oldErr(...a)};
let h=null,id=null,authFailure=null,tokenA=null;
try{
  h=harness('授权类挂起必须有用户确认入口');
  await h.rpc('setAutoExec',{patch:{enabled:true,promoteBacklog:false}});
  // ① agent 侧：看板不得给 agent 开任何授权解锁入口
  test('① 端到端：agent 没有调用入口（动态工具里不存在授权解锁）',()=>{
    assert(h.tools.length>=10,'应已注册看板动态工具：'+h.tools.length);
    const names=h.tools.map(t=>String(t.name));
    assert.deepEqual(names.filter(n=>/grant|authoriz/i.test(n)),[],'不得给 agent 注册授权解锁工具：'+names.join('、'));
    assert.equal(JSON.stringify(h.tools).includes('grantAuthorization'),false,'工具定义里也不得出现授权解锁出口');
  });
  const d=await dispatchHeld(h,'授权类挂起后必须能放回队列',6);
  id=d.id;
  authFailure={code:'AUTH_REQUIRED',message:'需要用户在一个无在途批次的窗口做一次人工移动',target:'dsh-auth',scope:'w',evidenceKey:'auth-e2e-1'};
  tokenA=fingerprint(normalizeFailure({failure:{...authFailure}}));
  d.held.resolve({structured:{status:'failed',reason:'需要授权',failure:{...authFailure}},stopReason:'completed'});
  await h.waitFor(async()=>(await h.view(id)).status==='blocked');
  await h.settleMany();await h.drain();
  const v1=await h.view(id);
  const agentTry=await h.rpc('grantAuthorization',{id,version:v1.version,failureToken:v1.failureControl.fingerprint,note:'agent 自己放行（应被拒）',evidenceKey:'ui-grant-agent',confirmed:true},{client:false});
  const noConfirm=await h.rpc('grantAuthorization',{id,version:v1.version,failureToken:v1.failureControl.fingerprint,note:'界面通道但缺人工确认标记（应被拒）',evidenceKey:'ui-grant-agent2'});
  const after=await h.view(id);
  test('① 端到端：无交互标记的调用被来源校验拒绝；缺人工确认标记的调用也被拒；状态不被改写',()=>{
    assert.equal(v1.status,'blocked');assert.equal(v1.failureControl.action,'hold');assert.equal(v1.failureControl.category,'authorization');
    assert.equal(agentTry.ok,false,'agent 直连（无交互标记）必须被拒');
    assert(String(agentTry.message).includes('只能由看板界面的人工点击发起'),String(agentTry.message));
    assert.equal(noConfirm.ok,false,'缺人工确认语义的调用必须被拒');
    assert(String(noConfirm.message).includes('用户确认才算授权'),String(noConfirm.message));
    assert.equal(after.status,'blocked','被拒后不得半放行');
    assert.equal((after.authorizationGrants||[]).length,0,'被拒的调用不得留下授权记账');
  });
  // ⑤ 既有防线：三条通道都拦得住
  const mv=await h.rpc('moveIssue',{id,to:'todo',version:after.version});
  const rt=await h.rpc('retryIssue',{id});
  const rf=await h.rpc('resolveFailure',{id,version:after.version,failureToken:tokenA,evidence:'已核实：用户已完成人工动作，允许继续一次',evidenceKey:'k14-rec-1'});
  test('⑤ 端到端：授权类挂起的既有防线不变（moveIssue / retryIssue / resolveFailure 全部仍被拒）',()=>{
    assert.equal(mv.ok,false);assert(String(mv.message).includes('禁止原地重试'),String(mv.message));
    assert.equal(rt.ok,false);assert(String(rt.message).includes('禁止原地重试'),String(rt.message));
    assert.equal(rf.ok,false);assert(String(rf.message).includes('授权问题需专门的授权验证流程'),String(rf.message));
    assert.equal(rf.state,undefined,'被拒的恢复不得回传任何状态');
  });
  await h.settleMany();
  const blocked=await h.view(id);
  // ③ 令牌不匹配
  const wrongToken=await h.rpc('grantAuthorization',{id,version:blocked.version,failureToken:'deadbeefdeadbeefdeadbeef',note:'我已完成所需的人工动作/批准',evidenceKey:'ui-grant-bad',confirmed:true});
  test('③ 端到端：failureToken 不匹配被拒（拒绝过期授权）',()=>{
    assert.equal(wrongToken.ok,false);assert(String(wrongToken.message).includes('拒绝过期授权'),String(wrongToken.message));
  });
  const stillBlocked=await h.view(id);
  assert.equal(stillBlocked.status,'blocked');
  // ② 正常授权
  const grant=await h.rpc('grantAuthorization',{id,version:stillBlocked.version,failureToken:tokenA,note:'我已完成所需的人工动作/批准',evidenceKey:'ui-grant-1',confirmed:true});
  await h.waitFor(async()=>(await h.view(id)).status==='todo');
  const v2=await h.view(id);
  const raw2=h.rawIssue(id);
  test('② 端到端：界面确认后任务回到待执行队列，评论/活动流/授权记账/落盘齐全',()=>{
    assert.equal(grant.ok,true,String(grant.message));
    assert.equal(v2.status,'todo','授权后必须回到待执行队列');
    assert.equal(v2.failureControl.action,'recovered');
    assert.equal((v2.authorizationGrants||[]).length,1);
    assert.equal(v2.authorizationGrants[0].failureToken,tokenA);
    assert.equal(v2.authorizationGrants[0].note,'我已完成所需的人工动作/批准');
    const audit=v2.comments.filter(c=>String(c.text).includes('用户确认授权'));
    assert.equal(audit.length,1,'必须有一条人工授权评论：'+JSON.stringify(v2.comments.map(c=>c.text)));
    assert.equal(audit[0].who,'user','授权必须记在 user 名下');
    assert(String(audit[0].text).includes(tokenA),'审计评论必须带上授权指纹：'+audit[0].text);
    const act=v2.activity.filter(x=>x.kind==='status'&&x.from==='blocked'&&x.to==='todo');
    assert.equal(act.length,1,'必须有 blocked→todo 的活动流：'+JSON.stringify(v2.activity));
    assert.equal(act[0].by,'user');assert.equal(act[0].authorizationToken,tokenA);
    assert(raw2&&raw2.authorizationGrants&&raw2.authorizationGrants.length===1,'授权记账必须落盘');
    assert.equal(raw2.status,'todo');
  });
  test('② 端到端：放回队列后能被调度器正常领取（不是只改状态）',()=>{
    assert.equal(queue(h.rawState(),Date.now()).includes(id),true,'授权放行后必须重新进入可调度队列');
    assert.equal(v2.run,null);
  });
  // ④ 第二次派发：先换新指纹（新授权），再用旧指纹确认（应被拒）
  await h.drain();
  await h.waitFor(()=>h.pending.some(p=>p.label==='executor-'+id));
  const second=h.take('executor-'+id);
  await h.waitFor(async()=>{const it=await h.view(id);return !!(it&&it.run&&it.run.subagentId)});
  second.resolve({structured:{status:'failed',reason:'需要授权（第二轮）',failure:{...authFailure,evidenceKey:'auth-e2e-2'}},stopReason:'completed'});
  await h.waitFor(async()=>(await h.view(id)).status==='blocked');
  const v3=await h.view(id);
  const tokenB=fingerprint(normalizeFailure({failure:{...authFailure,evidenceKey:'auth-e2e-2'}}));
  const replayOld=await h.rpc('grantAuthorization',{id,version:v3.version,failureToken:tokenA,note:'拿上一次的授权指纹放行新的失败（应被拒）',evidenceKey:'ui-grant-4',confirmed:true});
  const grantB=await h.rpc('grantAuthorization',{id,version:v3.version,failureToken:tokenB,note:'用户再次完成人工动作/批准',evidenceKey:'ui-grant-5',confirmed:true});
  await h.waitFor(async()=>(await h.view(id)).status==='todo');
  await h.drain();
  await h.waitFor(()=>h.pending.some(p=>p.label==='executor-'+id));
  const third=h.take('executor-'+id);
  await h.waitFor(async()=>{const it=await h.view(id);return !!(it&&it.run&&it.run.subagentId)});
  third.resolve({structured:{status:'failed',reason:'需要授权（同一失败再现）',failure:{...authFailure,evidenceKey:'auth-e2e-2'}},stopReason:'completed'});
  await h.waitFor(async()=>(await h.view(id)).status==='blocked');
  const v4=await h.view(id);
  const again=await h.rpc('grantAuthorization',{id,version:v4.version,failureToken:tokenB,note:'同一失败再点一次（应被拒）',evidenceKey:'ui-grant-6',confirmed:true});
  const v5=await h.view(id);
  test('④ 端到端：同一 failureToken 第二次确认被拒；新的失败指纹可以再次获得授权',()=>{
    assert.notEqual(tokenB,tokenA,'新失败的指纹必须不同（否则“再次挂起需新的授权”无从谈起）');
    assert.equal(replayOld.ok,false,'旧的授权指纹不得套用到新的失败');
    assert(String(replayOld.message).includes('拒绝过期授权'),String(replayOld.message));
    assert.equal(grantB.ok,true,String(grantB.message));
    assert.equal(again.ok,false,'同一 failureToken 第二次确认必须被拒');
    assert(String(again.message).includes('同一失败已授权一次'),String(again.message));
    assert.equal(v5.status,'blocked','被拒后必须仍是受阻状态（不得半恢复）');
    assert.equal((v5.authorizationGrants||[]).length,2,'两次授权必须都已记账（tokenA + tokenB）');
    assert.deepEqual((v5.authorizationGrants||[]).map(g=>g.failureToken),[tokenA,tokenB]);
    assert.equal(v5.failureControl.action,'hold','被拒后仍保持挂起，等待新的授权');
  });
  test('全程无宿主错误日志',()=>assert.deepEqual(hostErrors,[]));
}finally{
  console.error=oldErr;
  for(const r of roots)fs.rmSync(r,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}

// ============================== 三、界面入口（client.js） ==============================
const clientPath=fileURLToPath(new URL('./candidate-14/lib/client.js',import.meta.url));
const clientSrc=fs.readFileSync(clientPath,'utf8');
// 从 bundle 里按括号配对取出一整个函数（先跳过参数列表，参数里的解构花括号不能算进函数体）
function extractFunction(text,name){
  const start=text.indexOf('function '+name+'(');
  if(start<0)throw new Error('找不到函数：'+name);
  const open=text.indexOf('(',start);
  let pd=0,bodyStart=-1;
  for(let i=open;i<text.length;i++){
    const ch=text[i];
    if(ch==='(')pd++;
    else if(ch===')'){pd--;if(pd===0){bodyStart=i+1;break}}
  }
  if(bodyStart<0)throw new Error('参数列表括号不平衡：'+name);
  const head=text.slice(start,bodyStart);
  const from=text.indexOf('{',bodyStart);
  if(from<0)throw new Error('找不到函数体：'+name);
  let depth=0,quote=null,started=false;
  for(let i=from;i<text.length;i++){
    const ch=text[i],prev=text[i-1];
    if(quote){if(ch===quote&&prev!=='\\')quote=null;continue}
    if(ch==="'"||ch==='"'||ch==='`'){quote=ch;continue}
    if(ch==='{'){depth++;started=true;continue}
    if(ch==='}'){depth--;if(started&&depth===0)return head+text.slice(from,i+1)}
  }
  throw new Error('函数体括号不平衡：'+name);
}
const el=(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false&&x!==true)});
function walk(node,pred,out=[]){
  if(Array.isArray(node)){for(const n of node)walk(n,pred,out);return out}
  if(!node||typeof node!=='object')return out;
  if(pred(node))out.push(node);
  for(const c of node.children||[])walk(c,pred,out);
  return out;}
const textOf=node=>String((node.children||[]).map(c=>typeof c==='object'?(textOf(c)):String(c)).join(''));
function makeReact(){
  const hooks=[];let cursor=0;
  return {render:(Comp,props)=>{cursor=0;return Comp(props)},
    ReactStub:{useState:(init)=>{const i=cursor++;if(!(i in hooks))hooks[i]=init;return [hooks[i],v=>{hooks[i]=v}]}}};
}

test('⑥-界面：client.js 语法通过，且交互标记与授权确认组件已接线',()=>{
  const chk=spawnSync(process.execPath,['--check',clientPath],{encoding:'utf8'});
  assert.equal(chk.status,0,'client.js 语法检查必须通过：'+String(chk.stderr||'').slice(0,300));
  assert(clientSrc.includes("'X-Kanban-Client': 'board'"),'每次 RPC 必须携带界面交互标记（grantAuthorization 的来源校验依赖它）');
  assert(clientSrc.includes('function AuthorizationGrantView('),'必须新增授权确认组件');
  const defined=extractFunction(clientSrc,'AuthorizationGrantView');
  assert(defined.includes("call('grantAuthorization'"),'确认组件必须调用 grantAuthorization');
  assert(defined.includes('confirmed: true'),'确认组件必须显式声明人工确认语义');
  assert(clientSrc.includes('el(AuthorizationGrantView, { detail, selWs, act })'),'详情页必须挂上授权确认面板');
  assert(clientSrc.includes('el(AuthorizationGrantView, { key: i.id + \'-grant\''),'受阻列表必须能就地调出确认面板');
  assert(clientSrc.includes("isAuthHold(i) ? (authFor === i.id ? '收起授权确认' : '确认授权…') : '解除阻塞'"),'授权类的「解除阻塞」必须改为调出确认');
});

test('⑥-界面：确认面板的渲染与提交契约（未勾选不可提交，勾选后带 confirmed 提交）',()=>{
  const src=extractFunction(clientSrc,'AuthorizationGrantView');
  const noteLiteral=/const AUTH_NOTE_DEFAULT = ('[^']*')/.exec(clientSrc);
  assert(noteLiteral,'必须声明「我已完成所需的人工动作/批准」的默认授权说明');
  assert.equal(noteLiteral[1],"'我已完成所需的人工动作/批准'");
  const calls=[];const call=(m,a)=>{calls.push({m,a});return Promise.resolve({ok:true,message:'授权已确认，任务回到待执行队列（同一失败只放行一次）'})};
  const act=async(fn)=>await fn();
  const store=makeReact();
  const Comp=new Function('React','el','call','act','Date','const AUTH_NOTE_DEFAULT = '+noteLiteral[1]+';\n'+src+'\n;return AuthorizationGrantView;')(store.ReactStub,el,call,act,Date);
  const detail={id:'k-x',status:'blocked',blockedBy:[],version:9,authorizationGrants:[],
    failureControl:{action:'hold',category:'authorization',fingerprint:'fp-ui-1',holdReason:'需要用户授权'}};
  const render=(d)=>store.render(Comp,{detail:d,selWs:{id:'w'},act});
  // 非授权类挂起 / 已解除 / 有修复前置：一律不出现确认面板
  assert.equal(render({...detail,failureControl:{action:'diagnose',category:'unknown',fingerprint:'fp-2'}}),null,'诊断类不得出现授权确认');
  assert.equal(render({...detail,blockedBy:['repair-1']}),null,'有修复前置不得出现授权确认');
  assert.equal(render({...detail,status:'todo'}),null,'非受阻不得出现授权确认');
  const tree1=render(detail);
  const btn1=walk(tree1,n=>n.type==='button').find(n=>textOf(n).includes('确认授权并放回队列'));
  assert(btn1,'必须有确认按钮');
  assert.equal(btn1.props.disabled,true,'未勾选人工动作确认时必须禁用');
  const box=walk(tree1,n=>n.props&&n.props.type==='checkbox')[0];
  assert(box,'必须有“我已完成所需的人工动作/批准”勾选框');
  box.props.onChange({target:{checked:true}});
  const tree2=render(detail);
  const btn2=walk(tree2,n=>n.type==='button').find(n=>textOf(n).includes('确认授权并放回队列'));
  assert.equal(btn2.props.disabled,false,'勾选后必须可提交');
  return Promise.resolve(btn2.props.onClick()).then(()=>{
    assert.equal(calls.length,1,'提交必须只调用一次');
    assert.equal(calls[0].m,'grantAuthorization');
    const a=calls[0].a;
    assert.equal(a.id,'k-x');assert.equal(a.version,9);assert.equal(a.workspaceId,'w');
    assert.equal(a.failureToken,'fp-ui-1','必须带当前挂起指纹');
    assert.equal(a.confirmed,true);
    assert.equal(a.note,'我已完成所需的人工动作/批准');
    assert(String(a.evidenceKey).startsWith('ui-grant-'),String(a.evidenceKey));
    const tree3=render(detail);
    assert(walk(tree3,n=>n.props&&n.props.role==='status')[0],'提交后必须有结果提示');
    // 已授权过的同一指纹：只提示，不再给按钮
    const grantedTree=render({...detail,authorizationGrants:[{failureToken:'fp-ui-1'}]});
    assert.equal(walk(grantedTree,n=>n.type==='button').length,0,'同一指纹已授权过不得再给放行按钮');
    assert(textOf(grantedTree).includes('需要新的授权'),'必须写明需要新的授权');
  });
});

test('⑥-界面：受阻列表的「解除阻塞」对授权类不再走 moveIssue，改为调出确认面板',()=>{
  const src=extractFunction(clientSrc,'OtherPanelView');
  const moves=[],opens=[],grantNode={};
  const call=()=>Promise.resolve({ok:true});
  const act=async(fn)=>await fn();
  const AuthView=function AuthorizationGrantView(props){return {type:'grant',props,children:[]}};
  const store=makeReact();
  const Panel=new Function('React','el','call','AuthorizationGrantView','moveIssue','openDetail',src+'\n;return OtherPanelView;')(store.ReactStub,el,call,AuthView,(id,to)=>moves.push({id,to}),(id)=>opens.push(id));
  const authIssue={id:'k-auth',title:'授权类',status:'blocked',version:3,comments:[],activity:[],archivedAt:null,blockedBy:[],
    failureControl:{action:'hold',category:'authorization',fingerprint:'fp-a'}};
  const diagIssue={id:'k-diag',title:'诊断类',status:'blocked',version:4,comments:[],activity:[],archivedAt:null,blockedBy:[],
    failureControl:{action:'diagnose',category:'unknown',fingerprint:'fp-d'}};
  const props={otherOpen:true,otherTab:'blocked',setOtherTab:()=>{},issues:[authIssue,diagIssue],openDetail:id=>opens.push(id),moveIssue:(id,to)=>moves.push({id,to}),act,selWs:{id:'w'}};
  const t1=store.render(Panel,props);
  const authBtn=walk(t1,n=>n.type==='button').find(n=>textOf(n)==='确认授权…');
  const diagBtn=walk(t1,n=>n.type==='button').find(n=>textOf(n)==='解除阻塞');
  assert(authBtn,'授权类必须显示「确认授权…」而不是「解除阻塞」');
  assert(diagBtn,'非授权类仍保持「解除阻塞」');
  authBtn.props.onClick();
  assert.deepEqual(moves,[],'授权类的解锁按钮不得再调用 moveIssue（一定会被 retryGuard 拦下）');
  const t2=store.render(Panel,props);
  assert(walk(t2,n=>n.type===AuthView).length===1,'点击后必须就地渲染确认面板');
  const diagBtn2=walk(t2,n=>n.type==='button').find(n=>textOf(n)==='解除阻塞');
  diagBtn2.props.onClick();
  assert.deepEqual(moves,[{id:'k-diag',to:'todo'}],'非授权类仍走原来的 moveIssue');
  const collapse=walk(t2,n=>n.type==='button').find(n=>textOf(n)==='收起授权确认');
  collapse.props.onClick();
  const t3=store.render(Panel,props);
  assert.equal(walk(t3,n=>n.type===AuthView).length,0,'再点一次必须收起');
  assert.deepEqual(opens,[],'不得把用户甩到详情页了事');
});

for(const p of pendingTests)await Promise.resolve(p);
fs.writeFileSync(new URL('./test14-results.json',import.meta.url),JSON.stringify({passed,tests,scope:'候选14：授权类挂起的“用户授权确认”通道（grantAuthorization 来源校验 + 同一 failureToken 只放行一次 + 界面入口不再复用 moveIssue；纯规则 + 完整插件隔离RPC + client.js 组件渲染，零真实模型调用）'},null,2));
console.log('合计通过：'+passed);
