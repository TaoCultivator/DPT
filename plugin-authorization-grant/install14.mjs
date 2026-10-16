import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath} from 'node:url';
import {install,rollback} from './deployment-core.mjs';
const dir=path.dirname(fileURLToPath(import.meta.url));
const root='C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/dsh-task-board';
const candidate=path.join(dir,'candidate-14');
const manifest=JSON.parse(fs.readFileSync(path.join(dir,'deployment-manifest-14.json'),'utf8'));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
// 安装前逐条核对“原件哈希 == 在线文件”，任何漂移都要先停下来
for(const f of manifest.files){const live=sha(path.join(root,f.relative));if(live!==f.originalSha256)throw new Error('在线原件与清单不符：'+f.relative+' live='+live);if(sha(path.join(candidate,f.relative))!==f.candidateSha256)throw new Error('候选哈希不符：'+f.relative)}
const stamp=new Date().toISOString().replace(/[-:T]/g,'').slice(0,12).replace(/(\d{8})(\d{4})/,'$1-$2');
const backupDir=path.join(dir,'install-backup14-'+stamp);
const journal=install({root,candidate,manifest,backupDir,authorized:true,safeWindow:true});
let changed=0;for(const f of manifest.files){const after=sha(path.join(root,f.relative));if(after!==f.candidateSha256)throw new Error('安装后哈希不匹配：'+f.relative);if(f.originalSha256!==f.candidateSha256)changed++}
console.log('安装完成：备份目录='+backupDir);
console.log('8 个模块哈希全部匹配；其中哈希真的变化的文件数='+changed);
for(const f of manifest.files)if(f.originalSha256!==f.candidateSha256)console.log('  变化：'+f.relative+'  '+f.originalSha256.slice(0,12)+' -> '+f.candidateSha256.slice(0,12));
console.log('journal='+journal+'（回滚入口：rollback(journal,{safeWindow:true})，未自动执行）');
console.log('注意：在线 DSH 进程需重启后才会加载候选14（本次未重启、未改任何用户开关）。');
