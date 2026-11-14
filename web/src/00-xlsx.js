/* =============================================================================
 * อ่านไฟล์ Excel (.xlsx) ในเบราว์เซอร์ — ไม่ใช้ไลบรารีภายนอกเลย
 *
 * ยกมาจากโครงการพี่น้อง ohsp-data-ex (src/webapp/core.js) ซึ่งใช้งานจริงแล้ว
 * แก้จุดเดียวคือให้คืน "ทุกคอลัมน์" แทนที่จะคัดเฉพาะที่ใช้คำนวณ
 * เพราะ DentalDX อ้างคอลัมน์ตาม profile YAML และต้องโชว์ฟิลด์ต้นฉบับได้
 *
 * แตก zip ด้วย DecompressionStream ที่มากับเบราว์เซอร์ และอ่าน XML แบบสตรีม
 * จึงไม่ต้องฝังไลบรารีขนาดเป็นเมกะไบต์
 * ========================================================================== */
(function (root) {
'use strict';

const NA_VALUES = new Set(['', '<na>', 'na', 'nan', 'none', 'null', '-']);
const THAI0 = 0x0E50;

class UserError extends Error {
  constructor(title, hints) {
    super(title);
    this.title = title;
    this.hints = hints || [];
    this.isUserError = true;
  }
}

/* ======================================================================
 * 1) อ่านไฟล์ zip
 * ==================================================================== */
function u16(b, o) { return b[o] | (b[o + 1] << 8); }
function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }

function readZipDirectory(buf) {
  const b = new Uint8Array(buf);
  let eocd = -1;
  for (let i = b.length - 22; i >= Math.max(0, b.length - 65557); i--) {
    if (b[i] === 0x50 && b[i + 1] === 0x4b && b[i + 2] === 0x05 && b[i + 3] === 0x06) { eocd = i; break; }
  }
  if (eocd < 0) throw new UserError('ไฟล์นี้ไม่ใช่ไฟล์ Excel (.xlsx) หรือไฟล์เสียหาย');
  let count = u16(b, eocd + 10);
  let off = u32(b, eocd + 16);
  // ZIP64 (ไฟล์ใหญ่มาก)
  if (off === 0xffffffff || count === 0xffff) {
    const loc = eocd - 20;
    if (loc >= 0 && u32(b, loc) === 0x07064b50) {
      const z = Number(new DataView(buf).getBigUint64(loc + 8, true));
      count = Number(new DataView(buf).getBigUint64(z + 32, true));
      off = Number(new DataView(buf).getBigUint64(z + 48, true));
    }
  }
  const dec = new TextDecoder('utf-8');
  const entries = {};
  for (let n = 0; n < count; n++) {
    if (u32(b, off) !== 0x02014b50) break;
    const method = u16(b, off + 10);
    let csize = u32(b, off + 20), usize = u32(b, off + 24);
    const nlen = u16(b, off + 28), xlen = u16(b, off + 30), clen = u16(b, off + 32);
    let lho = u32(b, off + 42);
    const name = dec.decode(b.subarray(off + 46, off + 46 + nlen));
    if (csize === 0xffffffff || usize === 0xffffffff || lho === 0xffffffff) {
      const dv = new DataView(buf);
      let p = off + 46 + nlen, end = p + xlen;
      while (p + 4 <= end) {
        const id = u16(b, p), sz = u16(b, p + 2);
        if (id === 1) {
          let q = p + 4;
          if (usize === 0xffffffff) { usize = Number(dv.getBigUint64(q, true)); q += 8; }
          if (csize === 0xffffffff) { csize = Number(dv.getBigUint64(q, true)); q += 8; }
          if (lho === 0xffffffff) { lho = Number(dv.getBigUint64(q, true)); q += 8; }
        }
        p += 4 + sz;
      }
    }
    entries[name.replace(/^\/+/, '')] = { method, csize, lho };
    off += 46 + nlen + xlen + clen;
  }
  return { buf, b, entries };
}

function findEntry(zip, path) {
  if (zip.entries[path]) return zip.entries[path];
  const low = path.toLowerCase();
  for (const k in zip.entries) if (k.toLowerCase() === low) return zip.entries[k];
  return null;
}

/** คืน ReadableStream ของข้อความ (UTF-8) จากไฟล์ในซิป */
function entryTextStream(zip, entry) {
  const b = zip.b, h = entry.lho;
  if (u32(b, h) !== 0x04034b50) throw new UserError('ไฟล์ Excel เสียหาย (โครงสร้าง zip ไม่ถูกต้อง)');
  const start = h + 30 + u16(b, h + 26) + u16(b, h + 28);
  const data = new Blob([b.subarray(start, start + entry.csize)]);
  let s = data.stream();
  if (entry.method === 8) s = s.pipeThrough(new DecompressionStream('deflate-raw'));
  else if (entry.method !== 0) throw new UserError('ไฟล์ Excel ใช้การบีบอัดแบบที่ไม่รองรับ');
  return s.pipeThrough(new TextDecoderStream('utf-8'));
}

async function entryText(zip, path) {
  const e = findEntry(zip, path);
  if (!e) return null;
  const reader = entryTextStream(zip, e).getReader();
  const parts = [];
  for (;;) { const { done, value } = await reader.read(); if (done) break; parts.push(value); }
  return parts.join('');
}

/* ======================================================================
 * 2) XML
 * ==================================================================== */
const ENT = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };
function unescapeXml(s) {
  if (s.indexOf('&') < 0) return s;
  return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);/g, (m, e) => {
    if (e[0] === '#') {
      const cp = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return String.fromCodePoint(cp);
    }
    return ENT[e] !== undefined ? ENT[e] : m;
  });
}
const ATTR_RE = {};
function attr(tag, name) {
  const re = ATTR_RE[name] || (ATTR_RE[name] = new RegExp('\\s' + name + '\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\')'));
  const m = re.exec(tag);
  return m ? unescapeXml(m[1] !== undefined ? m[1] : m[2]) : null;
}
// ตัด namespace prefix ออก เช่น <x:row> -> <row> (บางโปรแกรมเขียนแบบนี้)
function stripNs(xml) { return /<[a-zA-Z0-9_]+:(row|c|v|is|t|si|r|rPh|sheetData)[\s>/]/.test(xml) ? xml.replace(/<(\/?)[a-zA-Z0-9_]+:/g, '<$1') : xml; }

