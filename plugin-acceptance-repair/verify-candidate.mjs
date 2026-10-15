import fs from 'node:fs';import path from 'node:path';import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url));
const nine='E:/AI图书馆/DSH-学习库/01-插件与技能调研/原始素材/2026-10-15-看板九级调度升级';
const cand=process.argv[2]||'candidate-3';
const scratch=path.join(dir,'verify-'+cand);fs.rmSync(scratch,{recursive:true,force:true});fs.mkdirSync(scratch,{recursive:true});
// 2026-10-15 环境缺陷替换：本机 Node v22.21.1 对“源目录位于 E:\AI图书馆\…”的 fs.cpSync(recursive) 会直接崩溃
// （0xC0000409，用候选9同样复现），改用 readdir+copyFileSync 手工递归复制，行为等价。
function copyTree(src,dest){fs.mkdirSync(dest,{recursive:true});for(const e of fs.readdirSync(src,{withFileTypes:true})){const s=path.join(src,e.name),t=path.join(dest,e.name);if(e.isDirectory())copyTree(s,t);else fs.copyFileSync(s,t)}}
// 被测对象就位为 scratch/plugin-candidate，使各套用例的相对导入全部指向它
copyTree(path.join(dir,cand),path.join(scratch,'plugin-candidate'));
const shared=['scheduler-core.mjs','host-adapter.mjs','failure-resolution.mjs','bounded-write.mjs','review-interruption.mjs','restart-recovery.mjs','deployment-core.mjs'];
for(const n of shared){const candFile=path.join(dir,cand,'lib',n);
  if(fs.existsSync(candFile)){fs.copyFileSync(candFile,path.join(scratch,n));continue}
  const alt=[path.join(nine,'plugin-candidate/lib',n),path.join(nine,n)];
  const src=alt.find(p=>fs.existsSync(p));
  if(!src)throw new Error('找不到共享模块：'+n);
  fs.copyFileSync(src,path.join(scratch,n));}
const nineTests=fs.readdirSync(nine).filter(f=>f.endsWith('.test.mjs'));
for(const t of nineTests)fs.copyFileSync(path.join(nine,t),path.join(scratch,t));
// 本目录的用例：把候选路径统一改写到 scratch/plugin-candidate
const localTests=['test.mjs','test2.mjs','test3.mjs','test4.mjs','test5.mjs','test6.mjs','test7.mjs','test8.mjs','test9.mjs'];
// 候选10 起新增 test10（诊断类分流自动立项）；更早的候选没有该能力，不强行套用，保证历史基线 26 套 181 组可原样复现。
if((Number(String(cand).replace(/\D/g,''))||0)>=10)localTests.push('test10.mjs');
// 候选11 起新增 test11（任何 ACCEPTANCE_* 失败码都归修复类）；同样不套用到更早候选，保证历史基线 27 套 190 组可原样复现。
if((Number(String(cand).replace(/\D/g,''))||0)>=11)localTests.push('test11.mjs');
for(const t of localTests){let s=fs.readFileSync(path.join(dir,t),'utf8');
  s=s.replace(/\.\/(candidate-\d+|plugin-candidate)\/lib\//g,'./plugin-candidate/lib/');
  fs.writeFileSync(path.join(scratch,t),s);}
const snapshot=fs.readdirSync('E:/Works/DPT/.dsh').filter(f=>/^kanban-state\.pre-scheduler-v2-.*\.json$/.test(f)).sort().pop();
const snapshotPath=snapshot?path.join('E:/Works/DPT/.dsh',snapshot):null;
let total=0;const failed=[];
for(const t of [...nineTests,...localTests]){
  process.stdout.write('  '+t.padEnd(34,' ')+' … ');
  const args=[path.join(scratch,t)];
  if(t==='scheduler-core.test.mjs'&&snapshotPath)args.push(snapshotPath);
  const r=spawnSync(process.execPath,args,{encoding:'utf8',cwd:scratch});
  const out=(r.stdout||'')+(r.stderr||'');const m=out.match(/合计通过：(\d+)/);const n=m?Number(m[1]):0;total+=n;
  console.log(r.status===0?('通过 '+n+' 组'):('失败（退出码 '+r.status+'）'));
  if(r.status!==0)failed.push({t,out:out.slice(-700)});}
fs.writeFileSync(path.join(dir,'verify-'+cand+'.json'),JSON.stringify({candidate:cand,suites:nineTests.length+localTests.length,total,failed},null,2));
if(failed.length){for(const f of failed)console.error('\n'+f.t+'\n'+f.out);process.exit(1)}
fs.rmSync(scratch,{recursive:true,force:true});
console.log('\n对 '+cand+' 共 '+(nineTests.length+localTests.length)+' 套：合计 '+total+' 组通过（临时目录已清理）。');






