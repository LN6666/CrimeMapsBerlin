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
 zh:{title:'继续提问',saved:'已保存的判断和统计无需登录，所有访客都能查看。',
  account:'实时提问在 Gemini 官网进行。请在那里使用自己的 Google 账号；可用功能和次数由 Gemini 决定。',
  privacy:'本站不接收你的 Google 账号资料、密码、授权或 Gemini 对话。只有你粘贴并发送后，下方公开统计才会交给 Google。',
  copy:'复制当前公开统计',open:'前往 Gemini 官网提问（新页面）',review:'查看将复制的公开统计',
  copied:'已复制。在 Gemini 中粘贴这些统计，再输入你的问题。',failed:'无法自动复制。请展开下方统计，手动选择并复制。',
  unavailable:'当前统计暂不可用。你仍可在 Gemini 官网自行提问。',
  fallback:'如果无法访问 Gemini，仍可继续阅读本站判断和已分析的报告。',
  instruction:'请用中文，仅依据下列公开公告统计帮助我分析。未评估或不确定不是没有相关事件，不要把这些材料说成完整犯罪数量或真实城市风险。',
  selection:'所选范围',missing:'缺少发布日期、未纳入本时间范围',labels:'标签：支持 / 已评估无支持 / 不确定 / 未评估；占全部公告比例',
  generated:'已保存的 AI 简评',pending:'简评仍等待标签审核；以下文字不是已完成的 AI 判断。',preview:'这是审核尚未完成的材料简评。'},
 en:{title:'Ask a follow-up question',saved:'Saved briefs and statistics are available to everyone without signing in.',
  account:'Live questions are asked on the Gemini website. Use your own Google account there; Gemini determines your available features and limits.',
  privacy:'This site receives none of your Google account details, passwords, authorisations or Gemini conversations. Google receives the public statistics below only when you paste and send them.',
  copy:'Copy current public statistics',open:'Ask on the Gemini website (new tab)',review:'Review the public statistics to be copied',
  copied:'Copied. Paste the statistics into Gemini, then enter your question.',failed:'Automatic copying is unavailable. Expand the statistics below to select and copy them manually.',
  unavailable:'Current statistics are unavailable. You can still ask your own question on the Gemini website.',
  fallback:'If you cannot access Gemini, you can still read this site’s briefs and saved reports.',
  instruction:'Please answer in English, using only the public announcement statistics below. Unassessed or uncertain does not mean no relevant event occurred. Do not describe these records as a complete crime count or a measure of actual city crime risk.',
  selection:'Selected scope',missing:'Records without publication dates, excluded from this period',labels:'Labels: supported / assessed without support / uncertain / unassessed; share of all announcements',
  generated:'Saved AI brief',pending:'The brief is awaiting label review; the following text is not a completed AI assessment.',preview:'This brief describes material whose review is still incomplete.'},
 de:{title:'Weitere Fragen stellen',saved:'Gespeicherte Einschätzungen und Statistiken sind für alle ohne Anmeldung verfügbar.',
  account:'Aktuelle Fragen stellst du auf der Gemini-Website mit deinem eigenen Google-Konto. Welche Funktionen und Kontingente verfügbar sind, bestimmt Gemini.',
  privacy:'Diese Website erhält keine Google-Kontodaten, Passwörter, Berechtigungen oder Gemini-Gespräche von dir. Die öffentlichen Zahlen unten erhält Google erst, wenn du sie dort einfügst und absendest.',
  copy:'Aktuelle öffentliche Statistik kopieren',open:'Auf der Gemini-Website fragen (neuer Tab)',review:'Öffentliche Statistik vor dem Kopieren ansehen',
  copied:'Kopiert. Füge die Statistik bei Gemini ein und stelle dort deine Frage.',failed:'Automatisches Kopieren ist nicht möglich. Öffne die Statistik unten und kopiere sie manuell.',
  unavailable:'Die aktuelle Statistik ist nicht verfügbar. Du kannst auf der Gemini-Website trotzdem eine eigene Frage stellen.',
  fallback:'Falls Gemini nicht erreichbar ist, bleiben die Einschätzungen und gespeicherten Berichte dieser Website verfügbar.',
  instruction:'Bitte antworte auf Deutsch und verwende nur die folgenden öffentlichen Meldungsstatistiken. Ungeprüft oder unklar bedeutet nicht, dass kein entsprechender Vorfall geschehen ist. Beschreibe diese Meldungen nicht als vollständige Straftatenzahl oder als Maß für das tatsächliche Kriminalitätsrisiko einer Stadt.',
  selection:'Ausgewählter Bereich',missing:'Einträge ohne Veröffentlichungsdatum, in diesem Zeitraum nicht enthalten',labels:'Merkmale: belegt / geprüft ohne Beleg / unklar / ungeprüft; Anteil an allen Meldungen',
  generated:'Gespeicherte KI-Einschätzung',pending:'Die Kategorien sind noch in Prüfung; der folgende Text ist keine abgeschlossene KI-Einschätzung.',preview:'Die Prüfung des Materials für diese Einschätzung ist noch unvollständig.'}
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
 root.className='content-tag-gemini-handoff';heading.textContent=c.title;root.append(heading);
 for(const text of [c.saved,c.account,c.privacy]){const p=document.createElement('p');p.textContent=text;root.append(p);}
 const copy=document.createElement('button');copy.type='button';copy.textContent=c.copy;
 const link=document.createElement('a');link.href=GEMINI_OFFICIAL_URL;link.target='_blank';link.rel='noopener noreferrer';
 link.referrerPolicy='no-referrer';link.textContent=c.open;
 const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
 const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('textarea');
 summary.textContent=c.review;text.readOnly=true;text.rows=8;text.setAttribute('aria-label',c.review);details.append(summary,text);
 const fallback=document.createElement('p');fallback.textContent=c.fallback;root.append(copy,link,status,details,fallback);parent.append(root);
 let dead=false;
 const refresh=()=>{if(dead)return;const context=publicGeminiContext(locale,selection());text.value=context??'';copy.disabled=!context;details.hidden=!context;status.textContent=context?'':c.unavailable;};
 const changed=()=>refresh();parent.addEventListener('change',changed);
 copy.addEventListener('click',async()=>{
  refresh();const context=text.value;if(!context)return;
  try{await navigator.clipboard.writeText(context);if(!dead)status.textContent=c.copied;}
  catch {if(!dead){details.open=true;text.focus();text.select();status.textContent=c.failed;}}
 });
 refresh();
 return {element:root,refresh,destroy(){dead=true;parent.removeEventListener('change',changed);root.remove();}};
}
