// เทียบผลคำนวณฝั่งเว็บ (web/src/*.js) กับผลจากเวอร์ชัน Python เดิม ทีละค่า
//
//   node web/parity_test.mjs <data dir> <profiles dir> <hospitals.csv> [python_ref.json]
//
// ไม่มี python_ref.json = แค่คำนวณแล้วเขียนผลออก (ใช้ดูว่าอ่านไฟล์ได้ไหม)
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const [dataDir, profDir, hospPath, refPath] = process.argv.slice(2);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, 'src');

const g = globalThis;
for (const f of ['00-xlsx.js', '01-expr.js', '02-data.js', '03-engine.js',
                 '04-service.js', '05-yaml.js'])
  eval(fs.readFileSync(path.join(SRC, f), 'utf8'));
const {Xlsx: X, DataIO: D, Engine: EN, Service: S, Yaml: Y} = g;

/** โหลดข้อมูลของ profile หนึ่งชุดจากโฟลเดอร์ data/<กลุ่ม>/ */
async function loadProfile(p, folder, hospitals) {
  let rows = [], header = null;
  const files = fs.readdirSync(folder)
    .filter(f => /\.xlsx$/i.test(f) && !f.startsWith('~$')).sort();
  for (const name of files) {
    const buf = fs.readFileSync(path.join(folder, name));
    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const t0 = Date.now();
    const parsed = await X.parseXlsx(ab);
    if (!header) header = parsed.header.slice();
    const objs = new Array(parsed.rows.length);
    for (let i = 0; i < parsed.rows.length; i++) {
      const o = {};
      for (let c = 0; c < parsed.header.length; c++) o[parsed.header[c]] = parsed.rows[i][c];
      objs[i] = o;
    }
    console.log(`  ${p.id}/${name}: ${parsed.rows.length.toLocaleString()} แถว ` +
                `${parsed.header.length} คอลัมน์ (${Date.now() - t0} ms)`);
    rows = rows.concat(D.normalizeRows(objs, name));
  }
  D.applyFilenameRules(rows, p.filename_columns);
  D.attachArea(rows, hospitals);
  D.prepare(rows);
  return {rows, header: header || []};
}

const hospitals = D.loadHospitals(D.decodeText(fs.readFileSync(hospPath)));
const got = {};
for (const pf of fs.readdirSync(profDir).filter(f => /\.ya?ml$/.test(f)).sort()) {
  const spec = Y.load(fs.readFileSync(path.join(profDir, pf), 'utf8'));
  if (!spec || !spec.id) continue;
  const p = new EN.Profile(spec);
  const folder = path.join(dataDir, spec.data_folder || p.id);
  if (!fs.existsSync(folder)) { console.log('ข้าม', p.id, '(ไม่มีโฟลเดอร์ข้อมูล)'); continue; }

  const ds = await loadProfile(p, folder, hospitals);
  const scope = {pv: null, amp: null, hos: null};
  const rep = S.report(ds, p, scope);
  const pend = S.personList(ds, p, 'pending', scope, false);
  const fail = S.personList(ds, p, 'failed', scope, false);

  const clicks = {};
  for (const t of rep.tables) {
    for (const met of (t.followup || [])) {
      const labels = t.rows.map(r => String(r.row));
      for (const lab of [...new Set([...labels.slice(0, 2), labels[labels.length - 1]])])
        clicks[`${t.no}|${met}|${lab}`] =
          S.metricList(ds, p, t.no, met, lab, scope, false).rows.length;
    }
  }
  got[p.id] = {
    summary: rep.summary, districts: rep.districts,
    tables: rep.tables.map(t => ({
      no: t.no, columns: t.columns,
      rows: t.rows.map(r => { const o = {}; for (const k in r) if (k !== '_sub' && k !== '_parent') o[k] = r[k]; return o; })
    })),
    pending_n: pend.rows.length, failed_n: fail.rows.length,
    pending_cols: pend.columns, failed_cols: fail.columns.filter(c => c !== '_bad'),
    clicks
  };
  console.log(`${p.id}: ยังไม่ตรวจ ${pend.rows.length.toLocaleString()} | ` +
              `ไม่ผ่านเกณฑ์ ${fail.rows.length.toLocaleString()}`);
}

if (!refPath) {
  console.log('\n(ไม่ได้ส่งไฟล์อ้างอิงมา จึงไม่ได้เทียบ)');
  process.exit(0);
}

const py = JSON.parse(fs.readFileSync(refPath, 'utf8'));
let checked = 0, diffs = 0;
const show = [];
const fail2 = (what, a, b) => {
  diffs++;
  if (show.length < 20) show.push(`${what}: python=${JSON.stringify(a)} js=${JSON.stringify(b)}`);
};
const eq = (a, b) => (a === null && b === null) ||
  (typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-9 : a === b);

for (const pid of Object.keys(py)) {
  const P = py[pid], J = got[pid];
  if (!J) { fail2(`${pid}`, 'มีผล', 'ไม่มีผล'); continue; }

  for (const k of Object.keys(P.summary)) {
    checked++;
    if (!eq(P.summary[k], J.summary[k])) fail2(`${pid} summary.${k}`, P.summary[k], J.summary[k]);
  }
  for (const k of ['pending_n', 'failed_n']) {
    checked++;
    if (P[k] !== J[k]) fail2(`${pid} ${k}`, P[k], J[k]);
  }
  for (const k of ['pending_cols', 'failed_cols']) {
    checked++;
    if (JSON.stringify(P[k]) !== JSON.stringify(J[k]))
      fail2(`${pid} ${k}`, P[k].join(','), (J[k] || []).join(','));
  }

  if (P.districts.length !== J.districts.length) fail2(`${pid} จำนวนอำเภอ`, P.districts.length, J.districts.length);
  P.districts.forEach((d, i) => {
    const q = J.districts[i] || {};
    for (const k of Object.keys(d)) {
      checked++;
      if (!eq(d[k], q[k])) fail2(`${pid} อำเภอ ${d.name}.${k}`, d[k], q[k]);
    }
  });

  P.tables.forEach((pt, ti) => {
    const jt = J.tables[ti] || {rows: []};
    pt.rows.forEach((pr, ri) => {
      const jr = jt.rows[ri] || {};
      for (const k of Object.keys(pr)) {
        if (k === 'row') continue;
        checked++;
        if (!eq(pr[k], jr[k])) fail2(`${pid} ตารางที่ ${pt.no} แถว "${pr.row}" [${k}]`, pr[k], jr[k]);
      }
    });
  });

  for (const k of Object.keys(P.clicks)) {
    checked++;
    if (P.clicks[k] !== J.clicks[k]) fail2(`${pid} คลิก ${k}`, P.clicks[k], J.clicks[k]);
  }
}

show.forEach(s => console.log('  ✗', s));
console.log(diffs
  ? `\nไม่ตรงกัน ${diffs} จุด (ตรวจ ${checked.toLocaleString()} ค่า)`
  : `\nตรงกันทุกค่า: ${checked.toLocaleString()} ค่า`);
process.exit(diffs ? 1 : 0);
