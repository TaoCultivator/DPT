#!/usr/bin/env node
/**
 * audit-plugins.mjs —— 已装插件「真实可用性」四层审计器（零重启、只读）
 *
 * 背景：插件在 `plugin_manager list_plugins` 里显示 enabled / active，只证明「挂上了」。
 * dsh-task-board 从安装第一天起所有落盘写入路径就是死的（调用 `shell.run`，而 DSH shell 服务
 * 只有 `resolve` + `execute`），而加载层一直是全绿。本脚本补的就是这一段保证。
 *
 * 四层：
 *   L1 加载层  —— 宿主 `plugin_manager list_plugins` 采集（本脚本读 evidence.json 的采集结果）
 *   L2 能力层  —— 会话内真实调用插件工具采集（同上）
 *   L3 契约层  —— 本脚本自动：扫插件源码里的服务调用点，与 cordis_inspect 导出的实时 Service
 *                 契约（contracts.json）逐条比对，产出「调用了不存在 / 签名不符的方法」清单
 *   L4 依赖层  —— 本脚本自动：包路径 / 软链目标 / 补丁清单 / 依赖可达性 / engines.dsh 兼容闸
 *
 * 用法：
 *   node audit-plugins.mjs [--profile <dir>] [--out <dir>] [--print] [--quiet]
 *
 * 可复跑性：产物**不含时间戳**，同一份输入两次运行的产物逐字节一致。校验方式见 README.md。
 *
 * 输入（与本脚本同目录）：
 *   contracts.json   宿主 Service 契约快照，由 cordis_inspect(host/Service.listService) 导出
 *   evidence.json    人工采集的 L1/L2 证据与结论（脚本不伪造；缺项一律标「未验证」）
 *
 * 只读承诺：不写被审计的插件目录，不启动/重启任何进程，只写 --out 目录。
 *
 * 精度约定（避免误报，三类易误报情形已显式处理）：
 *   1) 别名必须精确绑定：`const x = ctx.svc` 才算别名；`const x = ctx.svc.method()` 不算
 *      （否则 `const captain = ctx.agents.get(id)` 会把 captain 误判成 agents 服务）
 *   2) 宿主/客户端分平面：客户端半边（exports["./client"] 或 import dsh-client-*）不与宿主契约比对
 *   3) 契约方法名剥掉泛型：`open<S extends DomainSpec>(...)` 归一为 `open`
 */

import { readFileSync, existsSync, lstatSync, readdirSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs'
import { join, dirname, resolve, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { homedir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))

/* ------------------------------------------------------------------ 参数 */

function parseArgs(argv) {
  const out = { profile: null, out: null, print: false, quiet: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--profile') out.profile = argv[++i]
    else if (a === '--out') out.out = argv[++i]
    else if (a === '--print') out.print = true
    else if (a === '--quiet') out.quiet = true
    else if (a === '--help' || a === '-h') { console.log('node audit-plugins.mjs [--profile <dir>] [--out <dir>] [--print] [--quiet]'); process.exit(0) }
  }
  return out
}
const ARGS = parseArgs(process.argv.slice(2))

const DSH_HOME = process.env.DSH_HOME || join(homedir(), '.dsh')
const PROFILE_DIR = resolve(ARGS.profile || join(DSH_HOME, 'profiles', 'desktop'))
const OUT_DIR = ARGS.out ? resolve(ARGS.out) : HERE
const CONTRACTS_PATH = join(HERE, 'contracts.json')
const CLIENT_CONTRACTS_PATH = join(HERE, 'contracts.client.json')
const EVIDENCE_PATH = join(HERE, 'evidence.json')

/* ------------------------------------------------------------------ 工具 */

const SCAN_EXT = new Set(['.js', '.mjs', '.cjs', '.ts', '.mts', '.cts'])
const SKIP_DIRS = new Set(['node_modules', '.git', 'test', 'tests', '__tests__', 'coverage', '.cache', 'docs'])
const MAX_FILE_BYTES = 6 * 1024 * 1024

function walk(dir, acc = []) {
  let entries
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return acc }
  for (const e of entries) {
    const p = join(dir, e.name)
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(p, acc) }
    else if (e.isFile()) {
      if (/\.bak(-|$)/i.test(e.name) || e.name.endsWith('.map')) continue
      const ext = e.name.slice(e.name.lastIndexOf('.'))
      if (SCAN_EXT.has(ext)) acc.push(p)
    }
  }
  return acc
}

function safeReadText(p) {
  try {
    const st = lstatSync(p)
    if (!st.isFile() || st.size > MAX_FILE_BYTES) return null
    return readFileSync(p, 'utf8')
  } catch { return null }
}

function lineOf(text, index) {
  let n = 1
  for (let i = 0; i < index && i < text.length; i++) if (text.charCodeAt(i) === 10) n++
  return n
}

function linkInfo(p) {
  try {
    const st = lstatSync(p)
    if (!st.isSymbolicLink()) return { isLink: false, target: null, targetExists: null }
    try { return { isLink: true, target: realpathSync(p), targetExists: true } }
    catch { return { isLink: true, target: null, targetExists: false } }
  } catch { return { isLink: false, target: null, targetExists: null } }
}

