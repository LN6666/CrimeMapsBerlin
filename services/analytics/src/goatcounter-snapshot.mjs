import {readFile,writeFile,mkdir,rename,stat} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {statsFromExport} from './goatcounter-export.mjs';
import {LANGUAGES} from './contract.mjs';
import {renderChart} from './chart.mjs';
const [city,exportDirectory,repositoryDirectory]=process.argv.slice(2);
if(!exportDirectory || !repositoryDirectory) throw new Error('Usage: node src/goatcounter-snapshot.mjs CITY LOCAL_JSON_EXPORT_DIRECTORY CITY_REPOSITORY');
// Raw exports stay local. Only an allowlist of aggregate files is ever opened.
const read=async(name,limit=64*1024*1024)=>{
 const path=resolve(exportDirectory,name);if((await stat(path)).size>limit)throw new Error('export_too_large');return readFile(path,'utf8');
};
const jsonl=async name=>(await read(name)).split('\n').filter(Boolean).map(line=>JSON.parse(line));
const [info,paths,locations,locationStats,hitStats]=await Promise.all([read('info.json',65536).then(JSON.parse),jsonl('paths.jsonl'),jsonl('locations.jsonl'),jsonl('location_stats.jsonl'),jsonl('hit_stats.jsonl')]);
const stats=statsFromExport({info,paths,locations,locationStats,hitStats},city);
const data=JSON.stringify(stats,null,2)+'\n', dataSha=createHash('sha256').update(data).digest('hex');
const targets=[];
for(const locale of LANGUAGES)for(const layout of ['wide','stacked']){
 const name=`visitors-by-country.${locale}${layout==='stacked'?'.mobile':''}.svg`,svg=renderChart(stats,locale,layout);
 const metadata={schema_version:1,city,locale,layout,presentation:'world_map_and_rank',path:`docs/assets/${name}`,sha256:createHash('sha256').update(svg).digest('hex'),source_kind:'live_aggregate',metric:stats.metric,source:stats.source,source_site:stats.source_site,source_path:stats.source_path,generated_at_utc:stats.generated_at,range_start:stats.range_start,range_end:stats.range_end,public_stats_sha256:dataSha};
 targets.push([`docs/assets/${name}`,svg],[`docs/assets/${name.replace(/\.svg$/,'.json')}`,JSON.stringify(metadata,null,2)+'\n']);
}
targets.push(['web/public/safety/analytics/visitors-by-country.json',data],['docs/assets/visitors-by-country.data.json',data]);
// Validate/render every output before touching last-good files. Older exports
// are rejected, and this full-snapshot replacement never adds overlapping days.
const previous=resolve(repositoryDirectory,'web/public/safety/analytics/visitors-by-country.json');
try{const old=JSON.parse(await readFile(previous,'utf8'));if(old.city!==city || old.generated_at>stats.generated_at)throw new Error('preserve_newer_snapshot');}catch(error){if(error.code!=='ENOENT')throw error;}
const staged=[];
for(const [name,text] of targets){const file=resolve(repositoryDirectory,name);await mkdir(dirname(file),{recursive:true});const temporary=`${file}.${randomUUID()}.tmp`;await writeFile(temporary,text);staged.push([temporary,file]);}
for(const [temporary,file] of staged)await rename(temporary,file);
console.log(JSON.stringify({city,status:'saved_aggregate_snapshot',metric:stats.metric,generated_at:stats.generated_at,public_stats_sha256:dataSha,files:targets.map(([path])=>path)}));
