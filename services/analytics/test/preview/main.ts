import {mountAnalytics} from '../../../../web/src/safety/analytics';
import '../../../../web/src/safety/analytics.css';
import './presentation.css';
import {statsFromExport} from '../../src/goatcounter-export.mjs';
const query=new URLSearchParams(location.search),langs=['en','de','zh'] as const;
document.documentElement.dataset.theme=query.get('theme')==='dark'?'dark':'light';

const lang=langs.find(v=>v===query.get('lang'))??'en',city=query.get('namespace')??'berlin',fixture=query.get('fixture')??'absent';
document.documentElement.lang=lang;
const banner=document.querySelector('#fixture-label');if(banner)banner.textContent=fixture==='demo'?({en:'LOCAL PREVIEW — synthetic country totals; no live collection.',de:'LOKALE VORSCHAU — synthetische Länderzahlen; keine echte Erfassung.',zh:'本地设计预览：国别数字均为测试样例，不采集真实访问。'} as const)[lang]:({en:'Local design preview · no city statistics published yet',de:'Lokale Designvorschau · noch keine Stadtstatistik veröffentlicht',zh:'本地设计预览 · 本城真实统计尚未公布'} as const)[lang];
const countries=[['JP',2303],['CN',1217],['US',727],['SG',196],['HK',108],['KR',104],['TW',84],['DE',19],['',41]] as const;
const rows=(fixture==='low'?[['JP',19]]:countries) as readonly (readonly [string,number])[];
const e={info:{export_version:'1.0',created_for:'ryoushunnei.goatcounter.com',created_at:'2026-10-03T12:00:00Z'},paths:[{id:1,path:`/cities/${fixture==='wrongcity'?'essen':city}`}],locations:rows.map(([country])=>({country,region:''})),locationStats:rows.map(([location,count])=>({day:'2026-10-02',path_id:1,location,count})),hitStats:[{hour:'2026-10-02T12:00:00Z',path_id:1,ref_id:0,count:rows.reduce((n,r)=>n+r[1],0)}]};
const data=['demo','low','wrongcity','slow'].includes(fixture)?statsFromExport(e,fixture==='wrongcity'?'essen':city):null;
let reads=0,external=0;const counter=document.createElement('p');counter.id='requests';counter.hidden=query.get('debug')!=='1';document.body.append(counter);
const render=()=>{counter.textContent=`Local preview: snapshot reads=${reads}; external requests=${external}`;};render();
window.fetch=async(input,options)=>{
 const url=new URL(String(input),location.href);
 if(url.origin!==location.origin||!url.pathname.endsWith('/safety/analytics/visitors-by-country.json')){external++;render();throw new Error('External requests forbidden in preview');}
 reads++;render();
 if(fixture==='slow')await new Promise<void>((resolve,reject)=>{const timer=setTimeout(resolve,600);options?.signal?.addEventListener('abort',()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));},{once:true});});
 if(fixture==='unavailable')return new Response('{}',{status:503});
 if(!data)return new Response('{}',{status:404});
 return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
};
const component=mountAnalytics(document.querySelector<HTMLElement>('#analytics')!,{city,language:lang,snapshotUrl:new URL('/safety/analytics/visitors-by-country.json',location.href).href,collectionEnabled:query.get('collect')==='1'});
let language=lang;const languageSelect=document.querySelector<HTMLSelectElement>('#language')!;languageSelect.value=lang;languageSelect.addEventListener('change',()=>{language=languageSelect.value as typeof lang;component.setLanguage(language);document.documentElement.lang=language;});
const citySelect=document.querySelector<HTMLSelectElement>('#city')!;citySelect.value=city;citySelect.addEventListener('change',()=>{query.set('namespace',citySelect.value);location.search=query.toString();});
const theme=document.querySelector<HTMLSelectElement>('#theme')!;theme.value=query.get('theme')==='dark'?'dark':'light';theme.addEventListener('change',()=>{document.documentElement.dataset.theme=theme.value;});
document.querySelector('#destroy')?.addEventListener('click',()=>component.destroy());
if(query.get('narrow')==='1')document.querySelector<HTMLElement>('.preview-content')!.style.maxWidth='304px';
