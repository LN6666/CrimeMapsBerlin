import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtemp,writeFile,readFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const script=new URL('../src/snapshot.mjs',import.meta.url).pathname;
test('snapshot refuses local/unconnected input and preserves previous good file',async()=>{
 const root=await mkdtemp(join(tmpdir(),'crimemaps-snapshot-'));
 try {
  await mkdir(join(root,'docs/assets'),{recursive:true});await writeFile(join(root,'docs/assets/visitors-by-country.en.svg'),'previous reviewed image');
  const r=spawnSync(process.execPath,[script,'http://127.0.0.1:4188','berlin','en','docs/assets/visitors-by-country.en.svg'],{cwd:root,encoding:'utf8'});
  assert.equal(r.status,1);assert.equal(await readFile(join(root,'docs/assets/visitors-by-country.en.svg'),'utf8'),'previous reviewed image');
  const wrong=spawnSync(process.execPath,[script,'https://unconnected.invalid','evil-city','en','../outside.svg'],{cwd:root,encoding:'utf8'});assert.equal(wrong.status,1);
 } finally {await rm(root,{recursive:true,force:true});}
});