/* --------------------------------------------------------------- 最小 semver */

function parseSemver(v) {
  const m = String(v || '').trim().replace(/^[v=]+/, '').match(/^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?/)
  if (!m) return null
  return { major: +m[1], minor: m[2] === undefined ? 0 : +m[2], patch: m[3] === undefined ? 0 : +m[3], pre: m[4] || '' }
}
function cmp(a, b) {
  if (a.major !== b.major) return a.major - b.major
  if (a.minor !== b.minor) return a.minor - b.minor
  if (a.patch !== b.patch) return a.patch - b.patch
  if (a.pre === b.pre) return 0
  if (!a.pre) return 1
  if (!b.pre) return -1
  return a.pre < b.pre ? -1 : 1
}
/** 是否满足；无法解析 range 时返回 null（=不确定，不算失败） */
function satisfies(version, range) {
  const v = parseSemver(version)
  if (!v || !range) return null
  for (const or of String(range).split('||')) {
    const parts = or.trim().split(/\s+/).filter(Boolean)
    let ok = true, usable = false
    for (const raw of parts) {
      const m = raw.match(/^(\^|~|>=|<=|>|<|=)?\s*(.+)$/)
      if (!m) { ok = false; break }
      const op = m[1] || '=', ver = m[2]
      if (/^[xX*]$/.test(ver)) { usable = true; continue }
      // 通配 x
      const wildMinor = /^\d+\.(x|X|\*)(\.|$)/.test(ver)
      const wildPatch = /^\d+\.\d+\.(x|X|\*)$/.test(ver)
      const t = parseSemver(ver)
      if (!t) { ok = false; break }
      usable = true
      const c = cmp(v, t)
      if (op === '^') ok = v.major === t.major && c >= 0
      else if (op === '~') ok = v.major === t.major && v.minor === t.minor && c >= 0
      else if (op === '>=') ok = c >= 0
      else if (op === '<=') ok = c <= 0
      else if (op === '>') ok = c > 0
      else if (op === '<') ok = c < 0
      else if (wildPatch) ok = v.major === t.major && v.minor === t.minor
      else if (wildMinor) ok = v.major === t.major
      else ok = c === 0
      if (!ok) break
    }
    if (ok && usable) return true
  }
  return false
}

/** 契约签名 → 方法名（剥 @Remote(...) 装饰器、abstract/readonly/async、泛型 <>） */
function signatureToMethodName(sig) {
  let s = String(sig).trim()
  // 装饰器必须先剥，否则 `@Remote('modelCatalog') modelCatalog()` 会被 split('(') 切坏
  for (;;) {
    const m = s.match(/^@[A-Za-z_$][\w$]*\s*(\(([^()]|\([^()]*\))*\))?\s*/)
    if (!m || m[0] === '') break
    s = s.slice(m[0].length)
  }
  let head = s.split('(')[0].trim()
  head = head.replace(/^(abstract|readonly|async|public|static|declare|get|set)\s+/g, '')
  head = head.replace(/<[\s\S]*$/, '')          // 泛型
  head = head.replace(/[:?].*$/, '')            // 类型标注 / 可选符
  head = head.trim().replace(/^\*/, '')
  return head
}

/* ------------------------------------------------------------------ 契约 */

function loadContracts() {
  if (!existsSync(CONTRACTS_PATH)) {
    console.error('[致命] 找不到契约快照 ' + CONTRACTS_PATH)
    process.exit(2)
  }
  const raw = JSON.parse(readFileSync(CONTRACTS_PATH, 'utf8'))
  const services = {}
  for (const [key, val] of Object.entries(raw.services || {})) {
    const methods = (val.methods || []).map(m => (typeof m === 'string' ? m : m.signature || ''))
    const byName = new Map()
    for (const sig of methods) {
      const name = signatureToMethodName(sig)
      if (name && /^[A-Za-z_$][\w$]*$/.test(name)) byName.set(name, sig)
    }
    services[key] = { description: val.description || '', methods, byName }
  }
  const client = existsSync(CLIENT_CONTRACTS_PATH)
    ? (() => {
        const c = JSON.parse(readFileSync(CLIENT_CONTRACTS_PATH, 'utf8'))
        const s = {}
        for (const [key, val] of Object.entries(c.services || {})) {
          const methods = (val.methods || []).map(m => (typeof m === 'string' ? m : m.signature || ''))
          const byName = new Map()
          for (const sig of methods) { const n = signatureToMethodName(sig); if (n) byName.set(n, sig) }
          s[key] = { description: val.description || '', methods, byName }
        }
        return s
      })()
    : null
  return { raw, services, clientServices: client }
}

/* --------------------------------------------------------------- L3 扫描 */