/** ข้อความของ <si> หรือ <is>: รวม <t> ทั้งหมด ไม่รวมคำอ่าน <rPh> (เหมือน openpyxl) */
function richText(inner) {
  inner = inner.replace(/<rPh\b[\s\S]*?<\/rPh>/g, '');
  let out = '', m;
  const re = /<t(?:\s[^>]*)?>([\s\S]*?)<\/t>|<t(?:\s[^>]*)?\/>/g;
  while ((m = re.exec(inner))) if (m[1] !== undefined) out += m[1];
  return unescapeXml(out.replace(/\r\n?/g, '\n'));
}

async function readSharedStrings(zip, path) {
  const e = path && findEntry(zip, path);
  if (!e) return [];
  const out = [];
  const reader = entryTextStream(zip, e).getReader();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (value) buf += value;
    let last = 0, m;
    const re = /<(?:\w+:)?si\b[^>]*?(?:\/>|>([\s\S]*?)<\/(?:\w+:)?si>)/g;
    while ((m = re.exec(buf))) { out.push(m[1] === undefined ? '' : richText(stripNs(m[1]))); last = re.lastIndex; }
    buf = buf.slice(last);
    if (done) break;
  }
  return out;
}

/* ---------- รูปแบบตัวเลขที่เป็นวันที่ (เทียบ openpyxl.styles.numbers.is_date_format) ---------- */
const BUILTIN_DATE_IDS = new Set([14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47]);
function isDateFormat(code) {
  if (!code) return false;
  let s = code.split(';')[0];
  s = s.replace(/"[^"]*"/g, '').replace(/\\./g, '').replace(/\[[^\]]*\]/g, '');
  return /[dmyhs]/i.test(s);
}
function readDateStyles(xml) {
  const dates = new Set();
  if (!xml) return dates;
  xml = stripNs(xml);
  const custom = {};
  let m;
  const reF = /<numFmt\b[^>]*>/g;
  while ((m = reF.exec(xml))) custom[+attr(m[0], 'numFmtId')] = attr(m[0], 'formatCode');
  const cx = /<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/.exec(xml);
  if (!cx) return dates;
  const reX = /<xf\b[^>]*>/g;
  let i = 0;
  while ((m = reX.exec(cx[1]))) {
    const id = +(attr(m[0], 'numFmtId') || 0);
    if (BUILTIN_DATE_IDS.has(id) || (custom[id] !== undefined && isDateFormat(custom[id]))) dates.add(i);
    i++;
  }
  return dates;
}

/* ======================================================================
 * 3) แปลงค่าให้ได้ข้อความเหมือน str(value) ของ Python
 * ==================================================================== */
