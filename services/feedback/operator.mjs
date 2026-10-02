// Read/delete private feedback from an operator terminal. Secrets stay in environment.
// Never use this command from the public site or a public CI job.
const [command, cityOrId, cursor] = process.argv.slice(2);
const endpoint = process.env.CRIMEMAPS_FEEDBACK_ENDPOINT, token = process.env.CRIMEMAPS_FEEDBACK_ADMIN_TOKEN;
let api;
try {api = new URL(endpoint); if (api.protocol !== 'https:' || api.username || api.password || api.search || api.hash) throw Error();}
catch {throw Error('Set a real HTTPS CRIMEMAPS_FEEDBACK_ENDPOINT.');}
if (!/^[a-f0-9]{64}$/.test(token ?? '')) throw Error('Set the server-only CRIMEMAPS_FEEDBACK_ADMIN_TOKEN.');
if (!['list','delete'].includes(command)) throw Error('Usage: node operator.mjs list CITY [CURSOR] | delete RECEIPT_ID');
const url = new URL('/admin/feedback',api);
if (command === 'list') {url.searchParams.set('city',cityOrId ?? ''); if (cursor) url.searchParams.set('after',cursor);}
const r = await fetch(url, {method:command === 'list' ? 'GET':'POST',
  headers:{Authorization:`Bearer ${token}`,...command==='delete'?{'Content-Type':'application/json'}:{}},
  body:command==='delete'?JSON.stringify({action:'delete',id:cityOrId}):undefined, redirect:'error',signal:AbortSignal.timeout(15000)});
if (!r.ok) throw Error(`Operator request failed (${r.status}).`);
// JSON encoding prevents message content from becoming terminal control sequences.
if (command==='list') process.stdout.write(JSON.stringify(await r.json(),null,2)+'\n');
else process.stdout.write('Deletion requested.\n');
