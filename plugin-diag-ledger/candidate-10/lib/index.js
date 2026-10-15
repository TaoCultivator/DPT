import { recoverAfterRestart } from './restart-recovery.mjs'
import { holdInterruptedReview } from './review-interruption.mjs'
import { boundedWrite } from './bounded-write.mjs'
import { resolveFailure } from './failure-resolution.mjs'
import { migrate, effectivePriority, eligible, queue as schedulerQueue, routeFailure, releaseAfterRepair, hasCycle, openDiagnosisDisposition }  from './scheduler-core.mjs'
import { normalizeFailure } from './host-adapter.mjs'
export const inject = ['tools', 'webServer', 'fs', 'timer', 'subagents', 'agents', 'workspaceRegistry', 'agentDefaultModel', 'llm', 'shell']

export function apply(ctx) {
  const fs = ctx.fs
  const timer = ctx.timer
  const subagents = ctx.subagents
  const agents = ctx.agents
  const workspaceRegistry = ctx.workspaceRegistry
  const agentDefaultModel = ctx.agentDefaultModel
  const llm = ctx.llm
  const shell = ctx.shell

    const SEED_LABELS = [
      { name: '缺陷', color: '#eb5757' },
      { name: '特性', color: '#bb87fc' },
      { name: '改进', color: '#4ea7fc' },
      { name: 'phase-1', color: '#6f7ce8' },
      { name: 'phase-2', color: '#22b889' },
      { name: 'phase-3', color: '#f0bf00' },
      { name: 'phase-4', color: '#1687f8' },
      { name: 'phase-5', color: '#e8833a' },
      { name: 'phase-6', color: '#9aa4b2' },
    ]
    const MAX_RETRIES = 3
    const DEFAULT_LABEL_COLOR = '#8a94a6'
    // in_progress without any issue update for this long is treated as stuck
    // (5 分钟无进展 → 打回待执行；子代理失活则立即打回，不受此限)
    const STALE_EXEC_MS = 5 * 60 * 1000
    // periodic health scan interval (execution liveness, acceptance re-dispatch,
    // merge retry)
    const HEALTH_SCAN_MS = 60 * 1000

    // ---------------- per-workspace store ----------------
    const stores = new Map()
    function validatePriority(value) {
      if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 9) throw new Error('优先级必须为1–9整数，9最高')
      return value
    }
    const prioritySchema = { type: 'integer', minimum: 1, maximum: 9, description: '优先级1–9，9最高' }
    const failureSchema = { type: 'object', properties: { code: { type: 'string' }, message: { type: 'string' }, target: { type: 'string' }, scope: { type: 'string' }, evidenceKey: { type: 'string' } }, required: ['code', 'message', 'target'], additionalProperties: false }

    function emptyState() {
      return {
        version: 1, labels: SEED_LABELS.map(l => ({ ...l })), issues: [], batches: [],
        autoAccept: false, seq: 1,
        autoExec: { enabled: false, intervalSec: 60, model: null, provider: null, effort: null, concurrency: 3, promoteBacklog: true },
      }
    }

    async function loadStore(store) {
      if (!fs) { store.state = emptyState(); return }
      let target = null
      try {
        target = await fs.resolve('.dsh/kanban-state.json', { cwd: store.ws.path })
        const raw = await fs.readText(target)
        let parsed = null
        try {
          parsed = JSON.parse(raw)
        } catch (e) {
          // corrupt JSON: back up the original file, then rebuild an empty board
          await backupStateFile(store, target, raw, 'corrupt-json')
          throw new Error('看板JSON损坏，原文件保留，禁止自动清空')
        }
        if (parsed && Array.isArray(parsed.issues)) {
          parsed.labels = Array.isArray(parsed.labels) && parsed.labels.length ? parsed.labels : SEED_LABELS.map(l => ({ ...l }))
          parsed.batches = Array.isArray(parsed.batches) ? parsed.batches : []
          parsed.seq = typeof parsed.seq === 'number' ? parsed.seq : 1
          parsed.version = typeof parsed.version === 'number' ? parsed.version : 1
          parsed.autoAccept = !!parsed.autoAccept
          parsed.autoExec = parsed.autoExec && typeof parsed.autoExec === 'object'
            ? parsed.autoExec
            : { enabled: false, intervalSec: 60, model: null, provider: null, effort: null, concurrency: 3 }
          if (typeof parsed.autoExec.intervalSec !== 'number' || parsed.autoExec.intervalSec < 10) parsed.autoExec.intervalSec = 60
          if (typeof parsed.autoExec.concurrency !== 'number' || parsed.autoExec.concurrency < 1 || parsed.autoExec.concurrency > 10) parsed.autoExec.concurrency = 3
          if (typeof parsed.autoExec.promoteBacklog !== 'boolean') parsed.autoExec.promoteBacklog = true
          const migrated = migrate(parsed)
          if (parsed.schedulerSchemaVersion !== 2) {
            const backupTarget = await fs.resolve('.dsh/kanban-state.pre-scheduler-v2-' + Date.now() + '.json', { cwd: store.ws.path })
            await boundedWrite(() => fs.writeText(backupTarget, raw, { kind: 'createIfAbsent' }, undefined, { mode: 'danger-full-access', workspaceRoot: store.ws.path }))
          }
          store.state = migrated
          return
        }
        // unexpected shape: back up the original file, then rebuild an empty board
        await backupStateFile(store, target, raw, 'invalid-shape')
      } catch (e) {
        if (e && (e.code === 'ENOENT' || e.code === 'FS_NOT_FOUND')) { store.state = emptyState(); return }
        throw e // 未知错误、权限、迁移或备份失败都拒绝加载，不得覆盖原状态。
      }
      throw new Error('看板结构无效，原文件保留，禁止自动清空')
    }

    // keep a recoverable copy of a damaged state file before rebuilding
    async function backupStateFile(store, target, raw, why) {
      try {
        if (!fs || !target) return
        const bakPath = '.dsh/kanban-state.bak-' + why + '-' + Date.now().toString(36)
        const bak = await fs.resolve(bakPath, { cwd: store.ws.path })
        await boundedWrite(() => fs.writeText(bak, String(raw || ''), { kind: 'createIfAbsent' }, undefined, { mode: 'danger-full-access', workspaceRoot: store.ws.path }))
        console.warn('kanban: state file ' + why + ', backed up to ' + bak)
      } catch (e) {
        console.error('kanban: state backup failed', e)
      }
    }

    async function storeOf(workspaceId) {
      if (!workspaceRegistry) return null
      const ws = workspaceRegistry.get(workspaceId)
      if (!ws) return null
      let store = stores.get(workspaceId)
      if (!store) {
        // the store is registered BEFORE its first load finishes; concurrent
        // callers (client polling + refresh) must await the SAME loading
        // promise instead of reading store.state mid-load (TypeError: null.version)
        store = { ws, path: ws.path + '/.dsh/kanban-state.json', state: null, queue: Promise.resolve(), busy: new Set(), acceptBusy: new Set(), autoTimer: null, loading: null, mergeQueue: Promise.resolve() }
        stores.set(workspaceId, store)
        store.loading = loadStore(store).catch((e) => { stores.delete(workspaceId); throw e }).finally(() => { store.loading = null })
        await store.loading
        syncAutoTimer(store)
        // resume acceptance on (re)start: in_review issues left over from a
        // previous process would otherwise sit stuck — there is no poll that
        // scans them, only switches/batch-end trigger acceptance passes.
        // Any in-flight acceptance run belonged to the previous process and is
        // invalid now, so clear the marker first to allow re-dispatch.
        if (store.state) {
          // 统一重启恢复：执行中断自动重新入队、验收中断自动重派（各自有上限），
          // 无论自动验收是否开启都先清掉随进程失效的验收标记，否则界面会一直显示“验收中”。
          let needBatch = false
          for (const i of store.state.issues) {
            const from = i.status
            const r = recoverAfterRestart(i, Date.now(), '宿主重启中断执行')
            if (!r) continue
            if (r.action === 'requeue') {
              addComment(i, 'system', '自动恢复：宿主重启后重新入队（第 ' + r.count + ' 次）；分支与已写文件保留，续跑前先核对已有产出')
              logActivity(i, 'status', 'system', from, 'todo')
              needBatch = true
            } else if (r.action === 'hold') {
              addComment(i, 'system', '执行被连续 ' + r.count + ' 次重启打断，转为待诊断处理')
              logActivity(i, 'status', 'system', from, 'blocked')
            } else if (r.action === 'requeue-review') {
              addComment(i, 'system', '自动恢复：宿主重启后重新派发验收（第 ' + r.count + ' 次）')
            } else if (r.action === 'hold-review') {
              addComment(i, 'system', '验收被连续 ' + r.count + ' 次重启打断，转为待诊断处理')
            }
          }
          if (needBatch) scheduleBatch(store)
          if (store.state.autoAccept) scheduleAcceptancePass(store)
        }
      } else if (store.loading) {
        await store.loading
      }
      return store
    }

    // serialized mutation: fn(state) must return { commit, ...rest }; commit=true bumps version + persists
    function enqueue(store, fn) {
      const run = store.queue.then(() => fn(store.state), () => fn(store.state))
      store.queue = run.catch(() => {})
      return run
    }

    const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

    // cross-process write lock for the state file: `mkdir` is atomic, so a
    // second process cannot grab the same lock; stale locks older than 5 min
    // are force-removed so a crashed process cannot wedge persistence.
    // Same-process writes already serialize through store.queue.
    //
    // 2026-10-14 本机补丁（Windows 兼容取锁）：原实现三条命令都是 POSIX/BSD 专用——
    //   取锁 `mkdir X 2>/dev/null && echo $$ > X/pid`：Windows PowerShell 会把
    //   `2>/dev/null` 解析成写文件 `E:\dev\null`，命令直接失败（退出码 1）；
    //   判陈旧 `stat -f %m X`：BSD 语法，Windows 无此命令；
    //   释放 `rm -rf X`：PowerShell 不接受合并短开关 `-rf`。
    //   结果：取锁必然 8 秒超时 → persist() 被 catch 吞掉 → 看板状态从不落盘。
    // 2026-10-14 第二处修复（沙箱策略）：运行时 `SandboxPwshExecutor.resolve()` 的语义是
    //   `sandboxPolicy: request.sandboxPolicy ?? this.ctx.sandboxPolicy.resolve()`——
    //   插件属于「直接调用」，不传策略就落到**部署默认策略**；作者在 persist() 的注释里
    //   已写明该回落策略会拒绝写入（所以那里给 fs.writeText 显式传了 full-access），
    //   但文件锁的 shell 调用漏了同样的策略 —— 取锁即使语法正确仍会被沙箱拒掉。
    //   故下面每个 shell.resolve 都显式带上 full-access + workspaceRoot。
    // 补丁材料见 DSH-学习库 原始素材\2026-10-14-dsh-task-board-Windows取锁补丁。
    const IS_WIN = process.platform === 'win32'
    const psq = (s) => "'" + String(s).replace(/'/g, "''") + "'"
    const lockAcquireCmd = IS_WIN
      ? (lock) => `New-Item -ItemType Directory -Path ${psq(lock)} -ErrorAction Stop | Out-Null; Set-Content -Path ${psq(lock + '/pid')} -Value $PID`
      : (lock) => `mkdir ${JSON.stringify(lock)} 2>/dev/null && echo $$ > ${JSON.stringify(lock + '/pid')}`
    const lockAgeCmd = IS_WIN
      ? (lock) => `[DateTimeOffset]::new((Get-Item ${psq(lock)}).CreationTimeUtc).ToUnixTimeSeconds()`
      : (lock) => `stat -f %m ${JSON.stringify(lock)} 2>/dev/null`
    const lockRemoveCmd = IS_WIN
      ? (lock) => `Remove-Item -Recurse -Force ${psq(lock)} -ErrorAction SilentlyContinue; exit 0`
      : (lock) => `rm -rf ${JSON.stringify(lock)}`
    const makeDirCmd = IS_WIN
      ? (dir) => `New-Item -ItemType Directory -Path ${psq(dir)} -Force | Out-Null`
      : (dir) => `mkdir -p ${JSON.stringify(dir)}`

    // 2026-10-14 本机补丁 v3（真实根因）：DSH 的 shell 服务只有 resolve(request) 与
    // execute(spec)，**没有 run**。本插件沿用了旧 API `runShell(...)`，
    // 于是取锁/分支检查/合并/报告目录等所有 shell 调用都在第一步抛
    //   TypeError: shell.run is not a function
    // 诊断证据：E:\Works\DPT\.dsh\kanban-persist-error.log（2026-10-14T16:03:11Z）
    // 这里提供兼容层：有原生 run 就用原生；否则用 resolve → execute → result 组合出等价结果。
    const runShell = (async () => {
      if (shell && typeof shell.run === 'function') return shell.run.bind(shell)
      if (shell && typeof shell.execute === 'function') {
        return async (spec) => (await shell.execute(spec)).result()
      }
      return async () => ({ exitCode: 1, stdout: { text: '' }, stderr: { text: 'shell service unavailable' } })
    })

    // 2026-10-15 本机补丁 v4：文件锁改用 node:fs，**完全不走 shell**。
    // 原因链：v1 修命令方言、v2 加沙箱策略都无效（命令从未被执行），v3 修好 shell API 后
    // 依然 `state file lock timeout` —— 插件上下文的 shell 调用在本机取不到锁。
    // Node 内置 fs 没有「沙箱策略 / 命令方言 / API 版本」这三层中间态：本机桌面版就是本地进程，
    // mkdirSync 的 EEXIST 即原子取锁语义，可直接离线单测。
    async function withFileLock(ws, fn, maxWaitMs) {
      if (!ws || !ws.path) return fn()
      const { mkdirSync, rmSync, statSync, writeFileSync } = await import('node:fs')
      mkdirSync(ws.path + '/.dsh', { recursive: true })
      const lock = ws.path + '/.dsh/kanban.lock'
      const start = Date.now()
      const wait = maxWaitMs || 8000
      for (;;) {
        try {
          mkdirSync(lock)
          try { writeFileSync(lock + '/pid', String(process.pid)) } catch (e) {}
          break
        } catch (e) {
          if (e && e.code !== 'EEXIST') throw e
          try {
            const st = statSync(lock)
            if (Date.now() - st.mtimeMs > 5 * 60 * 1000) { rmSync(lock, { recursive: true, force: true }); continue }
          } catch (e2) {}
          if (Date.now() - start > wait) throw new Error('state file lock timeout')
          await sleep(200)
        }
      }
      try {
        return await fn()
      } finally {
        try { rmSync(lock, { recursive: true, force: true }) } catch (e) {}
      }
    }
    async function persist(store, baseVersion) {
      if (!fs) throw new Error('持久化服务缺失，禁止仅在内存里报告成功')
      try {
        await withFileLock(store.ws, async () => {
          const target = await fs.resolve('.dsh/kanban-state.json', { cwd: store.ws.path })
          // cross-process guard: another process may have committed a newer
          // version while we were queued — adopt it instead of overwriting
          if (typeof baseVersion === 'number') {
            try {
              const raw = await fs.readText(target)
              const parsed = JSON.parse(raw)
              if (parsed && typeof parsed.version === 'number' && parsed.version > baseVersion) {
                throw Object.assign(new Error('磁盘版本已被其它进程更新，请刷新后重试本次操作'), { code: 'STATE_VERSION_CONFLICT', latest: parsed })
              }
            } catch (e) {
              if (!e || !['ENOENT','FS_NOT_FOUND'].includes(e.code)) throw e
            }
          }
          // 2026-10-15 v4：先试 DSH 的 fs 服务（带显式 full-access 策略），失败则用 node:fs
          // 原子写（tmp + rename）。这样即使插件上下文的沙箱策略仍拒绝写，状态也一定落盘。
          const json = JSON.stringify(store.state, null, 2)
          // 宿主文件契约修正：唯一写入通道，失败不使用底层写绕过。
          await boundedWrite(() => fs.writeText(target, json, undefined, undefined, { mode: 'danger-full-access', workspaceRoot: store.ws.path }))
        })
      } catch (e) { await persistDiag(store, e); throw e }
    }

    // 2026-10-14 临时诊断（定位「状态不落盘」用；诊断完成后删除）：
    // 主进程的 console.error 没人接收，把 persist 的失败与阶段轨迹写进工作区文件。
    async function persistDiag(store, err) {
      try {
        const { appendFileSync, mkdirSync } = await import('node:fs')
        const dir = (store && store.ws && store.ws.path ? store.ws.path : '.') + '/.dsh'
        mkdirSync(dir, { recursive: true })
        const line = new Date().toISOString() + '  ' + String((err && err.stack) || err).split('\n').slice(0, 4).join(' | ') + '\n'
        appendFileSync(dir + '/kanban-persist-error.log', line)
      } catch (e2) { /* 诊断自身失败则放弃，不影响主流程 */ }
    }

    function restoreStateObject(target, value) {
      for (const key of Object.keys(target)) delete target[key]
      Object.assign(target, value)
    }
    async function mutate(store, fn) {
      if (!store.state) await loadStore(store)
      return enqueue(store, async (state) => {
        const before = structuredClone(state)
        let out
        try {
          out = await fn(state)
          if (!out || !out.commit) { restoreStateObject(state, before); return out }
          const base = before.version || 1
          state.version = base + 1
          await persist(store, base)
          return out
        } catch (error) {
          // 不更换state对象，保持已有回调对状态容器的引用；冲突时保留最新磁盘状态。
          restoreStateObject(state, error && error.code === 'STATE_VERSION_CONFLICT' && error.latest ? migrate(error.latest) : before)
          throw error
        }
      })
    }

    // ---------------- issue helpers ----------------
    function sessionCwd(session) {
  try {
    if (session && session.header && typeof session.header.cwd === 'string' && session.header.cwd) return session.header.cwd
    if (session && session.meta && typeof session.meta.cwd === 'string' && session.meta.cwd) return session.meta.cwd
  } catch (e) {}
  return null
}
    function nextId(state) { return 'k-' + Date.now().toString(36) + '-' + (state.seq++) }
    function findIssue(state, id) { return state.issues.find(i => i.id === id) }
    function logActivity(issue, kind, by, from, to, extra) {
      issue.activity = issue.activity || []
      issue.activity.push(Object.assign({ at: new Date().toISOString(), kind, by }, from !== undefined ? { from } : {}, to !== undefined ? { to } : {}, extra || {}))
      issue.version = (issue.version || 1) + 1
      issue.updatedAt = new Date().toISOString()
    }
    function addComment(issue, who, text) {
      issue.comments = issue.comments || []
      issue.comments.push({ who, at: new Date().toISOString(), text })
      if (who !== 'user') issue.unread = true
      issue.updatedAt = new Date().toISOString()
    }
    function validLabel(state, name) {
      if (!name) return null
      const n = String(name).trim()
      const found = (state.labels || []).find(l => l.name === n)
      if (found) return n
      const color = n.startsWith('phase') ? '#6f7ce8' : DEFAULT_LABEL_COLOR
      state.labels.push({ name: n, color })
      return n
    }
    function issueView(i) {
      return {
        id: i.id, title: i.title, description: i.description || '', status: i.status, priority: i.basePriority ?? i.priority ?? 1, basePriority: i.basePriority ?? i.priority ?? 1, effectivePriority: effectivePriority(i),
        labels: i.labels || [], dueDate: i.dueDate || null, assignee: i.assignee || null,
        participants: i.participants || [], parentId: i.parentId || null, blockedBy: i.blockedBy || [],
        blocks: i.blocks || [], related: i.related || [], comments: i.comments || [], activity: i.activity || [],
        run: i.run ? { batchId: i.run.batchId || null, subagentId: i.run.subagentId || null, status: i.run.status || 'done' } : null,
        acceptanceSubagentId: i.acceptanceSubagentId || null,
        retries: i.retries || 0, unread: !!i.unread, archivedAt: i.archivedAt || null,
        version: i.version || 1, createdAt: i.createdAt, updatedAt: i.updatedAt,
        lastFailure: i.lastFailure || null, acceptedAt: i.acceptedAt || null, repairForFingerprint: i.repairForFingerprint || null, diagnosisForFingerprint: i.diagnosisForFingerprint || null, repairRoot: i.repairRoot || null, affectedIssues: i.affectedIssues || [],
        failureControl: i.failureControl || null, diagnosticRecoveryHistory: i.diagnosticRecoveryHistory || [], manualHold: !!i.manualHold, acceptanceEvidence: i.acceptanceEvidence || null, reviewInterruption: i.reviewInterruption || null,
      }
    }
    function stateView(store) {
      const s = store.state || emptyState()
      return {
        version: s.version,
        autoAccept: !!s.autoAccept,
        autoExec: s.autoExec || { enabled: false, intervalSec: 60, model: null, provider: null, effort: null, concurrency: 3, promoteBacklog: true },
        labels: s.labels || [],
        statePath: store.path,
        issues: s.issues.map(i => Object.assign(issueView(i), {
          children: s.issues.filter(c => c.parentId === i.id).map(c => c.id),
        })),
        batches: (s.batches || []).map(b => ({ id: b.id, status: b.status, issueIds: (b.issueIds || []).slice(), startedAt: b.startedAt, finishedAt: b.finishedAt })),
      }
    }

    const TRANSITIONS = {
      backlog: ['todo', 'canceled'],
      todo: ['in_progress', 'backlog', 'canceled'],
      in_progress: ['blocked', 'todo', 'canceled'],
      blocked: ['todo', 'canceled'],
      in_review: ['done', 'todo', 'canceled'],
      done: ['todo'],
      canceled: ['backlog'],
    }

    // ---------------- execution engine ----------------
    function pickParent(ws) {
      try {
        const init = agents && typeof agents.currentInitiator === 'function' ? agents.currentInitiator() : undefined
        if (init) {
          // only use the initiator while it is still LIVE: a disposed agent's ctx
          // is inactive and subagents.start would throw
          // "cannot create effect on inactive context" when it registers effects
          let live = false
          try {
            if (agents && typeof agents.get === 'function' && init.session) {
              live = agents.get(init.session.id) === init
            }
          } catch (e) { live = false }
          if (live) return init
        }
      } catch (e) {}
      if (agents) {
        // 1) any live agent bound to this workspace
        for (const sid of ws.sessionIds) {
          const a = agents.get(sid)
          if (a) return a
        }
        // 2) fallback: any live agent in this process. The executor/acceptance
        // prompt pins the exact workspace path, so the host session only needs
        // to be alive — restart windows or cross-session workspaces can leave
        // the workspace's session list without a live agent (previously the
        // board wrote "没有可用的宿主会话" and left issues stuck).
        if (typeof agents.list === 'function') {
          try {
            const all = agents.list()
            if (all && all.length) return all[0]
          } catch (e) {}
        }
      }
      return null
    }

    function makeSignal() {
      return {
        aborted: false,
        throwIfAborted() { if (this.aborted) { const e = new Error('aborted'); e.name = 'AbortError'; throw e } },
        addEventListener() {},
        removeEventListener() {},
        dispatchEvent() { return true },
      }
    }

    const EXECUTOR_PERSONA = [
      'You are the executor subagent of an agent-driven feature board. You implement one issue card inside the current workspace directory.',
      'Work completely independently: never ask the user questions, never wait for confirmation. Use the standard tools to inspect and modify the workspace.',
      'Follow the instructions in the delegated task message exactly. When finished, answer with the structured result defined by the requested output schema.',
    ].join('\n')

    const ACCEPT_PERSONA = [
      'You are the acceptance subagent of an agent-driven feature board. You independently verify one issue card against its requirements inside the current workspace directory.',
      'Do not ask the user. Inspect the actual workspace state and run relevant verification commands before judging. Judge only the workspace, never other sessions.',
      'When finished, answer with the structured result defined by the requested output schema: verdict pass or fail, plus a report.',
    ].join('\n')

    function buildExecutorPrompt(issue, ws) {
      return [
        '功能看板执行任务。请在工作区中实现下面的议题。',
        '',
        '工作区: ' + ws.title + ' (' + ws.path + ')',
        '议题: [' + issue.id + '] ' + issue.title,
        '描述: ' + (issue.description || '（无）'),
        '优先级: ' + issue.priority,
        '标签: ' + ((issue.labels || []).join(', ') || '无'),
        '截止日期: ' + (issue.dueDate || '无'),
        '',
        (issue.comments || []).length ? '先前记录（可能包含被中断的上一轮）：\n' + (issue.comments || []).slice(-3).map(c => '- [' + c.who + '] ' + String(c.text || '').slice(0, 200)).join('\n') : '',
        '',
        '要求:',
        '失败时如有实证请返回 failure 对象，含 code/message/target/scope/evidenceKey；未知原因明确 UNKNOWN，不编造代码来强行重试。',
        '1. 若工作区是 git 仓库，优先在独立 worktree 中实现：git worktree add ../' + ws.title + '-vk-' + issue.id + ' -b vk/' + issue.id + '（如失败可退回直接修改）。',
        '2. 实现后运行测试/验证命令，确认通过后再提交。',
        '3. 按输出 schema 返回结构化结果：status=done 表示完成，summary 写明改动内容、验证命令与结果、剩余风险，files 列出变更文件；status=failed 表示失败，reason 写明失败原因。',
        '4. 汇报保持精简：summary/reason 只写要点（对话中勿输出长文或大段命令输出），文件路径引用优先；完整内容按需自行写入工作区 .dsh/kanban-reports/ 下文件并在 summary 中给出路径。',
        '5. 禁止自行合并或修改 master/主分支：只提交并 push 你自己的 vk/<id> 分支；代码合并由看板在验收通过后自动执行（不要执行 git merge/checkout master/git pull 到主分支）。',
        '6. 不要询问用户，自主决策并回报。',
      ].join('\n')
    }

    function buildAcceptancePrompt(issue, ws) {
      const comments = (issue.comments || []).map(c => '- [' + c.who + ' ' + c.at + '] ' + c.text).join('\n')
      return [
        '功能看板验收任务。请对下面议题做独立验收。',
        '',
        '工作区: ' + ws.title + ' (' + ws.path + ')',
        '议题: [' + issue.id + '] ' + issue.title,
        '需求描述: ' + (issue.description || '（无）'),
        '标签: ' + ((issue.labels || []).join(', ') || '无'),
        '',
        '相关记录:',
        comments || '（无）',
        '',
        '要求:',
        '1. 在工作区检查该需求是否真正实现（查看代码与改动），运行相关测试/验证命令。',
        '2. 只依据工作区当前状态独立判断。',
        '3. 按输出 schema 返回结构化结果：verdict=pass 通过；verdict=fail 打回，report 写明测试结果与具体返工点。',
        '4. 汇报保持精简：report 只写结论与返工点，不要输出大段日志或长文；需要完整证据时引用工作区文件路径。',
      ].join('\n')
    }

    // git branch of the main repo right now (null for non-git workspaces)
    async function currentBranch(ws) {
      if (!shell || !ws || !ws.path) return null
      try {
        const r = await runShell({
          command: `git -C ${JSON.stringify(ws.path)} branch --show-current`,
          timeoutMs: 15000,
          stdoutMaxBytes: 4096,
        })
        if (r.exitCode !== 0) return null
        const b = String((r.stdout && r.stdout.text) || '').trim()
        return b || null
      } catch (e) { return null }
    }

    // write a full report under .dsh/kanban-reports/ and return its relative
    // path — comments carry only a short first line plus this reference, so
    // the conversation stays lean while the full detail stays on disk
    async function saveReport(ws, name, text) {
      if (!ws || !ws.path || !fs) return null
      // 仅允许文件名，避免模型返回的名字逃逸报告目录。
      if (!/^[a-zA-Z0-9._-]+$/.test(name)) return null
      try {
        const target = await fs.resolve('.dsh/kanban-reports/' + name, { cwd: ws.path })
        await boundedWrite(() => fs.writeText(target, String(text || ''), undefined, undefined, { mode: 'danger-full-access', workspaceRoot: ws.path }))
        return '.dsh/kanban-reports/' + name
      } catch (error) { return null } // 不伪报不存在的报告链接；业务状态仍由主事务保存。
    }

    // merge the executor's vk/<id> branch back into the branch the task
    // started from, then clean up the worktree and branch. Called after the
    // issue reaches done (automatic or manual acceptance). Merges run ONE at
    // a time per workspace: several acceptance passes finishing together must
    // not race git merge into the same base branch (conflicts/aborted merges).
    async function mergeIssueBranch(store, cur) {
      if (!shell || !cur || !cur.id) return
      const ws = store.ws
      const branch = 'vk/' + cur.id
      const base = cur.baseBranch
      if (!base) return // non-git workspace or no baseline recorded
      const run = store.mergeQueue.then(() => doMerge(store, ws, cur, branch, base))
      store.mergeQueue = run.catch(() => {})
      await run
    }

    async function doMerge(store, ws, cur, branch, base) {
      try {
        const exists = await runShell({
          command: `git -C ${JSON.stringify(ws.path)} rev-parse --verify --quiet ${JSON.stringify(branch)}`,
          timeoutMs: 15000,
          stdoutMaxBytes: 4096,
        })
        if (exists.exitCode !== 0) return // executor never created the branch
        const r = await runShell({
          command: `git -C ${JSON.stringify(ws.path)} merge --no-ff -m "看板合并: ${cur.id} 验收通过" ${JSON.stringify(branch)}`,
          timeoutMs: 120000,
          stdoutMaxBytes: 8192,
        })
        if (r.exitCode !== 0) {
          await mutate(store, (s) => {
            const c = findIssue(s, cur.id)
            if (c) addComment(c, 'system', '合并分支 ' + branch + ' → ' + base + ' 失败（可能冲突）: ' + String((r.stderr && r.stderr.text) || '').slice(0, 200))
            c.mergeFails = (c.mergeFails || 0) + 1
            return { commit: true }
          })
          return
        }
        // cleanup: remove the executor worktree and delete the merged branch
        try {
          await runShell({
            command: `git -C ${JSON.stringify(ws.path)} worktree remove --force ${JSON.stringify('../' + ws.title + '-vk-' + cur.id)}`,
            timeoutMs: 30000,
            stdoutMaxBytes: 4096,
          })
        } catch (e) {}
        try {
          await runShell({
            command: `git -C ${JSON.stringify(ws.path)} branch -D ${JSON.stringify(branch)}`,
            timeoutMs: 30000,
            stdoutMaxBytes: 4096,
          })
        } catch (e) {}
        await mutate(store, (s) => {
          const c = findIssue(s, cur.id)
          if (c) { addComment(c, 'system', '已合并 ' + branch + ' → ' + base + '（验收通过）'); c.mergeFails = 0 }
          return { commit: true }
        })
      } catch (e) {
        // ignore transient failures; a comment is nice-to-have only
      }
    }

    async function updateBatchStatus(store, batchId) {
      await mutate(store, (s) => {
        const b = (s.batches || []).find(x => x.id === batchId)
        if (!b) return { commit: false }
        const open = s.issues.filter(i => i.run && i.run.batchId === batchId && (i.status === 'in_progress' || i.status === 'todo'))
        if (!open.length) { b.status = 'done'; b.finishedAt = new Date().toISOString() }
        return { commit: true }
      })
    }

    // 本机候选修复：异步结果只能由仍持有本轮执行权的回调写回。
    // 以批次唯一标识作执行令牌，验收另用唯一令牌；人工流转立即撤销令牌。
    // 本轮候选将失败处理和验收依赖解锁统一到纯规则核心。
    function applyRoutedFailure(state, id, attemptId, failure) {
      const routed = routeFailure(state, id, attemptId, normalizeFailure(failure), Date.now())
      if (!routed.applied) return { commit: false }
      Object.assign(state, routed.state)
      const cur = findIssue(state, id)
      cur.retries = (cur.retries || 0) + 1 // 仅作审计历史；不得用历史次数绕过新失败策略。
      addComment(cur, 'system', '失败分流: ' + routed.action + '；' + (cur.lastFailure.message || '原因待诊断'))
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
      return { commit: true, action: routed.action }
    }
    function releaseRepairedDependents(state, id) {
      const released = releaseAfterRepair(state, id, Date.now())
      if (released.released.length) Object.assign(state, released.state)
      return released.released
    }
    function retryGuard(issue) {
      if (issue.archivedAt) return '任务已归档'
      if ((issue.blockedBy || []).length) return '前置修复尚未验收完成，禁止重试'
      if (['hold','awaiting-repair','diagnose'].includes(issue.failureControl && issue.failureControl.action)) return '失败原因尚未解除，禁止原地重试'
      if (issue.failureControl && issue.failureControl.nextRetryAt > Date.now()) return '尚在退避等待窗口'
      return null
    }
    function manualReview(state, id, passed, report, failure) {
      const cur = findIssue(state, id)
      if (!cur || cur.status !== 'in_review') return { ok: false, message: '议题不在待验收状态' }
      if ((cur.blockedBy || []).length || cur.archivedAt) return { ok: false, message: '受阻或归档任务不能绕过前置验收' }
      if (!passed) {
        const executionAttempt = (cur.run && cur.run.attemptId) || ('manual-' + Date.now().toString(36))
        invalidateIssueAttempt(cur)
        cur.run = { attemptId: executionAttempt, status: 'running' }
        cur.status = 'in_progress'
        const out = applyRoutedFailure(state, id, executionAttempt, { failure, reason: report || '用户打回，原因待诊断' })
        return { ...out, ok: true, passed: false, message: '已按失败原因挂起或退避，不直接重试' }
      }
      if (!String(report || '').trim()) return { ok: false, message: '修复验收必须提供证据说明' }
      const executionAttempt = cur.run && cur.run.attemptId
      invalidateIssueAttempt(cur)
      cur.status = 'done'
      cur.acceptedAt = new Date().toISOString()
      cur.acceptanceEvidence = { passed: true, attemptId: 'manual-review-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2), executionAttemptId: executionAttempt, report, source: 'user' }
      addComment(cur, 'user', '验收通过: ' + report)
      logActivity(cur, 'status', 'user', 'in_review', 'done')
      const released = releaseRepairedDependents(state, id)
      return { commit: true, ok: true, passed: true, released, version: cur.version, message: '验收通过' }
    }
    function invalidateIssueAttempt(issue) {
      if (issue.run) issue.run.attemptId = null
      issue.acceptanceAttemptId = null
      issue.acceptanceSubagentId = null
    }
    function executorOwns(issue, batchId) {
      return !!issue && !issue.archivedAt && issue.status === 'in_progress'
        && !(issue.blockedBy || []).length && !!issue.run
        && issue.run.batchId === batchId && issue.run.attemptId === batchId
        && issue.run.status === 'running'
    }
    function acceptanceOwns(issue, attemptId) {
      return !!issue && !issue.archivedAt && issue.status === 'in_review'
        && !(issue.blockedBy || []).length && issue.acceptanceAttemptId === attemptId
    }

    async function runExecutorForIssue(store, issue) {
      const ws = store.ws
      const parent = pickParent(ws)
      if (!parent) {
        await mutate(store, (s) => {
          const cur = findIssue(s, issue.id)
          if (cur && cur.status === 'todo') { cur.status = 'blocked'; addComment(cur, 'system', '没有可用的宿主会话，无法派发执行'); logActivity(cur, 'status', 'system', 'todo', 'blocked') }
          return { commit: true }
        })
        return
      }
      const batch = { id: 'batch-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e4), status: 'running', issueIds: [issue.id], startedAt: new Date().toISOString(), finishedAt: null }
      // record the branch the executor will fork from (git workspaces only),
      // so a later merge-after-acceptance knows where to land
      const baseBranch = await currentBranch(store.ws)
      const claimed = await mutate(store, (s) => {
        const cur = findIssue(s, issue.id)
        if (!cur || !eligible(cur, Date.now())) return { commit: false }
        s.batches.push(batch)
        cur.status = 'in_progress'
        cur.run = { batchId: batch.id, attemptId: batch.id, subagentId: null, status: 'running' }
        cur.baseBranch = baseBranch
        logActivity(cur, 'status', 'system', 'todo', 'in_progress')
        return { commit: true }
      })
      // another executor already claimed this issue while we were waiting:
      // do NOT spawn a duplicate subagent (parallel batch safety)
      if (!claimed || !claimed.commit) return

      let run = null
      try {
        const auto = (store.state && store.state.autoExec) || {}
        run = await subagents.start('spawn', {
          label: 'executor-' + issue.id,
          prompt: [{ type: 'text', text: buildExecutorPrompt(issue, ws) }],
          persona: EXECUTOR_PERSONA,
          outputSchema: {
            type: 'object',
            properties: {
              status: { type: 'string', enum: ['done', 'failed'] },
              summary: { type: 'string' },
              reason: { type: 'string' },
              files: { type: 'array', items: { type: 'string' } },
              failure: failureSchema,
            },
            required: ['status'],
            additionalProperties: false,
          },
          parent,
          signal: makeSignal(),
          ...childModelOptions(store) !== undefined ? { agentOptions: childModelOptions(store) } : {},
        })
      } catch (e) {
        await mutate(store, (s) => {
          const cur = findIssue(s, issue.id)
          if (!executorOwns(cur, batch.id)) return { commit: false }
          return applyRoutedFailure(s, issue.id, batch.id, { error: { code: e.code, message: String(e), target: 'subagent-dispatch', scope: store.ws.id || store.ws.path } })
        })
        await updateBatchStatus(store, batch.id)
        return
      }

      await mutate(store, (s) => {
        const cur = findIssue(s, issue.id)
        if (!executorOwns(cur, batch.id)) return { commit: false }
        cur.run.subagentId = run.id
        return { commit: true }
      })

      const detachEffort = attachEffort(run, (store.state && store.state.autoExec && store.state.autoExec.effort) || null)

      let result = null
      try { result = await run.result } catch (e) { result = { error: { code: e.code, message: String(e), target: 'subagent-result', scope: store.ws.id || store.ws.path } } }
      try { detachEffort() } catch (e) {}
      try { await run.dispose() } catch (e) {}

      const structured = result && result.structured
      const stopReason = result && result.stopReason
      // keep the conversation lean: full summary/reason goes to a report file,
      // the comment carries the first line plus the file reference
      let reportPath = null
      if (structured && (structured.summary || structured.reason)) {
        const title = structured.status === 'done' ? '执行报告' : '执行失败报告'
        const files = (structured.files || []).length ? '\n\n变更文件:\n' + structured.files.map(f => '- ' + f).join('\n') : ''
        reportPath = await saveReport(store.ws, 'executor-' + issue.id + '-' + batch.id + '.md', '## ' + title + ' ' + issue.id + '\n\n' + (structured.summary || '') + (structured.reason ? '\n\n失败原因:\n' + structured.reason : '') + files + '\n')
      }
      const firstLine = (t) => String(t || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || ''
      await mutate(store, (s) => {
        const cur = findIssue(s, issue.id)
        if (!executorOwns(cur, batch.id)) return { commit: false }
        const ok = structured && structured.status === 'done' && (stopReason === 'completed' || stopReason === undefined)
        if (ok) {
          cur.status = 'in_review'
          cur.restartRecoveries = 0
          cur.run = { batchId: batch.id, attemptId: batch.id, subagentId: run.id, status: 'done' }
          addComment(cur, 'executor', '完成: ' + firstLine(structured.summary).slice(0, 120) + (reportPath ? '（详见 ' + reportPath + '）' : ''))
          logActivity(cur, 'status', 'executor', 'in_progress', 'in_review')
        } else if (stopReason === 'aborted' || (result && result.error && result.error.name === 'AbortError')) {
          // 宿主关闭或子代理被取消：这不是业务失败，保留现场交给重启恢复自动续跑。
          cur.status = 'in_progress'
          cur.run = { ...(cur.run || {}), attemptId: null, subagentId: null, status: 'interrupted' }
          addComment(cur, 'executor', '执行被中断（宿主关闭或取消），保留现场，等待自动续跑')
          return { commit: true }
        } else {
          const reason = (structured && structured.reason) || '执行未返回有效结果'
          return applyRoutedFailure(s, issue.id, batch.id, { failure: structured && structured.failure, error: result && result.error, reason })
        }
        return { commit: true }
      })
      await updateBatchStatus(store, batch.id)
    }

    // 待立项进入自动化流程：开关统一控制人工新建与失败自动生成的修复前置。
    // 你手动拖回待立项（manualHold）视为停用；有前置依赖、有父任务、已归档、重试耗尽的一律不动。
    async function promoteEligibleBacklog(store) {
      const auto = store.state && store.state.autoExec
      if (!auto || !auto.enabled || !auto.promoteBacklog) return 0
      let promoted = 0
      await mutate(store, (s) => {
        let touched = false
        const now = new Date().toISOString()
        // 前置都已完成且独立验收的，先解除依赖（包括历史上停在待立项的下游）
        for (const i of s.issues) {
          if (i.archivedAt || i.manualHold || !(i.blockedBy || []).length) continue
          if (!['backlog', 'blocked'].includes(i.status)) continue
          const deps = i.blockedBy.map(did => findIssue(s, did))
          if (deps.some(d => !d || d.status !== 'done' || !d.acceptedAt || !(d.acceptanceEvidence && d.acceptanceEvidence.passed))) continue
          i.blockedBy = []
          if (i.failureControl) i.failureControl.action = 'recovered'
          i.status = 'backlog'
          i.blockedByCleared = (i.blockedByCleared || 0) + 1
          addComment(i, 'system', '前置已全部验收完成，自动解除依赖并进入待领取')
          touched = true
        }
        for (const i of s.issues) {
          if (i.status !== 'backlog' || i.archivedAt || i.manualHold || i.parentId) continue
          if ((i.blockedBy || []).length) continue
          // 不再用 retries 卡领取：失败会按原因转入受阻或修复前置，天然有界。
          if (i.failureControl && ['hold', 'awaiting-repair', 'diagnose'].includes(i.failureControl.action)) continue
          i.status = 'todo'
          i.enqueuedAt = now
          addComment(i, 'system', i.repairForFingerprint ? '自动领取：修复前置转入等待认领' : (i.diagnosisForFingerprint ? '自动领取：诊断处置卡转入等待认领（先查决策台账，命中即处理）' : '自动领取：待立项已按开关转入等待认领'))
          logActivity(i, 'status', 'system', 'backlog', 'todo')
          touched = true
        }
        if (touched) promoted = 1
        return touched ? { commit: true } : { commit: false }
      })
      return promoted
    }

    async function runBatchLoop(store) {
      if (store.busy.has('batch')) { store.batchWakeRequested = true; return }
      store.busy.add('batch')
      try {
        try { await promoteEligibleBacklog(store) } catch (e) { console.error('kanban: backlog promotion failed', e) }
        // independent (unlinked) todo issues run in parallel sub-agents — no
        // conflict: git workspaces isolate each executor in its own worktree;
        // non-git workspaces fall back to sequential to avoid shared-dir clashes
        let isGit = false
        if (fs && store.ws && store.ws.path) {
          try { await fs.resolve('.git', { cwd: store.ws.path }); isGit = true } catch (e) { isGit = false }
        }
        // concurrency is user-configurable per workspace (autoExec.concurrency,
        // default 3); non-git workspaces stay sequential to avoid shared-dir clashes
        const auto = store.state.autoExec || {}
        const limit = isGit ? Math.max(1, Math.min(10, Number(auto.concurrency) || 3)) : 1
        const workers = []
        for (let w = 0; w < limit; w++) {
          workers.push((async () => {
            for (;;) {
              const id = schedulerQueue(store.state, Date.now()).find(id => !store.busy.has('claim:' + id))
              if (!id) break
              store.busy.add('claim:' + id)
              try {
                const candidate = findIssue(store.state, id)
                if (candidate) await runExecutorForIssue(store, candidate)
              } finally { store.busy.delete('claim:' + id) }
            }
          })())
        }
        await Promise.all(workers)
      } catch (e) {
        console.error('kanban: batch loop failed', e)
      } finally {
        store.busy.delete('batch')
        if (store.batchWakeRequested) {
          store.batchWakeRequested = false
          if (schedulerQueue(store.state, Date.now()).length) scheduleBatch(store)
        }
      }
      if (store.state.autoAccept) void runAcceptancePass(store).catch((e) => console.error('kanban: acceptance pass failed', e))
    }

    function scheduleBatch(store) {
      // timer.timeout registers a fiber effect and throws "cannot create effect
      // on inactive context" when called from an async callback after the
      // plugin fiber settled — fall back to a direct run in that case
      if (timer) {
        try {
          timer.timeout(() => { void runBatchLoop(store) }, 150)
          return
        } catch (e) { /* fall through to direct run */ }
      }
      void runBatchLoop(store)
    }

    // keep the per-workspace auto-exec poll timer in sync with store.state.autoExec
    function syncAutoTimer(store) {
      if (store.autoTimer) {
        try { store.autoTimer() } catch (e) {}
        store.autoTimer = null
      }
      if (!timer || !store.state || !store.state.autoExec || !store.state.autoExec.enabled) return
      const sec = Math.max(10, Number(store.state.autoExec.intervalSec) || 60)
      store.autoTimer = timer.interval(() => {
        if (!store.state || !store.state.autoExec || !store.state.autoExec.enabled) return
        if (store.busy.has('batch')) return
        // poll: dispatch pending todo issues, and let eligible backlog in through
        // the promotion step that runs inside the batch loop
        const st = store.state
        const pending = schedulerQueue(st, Date.now()).length > 0
        const promotable = !!st.autoExec.promoteBacklog && st.issues.some(i => {
          if (!['backlog', 'blocked'].includes(i.status) || i.archivedAt || i.manualHold || i.parentId) return false
          if (i.failureControl && ['hold', 'awaiting-repair', 'diagnose'].includes(i.failureControl.action)) return false
          if (!(i.blockedBy || []).length) return i.status === 'backlog'
          // 有前置但前置已全部独立验收完成的，也算“可以做”，触发一次释放
          const deps = i.blockedBy.map(did => findIssue(st, did))
          return deps.every(d => d && d.status === 'done' && d.acceptedAt && d.acceptanceEvidence && d.acceptanceEvidence.passed)
        })
        if (pending || promotable) void runBatchLoop(store)
      }, sec * 1000)
    }

    function childModelOptions(store) {
      const auto = (store && store.state && store.state.autoExec) || {}
      const opts = {}
      if (auto.provider) opts.provider = auto.provider
      if (auto.model) opts.model = auto.model
      return Object.keys(opts).length ? opts : undefined
    }

    // inject a fixed reasoningEffort into the live child's request pipeline
    function attachEffort(run, effort) {
      if (!effort || !run || !run.localAgent) return () => {}
      let disposed = false
      let disposer = () => {}
      try {
        disposer = run.localAgent.ctx.on('agent/request', async (_payload, next) => {
          const resolved = await next()
          if (disposed || !resolved || typeof resolved !== 'object') return resolved
          return Object.assign({}, resolved, { reasoningEffort: effort })
        })
      } catch (e) { /* child pipeline unavailable; skip effort */ }
      return () => { disposed = true; try { disposer() } catch (e) {} }
    }

    async function runAcceptanceForIssue(store, id) {
      const issue = findIssue(store.state, id)
      if (!issue || issue.status !== 'in_review' || issue.archivedAt || (issue.blockedBy || []).length) return
      const ws = store.ws
      const parent = pickParent(ws)
      if (!parent) {
        await mutate(store, (s) => { const cur = findIssue(s, id); if (cur) addComment(cur, 'system', '验收派发失败: 没有可用的宿主会话'); return { commit: true } })
        return
      }
      const attemptId = 'accept-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)
      const claim = await mutate(store, (s) => {
        const cur = findIssue(s, id)
        if (!cur || cur.status !== 'in_review' || cur.archivedAt || (cur.blockedBy || []).length || cur.acceptanceAttemptId || cur.acceptanceSubagentId) return { commit: false }
        cur.acceptanceAttemptId = attemptId
        cur.acceptanceScopeRevision = cur.scopeRevision ?? 1
        return { commit: true }
      })
      if (!claim || !claim.commit) return
      let run = null
      try {
        run = await subagents.start('spawn', {
          label: 'acceptance-' + id,
          prompt: [{ type: 'text', text: buildAcceptancePrompt(issue, ws) }],
          persona: ACCEPT_PERSONA,
          outputSchema: {
            type: 'object',
            properties: { verdict: { type: 'string', enum: ['pass', 'fail'] }, report: { type: 'string' }, failure: failureSchema },
            required: ['verdict'],
            additionalProperties: false,
          },
          parent,
          signal: makeSignal(),
          ...childModelOptions(store) !== undefined ? { agentOptions: childModelOptions(store) } : {},
        })
      } catch (e) {
        await mutate(store, (s) => { const cur = findIssue(s, id); if (!acceptanceOwns(cur, attemptId)) return { commit: false }; cur.acceptanceAttemptId = null; addComment(cur, 'system', '验收派发失败: ' + String(e)); return { commit: true } })
        return
      }
      await mutate(store, (s) => { const cur = findIssue(s, id); if (!acceptanceOwns(cur, attemptId)) return { commit: false }; cur.acceptanceSubagentId = run.id; return { commit: true } })

      const detachEffort = attachEffort(run, (store.state && store.state.autoExec && store.state.autoExec.effort) || null)

      let result = null
      try { result = await run.result } catch (e) { result = { error: { code: e.code, message: String(e), target: 'subagent-result', scope: store.ws.id || store.ws.path } } }
      try { detachEffort() } catch (e) {}
      try { await run.dispose() } catch (e) {}
      const structured = result && result.structured
      // keep the conversation lean: full acceptance report to a file, comment
      // carries the first line plus the reference
      const firstLine = (t) => String(t || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || ''
      let acceptReportPath = null
      if (structured && structured.report) {
        acceptReportPath = await saveReport(store.ws, 'acceptance-' + id + '-' + attemptId + '.md', '## 验收报告 ' + id + '\n\n' + structured.report + '\n')
      }
      const out = await mutate(store, (s) => {
        const cur = findIssue(s, id)
        if (!acceptanceOwns(cur, attemptId) || cur.acceptanceSubagentId !== run.id) return { commit: false }
        if ((cur.acceptanceScopeRevision ?? 1) !== (cur.scopeRevision ?? 1)) return { commit: false, stale: true }
        cur.acceptanceAttemptId = null
        cur.acceptanceScopeRevision = null
        cur.acceptanceSubagentId = null
        cur.reviewRestartRecoveries = 0
        if (structured && structured.verdict === 'pass') {
          cur.status = 'done'
          cur.acceptedAt = new Date().toISOString()
          cur.acceptanceEvidence = { passed: true, attemptId, executionAttemptId: cur.run && cur.run.attemptId, scopeRevision: cur.scopeRevision ?? 1, report: (structured && structured.report) || '' }
          addComment(cur, 'acceptance', '验收通过: ' + firstLine(structured.report).slice(0, 120) + (acceptReportPath ? '（详见 ' + acceptReportPath + '）' : ''))
          logActivity(cur, 'status', 'acceptance', 'in_review', 'done')
        } else if (!structured || !structured.verdict) {
          // 验收子代理被中断（宿主关闭等）没有返回结论：这不是验收不通过，
          // 保留执行成果留在待验收，等下一次验收派发接手。
          addComment(cur, 'system', '验收被中断（未返回结论），保留执行成果，等待重新派发验收')
          return { commit: true, interrupted: true }
        } else {
          cur.status = 'in_progress'
          cur.run.status = 'running'
          const acceptReport = String((structured && structured.report) || '验收未通过')
          // 验收打回=交付没满足验收判据：给一个明确的机器码，让失败分流自动开修复前置，
          // 而不是落入"未知原因、等人工给诊断证据"。
          const acceptFailure = (structured && structured.failure) || {
            code: 'ACCEPTANCE_CRITERIA_UNMET',
            message: acceptReport.slice(0, 1500),
            target: id,
            scope: store.ws.id || store.ws.path,
            evidenceKey: acceptReportPath || ('acceptance:' + id + ':' + attemptId),
          }
          return applyRoutedFailure(s, id, cur.run.attemptId, { failure: acceptFailure, error: result && result.error, reason: acceptReport })
        }
        const released = releaseRepairedDependents(s, id)
        return { commit: true, passed: !!(structured && structured.verdict === 'pass'), released }
      })
      if (out && out.released && out.released.length) scheduleBatch(store)
      if (out && out.passed) {
        const done = findIssue(store.state, id)
        if (done) await mergeIssueBranch(store, done)
      }
      if (store.state.autoAccept) scheduleAcceptancePass(store)
    }

    async function runAcceptancePass(store) {
      const candidates = store.state.issues.filter(i => i.status === 'in_review' && !i.archivedAt && !(i.blockedBy || []).length && !i.acceptanceAttemptId && !i.acceptanceSubagentId && !store.acceptBusy.has(i.id))
      for (const issue of candidates) {
        store.acceptBusy.add(issue.id)
        void runAcceptanceForIssue(store, issue.id)
          .catch((e) => console.error('kanban: acceptance dispatch failed', e))
          .finally(() => store.acceptBusy.delete(issue.id))
      }
    }

    function scheduleAcceptancePass(store) {
      // timer.timeout registers a fiber effect and throws "cannot create effect
      // on inactive context" when called from an async callback after the
      // plugin fiber settled — fall back to a direct run in that case
      if (timer) {
        try {
          timer.timeout(() => { void runAcceptancePass(store) }, 300)
          return
        } catch (e) { /* fall through to direct run */ }
      }
      void runAcceptancePass(store)
    }

    // ---------------- periodic health scan ----------------
    // Runs every HEALTH_SCAN_MS and repairs three failure modes that the
    // event-driven triggers miss:
    //  1) in_progress zombies — the subagent is gone (process restart) or idle
    //     (finished without the state being written back), or the issue has
    //     had no update for STALE_EXEC_MS → send back to todo for re-dispatch.
    //  2) in_review whose acceptance subagent died → clear the marker so the
    //     next acceptance pass re-dispatches.
    //  3) done issues whose vk/<id> merge previously failed → retry (bounded).
    async function healthScan(store) {
      if (!store.state) return
      const now = Date.now()
      const staleMs = STALE_EXEC_MS
      const out = await mutate(store, (s) => {
        let touched = false
        for (const i of s.issues) {
          if (i.archivedAt) continue
          if (i.status === 'in_progress' && i.run && ['running', 'interrupted'].includes(i.run.status)) {
            let alive = null
            try {
              if (i.run.subagentId) alive = agents.get(i.run.subagentId) || null
            } catch (e) { alive = null }
            const running = !!alive && alive.status === 'running'
            const lastT = i.updatedAt ? new Date(i.updatedAt).getTime() : 0
            // 2026-10-15 本机补丁 v5：原判据 `!running || stale`（stale = 议题记录 5 分钟未更新）
            // 会把「子代理还活着、正在写工作树」的长任务误判为卡死并打回待执行。
            // 实测后果：00:25:40 打回时子代理仍在写文件；且批次循环是单飞的，
            // 被打回的议题仍占着 worker 槽位 → 整条队列停摆；任务永远到不了待验收。
            // 改为：子代理不在/空闲 → 立即打回；仍在运行 → 只在超过硬上限（60 分钟）时打回。
            const HARD_STALE_MS = 60 * 60 * 1000
            const hardStale = running && (now - lastT > HARD_STALE_MS)
            if (!running || hardStale) {
              const why = alive === null ? '执行子代理已失活' : (alive.status !== 'running' ? '执行子代理已空闲（未正常落盘）' : '执行超过 ' + Math.round(HARD_STALE_MS / 60000) + ' 分钟无进展')
              if (alive === null) {
                const r = recoverAfterRestart(i, Date.now(), '执行子代理失活')
                if (r && r.action === 'requeue') {
                  addComment(i, 'system', '自动恢复：执行子代理已消失，重新入队（第 ' + r.count + ' 次）')
                  logActivity(i, 'status', 'system', 'in_progress', 'todo')
                } else if (r) {
                  addComment(i, 'system', '执行被连续 ' + r.count + ' 次中断，转为待诊断处理')
                  logActivity(i, 'status', 'system', 'in_progress', 'blocked')
                }
              } else {
                invalidateIssueAttempt(i)
                if (i.run) i.run.status = 'interrupted'
                i.status = 'blocked'
                i.failureControl = { ...(i.failureControl || {}), action: 'diagnose', holdReason: why }
                addComment(i, 'system', why + '；保留成果，挂起等待诊断，不自动重试')
                logActivity(i, 'status', 'system', 'in_progress', 'blocked')
              }
              touched = true
            }
          } else if (i.status === 'in_review' && i.acceptanceSubagentId) {
            let dead = false
            try {
              dead = !agents.get(i.acceptanceSubagentId)
            } catch (e) { dead = true }
            if (dead) {
              const r = recoverAfterRestart(i, Date.now(), '验收子代理失活')
              if (r && r.action === 'requeue-review') { addComment(i, 'system', '自动恢复：验收子代理失活，重新派发验收（第 ' + r.count + ' 次）'); touched = true }
              else if (r) { addComment(i, 'system', '验收被连续 ' + r.count + ' 次中断，转为待诊断处理'); touched = true }
            }
          }
        }
        return touched ? { commit: true, touched: true } : { commit: false }
      })
      if (out && out.touched) {
        if (store.state.autoAccept) scheduleAcceptancePass(store)
        scheduleBatch(store)
      }
      // bounded merge retry for previously failed automatic merges
      for (const i of store.state.issues) {
        if (i.status === 'done' && i.baseBranch && (i.mergeFails || 0) > 0 && (i.mergeFails || 0) < 3) {
          await mergeIssueBranch(store, i)
        }
      }
    }

    async function healthScanAll() {
      for (const store of stores.values()) {
        try {
          await healthScan(store)
        } catch (e) {
          console.error('kanban: health scan failed', e)
        }
      }
    }

    // ---------------- RPC handlers ----------------
    const handlers = {
      'kanban.getWorkspaces': async () => {
        const workspaces = workspaceRegistry ? workspaceRegistry.list().map(w => ({ id: w.id, title: w.title, path: w.path, sessionCount: w.sessionIds.length })) : []
        let defaultWorkspaceId = null
        try {
          const init = agents && typeof agents.currentInitiator === 'function' ? agents.currentInitiator() : undefined
          const cwd = sessionCwd(init && init.session)
          if (cwd && workspaceRegistry) {
            const ws = await workspaceRegistry.resolveByPath(cwd)
            if (ws) defaultWorkspaceId = ws.id
          }
        } catch (e) {}
        if (!defaultWorkspaceId && workspaces.length) defaultWorkspaceId = workspaces[0].id
        return { ok: true, workspaces, defaultWorkspaceId }
      },

      'kanban.getState': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '工作区不存在或不可用' }
        return { ok: true, state: stateView(store) }
      },

      'kanban.getDashboard': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '工作区不存在或不可用' }
        const s = store.state
        const issues = s.issues || []
        const pad2 = (n) => String(n).padStart(2, '0')
        const localDate = (iso) => {
          const d = new Date(iso)
          return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
        }
        const now = new Date()
        const today = localDate(now)
        const in7Str = localDate(new Date(now.getTime() + 7 * 86400000))

        // 各状态计数（archived 按归档标记单独计，不占原状态位）
        const totals = { backlog: 0, todo: 0, in_progress: 0, in_review: 0, blocked: 0, done: 0, canceled: 0, archived: 0 }
        for (const i of issues) {
          if (i.archivedAt) totals.archived += 1
          else if (totals[i.status] !== undefined) totals[i.status] += 1
        }

        // 完成度：以「非归档、非取消」议题为交付范围
        const active = issues.filter(i => !i.archivedAt && i.status !== 'canceled')
        const completion = {
          total: active.length,
          done: active.filter(i => i.status === 'done').length,
          percent: active.length ? Math.round(active.filter(i => i.status === 'done').length / active.length * 100) : 0,
        }

        // 优先级分布（键：urgent/high/medium/low/none）
        const priority = {}
        for (const i of issues) {
          if (i.archivedAt) continue
          const p = i.priority || 'none'
          priority[p] = (priority[p] || 0) + 1
        }

        // 标签分布：每标签 { name, color, count }，颜色取自 state.labels 定义
        const labels = (s.labels || []).map(l => {
          let count = 0
          for (const i of issues) { if (!i.archivedAt && (i.labels || []).includes(l.name)) count += 1 }
          return { name: l.name, color: l.color, count }
        })

        // 贡献者：activity.by + comments.who 合并统计，排除 'system'（自动流转噪音），取 top 8
        const contrib = new Map()
        const bump = (who) => { if (!who || who === 'system') return; contrib.set(who, (contrib.get(who) || 0) + 1) }
        for (const i of issues) {
          for (const a of (i.activity || [])) bump(a.by)
          for (const c of (i.comments || [])) bump(c.who)
        }
        const contributors = Array.from(contrib.entries())
          .map(([name, count]) => ({ name, count }))
          .sort((a, b) => b.count - a.count)
          .slice(0, 8)

        // 需要关注：未读 / 阻塞（含具体列表）
        const unreadList = issues.filter(i => !i.archivedAt && i.unread).map(i => ({ id: i.id, title: i.title }))
        const blockedList = issues.filter(i => !i.archivedAt && i.status === 'blocked').map(i => ({ id: i.id, title: i.title }))
        const attention = { unread: unreadList.length, blocked: blockedList.length, unreadList, blockedList }

        // 进行中
        const inProgress = issues.filter(i => !i.archivedAt && i.status === 'in_progress').map(i => ({
          id: i.id, title: i.title, assignee: i.assignee || null,
          run: i.run ? (i.run.status || 'done') : null, priority: i.priority || 'none',
        }))

        // 7 天内到期（排除已完成/取消/归档；dueDate 为 YYYY-MM-DD 字符串，字典序即日期序）
        const dueSoon = issues
          .filter(i => !i.archivedAt && i.status !== 'done' && i.status !== 'canceled' && i.dueDate && i.dueDate >= today && i.dueDate <= in7Str)
          .map(i => ({ id: i.id, title: i.title, dueDate: i.dueDate }))
          .sort((a, b) => (a.dueDate < b.dueDate ? -1 : a.dueDate > b.dueDate ? 1 : 0))

        // 近 14 天活动条数（含今天，无活动的天补 0）
        const days = []
        for (let i = 13; i >= 0; i--) days.push({ date: localDate(new Date(now.getTime() - i * 86400000)), count: 0 })
        const byDay = {}
        for (const i of issues) for (const a of (i.activity || [])) {
          const k = localDate(a.at)
          byDay[k] = (byDay[k] || 0) + 1
        }
        for (const d of days) d.count = byDay[d.date] || 0
        const activityByDay = days

        // 有子议题的父议题完成度
        const childrenProgress = issues.filter(i => !i.archivedAt).map(i => {
          const kids = issues.filter(c => c.parentId === i.id && !c.archivedAt)
          if (!kids.length) return null
          const done = kids.filter(c => c.status === 'done').length
          return { id: i.id, title: i.title, done, total: kids.length, percent: Math.round(done / kids.length * 100) }
        }).filter(Boolean)

        // 简单进度预测：近 7 天平均每日完成数 → 剩余交付范围的预计天数（估算法，非严格统计）
        const doneByDay = {}
        for (const i of issues) for (const a of (i.activity || [])) {
          if (a.kind === 'status' && a.to === 'done') { const k = localDate(a.at); doneByDay[k] = (doneByDay[k] || 0) + 1 }
        }
        let doneSum = 0
        for (const d of days.slice(-7)) doneSum += doneByDay[d.date] || 0
        const avgDonePerDay = Math.round(doneSum / 7 * 10) / 10
        const remaining = active.filter(i => i.status !== 'done').length
        const forecast = {
          avgDonePerDay, remaining,
          estDays: avgDonePerDay > 0 ? Math.ceil(remaining / avgDonePerDay) : null,
          note: avgDonePerDay > 0 ? '' : '近 7 天无完成记录，暂无法估算',
        }

        return {
          ok: true,
          dashboard: { totals, completion, priority, labels, contributors, attention, inProgress, dueSoon, activityByDay, childrenProgress, forecast },
        }
      },

      'kanban.createIssue': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const title = args && typeof args.title === 'string' ? args.title.trim() : ''
        if (!title) return { ok: false, message: '标题不能为空' }
        let requestedPriority
        try { requestedPriority = validatePriority(args.priority ?? 1) } catch (e) { return { ok: false, message: e.message } }
        const result = await mutate(store, (s) => {
          const labels = (Array.isArray(args.labels) ? args.labels : []).map(l => validLabel(s, l)).filter(Boolean)
          const issue = {
            id: nextId(s), title, description: (args && typeof args.description === 'string' ? args.description : '') || '',
            status: 'backlog', priority: requestedPriority, basePriority: requestedPriority, prioritySource: 'user', labels,
            dueDate: args && args.dueDate || null, assignee: args && args.assignee || null,
            participants: Array.isArray(args.participants) ? args.participants.slice() : [], parentId: args && args.parentId || null, blockedBy: [], blocks: [], related: [],
            comments: [], activity: [], retries: 0, unread: false, archivedAt: null, version: 1,
            createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
          }
          s.issues.push(issue)
          logActivity(issue, 'create', 'user')
          return { commit: true, issueId: issue.id }
        })
        return { ok: true, issueId: result.issueId, message: '已创建议题 ' + result.issueId }
      },

      'kanban.updateIssue': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id, version = args && args.version
        const patch = args && args.patch
        if (!id || !patch) return { ok: false, message: '参数缺失' }
        if ('priority' in patch) { try { validatePriority(patch.priority) } catch (e) { return { ok: false, message: e.message } } }
        let releasedDueToCanceled = []
        const allowed = ['title', 'description', 'priority', 'labels', 'dueDate', 'parentId', 'blockedBy', 'blocks', 'related', 'recurrence', 'unread']
        return mutate(store, (s) => {
          const cur = findIssue(s, id)
          if (!cur) return { ok: false, message: '议题不存在' }
          if (typeof version === 'number' && cur.version !== version) return { ok: false, conflict: true, message: '该议题已在其他位置更新，看板已重新同步' }
          if ('blockedBy' in patch) {
            if (!Array.isArray(patch.blockedBy) || patch.blockedBy.some(id => !s.issues.some(i => i.id === id))) return { ok: false, message: '前置依赖不存在' }
            const removed = (cur.blockedBy || []).filter(id => !patch.blockedBy.includes(id))
            // 前置已取消、已归档或已消失时允许显式解除，避免永久锁死；其余必须独立验收完成。
            const releasable = (id) => {
              const d = findIssue(s, id)
              if (!d) return true
              if (d.status === 'canceled' || d.archivedAt) return true
              return d.status === 'done' && !!d.acceptedAt && !!(d.acceptanceEvidence && d.acceptanceEvidence.passed)
            }
            const stuck = removed.filter(id => !releasable(id))
            releasedDueToCanceled = removed.filter(id => { const d = findIssue(s, id); return !d || d.status === 'canceled' || d.archivedAt })
            if (stuck.length) return { ok: false, message: '不能移除尚未独立验收完成的前置：' + stuck.join('、') }
            const graph = s.issues.map(i => i.id === id ? { ...i, blockedBy: patch.blockedBy } : i)
            if (hasCycle(graph)) return { ok: false, message: '拒绝循环依赖' }
          }
          for (const key of allowed) {
            if (!(key in patch)) continue
            if (key === 'priority') { cur.priority = patch.priority; cur.basePriority = patch.priority; cur.prioritySource = 'user' }
            else if (key === 'labels') cur.labels = (Array.isArray(patch.labels) ? patch.labels : []).map(l => validLabel(s, l)).filter(Boolean)
            else if (key === 'blockedBy' || key === 'blocks' || key === 'related') cur[key] = Array.isArray(patch[key]) ? patch[key].slice() : []
            else if (key === 'title' && typeof patch.title === 'string') cur.title = patch.title.trim()
            else cur[key] = patch[key]
          }
          if ('blockedBy' in patch && (cur.blockedBy || []).length) invalidateIssueAttempt(cur)
          // 解除掉已取消/归档的前置后，若不再有前置就把任务重新放回队列。
          if ('blockedBy' in patch && releasedDueToCanceled.length && !(cur.blockedBy || []).length) {
            if (cur.status !== 'todo') {
              const from = cur.status
              invalidateIssueAttempt(cur)
              cur.run = null
              cur.status = 'todo'
              cur.manualHold = false
              if (cur.failureControl) cur.failureControl.action = 'recovered'
              cur.enqueuedAt = new Date().toISOString()
              addComment(cur, 'user', '前置 ' + releasedDueToCanceled.join('、') + ' 已取消/归档，任务重新入队')
              logActivity(cur, 'status', 'user', from, 'todo')
            }
          }
          const meaningful = Object.keys(patch).some(k => k !== 'labels' && k !== 'unread')
          if (meaningful) logActivity(cur, 'update', 'user')
          return { commit: true, ok: true, version: cur.version, message: '已更新' }
        })
      },

      'kanban.moveIssue': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id, to = args && args.to, version = args && args.version
        if (!id || !to) return { ok: false, message: '参数缺失' }
        const out = await mutate(store, (s) => {
          const cur = findIssue(s, id)
          if (!cur) return { ok: false, message: '议题不存在' }
          if (typeof version === 'number' && cur.version !== version) return { ok: false, conflict: true, message: '该议题已在其他位置更新，看板已重新同步' }
          const from = cur.status
          if (to === 'todo') { const denied = retryGuard(cur); if (denied) return { ok: false, message: denied } }
          if (from === to) return { ok: true, message: '已在' + to }
          const allowed = TRANSITIONS[from] || []
          if (!allowed.includes(to)) return { ok: false, message: '不允许的流转: ' + from + ' → ' + to }
          const note = args.note
          if (from === 'in_review' && (to === 'done' || to === 'todo')) return manualReview(s, id, to === 'done', note || '', args.failure)
          if (to === 'done' && from === 'in_review' && note) addComment(cur, 'user', '验收通过: ' + note)
          if (to === 'todo' && from === 'in_review') {
            if (note) addComment(cur, 'user', '打回: ' + note)
            cur.retries = (cur.retries || 0) + 1
            cur.run = { batchId: null, subagentId: null, status: 'failed' }
          }
          if (to === 'todo' && from === 'done') cur.run = { batchId: null, subagentId: null, status: 'failed' }
          if (to === 'done') cur.acceptedAt = new Date().toISOString()
          invalidateIssueAttempt(cur)
          cur.status = to
          cur.manualHold = ['blocked','backlog','canceled'].includes(to)
          if (cur.run && ['blocked','backlog','canceled'].includes(to)) cur.run.status = 'revoked'
          logActivity(cur, 'status', 'user', from, to)
          return { commit: true, ok: true, version: cur.version, message: '已移动到 ' + to }
        })
        if (out && out.released && out.released.length) scheduleBatch(store)
        if (out.ok && to === 'todo' && store.state.autoAccept !== undefined) scheduleBatch(store)
        if (out.ok && to === 'done') {
          const done = findIssue(store.state, id)
          if (done) await mergeIssueBranch(store, done)
        }
        return out
      },

      'kanban.addComment': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id, text = args && typeof args.text === 'string' ? args.text.trim() : ''
        if (!id || !text) return { ok: false, message: '参数缺失' }
        return mutate(store, (s) => {
          const cur = findIssue(s, id)
          if (!cur) return { ok: false, message: '议题不存在' }
          addComment(cur, 'user', text)
          return { commit: true, ok: true, version: cur.version, message: '已评论' }
        })
      },

      'kanban.archiveIssue': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id, version = args && args.version, archived = !!(args && args.archived)
        return mutate(store, (s) => {
          const cur = findIssue(s, id)
          if (!cur) return { ok: false, message: '议题不存在' }
          if (typeof version === 'number' && cur.version !== version) return { ok: false, conflict: true, message: '该议题已在其他位置更新，看板已重新同步' }
          if (archived) invalidateIssueAttempt(cur)
          cur.archivedAt = archived ? new Date().toISOString() : null
          logActivity(cur, 'archive', 'user', archived ? 'active' : 'archived', archived ? 'archived' : 'active')
          return { commit: true, ok: true, version: cur.version, message: archived ? '已归档' : '已恢复' }
        })
      },

      'kanban.deleteIssue': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id, version = args && args.version
        return mutate(store, (s) => {
          const idx = s.issues.findIndex(i => i.id === id)
          if (idx < 0) return { ok: false, message: '议题不存在' }
          const cur = s.issues[idx]
          if (typeof version === 'number' && cur.version !== version) return { ok: false, conflict: true, message: '该议题已在其他位置更新，看板已重新同步' }
          if (s.issues.some(i => (i.blockedBy || []).includes(id))) return { ok: false, message: '该任务仍被依赖，禁止删除前置绕过验收' }
          s.issues.splice(idx, 1)
          for (const i of s.issues) {
            i.blockedBy = (i.blockedBy || []).filter(x => x !== id)
            i.blocks = (i.blocks || []).filter(x => x !== id)
            i.related = (i.related || []).filter(x => x !== id)
          }
          return { commit: true, ok: true, message: '已删除' }
        })
      },

      'kanban.setAutoAccept': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const enabled = !!(args && args.enabled)
        await mutate(store, (s) => { s.autoAccept = enabled; return { commit: true } })
        if (enabled) scheduleAcceptancePass(store)
        return { ok: true, message: '自动验收已' + (enabled ? '开启' : '关闭') }
      },

      'kanban.setAutoExec': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const patch = args && args.patch
        if (!patch) return { ok: false, message: '参数缺失' }
        await mutate(store, (s) => {
          s.autoExec = s.autoExec || { enabled: false, intervalSec: 60, model: null, provider: null, effort: null, concurrency: 3 }
          if (patch.enabled !== undefined) s.autoExec.enabled = !!patch.enabled
          if (patch.intervalSec !== undefined) s.autoExec.intervalSec = Math.max(10, Math.min(3600, Number(patch.intervalSec) || 60))
          if (patch.concurrency !== undefined) s.autoExec.concurrency = Math.max(1, Math.min(10, Number(patch.concurrency) || 3))
          if (patch.model !== undefined) s.autoExec.model = patch.model ? String(patch.model) : null
          if (patch.provider !== undefined) s.autoExec.provider = patch.provider ? String(patch.provider) : null
          if (patch.effort !== undefined) s.autoExec.effort = patch.effort ? String(patch.effort) : null
          if (patch.promoteBacklog !== undefined) s.autoExec.promoteBacklog = !!patch.promoteBacklog
          return { commit: true }
        })
        syncAutoTimer(store)
        if (store.state.autoExec && store.state.autoExec.enabled) {
          // 开启后立即领取一次待立项，再做首轮派发
          await promoteEligibleBacklog(store)
          const pending = schedulerQueue(store.state, Date.now()).length > 0
          if (pending) scheduleBatch(store)
        }
        return { ok: true, message: '自动化设置已更新', autoExec: store.state.autoExec }
      },

      'kanban.getModels': async () => {
        try {
          const sel = agentDefaultModel ? agentDefaultModel.currentSelection() : undefined
          const provider = sel ? sel.provider : ''
          let models = []
          if (llm && provider) {
            try { models = await llm.listModels(provider) } catch (e) { models = [] }
          }
          return {
            ok: true,
            current: sel ? { provider: sel.provider, model: sel.model, effort: sel.reasoningEffort || null } : null,
            models: models.map(m => ({ id: m.id, name: m.name })),
          }
        } catch (e) {
          return { ok: false, message: '读取模型列表失败: ' + String(e) }
        }
      },

      'kanban.startBatch': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const candidates = schedulerQueue(store.state, Date.now())
        if (!candidates.length) return { ok: true, message: '没有待执行的议题' }
        scheduleBatch(store)
        return { ok: true, message: '已开始执行批次（' + candidates.length + ' 个议题）' }
      },

      'kanban.accept': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id, pass = !!(args && args.pass), report = args && typeof args.report === 'string' ? args.report : ''
        return mutate(store, (s) => manualReview(s, id, pass, report, args.failure)).then(async (out) => {
          if (out && out.released && out.released.length) scheduleBatch(store)
          if (out && out.ok && out.passed) {
            const done = findIssue(store.state, id)
            if (done) await mergeIssueBranch(store, done)
          }
          return out
        })
      },

      // 调用此入口不产生任何权限授权，仅记录未知故障诊断后的一次恢复。
      'kanban.resolveFailure': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const out = await mutate(store, (state) => {
          const cur = findIssue(state, args.id)
          if (!cur) return { ok: false, message: '议题不存在' }
          if (typeof args.version !== 'number' || cur.version !== args.version) return { ok: false, conflict: true, message: '请刷新失败记录后再提交诊断' }
          try {
            const resolved = resolveFailure(state, args.id, args, Date.now())
            Object.assign(state, resolved.state)
            const changed = findIssue(state, args.id)
            addComment(changed, 'user', '诊断后单次恢复: ' + args.evidence)
            logActivity(changed, 'status', 'user', 'blocked', changed.status)
            return { commit: true, ok: true, message: '新证据已记录，仅恢复一次' }
          } catch (e) { return { ok: false, message: e.message } }
        })
        if (out.ok) {
          const cur = findIssue(store.state, args.id)
          if (cur && cur.status === 'in_review') { if (store.state.autoAccept) scheduleAcceptancePass(store) }
          else scheduleBatch(store)
        }
        return out
      },

      'kanban.retryIssue': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const id = args && args.id
        if (!id) return { ok: false, message: '参数缺失' }
        const out = await mutate(store, (s) => {
          const cur = findIssue(s, id)
          if (!cur) return { ok: false, message: '议题不存在' }
          if (cur.status === 'in_progress') return { ok: false, message: '议题正在执行中，无法重试' }
          const denied = retryGuard(cur)
          if (denied) return { ok: false, message: denied }
          invalidateIssueAttempt(cur)
          cur.manualHold = false
          cur.run = null // 保留retries和lastFailure，不清除历史证据
          if (cur.status !== 'todo') {
            const from = cur.status
            cur.status = 'todo'
            logActivity(cur, 'status', 'user', from, 'todo')
          }
          addComment(cur, 'user', '手动重试，重新加入执行队列')
          return { commit: true, ok: true, version: cur.version, message: '已重新入队，保留重试与失败历史' }
        })
        if (out.ok) scheduleBatch(store)
        return out
      },

      'kanban.createWorkspace': async (args) => {
        if (!workspaceRegistry) return { ok: false, message: '工作区服务不可用' }
        const path = args && typeof args.path === 'string' ? args.path.trim() : ''
        if (!path) return { ok: false, message: '路径不能为空' }
        try {
          const ws = await workspaceRegistry.create(path, args.title || undefined)
          return { ok: true, workspace: { id: ws.id, title: ws.title, path: ws.path, sessionCount: ws.sessionIds.length }, message: '已创建工作区 ' + ws.title }
        } catch (e) {
          return { ok: false, message: '创建工作区失败: ' + String(e) }
        }
      },

      'kanban.deleteWorkspace': async (args) => {
        if (!workspaceRegistry) return { ok: false, message: '工作区服务不可用' }
        const id = args && args.id
        const store = stores.get(id)
        if (store && store.state && store.state.issues.length) return { ok: false, message: '仅空项目可以删除。删除后无法恢复。' }
        const done = await workspaceRegistry.delete(id)
        stores.delete(id)
        return { ok: done, message: done ? '已删除工作区' : '工作区不存在' }
      },

      'kanban.addLabel': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const name = args && typeof args.name === 'string' ? args.name.trim() : ''
        if (!name) return { ok: false, message: '标签名不能为空' }
        return mutate(store, (s) => {
          if ((s.labels || []).some(l => l.name === name)) return { ok: false, message: '标签已存在' }
          s.labels.push({ name, color: args.color || DEFAULT_LABEL_COLOR })
          return { commit: true, ok: true, message: '已添加标签 ' + name }
        })
      },

      'kanban.deleteLabel': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const name = args && typeof args.name === 'string' ? args.name.trim() : ''
        if (!name) return { ok: false, message: '标签名不能为空' }
        return mutate(store, (s) => {
          const idx = (s.labels || []).findIndex(l => l.name === name)
          if (idx < 0) return { ok: false, message: '标签不存在' }
          s.labels.splice(idx, 1)
          for (const i of s.issues) {
            i.labels = (i.labels || []).filter(x => x !== name)
          }
          return { commit: true, ok: true, message: '已删除标签 ' + name }
        })
      },

      'kanban.updateLabel': async (args) => {
        const store = await storeOf(args && args.workspaceId)
        if (!store) return { ok: false, message: '请先选择工作区' }
        const name = args && typeof args.name === 'string' ? args.name.trim() : ''
        if (!name) return { ok: false, message: '标签名不能为空' }
        const nextName = args && typeof args.nextName === 'string' ? args.nextName.trim() : null
        const color = args && typeof args.color === 'string' ? args.color.trim() : null
        if (!nextName && !color) return { ok: false, message: '没有要更新的内容（nextName / color 至少给一项）' }
        return mutate(store, (s) => {
          const idx = (s.labels || []).findIndex(l => l.name === name)
          if (idx < 0) return { ok: false, message: '标签不存在' }
          const target = s.labels[idx]
          if (nextName) {
            if (nextName !== name && (s.labels || []).some(l => l.name === nextName)) {
              return { ok: false, message: '标签名「' + nextName + '」已存在' }
            }
            target.name = nextName
            // 同步所有议题的 labels 数组：旧名 → 新名
            for (const i of s.issues) {
              if ((i.labels || []).includes(name)) {
                i.labels = i.labels.map(x => x === name ? nextName : x)
              }
            }
          }
          if (color) {
            if (!/^#[0-9a-fA-F]{3,8}$/.test(color)) return { ok: false, message: '颜色格式不正确，应为 #hex' }
            target.color = color
          }
          return { commit: true, ok: true, message: '已更新标签 ' + name + (nextName ? ' → ' + nextName : '') }
        })
      },
    }

    async function readBody(req, limit) {
      const chunks = []
      let total = 0
      for await (const chunk of req) {
        total += chunk.length
        if (total > limit) throw new Error('body too large')
        chunks.push(chunk)
      }
      return Buffer.concat(chunks).toString('utf8')
    }

    // client RPC channel: POST { method, args } -> JSON response
    ctx.webServer.register({
      kind: 'exact',
      path: '/dsh-task-board',
      handler: async (req, res) => {
        res.setHeader('Content-Type', 'application/json')
        res.setHeader('Cache-Control', 'no-store')
        if (req.method !== 'POST') {
          res.writeHead(405)
          res.end(JSON.stringify({ ok: false, message: 'method not allowed' }))
          return
        }
        let payload = null
        try {
          payload = JSON.parse(await readBody(req, 4 * 1024 * 1024))
        } catch (e) {
          res.writeHead(400)
          res.end(JSON.stringify({ ok: false, message: 'bad request' }))
          return
        }
        const method = payload && payload.method
        const handler = handlers[method]
        if (!handler) {
          res.writeHead(404)
          res.end(JSON.stringify({ ok: false, message: 'unknown method: ' + method }))
          return
        }
        try {
          const out = await handler(payload.args)
          res.writeHead(200)
          res.end(JSON.stringify(out))
        } catch (e) {
          res.writeHead(500)
          res.end(JSON.stringify({ ok: false, message: 'handler error: ' + String(e) }))
        }
      },
    })

    // ---------------- dynamic tools (main agent) ----------------
    async function toolStore(exec) {
      try {
        // prefer the calling agent's session cwd (exec.agent set by the agent loop)
        const agent = exec && exec.agent
        let cwd = sessionCwd(agent && agent.session)
        if (!cwd) {
          const init = agents && typeof agents.currentInitiator === 'function' ? agents.currentInitiator() : undefined
          cwd = sessionCwd(init && init.session)
        }
        if (!cwd || !workspaceRegistry) return null
        const ws = await workspaceRegistry.resolveByPath(cwd)
        if (!ws) return null
        return storeOf(ws.id)
      } catch (e) { return null }
    }

    function toolDef(name, description, properties, required, execute) {
      return {
        name, description,
        parameters: { type: 'object', properties, required },
        output: {
          schema: {
            type: 'object',
            additionalProperties: true,
            properties: {
              ok: { type: 'boolean' },
              message: { type: 'string' },
              count: { type: 'number' },
              issues: { type: 'array', items: { type: 'object', additionalProperties: true } },
            },
          },
          render: (_args, value) => [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value) }],
        },
        execute,
      }
    }

    const str = (d) => ({ type: 'string', description: d || '' })

    const mainTools = [
      toolDef('kanban_list_issues', '列出当前工作区看板上的议题（id/标题/状态/优先级/标签）。调用前先用它确认任务清单。',
        { status: str('可选：按状态过滤 backlog/todo/in_progress/in_review/blocked/done/canceled'), workspacePath: str('可选：指定工作区路径，默认当前会话工作区') },
        [],
        async (args, exec) => {
          let store = null
          if (args && args.workspacePath && workspaceRegistry) {
            const ws = await workspaceRegistry.resolveByPath(args.workspacePath)
            store = ws ? await storeOf(ws.id) : null
          } else {
            store = await toolStore(exec)
          }
          if (!store) return { ok: false, message: '无法解析工作区（当前会话未绑定工作区？）' }
          const list = store.state.issues.filter(i => !i.archivedAt).filter(i => !args.status || i.status === args.status)
            .map(i => ({ id: i.id, title: i.title, status: i.status, priority: i.priority, labels: i.labels, parentId: i.parentId || null, blockedBy: i.blockedBy || [], retries: i.retries || 0 }))
          return { ok: true, message: JSON.stringify(list), count: list.length, issues: list }
        }),

      toolDef('kanban_create_issue', '在看板上新建一个议题（进入待立项 backlog）。',
        { title: str('议题标题'), description: str('需求描述'), priority: prioritySchema, labels: { type: 'array', items: { type: 'string' }, description: '标签名列表' }, parentId: str('可选：父议题 id'), workspacePath: str('可选：指定工作区路径，默认当前会话工作区') },
        ['title'],
        async (args, exec) => {
          let store = null
          if (args && args.workspacePath && workspaceRegistry) {
            const ws = await workspaceRegistry.resolveByPath(args.workspacePath)
            store = ws ? await storeOf(ws.id) : null
          } else {
            store = await toolStore(exec)
          }
          if (!store) return { ok: false, message: '无法解析工作区（当前会话未绑定工作区？）' }
          const out = await handlers['kanban.createIssue']({ workspaceId: store.ws.id, title: args.title, description: args.description, priority: args.priority, labels: args.labels, parentId: args.parentId })
          return out
        }),

      toolDef('kanban_update_issue', '更新议题字段（标题/描述/优先级/标签/截止/依赖）。',
        { id: str('议题 id'), title: str('新标题'), description: str('新描述'), priority: prioritySchema, labels: { type: 'array', items: { type: 'string' } }, dueDate: str('ISO 日期或 null'), blocks: { type: 'array', items: { type: 'string' } }, blockedBy: { type: 'array', items: { type: 'string' } }, version: { type: 'number', description: '可选乐观锁版本号，不匹配时返回冲突' } },
        ['id'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          const patch = {}
          for (const k of ['title', 'description', 'priority', 'labels', 'dueDate', 'blocks', 'blockedBy']) if (k in args) patch[k] = args[k]
          return handlers['kanban.updateIssue']({ workspaceId: store.ws.id, id: args.id, version: args.version, patch })
        }),

      toolDef('kanban_move_issue', '移动议题到目标状态：backlog/todo/in_progress/in_review/blocked/done/canceled。移到 todo 会自动派发执行。',
        { id: str('议题 id'), to: str('目标状态'), note: str('可选备注（验收通过/打回原因等）'), version: { type: 'number', description: '可选乐观锁版本号' } },
        ['id', 'to'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          return handlers['kanban.moveIssue']({ workspaceId: store.ws.id, id: args.id, to: args.to, note: args.note, version: args.version })
        }),

      toolDef('kanban_start_batch', '开始执行批次：把当前工作区所有待执行（todo）议题派发给 executor 子 agent。',
        {}, [],
        async (_args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          return handlers['kanban.startBatch']({ workspaceId: store.ws.id })
        }),

      toolDef('kanban_accept', '手动验收通过一张待验收（in_review）议题，进入完成。',
        { id: str('议题 id'), report: str('验收说明') }, ['id'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          return handlers['kanban.accept']({ workspaceId: store.ws.id, id: args.id, pass: true, report: args.report })
        }),

      toolDef('kanban_reject', '打回一张待验收（in_review）议题到待执行，retries+1 并记录原因。',
        { id: str('议题 id'), reason: str('打回原因') }, ['id', 'reason'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          return handlers['kanban.accept']({ workspaceId: store.ws.id, id: args.id, pass: false, report: args.reason })
        }),

      toolDef('kanban_retry_issue', '重置一张失败/受阻议题的重试计数并重新加入待执行队列（立即派发）。',
        { id: str('议题 id') }, ['id'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          return handlers['kanban.retryIssue']({ workspaceId: store.ws.id, id: args.id })
        }),

      toolDef('kanban_set_auto_accept', '开启/关闭自动验收：开启后进入待验收（in_review）的议题会自动派发 acceptance 子 agent 验收。',
        { enabled: { type: 'boolean', description: '是否开启' } }, ['enabled'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          return handlers['kanban.setAutoAccept']({ workspaceId: store.ws.id, enabled: args.enabled })
        }),

      toolDef('kanban_list_workspaces', '列出所有工作区（id/标题/路径/会话数）。',
        {}, [],
        async () => {
          const workspaces = workspaceRegistry ? workspaceRegistry.list().map(w => ({ id: w.id, title: w.title, path: w.path, sessionCount: w.sessionIds.length })) : []
          return { ok: true, message: JSON.stringify(workspaces), count: workspaces.length, issues: workspaces }
        }),

      toolDef('kanban_create_workspace', '为已有目录创建工作区（用于跨工作区隔离验证）。',
        { path: str('目录路径'), title: str('可选显示标题') }, ['path'],
        async (args) => {
          return handlers['kanban.createWorkspace']({ path: args.path, title: args.title })
        }),

      toolDef('kanban_delete_workspace', '删除工作区注册（仅空项目可删除；有议题时拒绝）。',
        { id: str('工作区 id') }, ['id'],
        async (args) => {
          return handlers['kanban.deleteWorkspace']({ id: args.id })
        }),

      toolDef('kanban_set_auto_exec', '配置自动化执行：开启后按 intervalSec 秒间隔自动检索并派发工作区待执行（todo）议题；可指定推理模型（model）与推理强度（effort: off/high/max）与并行并发数（concurrency: 1-10，仅 git 工作区生效，非 git 自动串行）。',
        { enabled: { type: 'boolean', description: '是否开启自动化执行' }, promoteBacklog: { type: 'boolean', description: '待立项是否自动进入自动化流程（默认开）：开启后新建需求与失败自动生成的修复前置都会自动转等待认领；你手动拖回待立项的任务视为停用，不会自动领取；有前置依赖的仍等前置验收通过' }, intervalSec: { type: 'number', description: '轮询间隔（秒），最小 10' }, model: str('推理模型 id，留空用默认'), effort: str('推理强度 off/high/max，留空用默认'), concurrency: { type: 'number', description: '并行执行上限 1-10，缺省 3' } },
        ['enabled'],
        async (args, exec) => {
          const store = await toolStore(exec)
          if (!store) return { ok: false, message: '无法解析工作区' }
          const patch = { enabled: args.enabled }
          if (args.intervalSec !== undefined) patch.intervalSec = args.intervalSec
          if (args.model !== undefined) patch.model = args.model
          if (args.effort !== undefined) patch.effort = args.effort
          if (args.promoteBacklog !== undefined) patch.promoteBacklog = args.promoteBacklog
          if (args.concurrency !== undefined) patch.concurrency = args.concurrency
          return handlers['kanban.setAutoExec']({ workspaceId: store.ws.id, patch })
        }),

      toolDef('kanban_update_label', '更新标签（改名/改色）。改名会同步所有议题上的标签名。',
        { name: str('当前标签名'), nextName: str('新标签名（可选）'), color: str('新颜色 #hex（可选）'), workspacePath: str('可选：指定工作区路径，默认当前会话工作区') },
        ['name'],
        async (args, exec) => {
          let store = null
          if (args && args.workspacePath && workspaceRegistry) {
            const ws = await workspaceRegistry.resolveByPath(args.workspacePath)
            store = ws ? await storeOf(ws.id) : null
          } else {
            store = await toolStore(exec)
          }
          if (!store) return { ok: false, message: '无法解析工作区（当前会话未绑定工作区？）' }
          const patch = {}
          if (args.nextName !== undefined) patch.nextName = args.nextName
          if (args.color !== undefined) patch.color = args.color
          return handlers['kanban.updateLabel']({ workspaceId: store.ws.id, name: args.name, ...patch })
        }),
    ]

    for (const tool of mainTools) {
      ctx.tools.register(tool)
    }

    // periodic health scan: registered here (active fiber) so the interval is
    // cleaned up with the plugin; the scan itself repairs zombies/stuck states
    if (timer) {
      try {
        ctx.effect(() => timer.interval(() => { void healthScanAll() }, HEALTH_SCAN_MS))
      } catch (e) { /* scan disabled is better than a fatal load failure */ }
    }
}
