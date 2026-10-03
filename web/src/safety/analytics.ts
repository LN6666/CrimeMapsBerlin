import en from './locales/en.json' with {type:'json'};
import de from './locales/de.json' with {type:'json'};
import zh from './locales/zh.json' with {type:'json'};
import {analyticsCopy,type AnalyticsKey,type AnalyticsLanguage} from './analytics-copy';
import {mountGoatCounter} from '../../../services/analytics/src/goatcounter-client.mjs';
export {markAnalyticsLanguageNavigation} from '../../../services/analytics/src/goatcounter-client.mjs';
import type {WorldStats,WorldStatus} from '../../../services/analytics/src/world-card.mjs';
export type {AnalyticsLanguage} from './analytics-copy';
export interface AnalyticsOptions {
 city:string; language:AnalyticsLanguage; collectionEnabled?:boolean; snapshotUrl?:string;
 translate?:(key:AnalyticsKey,values?:Record<string,string>)=>string;
}
const cityNames:Record<AnalyticsLanguage,Record<string,string>>={en,de,zh};
const cities=new Set(['berlin','hamburg','munich','cologne','frankfurt','dusseldorf','stuttgart','leipzig','dortmund','bremen','essen','dresden','hannover','nuremberg']);
export function mountAnalytics(container:HTMLElement,options:AnalyticsOptions) {
 let language=options.language,alive=true,visualVersion=0,retrieved=false,stats:WorldStats|undefined;
 let status:Exclude<WorldStatus,'live'>='not_connected';
 const city=options.city,controller=new AbortController();
 const collector=mountGoatCounter({city,enabled:options.collectionEnabled===true});
 const text=(key:AnalyticsKey)=>analyticsCopy[language][key];
 const el=<T extends keyof HTMLElementTagNameMap>(tag:T,cls='')=>{const e=document.createElement(tag);e.className=cls;return e;};
 const section=el('section','analytics-summary'),header=el('div','analytics-header'),identity=el('span','analytics-city'),title=el('h2'),summary=el('p','analytics-status'),details=el('details','analytics-distribution'),caption=el('summary'),world=el('div','analytics-world-host');
 const notes=el('details','analytics-notes'),notesCaption=el('summary');
 const collection=el('p'),privacy=el('p'),source=el('p'),period=el('p');
 summary.setAttribute('role','status');section.dataset.city=city;
 header.append(title,identity);
 notes.append(notesCaption,collection,privacy,period,source);details.append(caption,world,notes);section.append(header,summary,details);container.replaceChildren(section);
 const renderWorld=()=>{
  const version=++visualVersion;
  if(!alive||!details.open||!cities.has(city))return;
  const isCurrent=()=>alive&&details.open&&version===visualVersion;
  void import('./analytics-world-card').then(m=>m.renderAnalyticsWorldCard(world,{city,language,stats,status,isCurrent})).catch(()=>{if(isCurrent())world.textContent=text('analytics.unavailable');});
 };
 const render=()=>{
  if(!alive)return;
  identity.textContent=cityNames[language][`city.${city}`]??city;
  title.textContent=text('analytics.title');section.setAttribute('aria-label',text('analytics.title'));section.dataset.status=stats?'live':status;
  summary.textContent=stats?(stats.total_pv===null?text('analytics.small'):`${text('analytics.total')}: ${new Intl.NumberFormat(language).format(stats.total_pv)}`):text(status==='loading'?'analytics.loading':status==='unavailable'?'analytics.unavailable':'analytics.notConnected');
  details.hidden=!cities.has(city);caption.textContent=text('analytics.countries');notesCaption.textContent=text('analytics.notes');
  collection.textContent=text(options.collectionEnabled?'analytics.collection':'analytics.off');privacy.textContent=text('analytics.privacy');source.textContent=text('analytics.source');
  period.textContent=stats?`${text('analytics.range')}: ${stats.range_start} — ${stats.range_end} · ${text('analytics.updated')}: ${stats.generated_at}`:'';
  renderWorld();
 };
 const load=async()=>{
  if(retrieved||!options.snapshotUrl||!cities.has(city))return;
  retrieved=true;
  try {
   const url=new URL(options.snapshotUrl,location.href);
   if(url.origin!==location.origin||url.search||url.hash||!url.pathname.endsWith('/safety/analytics/visitors-by-country.json'))throw new Error('invalid_snapshot_url');
   status='loading';render();
   const response=await fetch(url.href,{signal:controller.signal,credentials:'omit',referrerPolicy:'no-referrer'});
   if(response.status===404){status='not_connected';render();return;}
   if(!response.ok)throw new Error('snapshot_unavailable');
   const raw=await response.text();if(raw.length>20000)throw new Error('oversized_snapshot');
   const parsed:unknown=JSON.parse(raw);
   const {isPublicStats}=await import('../../../services/analytics/src/world-card.mjs');
   if(!isPublicStats(parsed,city)||parsed.metric!=='goatcounter_pageviews')throw new Error('invalid_city_snapshot');
   if(alive){stats=parsed;render();}
  }catch(error){if(alive&&!controller.signal.aborted){status='unavailable';render();}}
 };
 details.addEventListener('toggle',()=>{if(details.open)void load();renderWorld();});
 render();
 return {setLanguage(next:AnalyticsLanguage){language=next;render();},destroy(){alive=false;visualVersion++;controller.abort();collector.destroy();section.remove();}};
}
