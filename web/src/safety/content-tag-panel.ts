import {contentTagStatistics, contentTagStatisticsForSummary, type ContentTagSummary, type ContentRecord, type ContentAssessment, type ContentTag} from "./content-tags";
import type {ContentTagCopy} from "./content-tag-copy";

/** The caller supplies the selected records before geometry filtering, and matching source-bound labels. */
export function mountContentTagPanel(parent: HTMLElement, options: {
  locale: "en" | "de" | "zh"; copy: ContentTagCopy; expanded?: boolean;
}) {
  const root = document.createElement("details"), summary = document.createElement("summary"), body = document.createElement("div");
  root.className = "content-tag-panel";
  if (options.expanded) {root.open=true; summary.hidden=true;}
  root.append(summary, body); parent.append(root);
  const c = options.copy;
  const number = new Intl.NumberFormat(options.locale, {maximumFractionDigits: 1});
  const percent = new Intl.NumberFormat(options.locale, {style: "percent", maximumSignificantDigits: 3});
  const interpolate = (template: string, params: Record<string, string | number>) =>
    template.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match));
  const line = (text: string, container: HTMLElement = body) => {
    const p = document.createElement("p"); p.textContent = text; container.append(p);
  };
  type Context={scopeLabel:string;textScope:"full_official_text"|"accepted_upstream_summary"|"mixed";
    weights?:Readonly<Partial<Record<ContentTag,number>>>;allSelectedMonths?:boolean};
  const reset=()=>{body.replaceChildren();summary.textContent=c.title;};
  const render=(stats:ReturnType<typeof contentTagStatistics>,context:Context)=>{
        line(interpolate(c.scope,{scope:context.scopeLabel}));
        line(interpolate(c.total,{count:stats.records}));
        line(c.basis);
        if (context.allSelectedMonths) line(c.timeScope);
        const scroll = document.createElement("div");
        scroll.style.overflowX = "auto";
        scroll.tabIndex = 0; scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", c.caption);
        const table = document.createElement("table"), caption = document.createElement("caption"), head = document.createElement("thead"), header = document.createElement("tr"), rows = document.createElement("tbody");
        caption.textContent = c.caption; table.append(caption,head,rows); head.append(header);
        for (const text of [c.label,c.supported,c.share,c.coverage,c.uncertain,c.pending,c.noSupport,c.index]) {
          const th=document.createElement("th"); th.scope="col"; th.textContent=text; header.append(th);
        }
        for (const tag of stats.tags) {
          const row=document.createElement("tr"), label=document.createElement("th");
          label.scope="row"; label.textContent=c.tags[tag.tag]; row.append(label);
          const values=[String(tag.counts.supported),
            tag.documented_share.value===null ? c.unknown : percent.format(tag.documented_share.value),
            tag.evaluation_coverage.value===null ? c.unknown : percent.format(tag.evaluation_coverage.value),
            String(tag.counts.uncertain),String(tag.counts.not_evaluated),String(tag.counts.no_support),
            tag.content_index===null ? c.unknown : number.format(tag.content_index)];
          for (const text of values) {const td=document.createElement("td"); td.textContent=text; row.append(td);}
          rows.append(row);
        }
        scroll.append(table); body.append(scroll);
        const methods=document.createElement("details"), methodTitle=document.createElement("summary");
        methodTitle.textContent=c.methodInfo;methods.append(methodTitle);
        for(const text of [c.formula,c.incomplete,c.overlap,c.hate]) line(text,methods);
        if(context.textScope==="accepted_upstream_summary") line(c.summaryScope,methods);
        if(context.textScope==="mixed") line(c.mixedScope,methods);
        body.append(methods);
        if(stats.composite) {
          line(interpolate(c.composite,{value:stats.composite.value===null ? c.unknown : number.format(stats.composite.value)}));
          line(c.compositeFormula);
          // Public weights appear beside the formula; they are never silently selected by this panel.
          for(const [tag,weight] of Object.entries(stats.composite.weights)) line(`${c.tags[tag as ContentTag]}: ${number.format(weight!)}`);
        }
  };
  const unavailable=()=>{body.replaceChildren();line(c.unavailable);};
  return {
    element:root,
    update(records:readonly ContentRecord[],assessments:readonly ContentAssessment[],context:Context){
      reset();try{render(contentTagStatistics(records,assessments,context.weights),context);}catch{unavailable();}
    },
    updateSummary(source:ContentTagSummary,context:Omit<Context,"textScope">){
      reset();try{render(contentTagStatisticsForSummary(source,context.weights),
        {...context,textScope:source.text_scope,allSelectedMonths:true});}catch{unavailable();}
    },
    invalidate(){reset();unavailable();},
    destroy(){root.remove();},
  };
}
