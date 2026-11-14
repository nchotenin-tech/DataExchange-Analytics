/* =============================================================================
 * อ่าน + ทำความสะอาดข้อมูล  (พอร์ตจาก core/loader.py และ core/derive.py)
 * ========================================================================== */
(function (root) {
  'use strict';

  var NA_TOKENS = ['<NA>', '<null>', '<NULL>', 'NULL', 'null', 'NaN', 'nan', '', '-'];

  var NUMERIC_COLS = [
    'pteeth', 'pcaries', 'pfilling', 'pextract',
    'dteeth', 'dcaries', 'dfilling', 'dextract',
    'need_fluoride', 'need_scaling', 'need_sealant',
    'need_pfilling', 'need_dfilling', 'need_pextract', 'need_dextract',
    'nprosthesis', 'permanent_permanent', 'permanent_prosthesis',
    'prosthesis_prosthesis'
  ];

  // รหัสที่มีเลข 0 นำหน้า ห้ามแปลงเป็นตัวเลข ("02" ต้องไม่กลายเป็น 2)
  var CODE_COLS = ['hoscode', 'pid', 'cid', 'sex', 'denttype', 'servplace',
                   'gum', 'schooltype', 'class', 'provider', 'providertype'];

  var DATE_COLS = ['date_serv', 'birth', 'd_update'];

  // ไฟล์จาก HDC บางเครื่องส่งเลขมาเป็นเลขไทย ๐-๙ ต้องแปลงก่อนคำนวณ
  var THAI0 = 0x0E50;
  function toAsciiDigits(s) {
    return String(s).replace(/[๐-๙]/g, function (c) {
      return String(c.charCodeAt(0) - THAI0);
    });
  }

  function cleanNA(v) {
    if (v === null || v === undefined) return null;
    var s = String(v);
    var t = s.trim();
    // ถ้าไม่ได้ตัดอะไรเลย คืนตัวเดิม — ตัวอ่าน xlsx ทำ intern ไว้แล้ว
    // ข้อความซ้ำ ๆ (รหัสหน่วยบริการ ชื่ออำเภอ) จึงใช้หน่วยความจำก้อนเดียว
    if (t === s) return NA_TOKENS.indexOf(t) >= 0 ? null : v;
    return NA_TOKENS.indexOf(t) >= 0 ? null : t;
  }

  /**
   * แปลงเป็นวันที่ — ต้องให้ผลเหมือน pandas.to_datetime(errors="coerce")
   *   "2026-01-15" และ "15/01/2026" -> 15 ม.ค. 2026
   *   "2564-03-05" (ปี พ.ศ.) -> ค่าว่าง  เพราะ pandas เก็บปีเกิน 2262 ไม่ได้
   *
   * ไม่แปลง พ.ศ. เป็น ค.ศ. ให้เอง ถึงแม้จะเดาได้ — เพราะจะทำให้ยอดผู้รับการตรวจ
   * ไม่ตรงกับรายงานเดิม ถ้าไฟล์มีปี พ.ศ. จริงต้องไปแก้ที่ต้นทาง
   */
  function parseDate(v) {
    if (v === null || v === undefined || v === '') return null;
    if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
    var s = String(v).trim();
    if (!s) return null;

    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]|$)/.exec(s);
    if (m) return mkDate(+m[1], +m[2], +m[3], s);

    m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:[ T]|$)/.exec(s);
    if (m) return mkDate(+m[3], +m[2], +m[1], s);

    if (/^\d+(\.\d+)?$/.test(s)) {         // serial number ของ Excel
      var n = parseFloat(s);
      if (n > 0 && n < 100000) {
        var d = new Date(Date.UTC(1899, 11, 30) + Math.floor(n) * 86400000);
        return isNaN(d.getTime()) ? null : d;
      }
    }
    noteIssue('วันที่อ่านไม่ออก', s);
    return null;
  }

  // ขอบเขตที่ pandas (datetime64[ns]) เก็บได้ — นอกช่วงนี้ของเดิมถือเป็นค่าว่าง
  var PD_MIN = Date.UTC(1677, 8, 21), PD_MAX = Date.UTC(2262, 3, 11);

  function mkDate(y, mo, da, raw) {
    if (mo < 1 || mo > 12 || da < 1 || da > 31) {
      noteIssue('วันที่อ่านไม่ออก', raw);
      return null;
    }
    var ms = Date.UTC(y, mo - 1, da);
    if (isNaN(ms) || ms < PD_MIN || ms > PD_MAX) {
      noteIssue(y > 2400 ? 'วันที่เป็นปี พ.ศ. (ต้องแก้ที่ต้นทาง)' : 'วันที่อ่านไม่ออก', raw);
      return null;
    }
    var d = new Date(ms);
    // กันวันที่ที่ไม่มีจริง เช่น 31/02 ซึ่ง Date จะเลื่อนไปเดือนถัดไปให้เอง
    if (d.getUTCMonth() !== mo - 1 || d.getUTCDate() !== da) {
      noteIssue('วันที่อ่านไม่ออก', raw);
      return null;
    }
    return d;
  }

  /**
   * แปลงเป็นตัวเลข — ต้องให้ผลเหมือน pandas.to_numeric(errors="coerce") เป๊ะ
   *
   * สำคัญ: ห้าม "ฉลาดกว่า" ของเดิม ค่าที่ pandas อ่านไม่ออกต้องเป็นค่าว่างเหมือนกัน
   * ไม่งั้นตัวเลขในรายงานราชการจะไม่ตรงกับเวอร์ชันก่อนหน้าโดยที่ไม่มีใครรู้ตัว
   *   "๒" (เลขไทย) -> ว่าง   "20 ซี่" -> ว่าง   "1,234" -> ว่าง
   *   "  1  " -> 1           "02 " -> 2
   * ค่าที่อ่านไม่ออกจะถูกนับไว้เตือนผู้ใช้ใน DataIO.issues แทน
   */
  function toNum(v) {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'number') return isNaN(v) ? null : v;
    var s = String(v).trim();
    if (s === '') return null;
    if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) {
      noteIssue('ตัวเลขอ่านไม่ออก', s);
      return null;
    }
    var n = Number(s);
    return isNaN(n) ? null : n;
  }

  // ---- รายการค่าที่อ่านไม่ออก (ไว้เตือนผู้ใช้ ไม่ได้เปลี่ยนผลคำนวณ) ----------
  var ISSUES = {};

  function noteIssue(kind, sample) {
    var k = ISSUES[kind] || (ISSUES[kind] = {kind: kind, n: 0, samples: []});
    k.n++;
    if (k.samples.length < 5 && k.samples.indexOf(sample) < 0) k.samples.push(sample);
  }

  function issues() {
    return Object.keys(ISSUES).map(function (k) { return ISSUES[k]; });
  }

  function clearIssues() { ISSUES = {}; }

  function dateShape(s) {
    if (/^\d{4}-\d{1,2}-\d{1,2}(?:[ T]|$)/.test(s)) return 'iso';
    if (/^\d{1,2}\/\d{1,2}\/\d{4}(?:[ T]|$)/.test(s)) return 'dmy';
    if (/^\d+(\.\d+)?$/.test(s)) return 'serial';
    return null;
  }

  /**
   * ทำให้ชื่อคอลัมน์และชนิดข้อมูลเป็นมาตรฐานเดียวกัน (เท่ากับ loader.normalize)
   *
   * วันที่: pandas เดารูปแบบจาก "ค่าแรกที่ไม่ว่างของทั้งคอลัมน์" แล้วใช้รูปแบบนั้น
   * กับทุกแถว แถวที่เขียนคนละแบบจึงกลายเป็นค่าว่าง — ต้องทำเหมือนกัน ไม่งั้น
   * ยอดผู้ได้รับการตรวจจะไม่ตรงกับรายงานเดิม
   */
  function normalizeRows(rawRows, sourceFile) {
    var out = new Array(rawRows.length), i, d, dc;

    for (i = 0; i < rawRows.length; i++) {
      var src = rawRows[i], row = {};
      for (var key in src) {
        if (!Object.prototype.hasOwnProperty.call(src, key)) continue;
        row[String(key).trim().toLowerCase()] = cleanNA(src[key]);
      }
      for (var n = 0; n < NUMERIC_COLS.length; n++) {
        var c = NUMERIC_COLS[n];
        if (c in row) row[c] = toNum(row[c]);
      }
      row._source_file = sourceFile;
      out[i] = row;
    }

    for (d = 0; d < DATE_COLS.length; d++) {
      dc = DATE_COLS[d];
      var shape = null;
      for (i = 0; i < out.length; i++) {
        var v0 = out[i][dc];
        if (v0 !== null && v0 !== undefined && v0 !== '') {
          shape = dateShape(String(v0).trim());
          break;
        }
      }
      for (i = 0; i < out.length; i++) {
        if (!(dc in out[i])) continue;
        var v = out[i][dc];
        if (v === null || v === undefined || v === '') { out[i][dc] = null; continue; }
        var s = String(v).trim();
        if (shape && dateShape(s) !== shape) {
          noteIssue('วันที่คนละรูปแบบกับคอลัมน์ (ถือเป็นค่าว่าง)', s);
          out[i][dc] = null;
          continue;
        }
        out[i][dc] = parseDate(s);
      }
    }
    return out;
  }

  /** สร้างคอลัมน์จากชื่อไฟล์ เช่น "...0-2 ปี.xlsx" -> agegroup = a0-2 */
  function applyFilenameRules(rows, specs) {
    if (!specs || !specs.length) return rows;
    for (var s = 0; s < specs.length; s++) {
      var spec = specs[s], col = spec.column;
      if (!col) continue;
      var rules = spec.rules || [], overwrite = !!spec.overwrite;
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var have = Object.prototype.hasOwnProperty.call(row, col) ? row[col] : null;
        if (have !== null && have !== undefined && have !== '' && !overwrite) continue;
        var file = String(row._source_file || '').toLowerCase();
        var val = spec['default'] === undefined ? null : spec['default'];
        for (var r = 0; r < rules.length; r++) {
          var needle = String(rules[r].contains || '').toLowerCase();
          if (needle && file.indexOf(needle) >= 0) { val = rules[r].value; break; }
        }
        row[col] = val;
      }
    }
    return rows;
  }

  // ---- คอลัมน์ที่คำนวณต่อ (derive.py) --------------------------------------

  var GUM_CODES = ['0', '1', '2', '3', '9'];
  var GUM_LABELS = {
    '0': 'ปกติ', '1': 'เลือดออก', '2': 'เหงือกอักเสบ/หินน้ำลาย',
    '3': 'ปริทันต์อักเสบ', '9': 'ตรวจไม่ได้'
  };

  function addAge(row) {
    var d = row.date_serv, b = row.birth;
    if (!d || !b) { row.age = null; row.age_month = null; return; }
    var years = d.getUTCFullYear() - b.getUTCFullYear();
    var beforeBday = (d.getUTCMonth() < b.getUTCMonth()) ||
      (d.getUTCMonth() === b.getUTCMonth() && d.getUTCDate() < b.getUTCDate());
    row.age = years - (beforeBday ? 1 : 0);
    row.age_month = years * 12 + (d.getUTCMonth() - b.getUTCMonth()) -
      (d.getUTCDate() < b.getUTCDate() ? 1 : 0);
  }

  function addGum(row) {
    var raw = row.gum;
    var g = (raw === null || raw === undefined) ? '' : String(raw).trim();
    if (g && g.length !== 6) g = '999999';
    for (var i = 0; i < GUM_CODES.length; i++) {
      var c = GUM_CODES[i];
      row['gum_sx_' + c] = g ? (g.split(c).length - 1) : null;
    }
    if (!g) { row.gum_status = null; row.gum_label = null; return; }
    var valid = g.split('').filter(function (ch) { return '0123'.indexOf(ch) >= 0; });
    row.gum_status = valid.length ? valid.sort().pop() : '9';
    row.gum_label = GUM_LABELS[row.gum_status] || null;
  }

  function sumMinCount1(row, cols) {
    var total = 0, any = false;
    for (var i = 0; i < cols.length; i++) {
      var v = row[cols[i]];
      if (v !== null && v !== undefined && !isNaN(v)) { total += v; any = true; }
    }
    return any ? total : null;
  }

  function prepare(rows) {
    var P = ['pcaries', 'pfilling', 'pextract'], D = ['dcaries', 'dfilling', 'dextract'];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      addAge(row);
      row.examined = !!row.date_serv;
      addGum(row);
      if (P.every(function (c) { return c in row; })) row.dmft_p = sumMinCount1(row, P);
      if (D.every(function (c) { return c in row; })) row.dmft_d = sumMinCount1(row, D);
    }
    return rows;
  }

  // ---- ตารางอ้างอิง --------------------------------------------------------

  /** hospitals.csv เป็น TIS-620 ไม่ใช่ UTF-8 — ต้องถอดรหัสให้ถูกไม่งั้นชื่อเพี้ยน */
  function decodeText(buf) {
    var bytes = new Uint8Array(buf);
    // มี BOM ของ UTF-8 หรือไม่
    if (bytes[0] === 0xEF && bytes[1] === 0xBB && bytes[2] === 0xBF) {
      return new TextDecoder('utf-8').decode(bytes.subarray(3));
    }
    try {
      return new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    } catch (e) {
      return new TextDecoder('windows-874').decode(bytes);   // = TIS-620
    }
  }

  /** CSV แบบง่าย รองรับเครื่องหมายคำพูดและ CRLF */
  function parseCSV(text) {
    var rows = [], row = [], field = '', q = false, i = 0;
    while (i < text.length) {
      var c = text[i];
      if (q) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
          q = false; i++; continue;
        }
        field += c; i++; continue;
      }
      if (c === '"') { q = true; i++; continue; }
      if (c === ',') { row.push(field); field = ''; i++; continue; }
      if (c === '\r') { i++; continue; }
      if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
      field += c; i++;
    }
    if (field !== '' || row.length) { row.push(field); rows.push(row); }
    if (!rows.length) return [];
    var head = rows[0].map(function (h) { return String(h).trim().toLowerCase(); });
    var out = [];
    for (var r = 1; r < rows.length; r++) {
      if (rows[r].length === 1 && rows[r][0] === '') continue;
      var o = {};
      for (var k = 0; k < head.length; k++) o[head[k]] = rows[r][k] === undefined ? '' : rows[r][k];
      out.push(o);
    }
    return out;
  }

  function loadHospitals(text) {
    var rows = parseCSV(text), map = {};
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i], code = String(r.hoscode || '').trim();
      if (!code || map[code]) continue;
      map[code] = {
        hoscode: code,
        hosname: (r.hosname || '').trim(),
        hostype: (r.hostype || '').trim(),
        ampcode: (r.ampcode || '').trim(),
        // ชื่อในไฟล์อ้างอิงมีรหัสนำหน้า เช่น "01-เมืองชัยภูมิ"
        ampname: String(r.ampname || '').replace(/^\d+-/, '').trim(),
        pvcode: (r.pvcode || '').trim(),
        pvname: String(r.pvname || '').replace(/^\d+-/, '').trim(),
        tumcode: (r.tumcode || '').trim(),
        tumbonname: String(r.tumbonname || '').replace(/^\d+-/, '').trim()
      };
    }
    return map;
  }

  /**
   * คลายตารางหน่วยบริการที่ถูกบีบไว้ตอน build
   * (CSV เต็ม 1.6 MB -> 0.6 MB เพราะชื่อจังหวัด/อำเภอ/ตำบลซ้ำกันเยอะ)
   */
  function expandHospitals(packed) {
    var map = {}, lines = packed.rows ? packed.rows.split('\n') : [];
    for (var i = 0; i < lines.length; i++) {
      var f = lines[i].split('\t');
      if (!f[0]) continue;
      map[f[0]] = {
        hoscode: f[0], hosname: '',
        pvname: packed.pv[+f[1]] || '', ampname: packed.amp[+f[2]] || '',
        tumbonname: f[3] === '' ? '' : (packed.tum[+f[3]] || ''),
        ampcode: f[4] || '', pvcode: f[5] || '', hostype: '', tumcode: ''
      };
    }
    return map;
  }

  function loadDictionary(text) {
    var rows = parseCSV(text), map = {};
    for (var i = 0; i < rows.length; i++) {
      var name = String(rows[i].name || '').trim().toLowerCase();
      if (name) map[name] = rows[i];
    }
    return map;
  }

  /** ผูก hoscode -> จังหวัด/อำเภอ/ชื่อหน่วยบริการ */
  function attachArea(rows, hospitals) {
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var code = row.hoscode === null || row.hoscode === undefined
        ? '' : String(row.hoscode).trim();
      row.hoscode = code;
      var h = hospitals[code];
      if (h) {
        if (!row.hosname) row.hosname = h.hosname;
        row.ampcode = h.ampcode;
        row.ampname = h.ampname || 'ไม่ระบุ';
        row.pvcode = h.pvcode;
        row.pvname = h.pvname || 'ไม่ระบุ';
        if (!row.tumbonname) row.tumbonname = h.tumbonname;
      } else {
        row.ampname = row.ampname || 'ไม่ระบุ';
        row.pvname = row.pvname || 'ไม่ระบุ';
      }
    }
    return rows;
  }

  root.DataIO = {
    NUMERIC_COLS: NUMERIC_COLS, CODE_COLS: CODE_COLS,
    normalizeRows: normalizeRows, applyFilenameRules: applyFilenameRules,
    prepare: prepare, decodeText: decodeText, parseCSV: parseCSV,
    loadHospitals: loadHospitals, loadDictionary: loadDictionary,
    expandHospitals: expandHospitals,
    attachArea: attachArea, parseDate: parseDate, toNum: toNum,
    issues: issues, clearIssues: clearIssues,
    GUM_LABELS: GUM_LABELS
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
