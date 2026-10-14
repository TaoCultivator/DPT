#!/usr/bin/env node
/**
 * self-check.mjs —— 审计器的「探针自检」（确定性、离线、零副作用）
 *
 * 为什么需要它：`findings.json` 里只有 1 条高危，读者无法判断这是「真的干净」还是「扫描器扫不出来」。
 * 这里用**合成的**最小插件包当对照组，逐条验证扫描器对已知缺陷类型确实会报警、
 * 对已知误报类型确实不报警 —— 审计结论的可信度就建立在这上面。
 *
 * 合成包写在系统临时目录，跑完即删；不触碰任何真实插件、不改工作区、不联网。
 * 用法：node self-check.mjs [--quiet]   退出码 0 = 全部符合预期，1 = 有对照组不符
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))
const QUITE = process.argv.includes('--quiet')

/* ------------------------------------------------------------- 合成对照组 */

// 每条：目录名 → { file, source }，外加对 findings 的期望
const CASES = [
  {
    id: 'shell-run-missing-method',
    why: '本议题的立案缺陷：shell 服务没有 run（dsh-task-board 第一天的死因）',
    file: 'lib/index.js',
    source: [
      "export function apply(ctx) {",
      "  const shell = ctx.shell",
      "  return shell.run('echo hi')",
      "}",
    ].join('\n'),
    expect: [{ rule: 'unknown-service-method', severity: 'blocker', method: 'run', service: 'shell' }],
  },
  {
    id: 'shell-execute-ok',
    why: '反例：同一服务的真实方法不得报警',
    file: 'lib/index.js',
    source: [
      "export function apply(ctx) {",
      "  const shell = ctx.shell",
      "  return shell.execute({ command: 'echo hi' })",
      "}",
    ].join('\n'),
    expect: [],
  },
  {
    id: 'fs-string-instead-of-target',
    why: '契约要求 FsTarget，传字符串字面量要报 high',
    file: 'lib/index.js',
    source: [
      "export function apply(ctx) {",
      "  const fs = ctx.fs",
      "  return fs.writeText('C:/tmp/x.txt', 'hi')",
      "}",
    ].join('\n'),
    expect: [{ rule: 'fs-string-instead-of-target', severity: 'high', method: 'writeText', service: 'fs' }],
  },
  {
    id: 'guarded-settings-get',
    why: '静默降级型：有 typeof 守卫不抛异常，但仍必须报出来（dsh-cost-meter 实测就是这类）',
    file: 'lib/index.js',
    source: [
      "export function apply(ctx) {",
      "  const settings = ctx.get('settings')",
      "  return typeof settings?.get === 'function' ? settings.get('llm-deepseek') : undefined",
      "}",
    ].join('\n'),
    expect: [{ rule: 'unknown-service-method', severity: 'high', guarded: true, method: 'get', service: 'settings' }],
  },
  {
    id: 'misses-sandbox-policy',
    why: 'fs.writeText 不传沙箱策略 → 落回部署默认策略（dsh-task-board v1/v2 的坑）',
    file: 'lib/index.js',
    source: [
      "import { readFileSync } from 'node:fs'",
      "export function apply(ctx) {",
      "  const target = readFileSync('x.json')",
      "  const fs = ctx.fs",
      "  return fs.writeText(target, 'hi')",
      "}",
    ].join('\n'),
    expect: [{ rule: 'missing-sandbox-policy', severity: 'medium', method: 'writeText', service: 'fs' }],
  },
  { id: '__alias-of-call-not-a-service (误报回归)', file: 'lib/index.js', why: 'const handle = ctx.plugin(...) 后 handle.dispose() 不得被当成「服务 plugin」', source: [
      "export function apply(ctx) {",
      "  const handle = ctx.plugin({ name: 'x' })",
      "  handle.dispose()",
      "}",
    ].join('\n'),
    expect: [],
    forbidUnknownKeys: ['plugin'],
  },
  {
    id: 'get-accessor-not-a-service (误报回归)',
    why: 'const get = ctx.get; get.call(ctx, name) 不得被当成「服务 get」',
    file: 'lib/index.js',
    source: [
      "function optionalService(ctx, name) {",
      "  const get = ctx.get",
      "  if (typeof get !== 'function') return undefined",
      "  try { return get.call(ctx, name) } catch { return undefined }",
      "}",
      "export default { name: 'x', apply(ctx) { return optionalService(ctx, 'agents') } }",
    ].join('\n'),
    expect: [],
    forbidUnknownKeys: ['get'],
  },
  {
    id: 'comment-is-not-code (误报回归)',
    why: '注释里写的调用点不得被当成真实调用（dshmarket verify.js 的实测假警报）',
    file: 'lib/index.js',
    source: [
      "// 反例：const forms = ctx.configForms; forms.get('x') 会被漏掉",
      "export function apply(ctx) {",
      "  /* const settings = ctx.get('settings'); settings.get('llm-deepseek') */",
      "  return 1",
      "}",
    ].join('\n'),
    expect: [],
    forbidUnknownKeys: ['configForms', 'settings'],
  },
  {
    id: 'silent-catch-counted',
    why: '静默吞异常必须被计数（这是 dsh-task-board 坏了 4 轮没人知道的土壤）',
    file: 'lib/index.js',
    source: [
      "export function apply(ctx) {",
      "  try { ctx.tools.register({}) } catch (e) { console.error(e) }",
      "  try { ctx.tools.register({}) } catch { /* 忽略 */ }",
      "}",
    ].join('\n'),
    expect: [],
    expectSilentCatch: 2,
  },
]

