import {test,expect} from '@playwright/test';
const stats={schema_version:1,city:'berlin',status:'live',metric:'accepted_opt_in_pageviews',total_pv:40,countries:[{code:'DE',pv:20},{code:'OTHER',pv:20}],generated_at:'2026-10-03T00:00:00.000Z',unique_visitors_measured:false,privacy:{minimum_sample:20,rounding:10}};
const allow={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'content-type','Access-Control-Allow-Methods':'POST, OPTIONS','Content-Type':'application/json'};
async function fakeBackend(page,body=stats){
 await page.route('https://analytics.invalid/v1/stats/**',route=>route.fulfill({status:200,headers:allow,body:JSON.stringify(body)}));
}
test('unconnected has honest text and no third-party traffic',async({page})=>{
 const external=[];page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:4188'))external.push(r.url());});
 await page.goto('/');await expect(page.getByText('Visit statistics are not connected yet.')).toBeVisible();
 await expect(page.getByRole('button',{name:'Count this page view'})).toBeHidden();expect(external).toEqual([]);
});
test('GET does not POST or load challenge; language switch is local and accessible',async({page})=>{
 let reads=0,writes=0,challenge=0;
 page.on('request',r=>{if(r.url().includes('/v1/stats'))reads++;if(r.url().includes('/v1/events'))writes++;if(r.url().includes('challenges.cloudflare.com'))challenge++;});
 await fakeBackend(page);await page.goto('/?configured=1');
 await expect(page.getByRole('status').first()).toHaveText('Counted page views: 40');
 await page.getByText('Page views by country or region',{exact:true}).click();
 await expect(page.locator('[data-region=DE]')).toContainText('Germany');await expect(page.locator('[data-region=DE] strong')).toHaveText('20');
 await page.getByRole('button',{name:'Language',exact:true}).click();await expect(page.getByRole('status').first()).toHaveText('Gezählte Seitenaufrufe: 40');
 await page.getByRole('button',{name:'Language',exact:true}).click();await expect(page.getByRole('status').first()).toHaveText('已计入的页面浏览次数：40');
 expect(reads).toBe(1);expect(writes).toBe(0);expect(challenge).toBe(0);
});
test('failures and malicious stats fail honestly without creating zeroes or HTML',async({page})=>{
 await page.route('https://analytics.invalid/**',route=>route.fulfill({status:503,headers:allow,body:'{"error":"unavailable"}'}));
 await page.goto('/?configured=1');await expect(page.getByText('Visit statistics are currently unavailable.')).toBeVisible();
 await expect(page.getByRole('button',{name:'Count this page view'})).toBeDisabled();
 await page.unroute('https://analytics.invalid/**');
 await fakeBackend(page,{...stats,countries:[{code:'<script>alert(1)</script>',pv:20}]});await page.reload();
 await expect(page.getByText('Visit statistics are currently unavailable.')).toBeVisible();expect(await page.locator('script').count()).toBe(2);
});
test('privacy preference disables collection before challenge script',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(navigator,'globalPrivacyControl',{value:true}));await fakeBackend(page);await page.goto('/?configured=1');
 await page.locator('details > summary').click();
 await expect(page.getByText('Your browser’s privacy setting prevents this page view from being counted.')).toBeVisible();
 await expect(page.getByRole('button',{name:'Count this page view'})).toBeHidden();
});
test('consent sends one bounded event without country, IP, cookies or credentials',async({page})=>{
 const events=[];
 await fakeBackend(page);
 await page.route('https://challenges.cloudflare.com/**',route=>route.fulfill({status:200,contentType:'application/javascript',body:"window.turnstile={render:(el,opts)=>{if(opts.size!=='compact')throw new Error('Wrong size');setTimeout(()=>opts.callback('local-test-token'),10);return 'widget-1';},remove:()=>{}};"}));
 await page.route('https://analytics.invalid/v1/events/**',route=>{
  if(route.request().method()==='OPTIONS')return route.fulfill({status:204,headers:allow});
  events.push({body:route.request().postDataJSON(),headers:route.request().headers()});return route.fulfill({status:202,headers:allow,body:'{"accepted":true}'});
 });
 await page.goto('/?configured=1');await expect(page.getByRole('button',{name:'Count this page view'})).toBeEnabled();
 await page.locator('details > summary').click();await page.getByRole('button',{name:'Count this page view'}).click();await expect(page.getByText('This page view was counted.')).toBeVisible();
 expect(events).toHaveLength(1);expect(events[0].body).toEqual({event:'pageview',path:'/crimemaps-Berlin/',token:'local-test-token'});expect(events[0].headers.cookie).toBeUndefined();expect(events[0].headers.referer).toBeUndefined();
 await expect(page.getByRole('button',{name:'Count this page view'})).toBeHidden();expect(await page.evaluate(()=>localStorage.length)).toBe(0);
});
test('destroy cancels pending stats and prevents late UI updates',async({page})=>{
 await page.route('https://analytics.invalid/**',async route=>{await new Promise(r=>setTimeout(r,600));try{await route.fulfill({status:200,headers:allow,body:JSON.stringify(stats)});}catch{}});
 await page.goto('/?configured=1');await page.getByRole('button',{name:'Destroy component'}).click();await expect(page.locator('.analytics-summary')).toHaveCount(0);
 await page.waitForTimeout(700);await expect(page.locator('.analytics-summary')).toHaveCount(0);
});
test('all three languages fit 320/390/430px and controls have 44px targets',async({page})=>{
 await fakeBackend(page);
 for(const language of ['en','de','zh'])for(const width of [320,390,430]){
  await page.setViewportSize({width,height:640});await page.goto(`/?configured=1&lang=${language}`);await expect(page.locator('details')).toBeVisible();await page.locator('details > summary').click();
  const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,button:document.querySelector('.analytics-summary button').getBoundingClientRect().height}));expect(size.scroll).toBeLessThanOrEqual(size.width);expect(size.button).toBeGreaterThanOrEqual(44);
 }
 await page.screenshot({path:'../../../evidence/mobile-preview-430-zh.png',fullPage:true});
});
