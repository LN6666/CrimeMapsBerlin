import {CITIES,publishStats} from './contract.mjs';
import {countPath} from './goatcounter-client.mjs';
export const SOURCE_SITE = 'ryoushunnei.goatcounter.com';
const day = value => typeof value==='string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && new Date(`${value}T00:00:00Z`).toISOString().slice(0,10)===value;
const integer = value => Number.isSafeInteger(value) && value>=0;
export function statsFromExport({info,paths,locations,locationStats,hitStats},city) {
  if (!CITIES.includes(city) || info?.export_version!=='1.0' || info.created_for!==SOURCE_SITE
      || !Number.isFinite(Date.parse(info.created_at)) || ![paths,locations,locationStats,hitStats].every(Array.isArray)) throw new Error('invalid_goatcounter_export');
  const wanted=countPath(city), matches=paths.filter(r=>r.path===wanted && !r.event);
  if (matches.length!==1 || !integer(matches[0].id)) throw new Error('missing_or_ambiguous_city_path');
  const pathId=matches[0].id;
  if (paths.filter(r=>r.id===pathId).length!==1) throw new Error('ambiguous_path_id');
  const selected=locationStats.filter(r=>r.path_id===pathId);
  const hits=hitStats.filter(r=>r.path_id===pathId);
  const referencedLocations=new Set(selected.map(r=>r.location)),countryMap=new Map();
  for(const row of locations) {
    if (!row || typeof row.country!=='string' || typeof row.region!=='string') continue;
    const key=row.country+(row.region?`-${row.region}`:'');
    // The real export contains a global dictionary, including unrelated legacy
    // non-country entries. Only dictionaries referenced by this city matter.
    if (!referencedLocations.has(key)) continue;
    if (!/^(?:[A-Z]{2}|)$/.test(row.country) || !/^[A-Za-z0-9-]*$/.test(row.region)) throw new Error('invalid_referenced_location_dictionary');
    if(countryMap.has(key)) throw new Error('duplicate_location_dictionary');
    countryMap.set(key,row.country||'ZZ');
  }
  const sums=new Map(), dates=[], pairs=new Set();let countryTotal=0,hitTotal=0;
  for(const row of selected) {
    if(!day(row.day) || row.day>info.created_at.slice(0,10) || !integer(row.count) || !countryMap.has(row.location)) throw new Error('invalid_country_row');
    const key=`${row.day}/${row.location}`;
    if(pairs.has(key)) throw new Error('overlapping_country_export');pairs.add(key);
    const country=countryMap.get(row.location),count=(sums.get(country)||0)+row.count;
    countryTotal+=row.count;if(!integer(count)||!integer(countryTotal)) throw new Error('count_overflow');
    sums.set(country,count);dates.push(row.day);
  }
  for(const row of hits) {
    if(typeof row.hour!=='string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$/.test(row.hour) || !Number.isFinite(Date.parse(row.hour))
        || row.hour>info.created_at || !integer(row.count)) throw new Error('invalid_hit_row');
    const key=`${row.hour}/${row.ref_id}`;
    if(pairs.has(key))throw new Error('overlapping_hit_export');pairs.add(key);
    hitTotal+=row.count;if(!integer(hitTotal))throw new Error('count_overflow');
  }
  if(!countryTotal || !dates.length)throw new Error('no_city_country_data');
  if(countryTotal!==hitTotal)throw new Error('country_total_mismatch');
  dates.sort();
  const stats=publishStats(city,[...sums].map(([country,pv])=>({country,pv,started_at:dates[0]})),new Date(info.created_at));
  return {...stats,metric:'goatcounter_pageviews',source:'goatcounter_json_export',source_site:SOURCE_SITE,source_path:wanted,
    counting:{sessions:false,individual_pageviews:false},range_start:dates[0],range_end:dates.at(-1)};
}