const RE = {
  // 别名：RHS 必须是精确的 ctx.<svc>，后面不能跟 . / ?. / 标识符（否则是 ctx.svc.method() 或 ctx.svc?.x 的链式结果）
  aliasCtx: /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:this\.)?ctx\.([A-Za-z_$][\w$]*)\s*(?![.\w$?])/g,
  aliasIndex: /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:this\.)?ctx\[['"]([\w$]+)['"]\]\s*(?![.\w$?])/g,
  aliasGet: /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:this\.)?ctx\.get\(\s*['"]([\w$]+)['"]\s*\)\s*(?![.\w$?[])/g,
  destruct: /\b(?:const|let|var)\s*\{([^}]{1,400})\}\s*=\s*(?:this\.)?ctx\b/g,
  directCall: /\bctx\.([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*\(/g,
  inject: /\binject\s*[:=]\s*\[([^\]]*)\]/g,
  catchBlock: /catch\s*(?:\([^)]*\))?\s*\{([^{}]*)\}/g,
}

// 只在「服务确实没有同名方法」时用于降级：这些名字在 JS 里更可能是集合/字符串/函数自带方法
const BUILTIN_NAMES = new Set(['slice', 'map', 'filter', 'forEach', 'find', 'findIndex', 'some', 'every', 'reduce', 'push', 'pop', 'shift', 'unshift', 'join', 'indexOf', 'includes', 'length', 'endsWith', 'startsWith', 'trim', 'split', 'replace', 'concat', 'call', 'apply', 'bind', 'then', 'catch', 'finally', 'toLowerCase', 'toUpperCase', 'toString', 'valueOf', 'hasOwnProperty'])

// cordis 核心自带的 ctx 成员（不属于 DSH Service 目录，不该当作「不存在的服务」）
const CORDIS_CORE = new Set(['loader', 'scope', 'root', 'fiber', 'registry', 'reflect', 'schema', 'logger', 'config', 'lifecycle', 'monitor', 'console', 'events'])

// 已在宿主源码里确证存在、但**未登记进 cordis_inspect Service 目录**的服务。
// 这是一条审计方法自身的覆盖盲区，必须显式登记而不是靠猜。
const KNOWN_UNREGISTERED_SERVICES = {
  webRuntime: '由 @deepseek-ai/dsh-web-app 提供；证据：app.asar 内 `const WEB_RUNTIME_SERVICE = "webRuntime"` 与 patch 文档 `inject: [webRuntime]`。不在 listService 目录中。',
}

/** 提取调用实参文本（配平括号、跳过字符串与注释） */
function readCallArgs(text, openParenIndex) {
  let depth = 0, i = openParenIndex, quote = null
  const start = i
  for (; i < text.length; i++) {
    const ch = text[i]
    if (quote) { if (ch === '\\') { i++; continue } if (ch === quote) quote = null; continue }
    if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue }
    if (ch === '/' && text[i + 1] === '/') { while (i < text.length && text[i] !== '\n') i++; continue }
    if (ch === '/' && text[i + 1] === '*') { i += 2; while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) i++; i++; continue }
    if (ch === '(' || ch === '[' || ch === '{') depth++
    else if (ch === ')' || ch === ']' || ch === '}') { depth--; if (depth === 0) return text.slice(start + 1, i) }
  }
  return text.slice(start + 1, Math.min(text.length, start + 400))
}

/** 该调用是否显式给了沙箱策略（命名参数或位置实参） */
function hasSandboxPolicy(argsText) {
  return /sandboxPolicy|Policy\s*:|mode\s*:/.test(argsText || '')
}

/** 文件里被「typeof X.method === 'function'」或「X.method === void 0」守卫过的方法名集合。
 *  有守卫 → 不会抛异常，但该分支永不生效（静默降级）；无守卫 → 调用即抛 TypeError。 */
