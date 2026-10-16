import {invalidate} from './scheduler-core.mjs';
// 诊断仅允许有新证据的一次恢复；不能充当解除缺陷依赖或扩大权限的后门。
export function resolveFailure(state,id,input,now=Date.now()) {
  const out=structuredClone(state),i=out.issues.find(x=>x.id===id);
  if(!i||i.archivedAt||i.status!=='blocked')throw new Error('仅可处理当前受阻任务');
  // 修复前置必须走验收闭环；只有“全部依赖都是自动开的诊断处置卡”时才允许人工补充新证据后的一次恢复。
  const deps=(i.blockedBy??[]).map(did=>out.issues.find(x=>x.id===did));
  const diagnosisOnly=(i.blockedBy??[]).length>0&&deps.every(d=>d&&!d.archivedAt&&d.status!=='canceled'&&d.diagnosisForFingerprint&&!d.repairForFingerprint);
  if((i.blockedBy??[]).length&&!diagnosisOnly)throw new Error('有修复前置，必须走前置验收闭环');
  const f=i.failureControl;
  if(!f||!['diagnose','hold'].includes(f.action))throw new Error('当前失败不允许诊断恢复');
  const failureToken=f.fingerprint??f.holdReason;
  if(!failureToken||input.failureToken!==failureToken)throw new Error('失败已变化或缺失，拒绝过期诊断');
  if(typeof input.evidence!=='string'||input.evidence.trim().length<10)throw new Error('必须提供可复核的新诊断证据');
  if(typeof input.evidenceKey!=='string'||input.evidenceKey.length<8)throw new Error('必须提供新证据标识');
  if(f.category==='configuration'||f.category==='repair'||f.holdReason==='repair-budget-exhausted')throw new Error('明确缺陷或预算耗尽必须修复验收，不能诊断强放行');
  if(f.category==='authorization')throw new Error('授权问题需专门的授权验证流程，诊断证据不等于授权');
  const history=i.diagnosticRecoveryHistory??[];
  if(history.some(x=>x.failureToken===failureToken))throw new Error('同一失败已恢复一次，禁止反复诊断重跑');
  if(history.some(x=>x.evidenceKey===input.evidenceKey))throw new Error('不能复用旧证据');
  i.diagnosticRecoveryHistory=[...history,{failureToken,evidenceKey:input.evidenceKey,evidence:input.evidence.trim(),at:new Date(now).toISOString()}];
  const resumeReview=!!i.reviewInterruption && i.run?.status==='done' && i.run?.attemptId===i.reviewInterruption.executionAttemptId;
  const completedRun=resumeReview?structuredClone(i.run):null;
  // 人工已提供新证据：诊断处置卡已无意义，解除依赖并作废，避免继续消耗算力。
  if(diagnosisOnly)for(const d of deps){d.status='canceled';d.canceledReason='人工已提供新证据并单次恢复：'+id;d.updatedAt=new Date(now).toISOString()}
  if(diagnosisOnly)i.blockedBy=[];
  invalidate(i);i.run=completedRun;i.status=resumeReview?'in_review':'todo';i.manualHold=false;f.action='recovered';delete f.nextRetryAt;
  return {state:out,released:id};
}