/* ------------------------------------------------------------------- 执行 */

const profile = mkdtempSync(join(tmpdir(), 'plugin-audit-selfcheck-'))
const out = join(profile, 'out')
try {
  const bundles = []
  for (const c of CASES) {
    const pkgDir = join(profile, 'node_modules', c.id)
    mkdirSync(join(pkgDir, 'lib'), { recursive: true })
    writeFileSync(join(pkgDir, 'package.json'), JSON.stringify({ name: c.id, version: '0.0.0' }, null, 2))
    writeFileSync(join(pkgDir, c.file), c.source, 'utf8')
    bundles.push(c.id)
  }
  writeFileSync(join(profile, 'package.json'), JSON.stringify({ name: 'selfcheck-profile', dsh: { profile: { bundles } } }, null, 2))

  const script = join(HERE, 'audit-plugins.mjs')
  const res = spawnSync(process.execPath, [script, '--profile', profile, '--out', out, '--quiet'], { encoding: 'utf8' })
  if (res.status !== 0) {
    console.error('审计器执行失败：', res.status, res.stderr)
    process.exit(1)
  }
  const report = JSON.parse(readFileSync(join(out, 'audit-result.json'), 'utf8'))
  const byName = new Map(report.bundles.map(b => [b.name, b]))

  let failed = 0
  for (const c of CASES) {
    const b = byName.get(c.id)
    const problems = []
    if (!b) { problems.push('组合包未出现在结果里'); } else {
      for (const want of c.expect) {
        const hit = b.findings.find(f => f.rule === want.rule && (!want.service || f.service === want.service) && (!want.method || f.method === want.method))
        if (!hit) problems.push('未报出 ' + want.rule + '（' + want.service + '.' + want.method + '）')
        else if (want.severity && hit.severity !== want.severity) problems.push('severity 期望 ' + want.severity + ' 实得 ' + hit.severity)
        else if (want.guarded !== undefined && hit.guarded !== want.guarded) problems.push('guarded 期望 ' + want.guarded + ' 实得 ' + hit.guarded)
      }
      if (c.expect.length === 0 && b.findings.length > 0) problems.push('期望零 finding，实得 ' + JSON.stringify(b.findings.map(f => f.rule + ':' + f.service + '.' + f.method)))
      for (const k of c.forbidUnknownKeys || []) {
        if (b.unknownServiceKeys.includes(k) || (b.weakUnknownKeys || []).includes(k)) problems.push('不应出现的目录外服务 key：' + k)
      }
      if (c.expectSilentCatch !== undefined && b.silentCatchCount !== c.expectSilentCatch) {
        problems.push('静默 catch 期望 ' + c.expectSilentCatch + ' 实得 ' + b.silentCatchCount)
      }
    }
    const ok = problems.length === 0
    if (!ok) failed++
    if (!QUITE) console.log((ok ? '✔' : '✘') + ' ' + c.id.padEnd(38) + (ok ? '' : ' ← ' + problems.join('；')) + '\n    ' + c.why)
  }
  if (!QUITE) console.log('\n对照组 ' + CASES.length + ' 个：通过 ' + (CASES.length - failed) + ' / 失败 ' + failed)
  process.exit(failed === 0 ? 0 : 1)
} finally {
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}
