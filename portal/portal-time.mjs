const clock=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Berlin',hour:'2-digit',hourCycle:'h23'});
export function cityPhotoScene(date=new Date()){
 const hour=Number(clock.formatToParts(date).find(p=>p.type==='hour').value);
 return hour>=19||hour<7?'night':'day';
}
