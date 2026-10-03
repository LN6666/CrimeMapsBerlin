export const COUNT_ENDPOINT:string;
export const SCRIPT_URL:string;
export const SCRIPT_INTEGRITY:string;
export function countPath(city:string):string;
export function countTitle(city:string):string;
export function markAnalyticsLanguageNavigation(city:string,win?:Window):void;
export function mountGoatCounter(options:{city:string;enabled?:boolean},win?:Window):{destroy():void};
export function mountGoatCounterConnectionTest(options:{enabled?:boolean},win?:Window):{destroy():void};
