import {mountGoatCounterConnectionTest} from '../../../src/goatcounter-client.mjs';
const button=document.querySelector<HTMLButtonElement>('#send')!;
button.addEventListener('click',()=>{button.disabled=true;mountGoatCounterConnectionTest({enabled:true});document.querySelector('#result')!.textContent='已启动一次连接测试；是否接收必须由运营者在私有统计/API核对。';},{once:true});
