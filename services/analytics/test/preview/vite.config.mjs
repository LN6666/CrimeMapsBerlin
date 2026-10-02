import {fileURLToPath} from 'node:url';
export default {server:{host:'127.0.0.1',port:4188,strictPort:true,fs:{allow:[fileURLToPath(new URL('../../../../../',import.meta.url))]}},root:fileURLToPath(new URL('./',import.meta.url))};
