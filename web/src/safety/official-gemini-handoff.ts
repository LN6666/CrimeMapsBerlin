import {BRIEF_COPY,BRIEF_PERIODS,type BriefWindow,type CachedBrief} from './cached-city-briefs';
import {MACRO_TAGS} from './macro-tags';
import {MACRO_COPY} from './macro-tag-copy';
import {CONTENT_TAG_CITIES} from './content-tags';

export const GEMINI_OFFICIAL_URL='https://gemini.google.com/app';
type Locale='zh'|'en'|'de';
export interface PublicGeminiSelection {
 key:string;as_of:string;unknown_publication_dates:number;window:BriefWindow;
 brief:{status:CachedBrief['status'];text:string};
}
export const GEMINI_HANDOFF_COPY={
 zh:{title:'在 Gemini 继续聊',intro:'复制统计，在 Gemini 用自己的账号继续问。',
  saved:'本站的统计和判断不需要登录。',
  account:'登录 Gemini 后，提问使用你自己账号的额度，按 Google 的使用限制执行。',
  privacy:'本站看不到你的账号或聊天。只有你粘贴并发送后，统计才会交给 Google。',
  copy:'复制统计',copyDone:'已复制',open:'打开 Gemini',newTab:'打开 Gemini（新标签页）',review:'看看复制的内容',details:'账号与数据',
  stays:'Gemini 会另开一页，这张地图会留在这里。',
  copied:'已复制，到 Gemini 粘贴就可以接着问。',failed:'请展开统计，手动复制。',
  unavailable:'当前统计暂时打不开，可以直接去 Gemini 提问。',
  fallback:'打不开 Gemini 时，本站的判断和报告仍可查看。',
  instruction:'请用中文，根据下列警方公告统计回答我的问题。未评估或不确定不代表没有相关事件。这些公告不是完整犯罪清单，也不能直接表示城市的实际犯罪风险。',
  selection:'所选范围',missing:'缺少发布日期，未计入这个时间段',labels:'标签：支持 / 已评估无支持 / 不确定 / 未评估；占全部公告比例',
  generated:'已保存的 AI 简评',pending:'标签还在审核。下面这段是进度说明，尚未生成 AI 判断。',preview:'这份简评所用的材料还没有全部审核完。'},
 en:{title:'Continue in Gemini',intro:'Copy these statistics and ask Gemini using your own account.',
  saved:'You can read this site’s statistics and briefs without signing in.',
  account:'When you sign in to Gemini, your questions use your own account’s allowance, subject to Google’s limits.',
  privacy:'This site cannot see your account or chats. Google receives the statistics only when you paste and send them.',
  copy:'Copy statistics',copyDone:'Copied',open:'Open Gemini',newTab:'Open Gemini (new tab)',review:'Preview the copy',details:'Account and data',
  stays:'Gemini opens in another tab. Your map stays here.',
  copied:'Copied. Paste into Gemini to ask your question.',failed:'Expand the statistics and copy them manually.',
  unavailable:'These statistics are unavailable. You can still open Gemini.',
  fallback:'If Gemini is unavailable, this site’s briefs and reports are still here.',
  instruction:'Please answer in English using the police announcement statistics below. Unassessed or uncertain does not mean no relevant event occurred. These announcements are not a complete crime count or a measure of actual city crime risk.',
  selection:'Selected scope',missing:'No publication date; excluded from this period',labels:'Labels: supported / assessed without support / uncertain / unassessed; share of all announcements',
  generated:'Saved AI brief',pending:'The labels are still being reviewed. The text below is a progress note, not an AI assessment.',preview:'Some of the material used for this brief is still under review.'},
 de:{title:'Bei Gemini weiterfragen',intro:'Kopiere die Statistik und frage Gemini mit deinem eigenen Konto.',
  saved:'Statistiken und Einschätzungen dieser Website kannst du ohne Anmeldung lesen.',
  account:'Nach der Anmeldung bei Gemini gelten die Nutzungsgrenzen deines eigenen Kontos.',
  privacy:'Diese Website kann dein Konto und deine Chats nicht sehen. Google erhält die Statistik erst, wenn du sie dort einfügst und absendest.',
  copy:'Statistik kopieren',copyDone:'Kopiert',open:'Gemini öffnen',newTab:'Gemini öffnen (neuer Tab)',review:'Kopierten Text ansehen',details:'Konto und Daten',
  stays:'Gemini öffnet sich in einem neuen Tab. Die Karte bleibt hier.',
  copied:'Kopiert. Füge den Text bei Gemini ein und stelle deine Frage.',failed:'Öffne die Statistik unten und kopiere sie manuell.',
  unavailable:'Diese Statistik ist gerade nicht verfügbar. Du kannst Gemini trotzdem öffnen.',
  fallback:'Falls Gemini nicht erreichbar ist, bleiben die Einschätzungen und Berichte dieser Website verfügbar.',
  instruction:'Bitte antworte auf Deutsch anhand der folgenden Polizeimeldungsstatistiken. Ungeprüft oder unklar bedeutet nicht, dass kein entsprechender Vorfall geschehen ist. Diese Meldungen sind keine vollständige Straftatenzahl und kein Maß für das tatsächliche Kriminalitätsrisiko einer Stadt.',
  selection:'Ausgewählter Bereich',missing:'Ohne Veröffentlichungsdatum; in diesem Zeitraum nicht enthalten',labels:'Merkmale: belegt / geprüft ohne Beleg / unklar / ungeprüft; Anteil an allen Meldungen',
  generated:'Gespeicherte KI-Einschätzung',pending:'Die Kategorien sind noch in Prüfung. Der folgende Text beschreibt den Arbeitsstand, nicht eine KI-Einschätzung.',preview:'Ein Teil des Materials für diese Einschätzung ist noch in Prüfung.'}
} as const;

