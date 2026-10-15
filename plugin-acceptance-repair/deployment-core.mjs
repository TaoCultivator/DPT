import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
export const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
function target(root,relative){if(!/^lib\/[a-zA-Z0-9._-]+$/.test(relative))throw new Error('拒绝安装路径逃逸');return path.join(root,relative)}
export function inspectPlan({root,candidate,manifest}) {
  const seen=new Set();return manifest.files.map(f=>{if(seen.has(f.relative))throw new Error('清单路径重复');seen.add(f.relative);const dest=target(root,f.relative),source=target(candidate,f.relative);const bytes=fs.readFileSync(source);if(sha(bytes)!==f.candidateSha256)throw new Error('候选哈希不匹配：'+f.relative);const existing=fs.existsSync(dest)?fs.readFileSync(dest):null;if(f.originalSha256===null?existing!==null:(!existing||sha(existing)!==f.originalSha256))throw new Error('原件已变化：'+f.relative);return {relative:f.relative,existing:existing?.toString('base64')??null,installedSha256:f.candidateSha256}});
}
// 仅提供库接口，不自动定位在线目录、不自动安装。调用方须保证宿主已停到安全窗口。
export function install({root,candidate,manifest,backupDir,authorized=false,safeWindow=false,injectAfterWrite}) {
  if(!authorized||!safeWindow)throw new Error('缺当次授权或安全窗口，拒绝安装');
  const files=inspectPlan({root,candidate,manifest});
  fs.mkdirSync(backupDir,{recursive:false});
  const journal={root:path.resolve(root),files,phase:'prepared'};
  const journalPath=path.join(backupDir,'installation.json');fs.writeFileSync(journalPath,JSON.stringify(journal,null,2),{flag:'wx'});
  let written=0;
  try {
    for(const f of files){const dest=target(root,f.relative);fs.mkdirSync(path.dirname(dest),{recursive:true});written++;fs.writeFileSync(dest,fs.readFileSync(target(candidate,f.relative)));injectAfterWrite?.(written)}
    for(const f of files)if(sha(fs.readFileSync(target(root,f.relative)))!==f.installedSha256)throw new Error('安装后哈希不匹配');
    journal.phase='installed';fs.writeFileSync(journalPath,JSON.stringify(journal,null,2));return journalPath;
  }catch(error){
    // 不改状态文档。只恢复本次确实写过的模块；调用方必须保证无并发写入。
    for(const f of files.slice(0,written).reverse()){const dest=target(root,f.relative);if(f.existing===null)fs.unlinkSync(dest);else fs.writeFileSync(dest,Buffer.from(f.existing,'base64'))}
    journal.phase='reverted-after-failure';fs.writeFileSync(journalPath,JSON.stringify(journal,null,2));throw error;
  }
}
export function rollback(journalPath,{safeWindow=false}={}) {
  if(!safeWindow)throw new Error('缺安全窗口，拒绝回滚');const journal=JSON.parse(fs.readFileSync(journalPath,'utf8'));if(journal.phase!=='installed')throw new Error('不是可回滚安装');
  for(const f of journal.files)if(!fs.existsSync(target(journal.root,f.relative))||sha(fs.readFileSync(target(journal.root,f.relative)))!==f.installedSha256)throw new Error('安装后文件已变化，拒绝覆盖新修改');
  for(const f of [...journal.files].reverse()){const dest=target(journal.root,f.relative);if(f.existing===null)fs.unlinkSync(dest);else fs.writeFileSync(dest,Buffer.from(f.existing,'base64'))}
  journal.phase='rolled-back';fs.writeFileSync(journalPath,JSON.stringify(journal,null,2));
}
