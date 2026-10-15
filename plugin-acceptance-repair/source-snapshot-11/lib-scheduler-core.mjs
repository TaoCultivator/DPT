import { createHash } from 'node:crypto';

export const LEGACY_PRIORITY = Object.freeze({ none: 1, low: 3, medium: 5, high: 7, urgent: 9 });
export const POLICY = Object.freeze({ transientRetries: 2, diagnosticAttempts: 1, backoffMs: [30000, 120000], maxRepairDepth: 3, maxRepairsPerRoot: 8 });
const copy = x => structuredClone(x);
const digest = x => createHash('sha256').update(JSON.stringify(x)).digest('hex').slice(0, 24);
export function priority(value) {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 9) return value;
  if (Object.hasOwn(LEGACY_PRIORITY, value) && typeof value === 'string') return LEGACY_PRIORITY[value];
  throw new Error('优先级必须为1–9整数或明确的旧版枚举');
}
export function migrate(state) {
  if (state.schedulerSchemaVersion === 2) { for (const i of state.issues) priority(i.basePriority); return copy(state); }
  const out = copy(state);
  out.schedulerMigration = { from: state.schedulerSchemaVersion ?? null, original: copy(state) };
  out.schedulerSchemaVersion = 2;
  for (const i of out.issues) { i.legacyPriority = i.priority; i.priority = priority(i.priority ?? 'none'); i.basePriority = i.priority; }
  out.schedulerMigration.migratedDigest = digest({ ...out, schedulerMigration: undefined });
  return out;
}
export function rollbackMigration(state) {
  const m = state.schedulerMigration;
  if (!m) throw new Error('无迁移原件，拒绝回滚');
  if (m.migratedDigest !== digest({ ...state, schedulerMigration: undefined })) throw new Error('迁移后有业务变化，拒绝破坏性回滚，需人工合并');
  return copy(m.original);
}
export function hasCycle(issues) {
  const by = new Map(issues.map(i => [i.id, i])), visiting = new Set(), done = new Set();
  function visit(id) { if (visiting.has(id)) return true; if (done.has(id)) return false; visiting.add(id);
    for (const dep of by.get(id)?.blockedBy ?? []) if (visit(dep)) return true;
    visiting.delete(id); done.add(id); return false;
  }
  return issues.some(i => visit(i.id));
}
export function attachDependency(state, id, dependencyId) {
  const out = copy(state), i = out.issues.find(x => x.id === id);
  if (!i || !out.issues.some(x => x.id === dependencyId)) throw new Error('任务或前置不存在');
  i.blockedBy = [...new Set([...(i.blockedBy ?? []), dependencyId])];
  if (hasCycle(out.issues)) throw new Error('拒绝循环依赖');
  i.status = 'blocked'; invalidate(i); return out;
}
export function invalidate(i) {
  if (i.run) i.run.attemptId = null;
  i.acceptanceAttemptId = null; i.acceptanceSubagentId = null;
}
export function effectivePriority(i) {
  const base = priority(i.basePriority ?? i.priority);
  if (i.status === 'blocked' || (i.blockedBy ?? []).length || i.failureControl?.action === 'hold') return Math.min(base, 2);
  return Math.max(1, base - Math.min(2, i.failureControl?.transientAttempts ?? 0));
}
export function eligible(i, now) {
  return i.status === 'todo' && !i.archivedAt && !(i.blockedBy ?? []).length && !i.parentId
    && i.run?.status !== 'running' && !i.run?.attemptId
    && !['hold', 'awaiting-repair', 'diagnose'].includes(i.failureControl?.action)
    && (!i.failureControl?.nextRetryAt || now >= i.failureControl.nextRetryAt);
}
export function queue(state, now = Date.now()) {
  return state.issues.map((i, n) => ({ i, n })).filter(({ i }) => eligible(i, now)).sort((a, b) =>
    effectivePriority(b.i) - effectivePriority(a.i)
    || String(a.i.enqueuedAt ?? a.i.createdAt ?? '').localeCompare(String(b.i.enqueuedAt ?? b.i.createdAt ?? ''))
    || a.n - b.n).map(({ i }) => i.id);
}
export function claim(state, id, attemptId, now = Date.now()) {
  const out = copy(state), i = out.issues.find(x => x.id === id);
  if (!attemptId || !i || !eligible(i, now)) return { state: out, claimed: false };
  i.status = 'in_progress'; i.run = { attemptId, status: 'running', scopeRevision: i.scopeRevision ?? 1 }; return { state: out, claimed: true };
}
// 仅信任机器代码/明确类别，不凭含糊文字猜测瞬时失败。
export function classify(f) {
  if (['RATE_LIMITED', 'HTTP_429', 'HTTP_502', 'HTTP_503', 'ETIMEDOUT', 'ECONNRESET'].includes(f.code)) return 'transient';
  if (['AUTH_REQUIRED', 'USER_APPROVAL_REQUIRED', 'RESTART_APPROVAL_REQUIRED'].includes(f.code)) return 'authorization';
  if (['UNSUPPORTED_REASONING_EFFORT', 'INVALID_CONFIG'].includes(f.code)) return 'configuration';
  // 验收判据未达成：交付没满足验收标准，属需要修复的缺陷（而不是未知原因等人工诊断）。
  if (['TEST_REGRESSION', 'CODE_DEFECT', 'DELIVERABLE_MISSING', 'ENVIRONMENT_MISSING', 'PERMISSION_DENIED', 'ACCEPTANCE_CRITERIA_UNMET'].includes(f.code)) return 'repair';
  return 'unknown';
}
export function fingerprint(f) {
  if (!f.code || !f.target || !f.scope || !f.evidenceKey) throw new Error('失败必须有代码、目标、作用域、证据指纹');
  return digest([f.scope, f.target, f.code, f.evidenceKey]);
}
export function routeFailure(state, id, attemptId, failure, now = Date.now()) {
  let out = copy(state); const i = out.issues.find(x => x.id === id);
  if (!i || i.status !== 'in_progress' || i.run?.attemptId !== attemptId || i.run?.status !== 'running' || i.archivedAt || (i.blockedBy ?? []).length)
    return { state: out, applied: false, action: 'stale' };
  const key = fingerprint(failure), category = classify(failure), prev = i.failureControl;
  const same = prev?.fingerprint === key;
  const control = { fingerprint: key, category, transientAttempts: same ? prev.transientAttempts ?? 0 : 0,
    diagnosticAttempts: same ? prev.diagnosticAttempts ?? 0 : 0, action: 'hold' };
  i.lastFailure = copy(failure); i.failureControl = control; i.run = { attemptId, status: 'failed' }; invalidate(i);
  if (category === 'transient' && control.transientAttempts < POLICY.transientRetries) {
    control.nextRetryAt = now + POLICY.backoffMs[control.transientAttempts++]; control.action = 'retry'; i.status = 'todo';
  } else if (category === 'transient' || category === 'authorization') { i.status = 'blocked'; control.action = 'hold'; }
  else if (category === 'unknown') { i.status = 'blocked'; control.action = control.diagnosticAttempts < POLICY.diagnosticAttempts ? 'diagnose' : 'hold';
    if (control.action === 'diagnose') control.diagnosticAttempts++; }
  else {
    let repair = out.issues.find(x => x.repairForFingerprint === key && !x.archivedAt && x.status !== 'canceled');
    const requested = priority(i.basePriority ?? i.priority);
    if (!repair) {
      const repairId = 'repair-' + key;
      if (out.issues.some(x => x.id === repairId)) { control.action = 'hold'; i.status = 'blocked'; return { state: out, applied: true, action: 'hold' }; }
      const repairRoot = i.repairRoot ?? i.id;
      const repairDepth = (i.repairDepth ?? 0) + 1;
      const repairCount = out.issues.filter(x => x.repairRoot === repairRoot).length;
      if (repairDepth > POLICY.maxRepairDepth || repairCount >= POLICY.maxRepairsPerRoot) {
        control.action = 'hold'; control.holdReason = 'repair-budget-exhausted'; i.status = 'blocked';
        return { state: out, applied: true, action: 'hold' };
      }
      repair = { id: repairId, repairRoot, repairDepth, title: '修复前置：' + failure.code + ' / ' + failure.target, priority: requested, basePriority: requested,
        status: 'backlog', blockedBy: [], repairForFingerprint: key, affectedIssues: [id], createdAt: new Date(now).toISOString(),
        evidence: copy(failure), acceptanceRequired: true, scopeRevision: 1,
        affectedContexts: [{ issueId: id, title: i.title ?? '', constraints: i.description ?? '', evidence: copy(failure) }],
        description: [
          '## 修复来源',
          '受阻任务：' + i.id + '；' + (i.title ?? ''),
          '失败代码：' + failure.code + '；目标：' + failure.target + '；作用域：' + failure.scope,
          '证据指纹：' + failure.evidenceKey,
          '原始失败说明：' + (failure.message ?? '请先核对原始失败证据，不凭标题猜原因'),
          '## 执行边界',
          '先独立复现并核对原任务约束，仅修失败原因；不得修改用户模型、权限或开关，不自行重启或发布。',
          '原任务说明仅供约束与引用，不是要求本修复重做原业务：',
          i.description ?? '（原任务无说明，先按证据定位）',
          '## 验收要求',
          '提供修复差异、最小复现修复前后对照及相关回归命令和结果；不能只重复声明已完成。',
          '修复必须独立验收通过；下游在此前保持受阻，不能清空依赖或失败记录强行重跑。',
        ].join('\n'),
        comments: [], activity: [], retries: 0, version: 1, updatedAt: new Date(now).toISOString() };
      out.issues.push(repair);
    } else {
      // 已完成但同证据再次失败：修复未覆盖此故障，熔断，不重复开同因工单。
      if (repair.status === 'done') { i.status = 'blocked'; control.action = 'hold'; return { state: out, applied: true, action: 'hold' }; }
      const additional = !(repair.affectedIssues ?? []).includes(id);
      repair.affectedIssues = [...new Set([...(repair.affectedIssues ?? []), id])];
      if (additional) {
        repair.affectedContexts = [...(repair.affectedContexts ?? []), { issueId: id, title: i.title ?? '', constraints: i.description ?? '', evidence: copy(failure) }];
        repair.description = (repair.description ?? '') + '\n\n## 新增受影响任务约束引用：' + id + '\n' + (i.title ?? '') + '\n' + (i.description ?? '无额外约束') + '\n原始失败：' + (failure.message ?? failure.code);
        repair.version = (repair.version ?? 1) + 1;
        repair.updatedAt = new Date(now).toISOString();
        // 作用域变化后，先前运行中/待验收的执行与验收结果不再覆盖新范围。
        repair.scopeRevision = (repair.scopeRevision ?? 1) + 1;
        invalidate(repair);
        if (repair.run && repair.run.status !== 'failed') repair.run.status = 'interrupted';
      }
      // 人工设级不覆盖；自动创建的修复可继承更紧急的受影响任务，封顶9。
      repair.suggestedPriority = Math.max(priority(repair.basePriority ?? repair.priority), repair.suggestedPriority ?? 1, requested);
      if (repair.prioritySource !== 'user') { repair.basePriority = repair.suggestedPriority; repair.priority = repair.suggestedPriority; }
    }
    control.action = 'awaiting-repair';
    out = attachDependency(out, id, repair.id);
  }
  return { state: out, applied: true, action: out.issues.find(x => x.id === id).failureControl.action };
}
export function releaseAfterRepair(state, repairId, now = Date.now()) {
  const out = copy(state), repair = out.issues.find(x => x.id === repairId);
  if (!repair || repair.archivedAt || repair.status !== 'done' || !repair.acceptedAt || !repair.acceptanceEvidence?.passed)
    return { state: out, released: [] };
  // 只有覆盖当前作用域的验收才能解锁下游。
  if ((repair.acceptanceEvidence.scopeRevision ?? 1) !== (repair.scopeRevision ?? 1))
    return { state: out, released: [] };
  const token = repairId + ':' + repair.acceptanceEvidence.attemptId;
  if (!repair.acceptanceEvidence.attemptId) throw new Error('缺验收轮次标识');
  const released = [];
  for (const i of out.issues) {
    if (!(i.blockedBy ?? []).includes(repairId)) continue;
    // 下游可能停在“受阻”，也可能仍是“待立项”；两者都要能在前置验收完成后被放行。
    if (i.archivedAt || !['blocked', 'backlog'].includes(i.status) || i.manualHold) continue;
    // 多前置必须全部完成且独立验收，不因单个前置完成而部分解锁。
    const deps = i.blockedBy.map(id => out.issues.find(x => x.id === id));
    if (deps.some(d => !d || d.archivedAt || d.status !== 'done' || !d.acceptedAt || !d.acceptanceEvidence?.passed || !d.acceptanceEvidence.attemptId)) continue;
    const tokens = deps.map(d => d.id + ':' + d.acceptanceEvidence.attemptId).sort();
    const signature = digest(tokens);
    if ((i.recoveryHistory ?? []).some(x => x.signature === signature)) continue;
    i.recoveryHistory = [...(i.recoveryHistory ?? []), { signature, tokens, releasedAt: new Date(now).toISOString(), releasedBy: token }];
    i.blockedBy = []; i.status = 'todo'; invalidate(i); i.run = null;
    if (i.failureControl) { i.failureControl.action = 'recovered'; delete i.failureControl.nextRetryAt; }
    i.enqueuedAt = new Date(now).toISOString(); released.push(i.id);
  }
  return { state: out, released };
}

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
