/* ทดสอบค่าผิดรูปแบบที่พบจริงจากไฟล์ HDC และไฟล์ขนาดใหญ่
 *
 *   python web/make_test_data.py /tmp/big --rows 40 --big 100000
 *   BIG_XLSX="/tmp/big/big/sample big.xlsx" node web/edge_test.mjs
 *
 * หลักการ: ค่าที่โปรแกรมเดิม (pandas) อ่านไม่ออก ฝั่งเว็บต้องอ่านไม่ออกเหมือนกัน
 * ห้าม "ฉลาดกว่า" ไม่งั้นตัวเลขรายงานจะไม่ตรงกับเวอร์ชันก่อนหน้า
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const g = globalThis;
for (const f of ['00-xlsx.js', '01-expr.js', '02-data.js', '03-engine.js'])
  eval(fs.readFileSync(path.join(HERE, 'src', f), 'utf8'));
const {Xlsx: X, DataIO: D} = g;

async function read(p) {
  const b = fs.readFileSync(p);
  const ab = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
  const t0 = Date.now();
  const r = await X.parseXlsx(ab);
  return {r, ms: Date.now() - t0};
}

function toObjects(parsed, name) {
  return D.normalizeRows(parsed.rows.map(row => {
    const o = {};
    parsed.header.forEach((h, i) => (o[h] = row[i]));
    return o;
  }), name);
}

let bad = 0;
const check = (name, got, want) => {
  const ok = Object.is(got, want) || (got === want);
  if (!ok) bad++;
  console.log((ok ? 'ok  ' : 'MISS') + ' ' + name.padEnd(42) +
              ' ได้ ' + JSON.stringify(got) +
              (ok ? '' : ' (ควรเป็น ' + JSON.stringify(want) + ')'));
};

/* ---- ค่าเดี่ยว ๆ: ต้องตีความเหมือน pandas ---- */
console.log('ค่าตัวเลข (ต้องเหมือน pandas.to_numeric)');
check('"  1  " ช่องว่างหน้าหลัง', D.toNum('  1  '), 1);
check('"02 " รหัสมีช่องว่างท้าย', D.toNum('02 '), 2);
check('"๒" เลขไทย -> ค่าว่าง', D.toNum('๒'), null);
check('"20 ซี่" ตัวเลขปนข้อความ -> ค่าว่าง', D.toNum('20 ซี่'), null);
check('"1,234" มีลูกน้ำ -> ค่าว่าง', D.toNum('1,234'), null);
check('"<NA>" -> ค่าว่าง', D.toNum(''), null);

console.log('\nวันที่ (ต้องเหมือน pandas.to_datetime)');
const iso = D.parseDate('2026-01-15');
check('"2026-01-15"', iso && iso.toISOString().slice(0, 10), '2026-01-15');
const dmy = D.parseDate('15/01/2026');
check('"15/01/2026"', dmy && dmy.toISOString().slice(0, 10), '2026-01-15');
check('"2564-03-05" ปี พ.ศ. -> ค่าว่าง', D.parseDate('2564-03-05'), null);
check('"31/02/2026" วันที่ไม่มีจริง -> ค่าว่าง', D.parseDate('31/02/2026'), null);

/* ---- ทั้งคอลัมน์: pandas เดารูปแบบจากค่าแรก ---- */
console.log('\nทั้งคอลัมน์ — แถวที่เขียนคนละรูปแบบต้องเป็นค่าว่าง');
const mixed = D.normalizeRows([
  {date_serv: '2026-01-15'}, {date_serv: '15/01/2026'}, {date_serv: '2026-02-20'}
], 'x');
check('แถวที่ 1 (รูปแบบหลัก)', !!mixed[0].date_serv, true);
check('แถวที่ 2 (คนละรูปแบบ)', mixed[1].date_serv, null);
check('แถวที่ 3 (รูปแบบหลัก)', !!mixed[2].date_serv, true);

/* ---- ไฟล์ตัวอย่างที่มีค่าแปลกปน ---- */
const sampleDir = process.env.SAMPLE_DIR || '/tmp/big';
const sample = path.join(sampleDir, '0-5y', 'sample 0-2.xlsx');
if (fs.existsSync(sample)) {
  console.log('\nอ่านไฟล์ตัวอย่างที่มีค่าแปลกปน');
  const {r} = await read(sample);
  const rows = D.prepare(toObjects(r, 'sample'));
  console.log('  อ่านได้ ' + rows.length + ' แถว ' + r.header.length + ' คอลัมน์');
  const issues = D.issues();
  if (issues.length) {
    console.log('  ค่าที่อ่านไม่ออก (โปรแกรมจะเตือนผู้ใช้):');
    issues.forEach(i => console.log('    - ' + i.kind + ' ' + i.n + ' ครั้ง เช่น ' +
      JSON.stringify(i.samples.slice(0, 3))));
  }
  check('ไม่มีแถวไหนทำให้คำนวณพัง', rows.every(x => 'examined' in x), true);
}

/* ---- ไฟล์ขนาดใหญ่ ---- */
const big = process.env.BIG_XLSX;
if (big && fs.existsSync(big)) {
  console.log('\nไฟล์ขนาดใหญ่');
  const {r, ms} = await read(big);
  console.log('  อ่าน ' + r.rows.length.toLocaleString() + ' แถว ใน ' + ms + ' ms');
  const t1 = Date.now();
  const rows = D.prepare(toObjects(r, 'big'));
  const mb = Math.round(process.memoryUsage().heapUsed / 1048576);
  console.log('  แปลง+คำนวณคอลัมน์ ' + (Date.now() - t1) + ' ms | หน่วยความจำ ' + mb + ' MB');
  check('อ่านครบทุกแถว', rows.length, r.rows.length);
  if (ms > 60000) { console.log('  ! ช้าเกินไป'); bad++; }
} else {
  console.log('\n(ข้ามการทดสอบไฟล์ขนาดใหญ่ — ไม่ได้ตั้ง BIG_XLSX)');
}

console.log(bad ? '\nพลาด ' + bad + ' ข้อ' : '\nผ่านหมด');
process.exit(bad ? 1 : 0);
