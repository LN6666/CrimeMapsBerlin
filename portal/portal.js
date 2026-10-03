import {cityPhotoScene} from './portal-time.mjs';
import {appearanceStorageKey,appearanceValue,readAppearance,saveAppearance} from './portal-appearance.mjs';
import {portalCopy as copy,portalAppearanceCopy as appearanceCopy} from './portal-locales.js';
function storage(){try{return window.localStorage;}catch{return undefined;}}
const appearanceSelect=document.querySelector('#appearance');
function synchronizeAppearance(){const value=readAppearance(storage());document.documentElement.dataset.theme=value;appearanceSelect.value=value;}
synchronizeAppearance();
appearanceSelect.addEventListener('change',()=>{const value=appearanceValue(appearanceSelect.value);document.documentElement.dataset.theme=value;saveAppearance(value,storage());});
window.addEventListener('pageshow',synchronizeAppearance);
window.addEventListener('storage',event=>{if(event.key===appearanceStorageKey||event.key===null)synchronizeAppearance();});
const languageCopy={"de":"Sprache","en":"Language","zh":"语言"};
const supported=["zh","de","en"];
function canonicalLocale(value){return value==="zh-CN"?"zh":supported.includes(value)?value:"de";}
const requested=new URL(location.href).searchParams.get("lang");
let locale=canonicalLocale(requested);
function text(key,args={}){return Object.entries(args).reduce((s,[key,value])=>s.replaceAll(`{${key}}`,value),copy[locale][key]);}
function cityHref(city){const query=new URLSearchParams({lang:locale}),incoming=new URL(location.href).searchParams.get("month"),month=incoming&&/^\d{4}-(0[1-9]|1[0-2])$/.test(incoming)?incoming:city.month;if(month)query.set("month",month);return city.map_path+"?"+query;}
function render(){
 document.documentElement.lang=locale==="zh"?"zh-CN":locale;
 document.querySelector(".language-switch").setAttribute("aria-label",languageCopy[locale]);
 document.title=copy[locale].title;
 document.querySelector('[data-appearance-label]').textContent=appearanceCopy[locale].label;
 appearanceSelect.setAttribute('aria-label',appearanceCopy[locale].label);
 for(const option of appearanceSelect.options)option.textContent=appearanceCopy[locale][option.value];
 for(const el of document.querySelectorAll("[data-copy]"))el.textContent=text(el.dataset.copy);
 const mark=document.querySelector(".home-mark"),brand=document.querySelector(".home-mark .brand-art");
 mark.href="./?lang="+locale;mark.setAttribute("aria-label",text("home"));
 brand.src="portal-assets/brand/crime-map-"+(locale==="de"?"de":"en")+".png";brand.alt=text("title");
 document.querySelector(".city-grid").setAttribute("aria-label",text("grid"));
 for(const tile of document.querySelectorAll(".city-tile")){
  const city=cities.find(c=>c.city===tile.dataset.city),name=city.names[locale];
  tile.href=cityHref(city);tile.setAttribute("aria-label",text("open",{city:name}));
  tile.querySelector(".city-name").textContent=name;
  tile.querySelector(".city-photo>img").alt=text("alt",{city:name,landmark:city.landmark[locale]});
 }
 for(const b of document.querySelectorAll("[data-language]"))b.setAttribute("aria-pressed",String(b.dataset.language===locale));
 for(const row of document.querySelectorAll("[data-external-city]")){
  const city=cities.find(c=>c.city===row.dataset.externalCity),name=city.names[locale];
  row.querySelector(".directory-city-name").textContent=name;
  for(const link of row.querySelectorAll("[data-link-kind]")){
   const key=link.dataset.linkKind==="map"?"externalMapLabel":"externalPoliceLabel";
   link.setAttribute("aria-label",text(key,{city:name}));
  }
 }
}
for(const button of document.querySelectorAll("[data-language]"))button.addEventListener("click",()=>{locale=button.dataset.language;const url=new URL(location.href);url.searchParams.set("lang",locale);history.replaceState(null,"",url);render();});
window.addEventListener("popstate",()=>{const value=new URL(location.href).searchParams.get("lang");locale=canonicalLocale(value);render();});
render();
const directory=document.querySelector(".official-directory");
directory.addEventListener("keydown",event=>{
 if(event.key==="Escape"&&directory.open){
  directory.open=false;
  directory.querySelector("summary").focus();
  event.preventDefault();
 }
});
function renderScene(){
 const scene=cityPhotoScene();
 if(document.documentElement.dataset.scene===scene)return;
 document.documentElement.dataset.scene=scene;
 for(const image of document.querySelectorAll('.city-photo>img'))image.src=image.dataset[scene+'Src'];
}
renderScene();
setInterval(()=>{if(!document.hidden)renderScene();},60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)renderScene();});
