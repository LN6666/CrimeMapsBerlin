import type {Map,LayerSpecification,ExpressionSpecification} from 'maplibre-gl';
import {locale} from './i18n';
export const VECTOR_SOURCE='basemap-vector';
export function localizedName(language:string):ExpressionSpecification {
 return ['coalesce',['get',`name_${language}`],['get','name'],''];
}
export function addVectorBasemap(map:Map) {
 map.addSource(VECTOR_SOURCE,{type:'vector',url:'https://vector.openstreetmap.org/shortbread_v1/tilejson.json',attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>',maxzoom:14});
 map.setGlyphs('https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf');
 const layers:LayerSpecification[]=[
  {id:'basemap-vector-land',type:'fill',source:VECTOR_SOURCE,'source-layer':'land',paint:{'fill-color':'#e5ede0','fill-opacity':0.75}},
  {id:'basemap-vector-water',type:'fill',source:VECTOR_SOURCE,'source-layer':'water_polygons',paint:{'fill-color':'#bdd9e4'}},
  {id:'basemap-vector-buildings',type:'fill',source:VECTOR_SOURCE,'source-layer':'buildings',minzoom:14,paint:{'fill-color':'#d5d3c9','fill-opacity':0.7}},
  {id:'basemap-vector-streets',type:'line',source:VECTOR_SOURCE,'source-layer':'streets',paint:{'line-color':'#fdfdfb','line-width':['interpolate',['linear'],['zoom'],8,0.5,14,2,18,6]}},
  {id:'basemap-vector-street-labels',type:'symbol',source:VECTOR_SOURCE,'source-layer':'street_labels',minzoom:13,layout:{'symbol-placement':'line','text-field':localizedName(locale),'text-font':['Noto Sans Regular'],'text-size':12},paint:{'text-color':'#4e575b','text-halo-color':'#ffffff','text-halo-width':1}},
  {id:'basemap-vector-place-labels',type:'symbol',source:VECTOR_SOURCE,'source-layer':'place_labels',layout:{'text-field':localizedName(locale),'text-font':['Noto Sans Regular'],'text-size':['interpolate',['linear'],['zoom'],5,11,13,16]},paint:{'text-color':'#34494e','text-halo-color':'#ffffff','text-halo-width':1.5}},
 ];
 for(const layer of layers)map.addLayer(layer,'roads-line');
}
export function removeVectorBasemap(map:Map) {
 for(const id of ['basemap-vector-place-labels','basemap-vector-street-labels','basemap-vector-streets','basemap-vector-buildings','basemap-vector-water','basemap-vector-land'])if(map.getLayer(id))map.removeLayer(id);
 if(map.getSource(VECTOR_SOURCE))map.removeSource(VECTOR_SOURCE);
}