const pad = (n, w = 2) => String(n).padStart(w, '0');
/** เลขวันที่ของ Excel -> 'YYYY-MM-DD HH:MM:SS' แบบ str(datetime) ของ Python */
function excelDate(serial, date1904) {
  let days = Math.floor(serial);
  let secs = Math.round((serial - days) * 86400);
  if (secs >= 86400) { days += 1; secs -= 86400; }
  let ms;
  if (date1904) ms = Date.UTC(1904, 0, 1) + days * 864e5;
  else {
    // Excel นับ 29 ก.พ. 1900 ที่ไม่มีจริง (openpyxl ทำแบบเดียวกัน)
    if (days < 60) days += 1;
    ms = Date.UTC(1899, 11, 30) + days * 864e5;
  }
  const d = new Date(ms + secs * 1000);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
         `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}
/** repr(float) ของ Python */
function pyFloatStr(x) {
  if (Number.isNaN(x)) return 'nan';
  if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
  if (Object.is(x, -0)) return '-0.0';
  const a = Math.abs(x);
  if (a >= 1e16 || (a !== 0 && a < 1e-4)) {
    let s = x.toExponential();                              // 1e+21, 1.5e-7
    s = s.replace(/e([+-])(\d)$/, 'e$10$2');               // Python ใช้เลขชี้กำลังอย่างน้อย 2 หลัก
    return s;
  }
  const s = String(x);
  return /[.e]/.test(s) ? s : s + '.0';
}
/** ค่าในเซลล์ตัวเลข -> ข้อความแบบ openpyxl (_cast_number) + str() */
function numberCellStr(v) {
  if (/[.eE]/.test(v)) return pyFloatStr(parseFloat(v));
  const t = v.trim();
  if (!/^[+-]?\d+$/.test(t)) return pyFloatStr(parseFloat(v));
  return BigInt(t).toString();
}

/** ใช้ข้อความชุดเดียวกันซ้ำ (ค่าในคอลัมน์ที่เก็บมีไม่กี่แบบ) ลดหน่วยความจำลงมาก */
const INTERN = new Map();
function intern(s) {
  let v = INTERN.get(s);
  if (v === undefined) {
    v = s.length > 200 ? s : Array.from(s).join('');      // คัดลอกเพื่อไม่ให้ค้างอ้างอิงข้อความ XML ทั้งก้อน
    if (INTERN.size < 200000) INTERN.set(v, v);
  }
  return v;
}

/* ======================================================================
 * 4) อ่านแผ่นงาน
 * ==================================================================== */
function colIndex(ref) {
  let n = 0;
  for (let i = 0; i < ref.length; i++) {
    const c = ref.charCodeAt(i);
    if (c >= 65 && c <= 90) n = n * 26 + (c - 64);
    else if (c >= 97 && c <= 122) n = n * 26 + (c - 96);
    else break;
  }
  return n - 1;
}

/**
 * อ่านไฟล์ .xlsx หนึ่งไฟล์ คืนทุกคอลัมน์ตามลำดับหัวตาราง
 * @returns {{rows: string[][], header: string[], sheet: string, width: number}}
 */
async function parseXlsx(buf, onProgress) {
  const zip = readZipDirectory(buf);
  const wbXml = await entryText(zip, 'xl/workbook.xml');
  if (!wbXml) throw new UserError('ไฟล์นี้ไม่ใช่ไฟล์ Excel (.xlsx) หรือไฟล์เสียหาย');
  const wb = stripNs(wbXml);
  const date1904 = /<workbookPr\b[^>]*\bdate1904\s*=\s*["'](1|true)["']/.test(wb);
  const relsXml = (await entryText(zip, 'xl/_rels/workbook.xml.rels')) || '';
  const rels = {};
  let m;
  const reR = /<(?:\w+:)?Relationship\b[^>]*>/g;
  while ((m = reR.exec(relsXml))) rels[attr(m[0], 'Id')] = { target: attr(m[0], 'Target'), type: attr(m[0], 'Type') || '' };
  const resolve = t => (t[0] === '/' ? t.slice(1) : 'xl/' + t).replace(/[^/]+\/\.\.\//g, '');

  const sheets = [];
  const reS = /<sheet\b[^>]*>/g;
  while ((m = reS.exec(wb))) {
    const rid = attr(m[0], 'r:id') || attr(m[0], 'id');
    if (rels[rid]) sheets.push({ name: attr(m[0], 'name'), path: resolve(rels[rid].target) });
  }
  if (!sheets.length) throw new UserError('ไม่พบแผ่นงานในไฟล์ Excel');
  const sheet = sheets.find(s => s.name === 'Data') || sheets[0];

  let sstPath = null, stylesPath = null;
  for (const id in rels) {
    if (/\/sharedStrings$/.test(rels[id].type)) sstPath = resolve(rels[id].target);
    if (/\/styles$/.test(rels[id].type)) stylesPath = resolve(rels[id].target);
  }
  const sst = await readSharedStrings(zip, sstPath || 'xl/sharedStrings.xml');
  const dateStyles = readDateStyles(await entryText(zip, stylesPath || 'xl/styles.xml'));

  const entry = findEntry(zip, sheet.path);
  if (!entry) throw new UserError('ไฟล์ Excel เสียหาย (ไม่พบแผ่นงาน ' + sheet.name + ')');

  const cellValue = (tag, inner) => {
    const t = attr(tag, 't') || 'n';
    if (t === 'inlineStr') {
      const is = /<is\b[^>]*>([\s\S]*?)<\/is>/.exec(inner);
      return is ? richText(is[1]) : null;
    }
    const vm = /<v\b[^>]*>([\s\S]*?)<\/v>|<v\b[^>]*\/>/.exec(inner);
    if (!vm) return null;
    const v = vm[1] === undefined ? '' : vm[1];
    if (t === 's') { const s = sst[parseInt(v, 10)]; return s === undefined ? null : s; }
    if (t === 'str' || t === 'e') return unescapeXml(v);
    if (t === 'b') return parseInt(v, 10) ? 'True' : 'False';
    if (t === 'd') return unescapeXml(v).replace('T', ' ');
    if (v === '') return null;
    const s = +(attr(tag, 's') || 0);
    if (dateStyles.has(s)) return excelDate(parseFloat(v), date1904);
    return numberCellStr(v);
  };

  let header = null, dsAt = -1, width = 0;
  const rows = [];
  const reCell = /<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g;
  const handleRow = inner => {
    const vals = [];
    let next = 0, cm, any = false;
    reCell.lastIndex = 0;
    while ((cm = reCell.exec(inner))) {
      const tag = ' ' + cm[1];
      const r = attr(tag, 'r');
      const ci = r ? colIndex(r) : next;
      next = ci + 1;
      const v = cm[2] === undefined ? null : cellValue(tag, cm[2]);
      if (v !== null) { vals[ci] = v; any = true; }
    }
    if (header === null) {
      header = [];
      for (let i = 0; i < vals.length; i++) header.push(vals[i] == null ? '' : String(vals[i]).trim().toLowerCase());
      width = header.length;
      // DentalDX อ่านทุกคอลัมน์ เพราะ profile YAML อ้างคอลัมน์ไหนก็ได้
      // และหน้ารายชื่อเด็กต้องโชว์ฟิลด์ต้นฉบับให้ตรวจย้อนได้
      dsAt = header.indexOf('date_serv');
      return;
    }
    if (!any) return;                                     // แถวว่างทั้งแถว
    const row = new Array(width);
    for (let i = 0; i < width; i++) row[i] = vals[i] == null ? '' : intern(vals[i]);
    rows.push(row);
  };

  const reader = entryTextStream(zip, entry).getReader();
  let buf2 = '', seen = 0, started = false;
  const reRow = /<row\b[^>]*?(?:\/>|>([\s\S]*?)<\/row>)/g;
  for (;;) {
    const { done, value } = await reader.read();
    if (value) { buf2 += value; seen += value.length; }
    if (!started) {
      const i = buf2.search(/<(?:\w+:)?sheetData\b/);
      if (i < 0 && !done) continue;
      started = true;
      if (i > 0) buf2 = buf2.slice(i);
    }
    const chunk = /<\w+:row\b/.test(buf2.slice(0, 4000)) ? stripNs(buf2) : buf2;
    let last = 0, rm;
    reRow.lastIndex = 0;
    while ((rm = reRow.exec(chunk))) {
      if (rm[1] !== undefined) handleRow(rm[1]);
      else if (header === null) handleRow('');
      last = reRow.lastIndex;
    }
    buf2 = chunk.slice(last);
    if (onProgress) onProgress(rows.length, seen);
    if (done) break;
  }
  if (header === null) throw new UserError('ไฟล์ว่าง ไม่มีข้อมูล');
  return { rows, header, sheet: sheet.name, width };
}

/* ======================================================================
 * 5) กลุ่มอายุ
 * ==================================================================== */

/** เลขไทย ๐-๙ -> 0-9 (ไฟล์จาก HDC บางเครื่องส่งมาเป็นเลขไทย) */
function toAsciiDigits(s) {
  return String(s).replace(/[\u0E50-\u0E59]/g, c => String(c.charCodeAt(0) - THAI0));
}

root.Xlsx = { parseXlsx, UserError, NA_VALUES, toAsciiDigits,
              _t: { excelDate, pyFloatStr, numberCellStr, isDateFormat, colIndex, intern } };
})(typeof globalThis !== 'undefined' ? globalThis : this);
