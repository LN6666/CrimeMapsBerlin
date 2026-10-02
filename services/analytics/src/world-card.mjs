import { LANGUAGES, validCity } from './contract.mjs';
import { WORLD_PATHS } from './world-boundaries.mjs';

export const WORLD_COPY = Object.freeze({
  en: {heading:'Countries and regions',ranking:'Published page views',map:'World map of published page views',none:'No published group',less:'Fewer',more:'More',empty:'No country or region count is published yet.',notConnected:'Statistics are not connected yet.',unavailable:'Statistics are currently unavailable.',loading:'Loading statistics…',small:'Too few page views to publish a total.',total:'Counted page views',other:'Other / unknown',approximate:'Approximate connection origins, not nationality or residence.',limits:'Gray means no published group, not zero visits. Small regions may only be readable in the ranking.',privacy:'Opt-in page views · groups below 20 hidden or combined · rounded down to 10.',boundary:'Simplified boundaries: Natural Earth (public domain).',updated:'Updated',missing:'Without a visible map outline'},
  de: {heading:'Länder und Regionen',ranking:'Veröffentlichte Seitenaufrufe',map:'Weltkarte der veröffentlichten Seitenaufrufe',none:'Keine veröffentlichte Gruppe',less:'Weniger',more:'Mehr',empty:'Noch keine Aufrufzahl für ein Land oder eine Region veröffentlicht.',notConnected:'Die Statistik ist noch nicht angeschlossen.',unavailable:'Die Statistik ist derzeit nicht verfügbar.',loading:'Statistik wird geladen…',small:'Zu wenige Seitenaufrufe, um eine Summe zu veröffentlichen.',total:'Gezählte Seitenaufrufe',other:'Andere / unbekannt',approximate:'Ungefähre Herkunft der Verbindung, keine Aussage über Nationalität oder Wohnort.',limits:'Grau bedeutet keine veröffentlichte Gruppe, nicht null Besuche. Kleine Regionen sind eventuell nur in der Rangliste lesbar.',privacy:'Freiwillige Aufrufe · Gruppen unter 20 verborgen oder zusammengefasst · auf Zehner abgerundet.',boundary:'Vereinfachte Grenzen: Natural Earth (gemeinfrei).',updated:'Aktualisiert',missing:'Ohne sichtbaren Kartenumriss'},
  zh: {heading:'国家／地区',ranking:'已公布的页面浏览',map:'已公布页面浏览的世界分布',none:'未公布分组',less:'较少',more:'较多',empty:'暂未公布国家或地区的浏览次数。',notConnected:'访问统计尚未接入。',unavailable:'访问统计暂时不可用。',loading:'正在读取统计…',small:'浏览次数较少，暂不公布总数。',total:'已计入的页面浏览',other:'其他／未知',approximate:'仅表示连接的大致来源，不表示国籍或住所。',limits:'灰色表示未公布分组，不表示零访问。小地区可能只能在排行中看清。',privacy:'自愿计入的页面浏览 · 少于20次的分组合并或隐藏 · 按10次向下取整。',boundary:'简化边界：Natural Earth（公共领域）。',updated:'更新时间',missing:'未显示地图轮廓'},
});
export const NO_DATA_COLOR = '#e7ebef';
export const BLUE_SCALE = Object.freeze(['#dcecf9','#acd2ee','#70b3e1','#328fc9','#1167a7']);
const boundaryCodes = new Set(WORLD_PATHS.map(p => p.code).filter(Boolean));
export const escapeXml = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
export function countryName(code,lang) {
  if (code === 'OTHER') return WORLD_COPY[lang].other;
  return new Intl.DisplayNames([lang === 'zh' ? 'zh-CN' : lang],{type:'region',fallback:'code'}).of(code) ?? code;
}
export function isPublicStats(s,expectedCity) {
  if (!s || s.schema_version!==1 || s.status!=='live' || !validCity(s.city) || (expectedCity && s.city!==expectedCity)
    || s.metric!=='accepted_opt_in_pageviews' || s.unique_visitors_measured!==false
    || s.privacy?.minimum_sample!==20 || s.privacy?.rounding!==10
    || !Number.isFinite(Date.parse(s.generated_at)) || !Array.isArray(s.countries) || s.countries.length>9) return false;
  if (!(s.total_pv===null || Number.isSafeInteger(s.total_pv) && s.total_pv>=20 && s.total_pv%10===0)) return false;
  if (!s.countries.every(r=>r && /^(?:[A-Z]{2}|OTHER)$/.test(r.code) && Number.isSafeInteger(r.pv) && r.pv>=20 && r.pv%10===0)) return false;
  if (new Set(s.countries.map(r=>r.code)).size!==s.countries.length) return false;
  return s.total_pv===null ? s.countries.length===0 : s.countries.reduce((n,r)=>n+r.pv,0)<=s.total_pv;
}
function model(city,lang,stats,status) {
  if (!validCity(city) || !LANGUAGES.includes(lang)) throw new Error('invalid_world_card');
  const copy=WORLD_COPY[lang], number=new Intl.NumberFormat(lang);
  const rows=(stats?.countries ?? []).map(r=>({...r})).sort((a,b)=>b.pv-a.pv || a.code.localeCompare(b.code));
  const max=Math.max(1,...rows.map(r=>r.pv));
  const values=new Map(rows.map(r=>[r.code,r.pv]));
  const shade=pv=>BLUE_SCALE[Math.min(4,Math.max(0,Math.ceil(pv/max*5)-1))];
  const regions=rows.map(r=>({...r,name:countryName(r.code,lang),formatted:number.format(r.pv),color:r.code==='OTHER'?NO_DATA_COLOR:shade(r.pv),width:Math.round(r.pv/max*1000)/10,mapped:boundaryCodes.has(r.code)}));
  const paths=WORLD_PATHS.map(p=>{
    const pv=values.get(p.code) ?? null;
    return {...p,pv,color:pv===null?NO_DATA_COLOR:shade(pv),label:p.code?countryName(p.code,lang):copy.none};
  });
  const message=status==='not_connected'?copy.notConnected:status==='unavailable'?copy.unavailable:status==='loading'?copy.loading:stats?.total_pv===null?copy.small:`${copy.total}: ${number.format(stats.total_pv)}`;
  return {city,lang,status,copy,message,regions,paths,max,generatedAt:stats?.generated_at ?? null,unmapped:regions.filter(r=>r.code!=='OTHER'&&!r.mapped).map(r=>r.name),total:stats?.total_pv ?? null};
}
export function buildWorldCardModel(stats,lang='en',expectedCity) {
  if (!isPublicStats(stats,expectedCity)) throw new Error('invalid_world_data');
  return model(stats.city,lang,stats,'live');
}
export function buildPlaceholderModel(city,lang='en',status='not_connected') {
  if (!['not_connected','unavailable','loading'].includes(status)) throw new Error('invalid_placeholder');
  return model(city,lang,null,status);
}
export function renderWorldCardSvg(m,layout='wide') {
  if (!['wide','stacked'].includes(layout)) throw new Error('invalid_layout');
  const stacked=layout==='stacked', width=stacked?400:840;
  const rankX=stacked?22:470, rankY=stacked?280:83;
  const rowsHeight=Math.max(112,m.regions.length*28);
  const footer=stacked?rankY+rowsHeight+32:Math.max(300,rankY+rowsHeight+32);
  const height=footer+(stacked?144:105);
  const text=(x,y,value,extra='')=>`<text x="${x}" y="${y}" ${extra}>${escapeXml(value)}</text>`;
  const units=line=>Array.from(line).reduce((n,char)=>n+(char.codePointAt(0)>0x024f?2:1),0);
  const wrap=(line,limit)=>{
    const out=[];let chunk='';
    const parts=m.lang==='zh'?Array.from(line):line.split(/\s+/);
    for(const part of parts){
      const next=chunk+(chunk&&m.lang!=='zh'?' ':'')+part;
      if(chunk&&units(next)>limit){out.push(chunk);chunk=part;}else chunk=next;
    }
    if(chunk)out.push(chunk);return out;
  };
  const description=[m.message,m.copy.approximate,m.copy.limits,m.copy.privacy,...m.regions.map(r=>`${r.name}: ${r.formatted}`),m.generatedAt??''].join('. ');
  const mapWidth=stacked?356:424, mapX=stacked?22:22, mapY=stacked?80:80;
  const paths=m.paths.map(p=>`<path data-country="${p.code}" data-pv="${p.pv??''}" fill="${p.color}" d="${p.d}"><title>${escapeXml(p.label+': '+(p.pv===null?m.copy.none:new Intl.NumberFormat(m.lang).format(p.pv)))}</title></path>`).join('');
  const bars=m.regions.map((r,i)=>{
    const y=rankY+i*28, full=r.name, label=Array.from(full).length>25?Array.from(full).slice(0,24).join('')+'…':full;
    return `<g data-region="${r.code}" data-pv="${r.pv}"><title>${escapeXml(full+': '+r.formatted)}</title>`+text(rankX,y,label,'font-size="12"')+text(width-22,y,r.formatted,'text-anchor="end" font-size="13" font-weight="600"')+`<rect x="${rankX}" y="${y+7}" width="${Math.max(2,Math.round(r.width/100*(width-rankX-85)))}" height="5" rx="2.5" fill="${r.color}"/></g>`;
  }).join('') || wrap(m.copy.empty,Math.floor((width-rankX-35)/6.3)).map((line,i)=>text(rankX,rankY+i*16,line,'font-size="11"')).join('');
  const lines=stacked
    ? [m.copy.approximate,m.copy.limits,m.copy.privacy,m.copy.boundary]
    : [m.copy.approximate,m.copy.limits,m.copy.privacy+' '+m.copy.boundary];
  // Keep words intact in English/German and wrap Chinese by character.
  const wrapped=lines.flatMap(line=>wrap(line,stacked?62:148));
  const finalHeight=Math.max(height,footer+wrapped.length*16+39);
  const legendY=stacked?249:264;
  const legend=BLUE_SCALE.map((color,i)=>`<rect x="${mapX+235+i*15}" y="${legendY-8}" width="15" height="7" fill="${color}"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${finalHeight}" viewBox="0 0 ${width} ${finalHeight}" role="img" aria-labelledby="title description" lang="${m.lang}" data-city="${m.city}" data-status="${m.status}" data-layout="${layout}"><title id="title">${escapeXml(m.copy.heading+' · '+m.city)}</title><desc id="description">${escapeXml(description)}</desc><rect x=".5" y=".5" width="${width-1}" height="${finalHeight-1}" rx="10" fill="#fff" stroke="#e1e7ed"/><g font-family="system-ui, sans-serif" font-size="12" fill="#25394b">${text(22,28,m.copy.heading,'font-size="17" font-weight="600"')}${text(22,51,m.message,'font-size="13"')}<g transform="translate(${mapX} ${mapY}) scale(${mapWidth/36000})" stroke="#fff" stroke-width="35" stroke-linejoin="round" fill-rule="evenodd">${paths}</g><rect x="${mapX}" y="${legendY-9}" width="10" height="9" fill="${NO_DATA_COLOR}"/>${text(mapX+15,legendY,m.copy.none,'font-size="10"')}${legend}${text(mapX+235,legendY+14,m.copy.less,'font-size="9"')}${text(mapX+310,legendY+14,m.copy.more,'text-anchor="end" font-size="9"')}${bars}${wrapped.map((line,i)=>text(22,footer+i*16,line,'font-size="10" fill="#536779"')).join('')}${m.generatedAt?text(22,finalHeight-15,`${m.copy.updated}: ${m.generatedAt}`,'font-size="10" fill="#536779"'):''}</g></svg>`;
}
