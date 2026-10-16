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
