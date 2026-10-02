import { LANGUAGES, validCity } from './contract.mjs';
const COPY={
  en:{title:'Map pageviews by country',pv:'Accepted pageviews',small:'Too few pageviews to publish a total.',other:'Other / unknown',since:'Counting since',updated:'Generated',note1:'Opt-in pageviews; unique visitors are not measured.',note2:'Groups below 20 are hidden or combined; values rounded down to 10.',note3:'Verification and rate limits reduce abuse; counts can still be manipulated.'},
  de:{title:'Kartenaufrufe nach Land',pv:'Gezählte Seitenaufrufe',small:'Zu wenige Aufrufe, um eine Gesamtzahl anzuzeigen.',other:'Andere / unbekannt',since:'Zählung seit',updated:'Erstellt',note1:'Freiwillig erfasste Aufrufe; einzelne Besucher werden nicht gezählt.',note2:'Gruppen unter 20 verborgen oder zusammengefasst; auf Zehner abgerundet.',note3:'Prüfung und Limits begrenzen Missbrauch; Zahlen bleiben manipulierbar.'},
  zh:{title:'地图页面访问国家分布',pv:'已接收的页面浏览',small:'访问量较少，暂不公布总数。',other:'其他／未知',since:'统计起始日期',updated:'生成时间',note1:'仅统计主动启用的页面浏览；不统计独立访客。',note2:'少于20次的分组合并或隐藏；数字按十次向下取整。',note3:'验证和限流减少滥用，但不能保证数字无法被人为增加。'},
};
export const escapeXml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
export function countryName(code,lang) {
  if(code==='OTHER') return COPY[lang].other;
  return new Intl.DisplayNames([lang==='zh'?'zh-CN':lang],{type:'region'}).of(code)??code;
}
export function validateStats(stats) {
  return stats && stats.schema_version===1 && stats.status==='live' && validCity(stats.city)
    && stats.metric==='accepted_opt_in_pageviews' && stats.unique_visitors_measured===false
    && (stats.total_pv===null || (Number.isSafeInteger(stats.total_pv) && stats.total_pv>=20 && stats.total_pv%10===0))
    && Array.isArray(stats.countries) && stats.countries.length<=9
    && stats.countries.every(r=>/^(?:[A-Z]{2}|OTHER)$/.test(r.code) && Number.isSafeInteger(r.pv) && r.pv>=20 && r.pv%10===0)
    && new Set(stats.countries.map(r=>r.code)).size===stats.countries.length
    && Number.isFinite(Date.parse(stats.generated_at))
    && (stats.collection_start_date===null || /^\d{4}-\d{2}-\d{2}$/.test(stats.collection_start_date))
    && stats.privacy?.minimum_sample===20 && stats.privacy?.rounding===10;
}
export function renderChart(stats,lang='en') {
  if(!LANGUAGES.includes(lang) || !validateStats(stats)) throw new Error('invalid_chart_data');
  const c=COPY[lang], f=new Intl.NumberFormat(lang);
  const rows=stats.countries;
  const total=stats.total_pv===null?c.small:`${c.pv}: ${f.format(stats.total_pv)}`;
  const footer=110+rows.length*32;
  const height=footer+112;
  const description=[total,...rows.map(r=>`${countryName(r.code,lang)}: ${f.format(r.pv)}`),c.note1,c.note2,c.note3,`${c.updated}: ${stats.generated_at}`].join('. ');
  const max=Math.max(1,...rows.map(r=>r.pv));
  const text=(x,y,value,extra='')=>`<text x="${x}" y="${y}" ${extra}>${escapeXml(value)}</text>`;
  const bars=rows.map((r,i)=>{
    const y=94+i*32;
    const full=countryName(r.code,lang), label=Array.from(full).length>27?Array.from(full).slice(0,26).join('')+'…':full;
    return `<g><title>${escapeXml(full)}</title>`+text(18,y+16,label)+`<rect x="220" y="${y}" width="${Math.max(2,Math.round(r.pv/max*300))}" height="22" rx="3" fill="#526a92"/>`+text(580,y+16,f.format(r.pv),'text-anchor="end"')+'</g>';
  }).join('');
  // Only trusted enums, integers, escaped text and fixed presentation attributes.
  return `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="${height}" viewBox="0 0 600 ${height}" role="img" aria-labelledby="title description" lang="${lang}"><title id="title">${escapeXml(c.title+' · '+stats.city)}</title><desc id="description">${escapeXml(description)}</desc><rect width="600" height="${height}" rx="8" fill="#f6f8fa"/><g font-family="system-ui, sans-serif" font-size="13" fill="#24292f">${text(18,30,c.title,'font-size="19" font-weight="600"')}${text(18,57,total)}${text(18,77,`${stats.city}${stats.collection_start_date?' · '+c.since+': '+stats.collection_start_date:''}`,'font-size="12"')}${bars}${text(18,footer,c.note1,'font-size="11"')}${text(18,footer+20,c.note2,'font-size="11"')}${text(18,footer+40,c.note3,'font-size="11"')}${text(18,footer+66,`${c.updated}: ${stats.generated_at}`,'font-size="11"')}</g></svg>`;
}
