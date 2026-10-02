import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { CITIES, LANGUAGES } from './contract.mjs';
import { renderPlaceholder } from './chart.mjs';
const [city,repoRoot='.']=process.argv.slice(2);
if(!CITIES.includes(city))throw new Error('A fixed city key is required');
const dir=resolve(repoRoot,'docs/assets');await mkdir(dir,{recursive:true});
const rows=[];
for(const lang of LANGUAGES)for(const layout of ['wide','stacked']){
  const name=`visitors-by-country.${lang}${layout==='stacked'?'.mobile':''}.svg`,file=resolve(dir,name),sidecar=file.replace(/\.svg$/,'.json');
  let exists=false;
  try {
    const existing=await readFile(file);exists=true;const previous=JSON.parse(await readFile(sidecar,'utf8'));
    if(previous.source_kind!=='not_connected' || previous.sha256!==createHash('sha256').update(existing).digest('hex'))throw new Error('Existing image must be preserved');
  } catch(error) {if(exists || error.code!=='ENOENT')throw error;}
  const svg=renderPlaceholder(city,lang,layout),sha256=createHash('sha256').update(svg).digest('hex');
  const metadata={schema_version:1,city,locale:lang,layout,presentation:'world_map_and_rank',path:`docs/assets/${name}`,sha256,source_kind:'not_connected',collection_status:'not_connected',metric:null,source:null,generated_at_utc:null};
  await writeFile(file,svg);await writeFile(sidecar,JSON.stringify(metadata,null,2)+'\n');rows.push(metadata);
}
console.log(JSON.stringify(rows));
