import type {PoliceEvent} from './model';
import type {Manifest,DataClient} from './data';
import type {Locale} from './i18n';
export interface AddressedText {city:string;source_id:string;source_sha256?:string;field:string;text_sha256:string;translated_text:string;method?:'official_excerpt'|'translated'|'unchanged_native'}
export interface DynamicTextPack {schema_version:1;locale:Locale;city?:string;month?:string;source_generation:string;texts:Record<string,string>;fields?:AddressedText[];native_text_hashes?:string[]}
interface TextField {event:PoliceEvent;field:string;original:string}
function sourceId(event:PoliceEvent):string {return String((event as PoliceEvent&{source_id?:string}).source_id??event.id.split(':').at(-1)??event.id);}
function fieldsFor(event:PoliceEvent):TextField[] {
 const fields:TextField[]=[];
 const add=(field:string,value:unknown)=>{if(typeof value==='string'&&value)fields.push({event,field,original:value});};
 add('/title',event.title);add('/location_label',event.location_label);
 event.incidents?.forEach((stage,i)=>{add(`/incidents/${i}/details`,stage.details);add(`/incidents/${i}/event_time/display`,stage.event_time?.display);});
 event.scene_locations?.forEach((scene,i)=>{
  const path=`/scene_locations/${i}`;
  add(`${path}/label`,scene.label);add(`${path}/details`,scene.details);add(`${path}/event_time/display`,scene.event_time?.display);
  scene.incidents?.forEach((incident,j)=>{add(`${path}/incidents/${j}/details`,incident.details);add(`${path}/incidents/${j}/event_time/display`,incident.event_time?.display);});
 });
 return fields;
}
export function publicTextFields(rows:readonly PoliceEvent[]):string[] {return [...new Set(rows.flatMap(fieldsFor).map(f=>f.original))];}
export async function textHash(value:string):Promise<string> {
 const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));
 return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
function acceptedText(value:unknown):value is string {return typeof value==='string'&&Boolean(value.trim())&&value.length<=32000;}
/** Source values and geometry stay intact. Only exact fields in a display copy are replaced. */
export class DynamicTranslations {
 private lookup=new Map<string,string>();
 private addressed=new Map<string,string>();
 private missingByEvent=new Map<string,number>();
 missing=0; matched=0;
 clear(){this.lookup.clear();this.addressed.clear();this.missingByEvent.clear();this.missing=0;this.matched=0;}
 text(original:string):string{return this.lookup.get(original)??original;}
 field(event:PoliceEvent,path:string,original:string):string {return this.addressed.get(`${event.id}\0${path}`)??this.text(original);}
 missingFor(event:PoliceEvent):number {return this.missingByEvent.get(event.id)??fieldsFor(event).length;}
 displayRows(rows:readonly PoliceEvent[]):PoliceEvent[] {
  return rows.map(event=>({...event,title:this.field(event,'/title',event.title),location_label:this.field(event,'/location_label',event.location_label),incidents:event.incidents?.map((stage,i)=>({...stage,details:stage.details?this.field(event,`/incidents/${i}/details`,stage.details):stage.details,event_time:stage.event_time?{...stage.event_time,display:this.field(event,`/incidents/${i}/event_time/display`,stage.event_time.display)}:stage.event_time})),scene_locations:event.scene_locations?.map((scene,i)=>{
   const path=`/scene_locations/${i}`;
   return {...scene,label:this.field(event,`${path}/label`,scene.label),details:scene.details?this.field(event,`${path}/details`,scene.details):scene.details,
    event_time:scene.event_time?{...scene.event_time,display:this.field(event,`${path}/event_time/display`,scene.event_time.display)}:scene.event_time,
    incidents:scene.incidents?.map((incident,j)=>({...incident,details:incident.details?this.field(event,`${path}/incidents/${j}/details`,incident.details):incident.details,event_time:incident.event_time?{...incident.event_time,display:this.field(event,`${path}/incidents/${j}/event_time/display`,incident.event_time.display)}:incident.event_time}))};
  })}));
 }
 async load(rows:readonly PoliceEvent[],manifest:Manifest,client:DataClient,month:string,locale:Locale,signal:AbortSignal,city=manifest.city.toLowerCase()) {
  this.clear();signal.throwIfAborted();const fields=rows.flatMap(fieldsFor);
  const markMissing=()=>{this.missing=fields.length;for(const e of rows)this.missingByEvent.set(e.id,fieldsFor(e).length);};
  const path=manifest.translations?.[locale]?.[month];
  if(!path){markMissing();return;}
  if(!/^translations\/(de|en|zh)\/\d{4}-(0[1-9]|1[0-2])\.json$/.test(path)||!path.startsWith(`translations/${locale}/`))throw Error('Invalid translation path');
  const pack=await client.json<DynamicTextPack>(`${client.base}/${path}`,signal);
  if(typeof pack.source_generation!=='string'||!pack.source_generation||pack.schema_version!==1||pack.locale!==locale||(pack.city&&pack.city!==city)||(pack.month&&pack.month!==month)||![manifest.generation,manifest.metadata.transport_source_generation,manifest.metadata.translation_source_generation].includes(pack.source_generation)||!pack.texts||typeof pack.texts!=='object'||Array.isArray(pack.texts))throw Error('Stale translation pack');
  if(pack.native_text_hashes&&(!Array.isArray(pack.native_text_hashes)||!pack.native_text_hashes.every(h=>typeof h==='string'&&/^[a-f0-9]{64}$/.test(h))))throw Error('Invalid native text receipt');
  const nativeHashes=new Set(pack.native_text_hashes??[]);
  const addresses=new Map<string,AddressedText>();
  for(const item of pack.fields??[]) {
   if(item.city!==city||!/^\/[A-Za-z0-9_/]+$/.test(item.field)||!(/^[a-f0-9]{64}$/.test(item.text_sha256))||!acceptedText(item.translated_text))continue;
   const key=`${item.source_id}\0${item.field}`;
   if(addresses.has(key))throw Error('Duplicate translation address');addresses.set(key,item);
  }
  const generic=new Map<string,string>();const addressed=new Map<string,string>();const missing=new Map<string,number>();let matches=0;
  const hashes=new Map<string,string>();const unique=[...new Set(fields.map(f=>f.original))];
  for(let i=0;i<unique.length;i+=32){signal.throwIfAborted();const values=await Promise.all(unique.slice(i,i+32).map(textHash));values.forEach((hash,j)=>hashes.set(unique[i+j],hash));}
  for(const f of fields) {
   const hash=hashes.get(f.original)!;const item=addresses.get(`${sourceId(f.event)}\0${f.field}`);
   const currentSHA=(f.event as PoliceEvent&{source_sha256?:string}).source_sha256;
   if(item&&item.text_sha256===hash&&(!item.source_sha256||!currentSHA||item.source_sha256===currentSHA)) {addressed.set(`${f.event.id}\0${f.field}`,item.translated_text);matches++;}
   else if(acceptedText(pack.texts[hash])) {generic.set(f.original,pack.texts[hash]);matches++;}
   else if(nativeHashes.has(hash)){generic.set(f.original,f.original);matches++;}
   else missing.set(f.event.id,(missing.get(f.event.id)??0)+1);
  }
  signal.throwIfAborted();this.lookup=generic;this.addressed=addressed;this.missingByEvent=missing;for(const e of rows)if(!missing.has(e.id))missing.set(e.id,0);this.matched=matches;this.missing=fields.length-matches;
 }
}
