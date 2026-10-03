import {CITIES} from './contract.mjs';
export const COUNT_ENDPOINT = 'https://ryoushunnei.goatcounter.com/count';
export const SCRIPT_URL = 'https://gc.zgo.at/count.v5.js';
export const SCRIPT_INTEGRITY = 'sha384-atnOLvQb9t+jTSipvd75X2yginT4PjVbqDdlJAmxMm+wYElFmeR6EmLP5bYeoRVQ';
const documents = new WeakMap();
const LANGUAGE_NAVIGATION = 'crimemaps:analytics-language-navigation';
export function markAnalyticsLanguageNavigation(city,win=window) {
  if (!CITIES.includes(city)) return;
  try {win.sessionStorage.setItem(LANGUAGE_NAVIGATION,JSON.stringify({city,at:Date.now()}));} catch { /* Optional count must not affect language navigation. */ }
}
function consumeLanguageNavigation(city,win) {
  try {
    const raw=win.sessionStorage?.getItem(LANGUAGE_NAVIGATION);
    if (!raw) return false;
    win.sessionStorage.removeItem(LANGUAGE_NAVIGATION);
    const marker=JSON.parse(raw),age=Date.now()-marker.at;
    return marker.city===city && age>=0 && age<15000;
  } catch {return false;}
}
export function countPath(city) {
  if (city === 'portal') return '/portal';
  if (!CITIES.includes(city)) throw new Error('invalid_analytics_city');
  return `/cities/${city}`;
}
export function countTitle(city) {
  countPath(city);
  return city === 'portal' ? 'CrimeMaps · City portal' : `CrimeMaps · ${city[0].toUpperCase()}${city.slice(1)}`;
}
// A single explicit installation per document, independent of map/language updates.
export function mountGoatCounter({city, enabled = false}, win = window) {
  if (city !== 'portal' && !CITIES.includes(city)) return {destroy() {}};
  if (consumeLanguageNavigation(city,win)) return {destroy() {}};
  return install({path:countPath(city),title:countTitle(city),enabled},win);
}
// Used only by the explicit local operator connection-test page; never a city.
export function mountGoatCounterConnectionTest({enabled = false}, win = window) {
  const local = ['localhost','127.0.0.1'].includes(win.location.hostname);
  return install({path:'/_connection-test',title:'CrimeMaps · Connection test',enabled,allowLocal:local},win);
}
function install({path,title,enabled,allowLocal=false},win) {
  const noop = {destroy() {}};
  if (!enabled) return noop;
  const doc = win.document;
  if ((!allowLocal && (win.location.protocol !== 'https:' || win.location.hostname !== 'ln6666.github.io'))
      || win.navigator.globalPrivacyControl || win.navigator.doNotTrack === '1'
      || documents.has(doc) || doc.querySelector('script[data-goatcounter]') || win.goatcounter) return noop;
  const script = doc.createElement('script');
  script.src = SCRIPT_URL; script.async = true; script.crossOrigin = 'anonymous';
  script.integrity = SCRIPT_INTEGRITY; script.referrerPolicy = 'no-referrer';
  script.dataset.goatcounter = COUNT_ENDPOINT;
  script.dataset.goatcounterSettings = JSON.stringify({no_onload:true,no_events:true,allow_local:allowLocal,path,title,referrer:'',event:false});
  const state = {alive:true,counted:false,ready:false}; documents.set(doc,state);
  const settings = {no_onload:true,no_events:true,allow_local:allowLocal,path,title,referrer:'',event:false,endpoint:COUNT_ENDPOINT};
  win.goatcounter = settings;
  const count = () => {
    if (!state.alive || !state.ready || state.counted || doc.visibilityState !== 'visible') return;
    const gc = win.goatcounter;
    if (typeof gc?.filter !== 'function' || typeof gc?.url !== 'function' || typeof gc?.get_data !== 'function') return;
    try {if (gc.filter()) return;} catch {return;}
    // The pinned official script also sends q=location.search and screen size.
    // Its exposed data hook is replaced before any count URL can be generated.
    const originalData=gc.get_data.bind(gc);
    gc.get_data = () => ({p:path,t:title,r:'',e:false,b:originalData().b});
    const url = gc.url();
    if (typeof url !== 'string' || new URL(url).origin !== new URL(COUNT_ENDPOINT).origin
        || new URL(url).pathname !== '/count') return;
    state.counted = true;
    doc.removeEventListener('visibilitychange',count);
    // Use the official URL/filter, with an explicit referrer policy. No retry:
    // a failed optional count must not duplicate a visit or affect the map.
    void win.fetch(url,{method:'POST',mode:'no-cors',credentials:'omit',cache:'no-store',keepalive:true,referrerPolicy:'no-referrer'}).catch(() => {});
  };
  const loaded = () => {state.ready = true; count();};
  script.addEventListener('load',loaded,{once:true});
  const failed = () => {state.alive = false; doc.removeEventListener('visibilitychange',count);};
  script.addEventListener('error',failed,{once:true});
  doc.addEventListener('visibilitychange',count);
  doc.head.append(script);
  return {destroy() {
    state.alive = false; doc.removeEventListener('visibilitychange',count);
    script.removeEventListener('load',loaded); script.removeEventListener('error',failed); script.remove();
    if (!state.counted) {documents.delete(doc); if (win.goatcounter === settings) delete win.goatcounter;}
  }};
}
