import type { WorldLanguage, WorldStats, WorldStatus } from '../../../services/analytics/src/world-card.mjs';
export async function renderAnalyticsWorldCard(host:HTMLElement, options:{city:string;language:WorldLanguage;stats?:WorldStats;status?:Exclude<WorldStatus,'live'>;isCurrent:()=>boolean}) {
  const {buildWorldCardModel,buildPlaceholderModel,BLUE_SCALE,NO_DATA_COLOR}=await import('../../../services/analytics/src/world-card.mjs');
  if (!options.isCurrent()) return;
  const model=options.stats?buildWorldCardModel(options.stats,options.language,options.city):buildPlaceholderModel(options.city,options.language,options.status);
  const el=<T extends keyof HTMLElementTagNameMap>(tag:T,cls='')=>{const e=document.createElement(tag);e.className=cls;return e;};
  const svgEl=<T extends keyof SVGElementTagNameMap>(tag:T,attrs:Record<string,string>={})=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))e.setAttribute(key,value);return e;};
  const card=el('div','analytics-world-card');card.dataset.city=model.city;card.dataset.status=model.status;
  const figure=el('figure','analytics-world-map'),svg=svgEl('svg',{viewBox:'0 0 36000 15500',role:'img','aria-label':model.copy.map});
  const group=svgEl('g',{'stroke':'#fff','stroke-width':'35','stroke-linejoin':'round','fill-rule':'evenodd'});
  for (const row of model.paths) {
    const path=svgEl('path',{d:row.d,fill:row.color,'data-country':row.code,'data-pv':row.pv===null?'':String(row.pv)});
    const title=svgEl('title');title.textContent=`${row.label}: ${row.pv===null?model.copy.none:new Intl.NumberFormat(model.lang).format(row.pv)}`;path.append(title);group.append(path);
  }
  svg.append(group);
  const legend=el('figcaption','analytics-world-legend'),missing=el('span');
  const gray=el('i');gray.style.background=NO_DATA_COLOR;gray.setAttribute('aria-hidden','true');missing.append(gray,document.createTextNode(model.copy.none));
  const scale=el('span','analytics-world-scale'),less=el('span'),more=el('span');less.textContent=model.copy.less;more.textContent=model.copy.more;
  scale.append(less);for(const color of BLUE_SCALE){const swatch=el('i');swatch.style.background=color;swatch.setAttribute('aria-hidden','true');scale.append(swatch);}scale.append(more);legend.append(missing,scale);figure.append(svg,legend);
  const rank=el('div','analytics-world-ranking'),heading=el('h3');heading.textContent=model.copy.ranking;rank.append(heading);
  const list=el('ol');list.setAttribute('aria-label',model.copy.heading);
  for(const row of model.regions){
    const li=el('li'),line=el('div','analytics-world-row'),position=el('span','analytics-world-position'),name=el('span'),value=el('strong'),track=el('span','analytics-world-track'),bar=el('span','analytics-world-bar');
    position.textContent=String(list.children.length+1).padStart(2,'0');position.setAttribute('aria-hidden','true');
    li.dataset.region=row.code;li.dataset.pv=String(row.pv);name.textContent=row.name;value.textContent=row.formatted;line.append(position,name,value);
    bar.style.width=`${row.width}%`;bar.style.background=row.color;bar.setAttribute('aria-hidden','true');track.append(bar);li.append(line,track);list.append(li);
  }
  if(model.regions.length)rank.append(list);else{const empty=el('p','analytics-world-empty');empty.textContent=model.status==='live'?model.copy.empty:model.message;rank.append(empty);}
  if(model.unmapped.length){const note=el('p');note.textContent=`${model.copy.missing}: ${model.unmapped.join(', ')}`;rank.append(note);}
  const note=el('p','analytics-world-context');note.textContent=model.copy.approximate;
  const explanation=el('p','analytics-world-explanation');explanation.textContent=model.copy.limits+' '+model.copy.privacy;
  const notes=el('details','analytics-world-footnotes'),caption=el('summary');caption.textContent=({en:'How to read the map',de:'Die Karte verstehen',zh:'如何阅读地图'})[model.lang];
  const source=el('p','analytics-world-explanation');source.textContent=model.copy.boundary;notes.append(caption,explanation,source);
  card.append(figure,rank,note,notes);if(options.isCurrent())host.replaceChildren(card);
}
