import {CONTENT_TAGS, CONTENT_TAG_CITIES, contentTagStatistics, contentTagStatisticsForSummary, type ContentTagSummary, type ContentRecord, type ContentAssessment, type ContentTag} from "./content-tags";
import {mountContentTagPanel} from "./content-tag-panel";
import type {ContentTagCopy} from "./content-tag-copy";
import {macroStatisticsForSummary,validateMacroCatalogue,type MacroSummary} from "./macro-tags";
import {MACRO_COPY} from "./macro-tag-copy";
import {mountMacroTagPanel} from "./macro-tag-panel";
import {mountCachedBriefs,type WindowCatalogue,type BriefCatalogue} from "./cached-city-briefs";

/** Local UI only. The caller supplies data and the existing police-eagle asset. */
export function mountContentTagLauncher(parent: HTMLElement, options: {
  locale: "en" | "de" | "zh"; copy: ContentTagCopy; eagleUrl: string;
  boundsElement?: HTMLElement; id: string;
  staticReportUrls?:Readonly<Record<string,string>>;
}) {
  const c=options.copy, root=document.createElement("div"), anchor=document.createElement("div");
  root.className="content-tag-widget"; anchor.className="content-tag-anchor";
  const trigger=document.createElement("button"), image=document.createElement("img"), label=document.createElement("span");
  trigger.type="button"; trigger.className="content-tag-eagle"; trigger.setAttribute("aria-label",c.open);
  trigger.setAttribute("aria-expanded","false"); trigger.setAttribute("aria-controls",`${options.id}-drawer`);
  const bubble=document.createElement("span"); bubble.className="content-tag-bubble"; bubble.id=`${options.id}-bubble`;
  bubble.setAttribute("role","tooltip"); bubble.textContent=c.askMe;
  const help=document.createElement("span");help.id=`${options.id}-help`;help.className="content-tag-help";help.textContent=c.dragHint;
  trigger.setAttribute("aria-describedby",`${bubble.id} ${help.id}`);
  image.src=options.eagleUrl; image.alt=""; image.draggable=false;
  label.textContent=c.launcher; label.className="content-tag-launcher-label";
  trigger.append(image,label); anchor.append(bubble,trigger,help);
  const drawer=document.createElement("section"), header=document.createElement("header"), title=document.createElement("h2"), close=document.createElement("button");
  drawer.className="content-tag-drawer"; drawer.id=`${options.id}-drawer`; drawer.hidden=true; drawer.tabIndex=-1;
  drawer.setAttribute("role","dialog"); drawer.setAttribute("aria-labelledby",`${options.id}-title`);
  title.id=`${options.id}-title`; title.textContent=c.launcher; close.type="button"; close.className="content-tag-close"; close.setAttribute("aria-label",c.close); close.textContent="×";
  header.append(title,close);
  const preview=document.createElement("p"), highlights=document.createElement("div"), content=document.createElement("div");
  const scopeLabel=document.createElement("label"), scopeSelect=document.createElement("select");
  scopeLabel.className="content-tag-scope";scopeLabel.hidden=true;scopeLabel.textContent=c.scopeChoice;
  scopeSelect.setAttribute("aria-label",c.scopeChoice);scopeLabel.append(scopeSelect);
  preview.className="content-tag-preview"; highlights.className="content-tag-highlights"; content.className="content-tag-body";
  const availability=document.createElement("p"); availability.className="content-tag-availability";
  availability.setAttribute("role","status"); availability.textContent=c.savedStatistics;
  const reportLink=document.createElement("a");reportLink.className="content-tag-report-link";reportLink.textContent=c.staticReport;reportLink.hidden=true;
  reportLink.target="_blank";reportLink.rel="noopener";
  for(const url of Object.values(options.staticReportUrls??{}))
    if(!url.startsWith("/")||url.startsWith("//")||/[\u0000-\u0020\\]/.test(url))throw Error("Static reports must use same-origin paths");
  const allMonths=document.createElement('p');allMonths.className='content-tag-all-months';allMonths.textContent=c.timeScope;
  drawer.append(header,scopeLabel,availability,reportLink,allMonths,preview,highlights,content); root.append(anchor,drawer); parent.append(root);
  const briefHost=document.createElement('div');drawer.insertBefore(briefHost,availability);
  const briefPanel=mountCachedBriefs(briefHost,options.locale);
  const macroCopy=MACRO_COPY[options.locale],macroContent=document.createElement("div");
  const behaviorDetails=document.createElement("details"),behaviorTitle=document.createElement("summary");
  behaviorDetails.className="content-tag-behavior-details";behaviorTitle.textContent=c.title;
  behaviorDetails.append(behaviorTitle);content.append(macroContent,behaviorDetails);
  const macroPanel=mountMacroTagPanel(macroContent,{locale:options.locale,copy:macroCopy});
  const panel=mountContentTagPanel(behaviorDetails,{locale:options.locale,copy:c,expanded:true});
  const number=new Intl.NumberFormat(options.locale), percent=new Intl.NumberFormat(options.locale,{style:"percent",maximumSignificantDigits:3});
  const showPreview=(stats:ReturnType<typeof contentTagStatistics>,full:number)=>{
    highlights.replaceChildren();
    preview.textContent=c.preview.replace("{count}",number.format(stats.records)).replace("{evaluated}",number.format(full));
    const hint=document.createElement("p");hint.textContent=c.previewPending;highlights.append(hint);
  };
  let catalogue:readonly ContentTagSummary[]=[];
  let macroCatalogue:readonly MacroSummary[]=[];
  let catalogueLabels:Readonly<Record<string,string>>={};
  const selectScope=()=>{
    const source=catalogue.find(item=>item.key===scopeSelect.value);
    briefPanel.setScope(scopeSelect.value);
    const reportUrl=source&&options.staticReportUrls?.[source.key];
    reportLink.hidden=!reportUrl;if(reportUrl)reportLink.href=reportUrl;
    highlights.replaceChildren();
    if(!source){preview.textContent=c.unavailable;return;}
    panel.updateSummary(source,{scopeLabel:catalogueLabels[source.key]});
    showPreview(contentTagStatisticsForSummary(source),0);
    const macroSource=macroCatalogue.find(item=>item.key===source.key);
    if(!macroSource){macroPanel.invalidate();return;}
    macroPanel.updateSummary(macroSource);
    preview.textContent=c.preview.replace("{count}",number.format(macroSource.records)).replace("{evaluated}",number.format(macroSource.fully_evaluated_records));
    highlights.replaceChildren();
    const leading=macroStatisticsForSummary(macroSource).tags.filter(item=>!['anti_lgbt','racism','xenophobia','religious_bias'].includes(item.tag)&&item.counts.supported>0)
      .sort((a,b)=>b.counts.supported-a.counts.supported).slice(0,3);
    for(const item of leading){const chip=document.createElement("p");chip.textContent=`${macroCopy.tags[item.tag]} · ${percent.format(item.share!)}`;highlights.append(chip);}
    if(!leading.length){const hint=document.createElement("p");hint.textContent=c.previewPending;highlights.append(hint);}
  };
  scopeSelect.addEventListener("change",selectScope);
  const position={x:0,y:0};
  const bounds=()=>{
    const rect=options.boundsElement?.getBoundingClientRect();
    return {left:Math.max(8,rect?.left??8),top:Math.max(8,rect?.top??8),
      right:Math.min(window.innerWidth-8,rect?.right??window.innerWidth-8),
      bottom:Math.min(window.innerHeight-8,rect?.bottom??window.innerHeight-8)};
  };
  const move=(x:number,y:number)=>{
    const b=bounds(), rect=anchor.getBoundingClientRect();
    position.x=Math.max(b.left,Math.min(x,Math.max(b.left,b.right-rect.width)));
    position.y=Math.max(b.top,Math.min(y,Math.max(b.top,b.bottom-rect.height)));
    anchor.dataset.tooltipBelow=String(position.y<48);
    anchor.style.left=`${position.x}px`; anchor.style.top=`${position.y}px`;
  };
  const initial=bounds(); move(initial.right-100,initial.bottom-120);
  const setOpen=(open:boolean)=>{
    drawer.hidden=!open; trigger.setAttribute("aria-expanded",String(open));
    if(open) close.focus(); else trigger.focus({preventScroll:true});
  };
  close.addEventListener("click",()=>setOpen(false));
  let drag: {pointer:number;startX:number;startY:number;x:number;y:number;moved:boolean}|null=null;
  let suppressClick=false;
  const clicked=(event:MouseEvent)=>{
    if(suppressClick && event.detail!==0) {suppressClick=false;return;}
    suppressClick=false; setOpen(drawer.hidden);
  };
  trigger.addEventListener("click",clicked);
  trigger.addEventListener("pointerdown",event=>{
    if(event.button!==0 || !event.isPrimary) return;
    suppressClick=false;
    drag={pointer:event.pointerId,startX:event.clientX,startY:event.clientY,x:position.x,y:position.y,moved:false};
    trigger.setPointerCapture(event.pointerId);
  });
  trigger.addEventListener("pointermove",event=>{
    if(!drag || event.pointerId!==drag.pointer) return;
    const dx=event.clientX-drag.startX,dy=event.clientY-drag.startY;
    if(Math.hypot(dx,dy)>6) drag.moved=true;
    if(drag.moved) {event.preventDefault();move(drag.x+dx,drag.y+dy);}
  });
  const endDrag=(event:PointerEvent)=>{
    if(!drag || event.pointerId!==drag.pointer) return;
    suppressClick=drag.moved; drag=null;
    if(trigger.hasPointerCapture(event.pointerId)) trigger.releasePointerCapture(event.pointerId);
  };
  trigger.addEventListener("pointerup",endDrag);
  trigger.addEventListener("pointercancel",endDrag);
  trigger.addEventListener("lostpointercapture",()=>{drag=null;});
  trigger.addEventListener("keydown",event=>{
    const shifts: Record<string,[number,number]>={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    const shift=shifts[event.key];
    if(shift){event.preventDefault();const step=event.shiftKey?30:10;move(position.x+shift[0]*step,position.y+shift[1]*step);}
  });
  const escape=(event:KeyboardEvent)=>{if(event.key==="Escape" && !drawer.hidden){event.preventDefault();setOpen(false);}};
  const resize=()=>move(position.x,position.y);
  window.addEventListener("keydown",escape); window.addEventListener("resize",resize);
  // Keep interactions inside the widget from selecting a map feature underneath it.
  for(const eventName of ["click","dblclick","pointerdown","wheel"])
    root.addEventListener(eventName,event=>event.stopPropagation());
  return {
    element:root, trigger,
    update(records:readonly ContentRecord[],assessments:readonly ContentAssessment[],context:{
      scopeLabel:string;textScope:"full_official_text"|"accepted_upstream_summary";
      weights?:Readonly<Partial<Record<ContentTag,number>>>;
    }) {
      scopeLabel.hidden=true; catalogue=[];macroCatalogue=[];macroPanel.invalidate();briefPanel.invalidate();reportLink.hidden=true;
      panel.update(records,assessments,context); highlights.replaceChildren();
      try {
        const stats=contentTagStatistics(records,assessments,context.weights);
        showPreview(stats,0);
      } catch {preview.textContent=c.unavailable;}
    },
    /** Small precomputed artifact: 14 city scopes plus their validated sum, supplied by the existing loader. */
    setSummaries(sources:readonly ContentTagSummary[],labels:Readonly<Record<string,string>>,selectedCity:string){
      catalogue=[];macroCatalogue=[];macroPanel.invalidate();briefPanel.invalidate();reportLink.hidden=true;scopeLabel.hidden=true;highlights.replaceChildren();preview.textContent=c.unavailable;panel.invalidate();
      const cities=sources.filter(item=>item.key!=="all14"), aggregate=sources.find(item=>item.key==="all14");
      if(cities.length!==14 || sources.length!==15 || new Set(sources.map(item=>item.key)).size!==15 || !aggregate ||
          cities.some(item=>!CONTENT_TAG_CITIES.includes(item.key as typeof CONTENT_TAG_CITIES[number])))
        throw Error("Expected fourteen cities and their total");
      for(const source of sources){
        contentTagStatisticsForSummary(source);
        if(!labels[source.key]?.trim() || source.mapping_sha256!==aggregate.mapping_sha256 || source.overlay_sha256!==aggregate.overlay_sha256)
          throw Error("Summary labels or source bindings do not match");
      }
      if(cities.reduce((sum,item)=>sum+item.records,0)!==aggregate.records ||
          cities.reduce((sum,item)=>sum+item.fully_evaluated_records,0)!==aggregate.fully_evaluated_records)
        throw Error("City totals do not match aggregate");
      for(const tag of CONTENT_TAGS) for(const verdict of ["supported","no_support","uncertain","not_evaluated"] as const)
        if(cities.reduce((sum,item)=>sum+item.tags.find(row=>row.tag===tag)!.counts[verdict],0)!==aggregate.tags.find(row=>row.tag===tag)!.counts[verdict])
          throw Error("Aggregate must sum counts, not average percentages");
      if(!sources.some(item=>item.key===selectedCity)) throw Error("Unknown selected scope");
      catalogue=sources;catalogueLabels=labels;scopeSelect.replaceChildren();
      for(const source of [aggregate,...cities]){const option=document.createElement("option");option.value=source.key;option.textContent=labels[source.key];scopeSelect.append(option);}
      scopeSelect.value=selectedCity;scopeLabel.hidden=false;selectScope();
    },
    /** Primary social-context layer. Call after setSummaries; both layers use identical selected records. */
    setMacroSummaries(sources:readonly MacroSummary[]){
      macroCatalogue=[];macroPanel.invalidate();briefPanel.invalidate();highlights.replaceChildren();preview.textContent=c.unavailable;reportLink.hidden=true;
      validateMacroCatalogue(sources);
      for(const source of sources){const behavior=catalogue.find(item=>item.key===source.key);
        if(!behavior||behavior.records!==source.records||behavior.mapping_sha256!==source.mapping_sha256)
          throw Error("Macro layer must use the same city records and mapping");}
      macroCatalogue=sources;selectScope();
    },
    /** Four saved briefs per city/total. Neither hovering nor selecting a period invokes a model. */
    setCachedBriefs(windows:WindowCatalogue,briefs:BriefCatalogue){
      briefPanel.invalidate();
      for(const scope of windows.scopes){const source=macroCatalogue.find(s=>s.key===scope.key);
        if(!source||source.records!==scope.total_selected_records||source.mapping_sha256!==windows.mapping_sha256||
          source.overlay_sha256!==windows.overlay_sha256)throw Error('Briefs require the current macro catalogue');}
      briefPanel.setCatalogues(windows,briefs);briefPanel.setScope(scopeSelect.value);
    },
    open:()=>setOpen(true), close:()=>setOpen(false),
    /** Invoke when Q&A is disabled, region-restricted, exhausted or fails. Saved data is preserved. */
    showStatisticsFallback(){availability.textContent=c.answerUnavailable;setOpen(true);},
    destroy(){window.removeEventListener("keydown",escape);window.removeEventListener("resize",resize);briefPanel.destroy();macroPanel.destroy();panel.destroy();root.remove();},
  };
}
