import {randomUUID,createHash} from 'node:crypto';
import * as core from './scheduler-core.mjs';
const clone=x=>structuredClone(x);
const hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
const supportedCodes=new Set(['RATE_LIMITED','HTTP_429','HTTP_502','HTTP_503','ETIMEDOUT','ECONNRESET','AUTH_REQUIRED','USER_APPROVAL_REQUIRED','RESTART_APPROVAL_REQUIRED','UNSUPPORTED_REASONING_EFFORT','INVALID_CONFIG','TEST_REGRESSION','CODE_DEFECT','DELIVERABLE_MISSING','ENVIRONMENT_MISSING','PERMISSION_DENIED','ACCEPTANCE_CRITERIA_UNMET']);
export function normalizeFailure(result={}) {
  // 只采信结构化代码，保留原始报告；不能用模糊字符串把未知错误判成可自动重试。
  const machine=result.failure??result.error??{};
  const code=supportedCodes.has(machine.code)?machine.code:'UNKNOWN';
  const target=machine.target??'executor';const scope=machine.scope??'workspace';
  const evidence={code:machine.code??null,target,scope,reason:machine.message??result.reason??'未返回有效结构化结果'};
  return {code,target,scope,evidenceKey:machine.evidenceKey??hash(evidence),message:evidence.reason,rawEvidence:evidence};
}
// 本适配器是候选Host的唯一事务入口。mutate须由既有store.queue串行化并负责落盘。
export function createAdapter({mutate,now=()=>Date.now(),token=()=>randomUUID()}) {
  const commit=fn=>mutate(current=>{
    const originalVersion=current.version??1;
    const out=fn(clone(current));
    if(!out.changed)return {...out,state:current};
    out.state.version=originalVersion+1;return out;
  });
  return {
    claimNext:()=>commit(state=>{
      const id=core.queue(state,now())[0];if(!id)return {state,changed:false,claim:null};
      const attemptId=token(),r=core.claim(state,id,attemptId,now());
      return {state:r.state,changed:r.claimed,claim:r.claimed?{id,attemptId}:null};
    }),
    fail:(id,attemptId,result)=>commit(state=>{
      const r=core.routeFailure(state,id,attemptId,normalizeFailure(result),now());
      if(!r.applied)return {state:r.state,changed:false,action:r.action};
      // 诊断类分流不再停在“受阻 + 等人给证据”：自动开一张阻塞处置卡（先查 decision-ledger 台账）。
      if(r.action==='diagnose'){const opened=core.openDiagnosisDisposition(r.state,id);return {state:r.state,changed:true,action:(opened.created||opened.reused)?r.action:'hold'}}
      return {state:r.state,changed:true,action:r.action};
    }),
    succeed:(id,attemptId,report)=>commit(state=>{
      const i=state.issues.find(x=>x.id===id);
      if(!i||i.archivedAt||i.status!=='in_progress'||i.run?.attemptId!==attemptId||i.run.status!=='running'||(i.blockedBy??[]).length)return {state,changed:false};
      i.status='in_review';i.run.status='done';i.executionEvidence={attemptId,report,completedAt:new Date(now()).toISOString()};
      return {state,changed:true};
    }),
    claimReview:id=>commit(state=>{
      const i=state.issues.find(x=>x.id===id);
      if(!i||i.archivedAt||i.status!=='in_review'||i.acceptanceAttemptId||(i.blockedBy??[]).length)return {state,changed:false,claim:null};
      const attemptId=token();i.acceptanceAttemptId=attemptId;i.acceptanceScopeRevision=i.scopeRevision??1;
      return {state,changed:true,claim:{id,attemptId,executionAttemptId:i.run?.attemptId,scopeRevision:i.acceptanceScopeRevision}};
    }),
    review:(id,reviewAttemptId,executionAttemptId,verdict)=>commit(state=>{
      const i=state.issues.find(x=>x.id===id);
      if(!i||i.status!=='in_review'||i.archivedAt||(i.blockedBy??[]).length||i.acceptanceAttemptId!==reviewAttemptId||i.run?.attemptId!==executionAttemptId)return {state,changed:false,released:[]};
      // 作用域在验收期间变化则拒绝过期验收结果，不得据旧范围解锁新增下游。
      if((i.acceptanceScopeRevision??1)!==(i.scopeRevision??1))return {state,changed:false,stale:true,released:[]};
      i.acceptanceAttemptId=null;i.acceptanceScopeRevision=null;
      if(verdict.passed===true){
        i.status='done';i.acceptedAt=new Date(now()).toISOString();
        i.acceptanceEvidence={passed:true,attemptId:reviewAttemptId,executionAttemptId,scopeRevision:i.scopeRevision??1,report:verdict.report??''};
        const r=core.releaseAfterRepair(state,id,now());return {state:r.state,changed:true,released:r.released};
      }
      // 验收失败也是按原因分流，而不是直接todo原地重试。
      i.status='in_progress';i.run.status='running';
      const r=core.routeFailure(state,id,executionAttemptId,normalizeFailure(verdict),now());
      return {state:r.state,changed:true,action:r.action,released:[]};
    }),
    manualMove:(id,status)=>commit(state=>{
      const allowed=new Set(['backlog','todo','blocked','canceled']);if(!allowed.has(status))throw new Error('人工流转不可绕过执行与验收');
      const i=state.issues.find(x=>x.id===id);if(!i)return {state,changed:false};
      if(status==='todo'&&(i.blockedBy??[]).length)throw new Error('前置未完成，禁止强行入队');
      core.invalidate(i);i.status=status;i.manualHold=['backlog','blocked','canceled'].includes(status);if(i.run)i.run.status='revoked';
      return {state,changed:true};
    }),
    setPriority:(id,value)=>commit(state=>{
      // API新值必须是真数字，迁移兼容旧枚举不等于允许工具继续写旧值。
      if(typeof value!=='number')throw new Error('新API优先级只接受1–9整数');const p=core.priority(value);
      const i=state.issues.find(x=>x.id===id);if(!i)return {state,changed:false};
      i.basePriority=p;i.priority=p;i.prioritySource='user';return {state,changed:true};
    }),
    deleteIssue:id=>commit(state=>{
      if(state.issues.some(i=>(i.blockedBy??[]).includes(id)))throw new Error('存在依赖，禁止删除前置以绕过验收');
      const n=state.issues.length;state.issues=state.issues.filter(x=>x.id!==id);return {state,changed:n!==state.issues.length};
    }),
  };
}
