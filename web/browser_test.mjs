/* ทดสอบไฟล์ HTML ที่ build แล้วใน DOM จำลอง โดยป้อนไฟล์ข้อมูลจริงเข้าไป
 *
 *   node web/browser_test.mjs [dist/DentalDX-Dashboard-vX.Y.Z.html]
 *
 * ตรวจว่า: เลือกโฟลเดอร์แล้วได้ dashboard, ตัวเลขตรง, คลิกดูรายชื่อได้,
 * ส่งออกไฟล์ได้ และสิ่งที่เบราว์เซอร์จำไว้ต้องไม่มีข้อมูลรายบุคคล
 */
/* รันไฟล์ HTML ที่ build แล้วใน DOM จำลอง ป้อนไฟล์ข้อมูลจริงเข้าไป */
import fs from 'node:fs'; import path from 'node:path';
import {JSDOM} from 'jsdom';
import {DecompressionStream, ReadableStream, TextDecoderStream} from 'node:stream/web';

const ROOT=process.env.DX_ROOT||path.resolve(path.dirname(new URL(import.meta.url).pathname),'..');
let file=process.argv[2];
if(!file){
  const d=path.join(ROOT,'dist');
  const found=fs.readdirSync(d).filter(f=>/^DentalDX-Dashboard-v.*\.html$/.test(f)).sort();
  if(!found.length) throw new Error('ไม่พบไฟล์ใน dist/ — รัน python web/build_webapp.py ก่อน');
  file=path.join('dist',found[found.length-1]);
}
const html=fs.readFileSync(path.join(ROOT,file),'utf8');

const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,url:'https://local.test/',
  beforeParse(w){
    w.DecompressionStream=DecompressionStream;
    w.TextDecoder=TextDecoder; w.TextEncoder=TextEncoder;
    w.ReadableStream=ReadableStream; w.TextDecoderStream=TextDecoderStream;
    // jsdom ยังไม่มี Blob.stream() ซึ่งเบราว์เซอร์จริงมี — ใส่ให้เทสต์รันได้
    // jsdom รุ่นเก่ายังไม่มี Blob.stream()/arrayBuffer() ซึ่งเบราว์เซอร์จริงมีครบ
    w.eval(`
      var _native = Blob.prototype.arrayBuffer;
      function _ab(b){
        if (_native) return _native.call(b);
        return new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = () => rej(r.error);
          r.readAsArrayBuffer(b);
        });
      }
      if(!Blob.prototype.arrayBuffer) Blob.prototype.arrayBuffer=function(){return _ab(this);};
      if(!Blob.prototype.stream){Blob.prototype.stream=function(){
        const b=this; return new ReadableStream({async start(c){
          c.enqueue(new Uint8Array(await _ab(b))); c.close();}});};}
    `);

  }});
const w=dom.window;
w.addEventListener('error',e=>console.log('PAGE ERROR:',e.message));
dom.virtualConsole?.on?.('jsdomError',e=>console.log('JSDOM ERROR:',e.message));
await new Promise(r=>w.addEventListener('load',r));
console.log('โหลดหน้าแล้ว | มี window.DX:', typeof w.DX, '| มี DX_init:', typeof w.DX_init);

/* สร้าง File object จากไฟล์จริงพร้อม webkitRelativePath */
function mkFile(abs, rel){
  const buf=fs.readFileSync(abs);
  const f=new w.File([new Uint8Array(buf)], path.basename(abs));
  Object.defineProperty(f,'webkitRelativePath',{value:rel});
  return f;
}
const files=[];
const DATA=process.env.DX_DATA||path.join(ROOT,'data');
for(const g of fs.readdirSync(DATA).filter(d=>fs.statSync(path.join(DATA,d)).isDirectory()))
  for(const n of fs.readdirSync(path.join(DATA,g)).filter(x=>/\.xlsx$/i.test(x)))
    files.push(mkFile(path.join(DATA,g,n), `Dashboard-Exam/data/${g}/${n}`));
for(const n of fs.readdirSync(path.join(ROOT,'profiles')).filter(x=>/\.ya?ml$/.test(x)))
  files.push(mkFile(path.join(ROOT,'profiles',n), `Dashboard-Exam/profiles/${n}`));
console.log('ป้อนไฟล์:', files.map(f=>f.webkitRelativePath).join(', '));

/* เดินตามเส้นทางผู้ใช้จริง: กดปุ่มเลือกโฟลเดอร์ -> onchange */
const t0=Date.now();
const $0=s=>w.document.querySelector(s);
$0('#pickInput').onchange({target:{files}});
/* onchange ไม่คืน promise (เบราว์เซอร์ก็ไม่รอ) จึงรอจนหน้าเลือกโฟลเดอร์หายไป */
for(let i=0;i<600;i++){
  await new Promise(r=>setTimeout(r,100));
  if(!$0('#pick')) break;
  const e=$0('#pickErr');
  if(e && !e.hidden){ console.log('ERROR BOX:',e.textContent); break; }
}
await new Promise(r=>setTimeout(r,500));
console.log(`โหลด+วาดหน้าเสร็จใน ${Date.now()-t0} ms`);
if($0('#pickErr') && !$0('#pickErr').hidden) console.log('ERROR BOX:',$0('#pickErr').textContent);
const ds=w.DX.datasets();
for(const id in ds) console.log(`  ${id}: ${ds[id].rows.length.toLocaleString()} แถว`);

