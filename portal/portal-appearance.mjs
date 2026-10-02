export const appearanceStorageKey='crimemaps:appearance:v1';
export function appearanceValue(value){return value==='light'?'light':'blue';}
export function readAppearance(storage){try{return appearanceValue(storage?.getItem(appearanceStorageKey));}catch{return 'blue';}}
export function saveAppearance(value,storage){try{storage?.setItem(appearanceStorageKey,appearanceValue(value));}catch{/* The selection works even when storage is unavailable. */}}
