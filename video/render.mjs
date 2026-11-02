import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {validateProps} from './src/protocol.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
function readSafe(relative){
 let target=root;
 for (const part of relative.split('/')) {
  if (!part || part==='.' || part==='..') throw new Error('Unsafe local path.');
  target=path.join(target,part);
  const info=fs.lstatSync(target);
  if (info.isSymbolicLink()) throw new Error('Symlink media/config refused.');
 }
 const info=fs.statSync(target);
 if(!info.isFile()||info.nlink!==1)throw new Error('Single-linked regular local files required.');
 return target;
}
try {
 const mode=process.argv[2];
 if(!['draft','final'].includes(mode)||process.argv.length>4)throw new Error('Use node render.mjs draft|final [reviewed-props.json].');
 let props={};
 if(process.argv[3]){
  if(process.argv[3]!=='reviewed-props.json')throw new Error('Use fixed ignored reviewed-props.json.');
  props=JSON.parse(fs.readFileSync(readSafe('reviewed-props.json'),'utf8'));
 }
 validateProps(props,mode==='final');
 for(const clip of [props.gameChat?.file,props.codex?.file,props.narration].filter(Boolean))readSafe('public/'+clip);
 const cli=path.join(root,'node_modules','@remotion','cli','remotion-cli.js');
 if(!fs.existsSync(cli))throw new Error('Coordinator must install reviewed pinned dependencies first.');
 const args=[cli,'render','src/index.js',mode==='draft'?'Draft':'Final',`out/${mode}.mp4`,'--props',JSON.stringify(props),'--codec','h264'];
 const result=spawnSync(process.execPath,args,{cwd:root,stdio:'inherit'});
 process.exitCode=result.status??1;
} catch {console.error('Render refused: missing/unsafe reviewed local assets, invalid props, or dependencies unavailable. See video/README.md.');process.exitCode=1;}