/** Explicit public-field allowlist. Never accepts a visitor question, identity, URL or raw report. */
export function publicGeminiContext(locale:Locale,s:PublicGeminiSelection|null):string|null{
 if(!s)return null;
 if(!['all14',...CONTENT_TAG_CITIES].includes(s.key)||!BRIEF_PERIODS.includes(s.window.period))throw Error('Unknown public selection');
 const c=GEMINI_HANDOFF_COPY[locale],bc=BRIEF_COPY[locale],mc=MACRO_COPY[locale],w=s.window;
 const lines=[c.instruction,`${c.selection}: ${s.key}`,`${bc.period}: ${bc.periods[BRIEF_PERIODS.indexOf(w.period)]}`,
  `${w.start} — ${w.end} · ${bc.date}`,`As of: ${s.as_of}`,
  bc.counts.replace('{records}',String(w.records)).replace('{evaluated}',String(w.fully_evaluated_records)),
  `${c.missing}: ${s.unknown_publication_dates}`,c.labels];
 for(const tag of MACRO_TAGS){const t=w.tags.find(t=>t.tag===tag);if(!t)throw Error('Missing public label');
  const k=t.counts,share=w.records?new Intl.NumberFormat(locale,{style:'percent',maximumFractionDigits:2}).format(k.supported/w.records):'—';
  lines.push(`${mc.tags[tag]}: ${k.supported} / ${k.no_support} / ${k.uncertain} / ${k.not_evaluated}; ${share}`);
 }
 if(s.brief.status==='awaiting_labels')lines.push(c.pending);
 else {lines.push(c.generated);if(s.brief.status==='generated_preview')lines.push(c.preview);}
 lines.push(s.brief.text);
 const text=lines.join('\n');if(text.length>8000)throw Error('Public context is too large');return text;
}

/** No login, token, API request, tracking, storage or automatic transfer to Google. */
export function mountOfficialGeminiHandoff(parent:HTMLElement,locale:Locale,selection:()=>PublicGeminiSelection|null){
 const c=GEMINI_HANDOFF_COPY[locale],root=document.createElement('section'),heading=document.createElement('h3');
 root.className='content-tag-gemini-handoff';heading.textContent=c.title;
 const intro=document.createElement('p');intro.className='content-tag-gemini-intro';intro.textContent=c.intro;
 const actions=document.createElement('div');actions.className='content-tag-gemini-actions';
 const copy=document.createElement('button');copy.type='button';copy.className='content-tag-gemini-copy';copy.textContent=c.copy;
 const link=document.createElement('a');link.className='content-tag-gemini-open';link.href=GEMINI_OFFICIAL_URL;link.target='_blank';link.rel='noopener noreferrer';
 link.referrerPolicy='no-referrer';link.setAttribute('aria-label',c.newTab);
 const label=document.createElement('span'),arrow=document.createElement('span');label.textContent=c.open;arrow.textContent='↗';arrow.setAttribute('aria-hidden','true');link.append(label,arrow);actions.append(copy,link);
 const stays=document.createElement('p');stays.className='content-tag-gemini-stays';stays.textContent=c.stays;
 const status=document.createElement('p');status.className='content-tag-gemini-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.hidden=true;
 const tools=document.createElement('div');tools.className='content-tag-gemini-tools';
 const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('textarea');
 summary.textContent=c.review;text.readOnly=true;text.rows=8;text.setAttribute('aria-label',c.review);details.append(summary,text);
 const info=document.createElement('details'),infoTitle=document.createElement('summary');infoTitle.textContent=c.details;info.append(infoTitle);
 for(const value of [c.account,c.privacy,c.saved,c.fallback]){const p=document.createElement('p');p.textContent=value;info.append(p);}
 tools.append(details,info);root.append(heading,intro,actions,stays,status,tools);parent.append(root);
 let dead=false,lastContext:string|null|undefined=undefined;
 const refresh=()=>{if(dead)return;const context=publicGeminiContext(locale,selection());text.value=context??'';copy.disabled=!context;details.hidden=!context;
  if(context!==lastContext){copy.textContent=c.copy;copy.dataset.copied='false';status.textContent=context?'':c.unavailable;status.hidden=!!context;lastContext=context;}
 };
 const changed=()=>refresh();parent.addEventListener('change',changed);
 copy.addEventListener('click',async()=>{
  refresh();const context=text.value;if(!context)return;
  try{await navigator.clipboard.writeText(context);if(!dead&&text.value===context){copy.textContent=c.copyDone;copy.dataset.copied='true';status.textContent=c.copied;status.hidden=false;}}
  catch {if(!dead&&text.value===context){details.open=true;text.focus();text.select();status.textContent=c.failed;status.hidden=false;}}
 });
 refresh();
 return {element:root,refresh,destroy(){dead=true;parent.removeEventListener('change',changed);root.remove();}};
}