function guardedMethods(text) {
  const out = new Set()
  let m
  const re1 = /typeof\s+[A-Za-z_$][\w$]*\s*\??\.?\s*\.?\s*([A-Za-z_$][\w$]*)\s*[!=]==\s*['"]function['"]/g
  while ((m = re1.exec(text))) out.add(m[1])
  const re2 = /[A-Za-z_$][\w$]*\s*\??\.([A-Za-z_$][\w$]*)\s*[!=]==\s*(?:void 0|undefined)/g
  while ((m = re2.exec(text))) out.add(m[1])
  return out
}

function scanFile(relPath, text, plane, contracts, findings, refs) {
  const aliases = new Map()
  const guarded = guardedMethods(text)
  // 打包进来的第三方运行时（如 dsh-genui 内联的 zod）也用 ctx 命名，必须与插件自身代码区分
  const vendored = /__commonJS\(|__toCommonJS\(|__require\(/.test(text)
  let m

  RE.aliasCtx.lastIndex = 0
  while ((m = RE.aliasCtx.exec(text))) aliases.set(m[1], { service: m[2], line: lineOf(text, m.index) })
  RE.aliasIndex.lastIndex = 0
  while ((m = RE.aliasIndex.exec(text))) aliases.set(m[1], { service: m[2], line: lineOf(text, m.index) })
  RE.aliasGet.lastIndex = 0
  while ((m = RE.aliasGet.exec(text))) aliases.set(m[1], { service: m[2], line: lineOf(text, m.index) })
  RE.destruct.lastIndex = 0
  while ((m = RE.destruct.exec(text))) {
    const line = lineOf(text, m.index)
    for (const piece of m[1].split(',')) {
      const t = piece.trim()
      if (!t) continue
      const asMatch = t.match(/^([\w$]+)\s*:\s*([\w$]+)/)
      if (asMatch) { aliases.set(asMatch[2], { service: asMatch[1], line }); continue }
      const plain = t.match(/^([\w$]+)/)
      if (plain) aliases.set(plain[1], { service: plain[1], line })
    }
  }

  const table = plane === 'client' ? (contracts.clientServices || null) : contracts.services

  // inject 声明的服务 key
  // 只把「至少含一个已知宿主服务 key」的 inject 列表当作 cordis 服务声明 —— 否则
  // 它更可能是 UI 组件注册表（如 dsh-genui 的 inject: ['select','TreeRoot',...]）
  const knownInject = []
  RE.inject.lastIndex = 0
  while ((m = RE.inject.exec(text))) {
    const line = lineOf(text, m.index)
    const keys = m[1].split(',').map(p => p.trim().replace(/^['"`]|['"`]$/g, '')).filter(k => k && !/[{}]/.test(k))
    for (const key of keys) refs.inject.push({ file: relPath, line, service: key, plane })
    if (plane === 'client' || !table) continue
    const recognized = keys.some(k => table[k])
    if (!recognized) continue
    for (const key of keys) knownInject.push({ key, line })
  }
  if (plane === 'host' && table) {
    for (const { key, line } of knownInject) {
      if (table[key] || CORDIS_CORE.has(key)) continue
      const unreg = KNOWN_UNREGISTERED_SERVICES[key]
      findings.push({
        rule: unreg ? 'service-not-in-catalog' : 'inject-unknown-service',
        severity: unreg ? 'low' : 'high',
        file: relPath, line, service: key, method: null,
        message: unreg
          ? 'inject 的 ' + key + ' 不在 Service 目录里，但已由宿主源码确证存在（审计目录覆盖盲区，非缺陷）'
          : 'inject 声明了宿主不存在的服务 ' + key,
        evidence: unreg || 'cordis_inspect 宿主 Service 目录中无该 key',
      })
    }
  }

  const judge = (service, method, line, argsText, how) => {
    if (!table) {
      refs.calls.push({ file: relPath, line, service, method, plane: 'client', args: (argsText || '').slice(0, 200), how })
      refs.clientContractUnavailable = true
      return
    }
    const svc = table[service]
    if (!svc) {
      // 不在目录里：cordis 核心成员忽略；其余登记为「目录覆盖盲区」候选，供人工复核
      if (plane === 'host' && !vendored && !CORDIS_CORE.has(service)) {
        refs.unknownServiceKeys.push({ file: relPath, line, service, method })
      }
      return
    }
    refs.calls.push({ file: relPath, line, service, method, args: (argsText || '').slice(0, 200), how })
    if (svc.byName.has(method)) {
      const sig = svc.byName.get(method)
      if (/sandboxPolicy/.test(sig) && !hasSandboxPolicy(argsText)) {
        findings.push({
          rule: 'missing-sandbox-policy', severity: 'medium', file: relPath, line,
          service, method,
          message: service + '.' + method + '() 未显式传沙箱策略，将落回部署默认策略',
          evidence: '契约签名：' + sig,
        })
      }
      return
    }
    const builtin = BUILTIN_NAMES.has(method)
    const isGuarded = guarded.has(method)
    findings.push({
      rule: builtin ? 'suspected-builtin-method' : 'unknown-service-method',
      severity: builtin ? 'low' : (isGuarded ? 'high' : 'blocker'),
      guarded: isGuarded,
      file: relPath, line, service, method,
      message: service + '.' + method + '() 在宿主契约里不存在（' + how + '）'
        + (builtin ? ' —— 名字同为 JS 内置方法，需人工确认'
          : isGuarded ? ' —— 调用点有 typeof/undefined 守卫，**不会抛异常，但该分支永不生效（静默降级）**'
            : ' —— 无守卫，调用即抛 TypeError'),
      evidence: '可用方法：' + (svc.methods.slice(0, 8).map(signatureToMethodName).join(' / ') || '（无）') + (svc.methods.length > 8 ? ' …共 ' + svc.methods.length + ' 个' : ''),
    })
  }

  RE.directCall.lastIndex = 0
  while ((m = RE.directCall.exec(text))) {
    const open = text.indexOf('(', m.index + m[0].length - 1)
    judge(m[1], m[2], lineOf(text, m.index), readCallArgs(text, open), 'ctx.<svc>.<method>() 直调')
  }

  for (const [alias, info] of aliases) {
    const re = new RegExp('\\b' + alias.replace(/\$/g, '\\$') + '\\.([A-Za-z_$][\\w$]*)\\s*\\(', 'g')
    re.lastIndex = 0
    while ((m = re.exec(text))) {
      const method = m[1]
      const line = lineOf(text, m.index)
      const open = text.indexOf('(', m.index + m[0].length - 1)
      const argsText = readCallArgs(text, open)
      const svc = table && table[info.service]
      if (svc && !svc.byName.has(method)) {
        const builtin = BUILTIN_NAMES.has(method)
        const isGuarded = guarded.has(method)
        findings.push({
          rule: builtin ? 'suspected-builtin-method' : 'unknown-service-method',
          severity: builtin ? 'low' : (isGuarded ? 'high' : 'blocker'),
          guarded: isGuarded,
          file: relPath, line, service: info.service, method,
          message: info.service + '.' + method + '() 在宿主契约里不存在（经由别名 ' + alias + '，声明在第 ' + info.line + ' 行）'
            + (builtin ? ' —— 名字同为 JS 内置方法，需人工确认'
              : isGuarded ? ' —— 调用点有 typeof/undefined 守卫，**不会抛异常，但该分支永不生效（静默降级）**'
                : ' —— 无守卫，调用即抛 TypeError'),
          evidence: '可用方法：' + (svc.methods.slice(0, 8).map(signatureToMethodName).join(' / ') || '（无）') + (svc.methods.length > 8 ? ' …共 ' + svc.methods.length + ' 个' : ''),
        })
      } else {
        judge(info.service, method, line, argsText, '经由别名 ' + alias + '（声明在第 ' + info.line + ' 行）')
      }
      // fs 系列第一参必须是 FsTarget
      if (svc && /^(writeText|editText|readText|listDir|stat)$/.test(method) && /^\s*['"`]/.test(argsText)) {
        findings.push({
          rule: 'fs-string-instead-of-target', severity: 'high', file: relPath, line,
          service: info.service, method,
          message: info.service + '.' + method + '() 第一参是字符串字面量，契约要求 FsTarget',
          evidence: '调用实参：' + argsText.slice(0, 120),
        })
      }
    }
  }

  RE.catchBlock.lastIndex = 0
  while ((m = RE.catchBlock.exec(text))) {
    const body = m[1], line = lineOf(text, m.index)
    const empty = body.trim() === ''
    const logsOnly = /console\.(error|warn|log|info)\s*\(/.test(body) && !/\bthrow\b/.test(body) && !/\breturn\b/.test(body) && !/\breject\b/.test(body)
    if (empty || logsOnly) refs.silentCatch.push({ file: relPath, line, kind: empty ? 'empty' : 'console-only', vendored })
  }
}

/* --------------------------------------------------------------- L4 检查 */

function clientEntries(pkg, dir) {
  const out = new Set()
  const push = (v) => {
    if (!v) return
    if (typeof v === 'string') { out.add(v.replace(/^\.\//, '')); return }
    if (typeof v === 'object') { if (v.default) push(v.default); if (v.import) push(v.import); if (v.require) push(v.require) }
  }
  const ex = pkg.exports || {}
  for (const [k, v] of Object.entries(ex)) if (k === './client' || k.startsWith('./client/')) push(v)
  if (pkg.dsh && pkg.dsh.client && typeof pkg.dsh.client.entry === 'string') push(pkg.dsh.client.entry)
  return [...out]
}

function checkBundle(profileDir, name, runtimeVersion, contracts) {
  const result = {
    name,
    kind: /^@deepseek-ai\//.test(name) ? '官方' : '第三方',
    dir: null, realDir: null, isLink: false, linkTargetExists: null,
    staticScanReachable: false, staticScanReason: null,
    version: null, dshBundlePatch: null, patchExists: null,
    clientEntries: [], fileCount: 0, scannedFiles: [],
    depsDeclared: 0, depsMissing: [], enginesDsh: null, enginesRange: null, enginesOk: null,
    compatRange: null, compatReleases: null, compatVerdict: null,
    findings: [], refs: { inject: [], calls: [], silentCatch: [], clientCalls: [], clientSilentCatch: [], unknownServiceKeys: [] },
  }
  const dir = join(profileDir, 'node_modules', ...name.split('/'))
  if (!existsSync(join(dir, 'package.json'))) {
    result.staticScanReason = 'profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）'
    return result
  }
  result.dir = dir
  const link = linkInfo(dir)
  result.isLink = link.isLink
  result.linkTargetExists = link.targetExists
  result.realDir = link.target || dir

  const pkgText = safeReadText(join(dir, 'package.json'))
  if (!pkgText) { result.staticScanReason = 'package.json 不可读'; return result }
  let pkg
  try { pkg = JSON.parse(pkgText) } catch { result.staticScanReason = 'package.json 解析失败'; return result }
  result.version = pkg.version || null
  result.enginesRange = (pkg.dsh && pkg.dsh.engines && pkg.dsh.engines.dsh) || (pkg.engines && pkg.engines.dsh) || null
  result.enginesDsh = result.enginesRange
  if (result.enginesRange && runtimeVersion) result.enginesOk = satisfies(runtimeVersion, result.enginesRange)
  // 部分插件另带「按发布版逐条登记」的兼容闸（dsh-cost-meter 是典型）
  const compat = (pkg.dsh && pkg.dsh.compatibility) || null
  if (compat) {
    result.compatRange = compat.dsh || null
    result.compatReleases = compat.dshReleases || null
    result.compatVerdict = (compat.dshReleases && runtimeVersion) ? (compat.dshReleases[runtimeVersion] ?? '未登记') : null
  }

  if (pkg.dsh && pkg.dsh.bundle && pkg.dsh.bundle.patch) {
    result.dshBundlePatch = pkg.dsh.bundle.patch
    result.patchExists = existsSync(join(dir, pkg.dsh.bundle.patch))
  }

  const deps = Object.keys(pkg.dependencies || {})
  result.depsDeclared = deps.length
  for (const d of deps) {
    const inProfile = existsSync(join(profileDir, 'node_modules', ...d.split('/'), 'package.json'))
    const inPkg = existsSync(join(dir, 'node_modules', ...d.split('/'), 'package.json'))
    if (!inProfile && !inPkg) result.depsMissing.push(d)
  }

  result.clientEntries = clientEntries(pkg, dir)
  const clientAbs = new Set(result.clientEntries.map(p => resolve(dir, p)))
  const files = walk(dir)
  result.staticScanReachable = true
  result.fileCount = files.length
  for (const f of files) {
    const rel = relative(dir, f).split(sep).join('/')
    result.scannedFiles.push(rel)
    const text = safeReadText(f)
    if (text == null) continue
    // 分平面：客户端入口文件、客户端源码目录、或引用了 dsh-client-* 包的文件，一律按客户端平面处理
    const isClient = clientAbs.has(resolve(f))
      || /@deepseek-ai\/dsh-client-[a-z-]+/.test(text)
      || (clientAbs.size > 0 && /(^|\/)(src\/)?client\//.test(rel))
    const planeRefs = isClient
      ? { inject: result.refs.inject, calls: result.refs.clientCalls, silentCatch: result.refs.clientSilentCatch }
      : result.refs
    scanFile(rel, text, isClient ? 'client' : 'host', contracts, isClient ? [] : result.findings, planeRefs)
  }
  result.findings.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.rule.localeCompare(b.rule))
  return result
}

/* ------------------------------------------------------------------ 输出 */

function renderMatrix(report) {
  const L = []
  L.push('# 已装插件真实可用性矩阵（L1 加载 / L2 能力 / L3 契约 / L4 依赖）')
  L.push('')
  L.push('- 审计对象：`' + report.profile + '` 的 `dsh.profile.bundles` 全量组合包')
  L.push('- 宿主版本：' + (report.runtimeVersion || '未知'))
  L.push('- 契约来源：' + report.contractSource + '（宿主服务 ' + report.contractServiceCount + ' 个' + (report.clientContractAvailable ? '；客户端服务 ' + report.clientContractServiceCount + ' 个' : '；**客户端契约不可达**') + '）')
  L.push('- 生成方式：`node audit-plugins.mjs`（只读、零重启；产物不含时间戳，可逐字节复跑比对）')
  L.push('')
  L.push('## 汇总')
  L.push('')
  const s = report.summary
  L.push('| 指标 | 数量 |')
  L.push('| --- | --- |')
  L.push('| 组合包 | ' + s.bundles + ' |')
  L.push('| 源码静态可扫（宿主半边） | ' + s.staticScanned + ' |')
  L.push('| 源码不可达（app.asar 内） | ' + s.staticUnreachable + ' |')
  L.push('| 契约缺陷 · blocker | ' + s.blocker + ' |')
  L.push('| 契约缺陷 · high | ' + s.high + ' |')
  L.push('| 契约缺陷 · medium | ' + s.medium + ' |')
  L.push('| 契约缺陷 · low（疑似内置方法，待人工确认） | ' + s.low + ' |')
  L.push('| 静默 catch（宿主半边，非内联运行时） | ' + s.silentCatch + ' |')
  L.push('| 静默 catch（内联第三方运行时，已分离） | ' + s.silentCatchVendored + ' |')
  L.push('| 静默 catch（客户端半边，另计） | ' + s.clientSilentCatch + ' |')
  L.push('| 结论 · 可用 | ' + s.verified + ' |')
  L.push('| 结论 · 部分可用 | ' + s.partial + ' |')
  L.push('| 结论 · 不可用 | ' + s.unavailable + ' |')
  L.push('| 结论 · 未验证 / 待核 | ' + s.unverified + ' |')
  L.push('')
  L.push('## 全量矩阵')
  L.push('')
  L.push('| # | 组合包 | 类型 | 声称能力 | L1 加载 | L2 能力 | L3 契约 | L4 依赖 | 结论 |')
  L.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
  report.bundles.forEach((b, i) => {
    const ev = b.l1l2 || {}
    const l3 = !b.staticScanReachable
      ? '静态不可达'
      : (b.findings.length ? b.findings.length + ' 项契约缺陷（' + b.findings.filter(f => f.severity === 'high' || f.severity === 'blocker').length + ' 项高危）' : '无缺陷（' + b.callCount + ' 处服务调用）')
    const l4 = [
      b.dir ? '包已就位' : '包未解析',
      b.isLink ? (b.linkTargetExists ? '软链有效' : '**软链失效**') : null,
      b.depsMissing && b.depsMissing.length ? '**缺依赖 ' + b.depsMissing.length + '**' : null,
      b.enginesOk === false ? '**peer 不兼容**' : (b.enginesOk === true ? 'peer 兼容' : null),
      b.patchExists === false ? '**补丁清单缺失**' : null,
    ].filter(Boolean).join('；')
    L.push('| ' + (i + 1) + ' | `' + b.name + '` | ' + b.kind + ' | ' + (ev.claim || '—') + ' | ' + (ev.l1 || '未验证') + ' | ' + (ev.l2 || '未验证') + ' | ' + l3 + ' | ' + l4 + ' | **' + b.conclusion + '** |')
  })
  L.push('')
  L.push('## 逐包明细（L3/L4 自动证据）')
  L.push('')
  for (const b of report.bundles) {
    L.push('### ' + b.name)
    L.push('')
    L.push('- 类型：' + b.kind + (b.version ? ' · 版本 ' + b.version : ''))
    L.push('- 包目录：' + (b.dir ? '`' + b.dir + '`' : '**未解析**'))
    L.push('- 静态扫描：' + (b.staticScanReachable ? b.fileCount + ' 个源文件（宿主半边与客户端半边分平面）' : '不可达 —— ' + (b.staticScanReason || '')))
    if (b.clientEntries && b.clientEntries.length) L.push('- 客户端入口：' + b.clientEntries.map(x => '`' + x + '`').join('、'))
    L.push('- 补丁清单：' + (b.dshBundlePatch ? '`' + b.dshBundlePatch + '`' + (b.patchExists ? '（存在）' : '（**缺失**）') : '未声明'))
    L.push('- 依赖：声明 ' + b.depsDeclared + ' 个' + (b.depsMissing && b.depsMissing.length ? '，**缺 ' + b.depsMissing.join('、') + '**' : '，全部可达'))
    L.push('- engines.dsh：' + (b.enginesRange ? '`' + b.enginesRange + '` → ' + (b.enginesOk === false ? '**不兼容宿主 ' + report.runtimeVersion + '**' : b.enginesOk === true ? '兼容宿主 ' + report.runtimeVersion : '无法判定') : '未声明'))
    if (b.compatRange || b.compatVerdict) L.push('- 逐版兼容闸（dsh.compatibility）：' + (b.compatRange ? '`' + b.compatRange + '`' : '范围未声明') + (b.compatVerdict ? '；本机 ' + report.runtimeVersion + ' → **' + b.compatVerdict + '**' : ''))
    L.push('- 宿主服务引用：' + (b.callCount ? b.callCount + ' 处调用 / ' + b.inject.length + ' 个 inject key' : '无（或静态不可达）'))
    if (b.unknownServiceKeys && b.unknownServiceKeys.length) {
      L.push('- 目录外服务 key（覆盖盲区候选，需人工复核）：' + b.unknownServiceKeys.map(k => '`' + k + '`' + (KNOWN_UNREGISTERED_SERVICES[k] ? '（已确证存在）' : '（未确证）')).join('、'))
    }
    L.push('- 静默 catch：宿主半边 ' + b.silentCatchCount + ' 处（空 catch ' + b.silentCatchEmpty + ' 处；内联第三方运行时另计 ' + (b.silentCatchVendored || 0) + ' 处）；客户端半边 ' + (b.clientSilentCatchCount || 0) + ' 处')
    if (b.findings.length) {
      L.push('- **L3 契约缺陷**：')
      for (const f of b.findings) {
        L.push('  - `[' + f.severity + ']` `' + f.rule + '` @ `' + f.file + ':' + f.line + '` —— ' + f.message)
        if (f.evidence) L.push('    - 依据：' + f.evidence)
      }
    } else if (b.staticScanReachable) {
      L.push('- **L3 契约缺陷**：无')
    }
    const ev = b.l1l2 || {}
    if (ev.evidencePaths && ev.evidencePaths.length) {
      L.push('- 证据路径：')
      for (const p of ev.evidencePaths) L.push('  - ' + p)
    }
    if (ev.note) L.push('- 备注：' + ev.note)
    L.push('')
  }
  return L.join('\n')
}

/* ------------------------------------------------------------------ 主流程 */

function main() {
  const contracts = loadContracts()
  let runtimeVersion = null
  const runtimePath = join(DSH_HOME, 'dsh-runtimes', 'dsh-primary-runtime', 'runtime.json')
  if (existsSync(runtimePath)) {
    try { runtimeVersion = JSON.parse(readFileSync(runtimePath, 'utf8')).desktopVersion || null } catch {}
  }

  const profilePkgPath = join(PROFILE_DIR, 'package.json')
  if (!existsSync(profilePkgPath)) { console.error('[致命] 找不到 profile package.json：' + profilePkgPath); process.exit(2) }
  const profilePkg = JSON.parse(readFileSync(profilePkgPath, 'utf8'))
  const bundles = ((profilePkg.dsh || {}).profile || {}).bundles || []

  const evidence = existsSync(EVIDENCE_PATH) ? JSON.parse(readFileSync(EVIDENCE_PATH, 'utf8')) : { bundles: {} }

  const rows = []
  for (const name of bundles) {
    const b = checkBundle(PROFILE_DIR, name, runtimeVersion, contracts)
    const ev = (evidence.bundles && evidence.bundles[name]) || {}
    b.evidence = ev
    b.conclusion = ev.conclusion || (b.findings.some(f => f.severity === 'blocker' || f.severity === 'high') ? '待核（发现 L3 契约缺陷）' : '未验证')
    rows.push(b)
  }

  for (const r of rows) {
    const seen = new Set()
    r.findings = r.findings.filter(f => {
      const k = [f.rule, f.file, f.line, f.service, f.method].join('|')
      if (seen.has(k)) return false
      seen.add(k); return true
    })
  }

  const allFindings = []
  for (const r of rows) for (const f of r.findings) allFindings.push({ bundle: r.name, ...f })
  const sevOrder = { blocker: 0, high: 1, medium: 2, low: 3 }
  allFindings.sort((a, b) => (sevOrder[a.severity] - sevOrder[b.severity]) || a.bundle.localeCompare(b.bundle) || a.file.localeCompare(b.file) || (a.line - b.line))

  const report = {
    profile: PROFILE_DIR,
    runtimeVersion,
    contractSource: contracts.raw.source || 'contracts.json',
    contractServiceCount: Object.keys(contracts.services).length,
    clientContractAvailable: false,
    clientContractServiceCount: 0,
    bundleCount: bundles.length,
    bundles: rows.map(r => ({
      name: r.name, kind: r.kind, version: r.version,
      dir: r.dir, isLink: r.isLink, linkTargetExists: r.linkTargetExists,
      staticScanReachable: r.staticScanReachable, staticScanReason: r.staticScanReason,
      fileCount: r.fileCount, clientEntries: r.clientEntries,
      dshBundlePatch: r.dshBundlePatch, patchExists: r.patchExists,
      depsDeclared: r.depsDeclared, depsMissing: r.depsMissing,
      enginesDsh: r.enginesDsh, enginesOk: r.enginesOk,
      compatRange: r.compatRange || null, compatVerdict: r.compatVerdict || null,
      inject: [...new Set(r.refs.inject.map(x => x.service))],
      unknownServiceKeys: [...new Set(r.refs.unknownServiceKeys.map(x => x.service))],
      callCount: r.refs.calls.length,
      silentCatchCount: r.refs.silentCatch.filter(x => !x.vendored).length,
      silentCatchVendored: r.refs.silentCatch.filter(x => x.vendored).length,
      silentCatchEmpty: r.refs.silentCatch.filter(x => x.kind === 'empty' && !x.vendored).length,
      clientSilentCatchCount: r.refs.clientSilentCatch.length,
      findings: r.findings,
      l1l2: r.evidence,
      conclusion: r.conclusion,
    })),
    findings: allFindings,
    summary: {
      bundles: rows.length,
      staticScanned: rows.filter(r => r.staticScanReachable).length,
      staticUnreachable: rows.filter(r => !r.staticScanReachable).length,
      blocker: allFindings.filter(f => f.severity === 'blocker').length,
      high: allFindings.filter(f => f.severity === 'high').length,
      medium: allFindings.filter(f => f.severity === 'medium').length,
      low: allFindings.filter(f => f.severity === 'low').length,
      silentCatch: rows.reduce((n, r) => n + r.refs.silentCatch.filter(x => !x.vendored).length, 0),
      silentCatchVendored: rows.reduce((n, r) => n + r.refs.silentCatch.filter(x => x.vendored).length, 0),
      clientSilentCatch: rows.reduce((n, r) => n + r.refs.clientSilentCatch.length, 0),
      unavailable: rows.filter(r => (r.evidence.conclusion || '').includes('不可用')).length,
      partial: rows.filter(r => (r.evidence.conclusion || '').includes('部分')).length,
      verified: rows.filter(r => (r.evidence.conclusion || '') === '可用').length,
      unverified: rows.filter(r => !r.evidence.conclusion || (r.evidence.conclusion || '').includes('未验证') || (r.evidence.conclusion || '').includes('待核')).length,
    },
  }

  if (ARGS.print) { console.log(JSON.stringify(report, null, 2)); return }

  mkdirSync(OUT_DIR, { recursive: true })
  writeFileSync(join(OUT_DIR, 'audit-result.json'), JSON.stringify(report, null, 2), 'utf8')
  writeFileSync(join(OUT_DIR, 'matrix.md'), renderMatrix(report), 'utf8')
  writeFileSync(join(OUT_DIR, 'findings.json'), JSON.stringify(report.findings, null, 2), 'utf8')
  writeFileSync(join(OUT_DIR, 'service-refs.json'), JSON.stringify(rows.map(r => ({
    name: r.name, inject: [...new Set(r.refs.inject.map(x => x.service))],
    calls: r.refs.calls, silentCatch: r.refs.silentCatch,
  })), null, 2), 'utf8')

  if (!ARGS.quiet) {
    const s = report.summary
    console.log('审计完成：' + s.bundles + ' 个组合包 / 宿主半边静态可扫 ' + s.staticScanned + ' / 不可达 ' + s.staticUnreachable)
    console.log('L3 契约缺陷：blocker ' + s.blocker + ' · high ' + s.high + ' · medium ' + s.medium + ' · low ' + s.low + ' · 静默 catch ' + s.silentCatch + ' 处')
    console.log('结论分布：可用 ' + s.verified + ' / 部分可用 ' + s.partial + ' / 不可用 ' + s.unavailable + ' / 未验证及待核 ' + s.unverified)
    console.log('产物目录：' + OUT_DIR)
  }
}

main()