const $=s=>w.document.querySelector(s);
console.log('\nหน้าเลือกโฟลเดอร์ถูกเอาออก:', !$('#pick'));
console.log('ชื่อรายงาน :', $('#title')?.textContent);
console.log('ขอบเขต     :', $('#scope')?.textContent);
console.log('กลุ่มอายุ   :', [...$('#selProfile').options].map(o=>o.textContent).join(' | '));
console.log('\nการ์ดสรุป:');
w.document.querySelectorAll('#cards .card').forEach(c=>
  console.log('  ',c.querySelector('.k')?.textContent.trim(),'=',c.querySelector('.v')?.textContent.trim()));
const tabs=[...w.document.querySelectorAll('button.tab')].map(b=>b.querySelector('b').textContent);
console.log('\nแท็บ:', tabs.join(' | '));
console.log('มีแท็บ EDA/ถาม-ตอบ หลงเหลือ:', tabs.some(t=>/สำรวจ|ถาม/.test(t)));
const rows=w.document.querySelectorAll('.pane[data-tab=overview] tbody tr');
console.log('\nตารางภาพรวม:',rows.length,'แถว');
[...rows].slice(0,3).forEach(tr=>console.log('  ',[...tr.children].slice(0,6).map(td=>td.textContent.trim()).join(' | ')));


/* ---- คลิกแท็บตารางที่ 2 ---- */
const tabBtns=[...w.document.querySelectorAll('button.tab')];
const t2=tabBtns.find(b=>b.querySelector('b').textContent.includes('ตารางที่ 2'));
if(!t2){ console.log('\n(ไม่พบแท็บตารางที่ 2)'); process.exit(1); }
t2.onclick(); await new Promise(r=>setTimeout(r,200));
const pane=$('.pane[data-tab=t2]');
console.log('\nตารางที่ 2:', pane.querySelectorAll('tbody tr').length,'แถว');
const head=[...pane.querySelectorAll('thead tr')].map(tr=>[...tr.children].map(c=>c.textContent.trim()).join(' | '));
head.forEach(h=>console.log('  หัว:',h.slice(0,110)));
const r1=pane.querySelector('tbody tr');
console.log('  แถวแรก:',[...r1.children].map(c=>c.textContent.trim()).slice(0,8).join(' | '));

/* ---- คลิกตัวเลขเพื่อดูรายชื่อเด็ก ---- */
const clickable=pane.querySelector('td.clickme, td[data-met]');
console.log('\nช่องที่คลิกได้:', clickable? clickable.getAttribute('data-met')||'(มี)':'ไม่พบ');
if(clickable){
  clickable.click(); await new Promise(r=>setTimeout(r,500));
  const m=$('#modal')||$('.sheet');
  console.log('  หัวข้อรายชื่อ:', ($('#mTitle')||{}).textContent);
  console.log('  จำนวนที่แสดง:', ($('#mCount')||{}).textContent);
  const mrows=w.document.querySelectorAll('.mbody tbody tr');
  console.log('  แถวในตารางรายชื่อ:', mrows.length);
  if(mrows[0]) console.log('  ตัวอย่าง:', [...mrows[0].children].slice(0,4).map(c=>c.textContent.trim()).join(' | '));
}

/* ---- ส่งออก Excel ---- */
let saved=null;
w.URL.createObjectURL=b=>{saved=b;return 'blob:x';};
w.URL.revokeObjectURL=()=>{};
w.HTMLAnchorElement.prototype.click=function(){};
const xp=w.document.querySelector('#topExport button[data-xp]');
console.log('\nปุ่มบันทึกรายงาน:', xp? xp.textContent.trim():'ไม่พบ');
if(xp){ xp.onclick(); await new Promise(r=>setTimeout(r,300));
  console.log('  สร้างไฟล์ได้:', saved? (saved.size||saved.length)+' ไบต์':'ไม่สำเร็จ'); }

/* ---- เบราว์เซอร์จำรายงานล่าสุด (ตัวเลขสรุปเท่านั้น) ---- */
const last=w.DX.loadLast();
console.log('\nจำรายงานล่าสุด:', last? last.profile.label+' ตรวจแล้ว '+last.summary.examined:'ไม่มี');
const blob=JSON.stringify(last||{});
console.log('  มีข้อมูลรายบุคคลปนไหม:', /cid|เลขบัตร|lname|\bname\b/.test(blob)?'มี!!':'ไม่มี');

/* ---- แท็บสำรวจข้อมูล (EDA) ---- */
const edaBtn=[...w.document.querySelectorAll('button.tab')]
  .find(b=>b.querySelector('b').textContent.includes('สำรวจข้อมูล'));
console.log('\nแท็บสำรวจข้อมูล:', edaBtn? 'มี':'ไม่มี');
if(edaBtn){
  edaBtn.onclick(); await new Promise(r=>setTimeout(r,1500));
  const ep=$('.pane[data-tab=eda]');
  const txt=ep.textContent;
  console.log('  กฎตรวจค่าผิดปกติ:', ep.querySelectorAll('table tbody tr').length, 'แถว');
  console.log('  มีหัวข้อครบ:', ['ค่าผิดปกติ','การกระจาย','ความถี่','เทียบ']
    .filter(k=>txt.includes(k)).length, '/ 4');
  console.log('  มีกราฟ (svg):', ep.querySelectorAll('svg').length, 'รูป');
  const card=ep.querySelector('[data-col]')||ep.querySelector('td.clickme');
  if(card){ card.click(); await new Promise(r=>setTimeout(r,600));
    console.log('  คลิกการ์ด -> รายชื่อ:', w.document.querySelectorAll('.mbody tbody tr').length,'แถว'); }
}
