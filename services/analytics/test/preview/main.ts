import {mountAnalytics} from '../../../../web/src/safety/analytics';
import '../../../../web/src/safety/analytics.css';
const query=new URLSearchParams(location.search);
const lang=(query.get('lang')??'en') as 'en'|'de'|'zh';
const fixture=query.get('fixture');
const city=query.get('namespace')??'berlin';
const banner=document.querySelector('#fixture-label');if(banner)banner.textContent=({en:'LOCAL DEMO — synthetic counts, not real traffic; no live collection.',de:'LOKALE DEMO — Beispielzahlen, kein echter Verkehr; keine Live-Erfassung.',zh:'本地演示：数字为测试样例，不是真实流量；未接通统计服务。'} as const)[lang];
if(fixture) {
  const stats={schema_version:1,city,status:'live',metric:'accepted_opt_in_pageviews',total_pv:40 as number|null,countries:[{code:'DE',pv:20},{code:'OTHER',pv:20}],generated_at:'2026-10-03T00:00:00.000Z',unique_visitors_measured:false,privacy:{minimum_sample:20,rounding:10}};
  if(fixture==='demo'){stats.total_pv=4730;stats.countries=[{code:'JP',pv:2300},{code:'CN',pv:1200},{code:'US',pv:720},{code:'SG',pv:190},{code:'HK',pv:100},{code:'KR',pv:100},{code:'TW',pv:80},{code:'OTHER',pv:40}];}
  if(fixture==='low'){stats.total_pv=null;stats.countries=[];}
  const counter=document.createElement('p');counter.id='requests';document.body.append(counter);
  const event=document.createElement('p');event.id='last-event';document.body.append(event);
  let reads=0,writes=0,challenges=0,cancelled=0;
  const render=()=>{counter.textContent=`Local fixture requests: GET=${reads}; POST=${writes}; challenge=${challenges}; cancelled=${cancelled}`;};render();
  (window as unknown as {turnstile:unknown}).turnstile={render:(_el:HTMLElement,opts:{callback:(token:string)=>void;size:string})=>{if(opts.size!=='compact')throw new Error('Wrong challenge size');event.dataset.challengeSize=opts.size;event.textContent='Local challenge parameters: size=compact (150×140 minimum)';challenges++;render();setTimeout(()=>opts.callback('local-fixture-token'),40);return 'local-test-widget';},remove:()=>{}};
  window.fetch=async(input,init)=>{
    const url=String(input);
    if(!url.startsWith('https://analytics.invalid/'))throw new Error('Fixture prohibits external fetch');
    if(init?.method==='POST') {
      writes++;event.textContent=`Local fixture payload: ${init.body}; credentials=${init.credentials}; referrerPolicy=${init.referrerPolicy}`;render();return new Response('{"accepted":true}',{status:202,headers:{'Content-Type':'application/json'}});
    }
    reads++;render();
    if(fixture==='delay')await new Promise((resolve,reject)=>{const timer=setTimeout(resolve,1500);init?.signal?.addEventListener('abort',()=>{clearTimeout(timer);cancelled++;render();reject(new DOMException('Aborted','AbortError'));},{once:true});});
    if(fixture==='failure')return new Response('{"error":"unavailable"}',{status:503});
    const result=fixture==='malicious'?{...stats,countries:[{code:'<script>evil</script>',pv:20}]}:stats;
    return new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});
  };
  if(fixture==='privacy')Object.defineProperty(navigator,'globalPrivacyControl',{value:true});
}
const configured=query.get('configured')==='1'||(!!fixture&&fixture!=='unconnected');
const component=mountAnalytics(document.querySelector<HTMLElement>('#analytics')!,{city,language:lang,endpoint:configured?'https://analytics.invalid':undefined,siteKey:configured&&(query.get('consent')==='1'||!fixture)?'local-fixture-public-key':undefined});
let language=lang;
document.querySelector('#language')?.addEventListener('click',()=>{language=language==='en'?'de':language==='de'?'zh':'en';component.setLanguage(language);});
document.querySelector('#destroy')?.addEventListener('click',()=>component.destroy());
