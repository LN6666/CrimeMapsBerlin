import {mkdir,writeFile,rename,rm} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {renderChart,validateStats} from './chart.mjs';
import {LANGUAGES,validCity} from './contract.mjs';
// Fetch live public aggregates; never create demonstration counts for a README.
const [endpoint,city,lang,out]=process.argv.slice(2);
let temporary=[];
try {
  const base=new URL(endpoint);
  if(base.protocol!=='https:' || base.username || base.password || base.search || base.hash || !validCity(city) || !LANGUAGES.includes(lang)
    || out!==`docs/assets/visitors-by-country.${lang}.svg`) throw new Error('usage');
  const url=new URL(`/v1/stats/${city}`,base);
  const response=await fetch(url,{signal:AbortSignal.timeout(6000),credentials:'omit',redirect:'error'});
  if(!response.ok) throw new Error('unavailable');
  const stats=await response.json();
  const age=Date.now()-Date.parse(stats.generated_at);
  if(!validateStats(stats) || stats.city!==city || age< -60000 || age>600000) throw new Error('invalid_live_stats');
  const svg=renderChart(stats,lang);
  const metadata={schema_version:1,city,locale:lang,path:out,sha256:createHash('sha256').update(svg).digest('hex'),generated_at_utc:stats.generated_at,source_kind:'live_aggregate',source:url.toString(),metric:stats.metric,minimum_sample:20,rounding:10};
  const file=resolve(out),sidecar=file.replace(/\.svg$/,'.json'),suffix=`.tmp-${randomUUID()}`;
  temporary=[file+suffix,sidecar+suffix];await mkdir(dirname(file),{recursive:true});
  await writeFile(temporary[0],svg,{encoding:'utf8'});await writeFile(temporary[1],JSON.stringify(metadata,null,2)+'\n',{encoding:'utf8'});
  // Prepare both files before replacement. Consumers verify the sidecar digest;
  // a partial rename cannot be accepted as a matching reviewed snapshot.
  await rename(temporary[0],file);await rename(temporary[1],sidecar);
  console.log(JSON.stringify(metadata));
} catch {
  console.error('Snapshot not accepted. Usage from repo root: node services/analytics/src/snapshot.mjs https://CONNECTED-WORKER city de|en|zh docs/assets/visitors-by-country.LANG.svg. A current live endpoint is required.');
  process.exitCode=1;
} finally {
  await Promise.all(temporary.map(file=>rm(file,{force:true})));
}
