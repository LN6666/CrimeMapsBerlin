import {MACRO_TAGS,HATE_FACETS,macroStatisticsForSummary,type MacroSummary,type MacroTag} from "./macro-tags";
import type {MacroCopy} from "./macro-tag-copy";

export function mountMacroTagPanel(parent:HTMLElement,options:{locale:"en"|"de"|"zh";copy:MacroCopy}){
 const root=document.createElement("section"),c=options.copy;
 root.className="content-tag-panel macro-tag-panel";parent.append(root);
 const number=new Intl.NumberFormat(options.locale,{maximumFractionDigits:2});
 const percent=new Intl.NumberFormat(options.locale,{style:"percent",maximumSignificantDigits:3});
 const line=(text:string,target:HTMLElement=root)=>{const p=document.createElement("p");p.textContent=text;target.append(p);};
 const invalidate=()=>{root.replaceChildren();line(c.unavailable);};invalidate();
 const render=(source:MacroSummary)=>{
  const stats=macroStatisticsForSummary(source);root.replaceChildren();
  const title=document.createElement("h3");title.textContent=c.title;root.append(title);
  const table=(tags:readonly MacroTag[],captionText:string,parent:HTMLElement)=>{
   const scroll=document.createElement("div");scroll.style.overflowX="auto";scroll.tabIndex=0;
   scroll.setAttribute("role","region");scroll.setAttribute("aria-label",captionText);
   const table=document.createElement("table"),caption=document.createElement("caption"),head=document.createElement("thead"),header=document.createElement("tr"),body=document.createElement("tbody");
   caption.textContent=captionText;table.append(caption,head,body);head.append(header);
   for(const text of [c.label,c.count,c.share,c.police,c.lead,c.coverage,c.uncertain,c.pending,c.index]){
    const th=document.createElement("th");th.scope="col";th.textContent=text;header.append(th);}
   for(const tag of tags){const item=stats.tags.find(item=>item.tag===tag)!;
    const row=document.createElement("tr"),label=document.createElement("th");label.scope="row";label.textContent=c.tags[tag];row.append(label);
    const values=[String(item.counts.supported),item.share===null?c.unknown:percent.format(item.share),String(item.police_category_stated),String(item.narrative_lead),
     item.evaluated===null?c.unknown:percent.format(item.evaluated),String(item.counts.uncertain),String(item.counts.not_evaluated),item.content_index===null?c.unknown:number.format(item.content_index)];
    for(const text of values){const cell=document.createElement("td");cell.textContent=text;row.append(cell);}body.append(row);}
   scroll.append(table);parent.append(scroll);
  };
  table(MACRO_TAGS,c.caption,root);
  const facets=document.createElement("details"),facetTitle=document.createElement("summary");facetTitle.textContent=c.facetTitle;facets.append(facetTitle);table(HATE_FACETS,c.facetTitle,facets);root.append(facets);
  const methods=document.createElement("details"),methodTitle=document.createElement("summary");methodTitle.textContent=c.methods;methods.append(methodTitle);
  for(const text of [c.basis,c.formula,c.incomplete,c.overlap])line(text,methods);root.append(methods);
 };
 return{updateSummary(source:MacroSummary){try{render(source);}catch{invalidate();}},invalidate,destroy(){root.remove();}};
}
