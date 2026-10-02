export type WorldLanguage = 'en' | 'de' | 'zh';
export type WorldStatus = 'live' | 'not_connected' | 'unavailable' | 'loading';
export interface WorldStats {schema_version:number;city:string;status:string;metric:string;total_pv:number|null;countries:{code:string;pv:number}[];generated_at:string;unique_visitors_measured:boolean;privacy:{minimum_sample:number;rounding:number};collection_start_date?:string|null}
export interface WorldCardModel {city:string;lang:WorldLanguage;status:WorldStatus;copy:Record<string,string>;message:string;regions:{code:string;pv:number;name:string;formatted:string;color:string;width:number;mapped:boolean}[];paths:{code:string;d:string;pv:number|null;color:string;label:string}[];max:number;generatedAt:string|null;unmapped:string[];total:number|null}
export const WORLD_COPY: Record<WorldLanguage,Record<string,string>>;
export const NO_DATA_COLOR:string;
export const BLUE_SCALE:readonly string[];
export function isPublicStats(s:unknown,expectedCity?:string):s is WorldStats;
export function buildWorldCardModel(stats:unknown,lang?:WorldLanguage,expectedCity?:string):WorldCardModel;
export function buildPlaceholderModel(city:string,lang?:WorldLanguage,status?:Exclude<WorldStatus,'live'>):WorldCardModel;
export function renderWorldCardSvg(model:WorldCardModel,layout?:'wide'|'stacked'):string;
export function countryName(code:string,lang:WorldLanguage):string;
export function escapeXml(value:unknown):string;
