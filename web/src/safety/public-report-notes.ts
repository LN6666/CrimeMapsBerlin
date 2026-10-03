import type {PoliceEvent,SceneLocation} from './model';

function text(parent:HTMLElement,tag:'p'|'small'|'li',value:string):void {
 const node=document.createElement(tag);node.textContent=value;parent.append(node);
}

/** Only explicitly reviewed public notes enter the report card. */
export function appendPublicEventNotes(parent:HTMLElement,event:PoliceEvent):void {
 const fields=new Set(event.public_display_fields??[]);
 if(fields.has('status_update')&&event.status_update)text(parent,'p',event.status_update);
 if(fields.has('public_uncertainty')&&event.public_uncertainty?.length){
  const list=document.createElement('ul');
  for(const note of event.public_uncertainty)if(note)text(list,'li',note);
  if(list.childElementCount)parent.append(list);
 }
}

export function appendPublicSceneReferenceNote(parent:HTMLElement,scene:SceneLocation):void {
 if(scene.public_display_fields?.includes('public_reference_note')&&scene.public_reference_note)
  text(parent,'small',scene.public_reference_note);
}
