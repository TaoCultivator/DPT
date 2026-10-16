import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {spawnSync} from 'node:child_process';import {fileURLToPath,pathToFileURL} from 'node:url';
// 安装后独立核对：① 在线 8 个模块哈希 == 清单候选哈希；② 在线文件与 candidate-14 逐字节一致；
// ③ 直接对“在线已安装文件”跑一遍 test14，证明装的这份（而不只是候选目录）能过。
const dir=path.dirname(fileURLToPath(import.meta.url));
const root='C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/dsh-task-board';
const lib=path.join(root,'lib');
const manifest=JSON.parse(fs.readFileSync(path.join(dir,'deployment-manifest-14.json'),'utf8'));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const report={root,modules:manifest.files.length,files:[]};
for(const f of manifest.files){
  const live=sha(path.join(root,f.relative)),cand=sha(path.join(dir,'candidate-14',f.relative));
  const same=live===f.candidateSha256&&live===cand;
  report.files.push({module:f.relative,liveSha256:live.slice(0,12),manifestMatches:live===f.candidateSha256,candidateMatches:live===cand});
  if(!same)throw new Error('安装后核对失败：'+f.relative+' live='+live+' manifest='+f.candidateSha256+' candidate='+cand);
}
report.allHashesMatch=true;report.changedModules=manifest.files.filter(f=>f.originalSha256!==f.candidateSha256).map(f=>f.relative);
console.log('① 哈希核对：'+manifest.files.length+'/'+manifest.files.length+' 与清单候选哈希一致，且与 candidate-14 逐字节一致');
console.log('   实际变化的模块：'+report.changedModules.join('、'));

// ③ 把 test14 的导入改写到“在线已安装文件”，对在线副本再跑一遍
const scratch=path.join(dir,'verify-installed-14');
if(fs.existsSync(scratch))throw new Error('临时目录已被占用，拒绝覆盖：verify-installed-14');
fs.mkdirSync(scratch,{recursive:true});
try{
  const text=fs.readFileSync(path.join(dir,'test14.mjs'),'utf8')
    .replace(/\.\/candidate-14\/lib\/([a-zA-Z0-9._-]+)/g,(_m,n)=>pathToFileURL(path.join(lib,n)).href);
  if(text.includes('candidate-14'))throw new Error('导入改写不完整，仍指向候选目录');
  const tf=path.join(scratch,'test14-live.mjs');fs.writeFileSync(tf,text);
  const r=spawnSync(process.execPath,[tf],{encoding:'utf8',cwd:scratch});
  const out=(r.stdout||'')+(r.stderr||'');
  const m=out.match(/合计通过：(\d+)/);
  report.liveSuitePassed=r.status===0;
  report.liveSuitePassedCount=m?Number(m[1]):0;
  console.log('② 对在线已安装文件跑 test14.mjs：'+(r.status===0?('通过 '+report.liveSuitePassedCount+' 组'):'失败（退出码 '+r.status+'）'));
  if(r.status!==0){console.error(out.slice(-1500));throw new Error('在线文件未通过 test14')}
  if(report.liveSuitePassedCount!==14)throw new Error('在线用例组数异常：'+report.liveSuitePassedCount+'（应为 14）');
}finally{fs.rmSync(scratch,{recursive:true,force:true})}
report.verifiedAt=new Date().toISOString();
report.restartRequired=true;
fs.writeFileSync(path.join(dir,'verify-installed-14.json'),JSON.stringify(report,null,2));
console.log('独立核对通过：'+manifest.files.length+' 个模块哈希全部匹配 + 在线文件通过全部用例（需重启后才会加载这份代码）。');
