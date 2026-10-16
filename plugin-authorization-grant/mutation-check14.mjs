import fs from 'node:fs';import path from 'node:path';import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url));
const scratch=path.join(dir,'mutation-check-14');
if(fs.existsSync(scratch))throw new Error('临时目录已被占用，拒绝覆盖：mutation-check-14');
// 变异检查：把候选14 分别改回“事故现场的错误实现 / 去掉来源校验 / 去掉一次性限制 / 界面复用 moveIssue”，
// 要求 test14 的每一条对应用例都必须判负。用例若在变异体上仍然全绿，说明它只是记录现状、抓不住回归。
const copyTree=(src,dest)=>{fs.mkdirSync(dest,{recursive:true});for(const e of fs.readdirSync(src,{withFileTypes:true})){const s=path.join(src,e.name),t=path.join(dest,e.name);if(e.isDirectory())copyTree(s,t);else fs.copyFileSync(s,t)}};
const T_AGENT_TOOLS='① 端到端：agent 没有调用入口';
const T_ORIGIN='① 端到端：无交互标记的调用被来源校验拒绝';
const T_TOKEN='③ 端到端：failureToken 不匹配被拒';
const T_ONCE='④ 端到端：同一 failureToken 第二次确认被拒';
const T_QUEUE='② 端到端：放回队列后能被调度器正常领取';
const T_UI_LIST='⑥-界面：受阻列表的「解除阻塞」对授权类不再走 moveIssue';
const T_UI_WIRE='⑥-界面：client.js 语法通过';
const cases=[
  {name:'去掉来源校验（agent 也能解锁授权类挂起）',file:'index.js',
   from:"        if (origin !== CLIENT_ORIGIN) return { ok: false, message: '授权确认只能由看板界面的人工点击发起：agent 不得解锁授权类挂起' }",
   to:"        if (false) return { ok: false, message: '授权确认只能由看板界面的人工点击发起：agent 不得解锁授权类挂起' }",
   mustNotPass:T_ORIGIN},
  {name:'给 agent 补一个授权解锁工具（等于把通道开放给 agent）',file:'index.js',
   from:'    for (const tool of mainTools) {',
   to:"    mainTools.push({ name: 'kanban_grant_authorization', description: '解锁授权类挂起', parameters: { type: 'object', properties: {}, required: [] }, execute: async () => ({ ok: true }) })\n    for (const tool of mainTools) {",
   mustNotPass:T_AGENT_TOOLS},
  {name:'不校验 failureToken（过期授权可以反复套用）',file:'failure-resolution.mjs',
   from:"  if (!failureToken || input.failureToken !== failureToken) throw new Error('失败已变化或缺失，拒绝过期授权');",
   to:"  if (false) throw new Error('失败已变化或缺失，拒绝过期授权');",
   mustNotPass:T_TOKEN},
  {name:'不要求人工确认标记（程序化调用也能放行）',file:'failure-resolution.mjs',
   from:"  if (input.confirmed !== true) throw new Error('必须由看板界面上的用户确认才算授权');",
   to:"  if (false) throw new Error('必须由看板界面上的用户确认才算授权');",
   mustNotPass:T_ORIGIN},
  {name:'去掉一次性限制（点一次永久放行）',file:'failure-resolution.mjs',
   from:"  if (history.some(x => x.failureToken === failureToken)) throw new Error('同一失败已授权一次，禁止反复放行，再次受阻需新的授权');",
   to:"  if (false) throw new Error('同一失败已授权一次，禁止反复放行，再次受阻需新的授权');",
   mustNotPass:T_ONCE},
  {name:'只改状态不解除 hold（回到 todo 也调不动）',file:'failure-resolution.mjs',
   from:"  f.action = 'recovered'; delete f.nextRetryAt;",
   to:"  delete f.nextRetryAt;",
   mustNotPass:T_QUEUE},
  {name:'界面「解除阻塞」继续复用 moveIssue（事故现场：必被 retryGuard 拦下）',file:'client.js',
   from:'if (isAuthHold(i)) setAuthFor(authFor === i.id ? null : i.id); else',
   to:'if (false) setAuthFor(authFor === i.id ? null : i.id); else',
   mustNotPass:T_UI_LIST},
  {name:'界面不再携带交互标记（服务端来源校验会拒掉所有界面授权）',file:'client.js',
   from:"headers: { 'Content-Type': 'application/json', 'X-Kanban-Client': 'board' },",
   to:"headers: { 'Content-Type': 'application/json' },",
   mustNotPass:T_UI_WIRE},
];
const expected=JSON.parse(fs.readFileSync(path.join(dir,'test14-results.json'),'utf8')).tests;
const results=[];
for(const c of cases){
  fs.rmSync(scratch,{recursive:true,force:true});fs.mkdirSync(scratch,{recursive:true});
  copyTree(path.join(dir,'candidate-14','lib'),path.join(scratch,'lib'));
  const f=path.join(scratch,'lib',c.file),text=fs.readFileSync(f,'utf8');
  if(text.split(c.from).length-1!==1)throw new Error('变异锚点不唯一：'+c.name);
  fs.writeFileSync(f,text.replace(c.from,c.to));
  const tf=path.join(scratch,'test14.mjs');
  fs.writeFileSync(tf,fs.readFileSync(path.join(dir,'test14.mjs'),'utf8').replace(/\.\/candidate-14\/lib\//g,'./lib/'));
  const r=spawnSync(process.execPath,[tf],{encoding:'utf8',cwd:scratch});
  const out=(r.stdout||'')+(r.stderr||'');
  const passedTests=expected.filter(n=>out.includes('通过：'+n));
  const notPassed=expected.filter(n=>!out.includes('通过：'+n));
  const detail=(out.match(/(AssertionError[^\n]*|ReferenceError[^\n]*|Error: [^\n]*)/)||[null])[0];
  const caught=r.status!==0&&!passedTests.includes(c.mustNotPass);
  results.push({mutant:c.name,mustNotPass:c.mustNotPass,caught,exitCode:r.status,passedTests,firstUnpassed:notPassed[0]||null,detail:detail?String(detail).slice(0,160):null});
  console.log((caught?'✓ 变异已被抓住：':'✗ 变异未被抓住（用例无效）：')+c.name);
  console.log('   退出码='+r.status+'；通过 '+passedTests.length+'/'+expected.length+'；第一条未通过的用例='+(notPassed[0]||'（无）'));
}
fs.rmSync(scratch,{recursive:true,force:true});
const allCaught=results.every(r=>r.caught);
fs.writeFileSync(path.join(dir,'mutation-check14-results.json'),JSON.stringify({candidate:'candidate-14',suite:'test14.mjs',mutants:results.length,results,allCaught,note:'把候选改回本轮事故的错误实现/去掉来源校验与一次性限制/界面复用 moveIssue，要求对应用例必须判负；仍然全绿即视为用例无效'},null,2));
if(!allCaught){console.error('变异检查未通过：有变异体没有被用例抓住');process.exit(1)}
console.log('变异检查通过：'+results.length+' 个变异体全部被 test14 抓住（临时目录已清理）。');
