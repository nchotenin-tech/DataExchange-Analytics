/* =============================================================================
 * ตัวต่อสาย — เปลี่ยนหน้า dashboard เดิมจาก "ยิงไป Flask" เป็น "คำนวณในเครื่อง"
 *
 * หน้า dashboard เดิมเรียกข้อมูลผ่าน api() แค่ 4 จุด เราจึงแทนที่ api() ตัวเดียว
 * ส่วนฟังก์ชันวาดหน้าจอทั้งหมดใช้ของเดิมได้เลย เพราะรูปแบบ JSON เหมือนกันเป๊ะ
 *
 * ข้อมูลรายบุคคลอยู่ใน DATASETS ซึ่งเป็นตัวแปรในหน่วยความจำเท่านั้น
 * ไม่มีการเขียนลง localStorage / IndexedDB / ไฟล์ใด ๆ
 * ========================================================================== */
(function (root) {
  'use strict';

  var D = root.DataIO, EN = root.Engine, S = root.Service, Y = root.Yaml,
      X = root.Xlsx, Save = root.Save, Eda = root.Eda;

  var DATASETS = {};      // profileId -> {rows, header}  (ข้อมูลรายบุคคล)
  var PROFILES = {};      // profileId -> Engine.Profile
  var HOSPITALS = {};
  var DICTIONARY = {};
  var HANDLES = [];       // File object ที่ผู้ใช้เลือกไว้ สำหรับปุ่มโหลดใหม่
  var LAST_KEY = 'dentaldx.lastReport.v1';

  function $(s) { return document.querySelector(s); }
  function text(el, s) { if (el) el.textContent = s; }

  // ---- อ่านไฟล์ที่ผู้ใช้เลือก ------------------------------------------------

  function relPath(f) {
    return (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
  }

  /** จัดไฟล์ที่เลือกเข้ากลุ่ม: data/<โฟลเดอร์>/*.xlsx, profiles/*.yaml, hospitals.csv */
  function classify(files) {
    var out = {data: {}, profiles: [], hospitals: null};
    for (var i = 0; i < files.length; i++) {
      var f = files[i], p = relPath(f), low = p.toLowerCase();
      var base = p.split('/').pop();
      if (base.indexOf('~$') === 0) continue;

      if (/\.ya?ml$/.test(low) && low.indexOf('/profiles/') >= 0) { out.profiles.push(f); continue; }
      if (/hospitals\.csv$/.test(low)) { out.hospitals = f; continue; }
      if (!/\.xlsx$/.test(low)) continue;

      // data/<กลุ่ม>/ไฟล์.xlsx  -> ใช้ชื่อโฟลเดอร์ที่อยู่ใต้ data เป็นชื่อกลุ่ม
      var parts = p.split('/');
      var di = -1;
      for (var k = 0; k < parts.length - 1; k++) {
        if (parts[k].toLowerCase() === 'data') { di = k; break; }
      }
      var group = di >= 0 && di + 1 < parts.length - 1 ? parts[di + 1]
                : (parts.length > 1 ? parts[parts.length - 2] : '');
      if (!group) continue;
      (out.data[group] = out.data[group] || []).push(f);
    }
    return out;
  }

  function readArrayBuffer(file) {
    return new Promise(function (res, rej) {
      var r = new FileReader();
      r.onload = function () { res(r.result); };
      r.onerror = function () { rej(new Error('อ่านไฟล์ ' + file.name + ' ไม่ได้')); };
      r.readAsArrayBuffer(file);
    });
  }

  async function readText(file) {
    return D.decodeText(await readArrayBuffer(file));
  }

  function progress(msg) {
    var el = $('#loadMsg');
    if (el) el.textContent = msg;
  }

  /** โหลดข้อมูลทั้งชุดจากไฟล์ที่ผู้ใช้เลือก */
  async function loadFiles(files) {
    var got = classify(files);
    var groups = Object.keys(got.data);
    if (!groups.length) {
      throw new Error('ไม่พบไฟล์ .xlsx ในโฟลเดอร์ data\\<กลุ่มอายุ>\\ ' +
        'กรุณาเลือกโฟลเดอร์ Dashboard-Exam ที่มีโฟลเดอร์ data อยู่ข้างใน');
    }

    // profile: ใช้ไฟล์ข้าง ๆ ก่อน ถ้าไม่มีใช้ที่ฝังมาในโปรแกรม
    PROFILES = {};
    var specs = [];
    if (got.profiles.length) {
      for (var i = 0; i < got.profiles.length; i++) {
        var raw = await readText(got.profiles[i]);
        try {
          var spec = Y.load(raw);
          if (spec && spec.id) specs.push(spec);
        } catch (e) {
          throw new Error('ไฟล์ ' + got.profiles[i].name + ' ผิดรูปแบบ YAML: ' + e.message);
        }
      }
    }
    if (!specs.length) specs = JSON.parse($('#embedded-profiles').textContent);
    specs.forEach(function (s) { PROFILES[s.id] = new EN.Profile(s); });

    // ใช้ hospitals.csv ที่วางไว้ข้างโปรแกรมก่อน (เผื่อมีหน่วยบริการใหม่)
    // ไม่มีก็ใช้ตารางที่ฝังมาในไฟล์ HTML
    DICTIONARY = D.loadDictionary($('#embedded-dictionary').textContent);
    HOSPITALS = got.hospitals
      ? D.loadHospitals(await readText(got.hospitals))
      : D.expandHospitals(JSON.parse($('#embedded-hospitals').textContent));

    DATASETS = {};
    for (var g = 0; g < groups.length; g++) {
      var name = groups[g];
      var p = null;
      for (var id in PROFILES) {
        if (PROFILES[id].data_folder === name || id === name) { p = PROFILES[id]; break; }
      }
      if (!p) continue;

      var rows = [], header = null, list = got.data[name];
      for (var fi = 0; fi < list.length; fi++) {
        progress('กำลังอ่าน ' + name + '/' + list[fi].name + ' …');
        var parsed = await X.parseXlsx(await readArrayBuffer(list[fi]), function (n) {
          if (n % 20000 === 0 && n) progress('กำลังอ่าน ' + list[fi].name + ' … ' +
            n.toLocaleString() + ' แถว');
        });
        if (!header) header = parsed.header.slice();
        var objs = new Array(parsed.rows.length);
        for (var r = 0; r < parsed.rows.length; r++) {
          var o = {};
          for (var c = 0; c < parsed.header.length; c++) o[parsed.header[c]] = parsed.rows[r][c];
          objs[r] = o;
        }
        rows = rows.concat(D.normalizeRows(objs, list[fi].name));
      }
      progress('กำลังคำนวณ ' + p.label + ' …');
      D.applyFilenameRules(rows, p.filename_columns);
      D.attachArea(rows, HOSPITALS);
      D.prepare(rows);
      DATASETS[p.id] = {rows: rows, header: header || []};
    }

    if (!Object.keys(DATASETS).length) {
      throw new Error('ไฟล์ที่เลือกไม่ตรงกับกลุ่มอายุใน profiles — ' +
        'ชื่อโฟลเดอร์ใต้ data\\ ต้องตรงกับ data_folder ใน profile (เช่น 0-5y, 6-12y)');
    }
    HANDLES = files;
  }

  // ---- แทนที่ api() ของหน้า dashboard เดิม -----------------------------------

  function qs(path) {
    var i = path.indexOf('?');
    return new URLSearchParams(i < 0 ? '' : path.slice(i + 1));
  }

  function scopeOf(q) {
    return {pv: q.get('pv') || null, amp: q.get('amp') || null, hos: q.get('hos') || null};
  }

  function needProfile(q) {
    var p = PROFILES[q.get('profile')];
    if (!p) throw new Error('ไม่พบกลุ่มอายุ: ' + q.get('profile'));
    if (!DATASETS[p.id]) throw new Error('ยังไม่ได้โหลดข้อมูลของ ' + p.label);
    return p;
  }

  async function api(path) {
    var q = qs(path);

    if (path.indexOf('/api/profiles') === 0) {
      return Object.keys(DATASETS).map(function (id) {
        var p = PROFILES[id];
        return {id: p.id, label: p.label, age_min: p.age_min, age_max: p.age_max,
                folder: p.data_folder, files: 1};
      }).sort(function (a, b) { return a.age_min - b.age_min; });
    }

    if (path.indexOf('/api/areas') === 0) {
      var pa = PROFILES[q.get('profile')];
      return pa && DATASETS[pa.id] ? S.areaTree(DATASETS[pa.id].rows) : {};
    }

    if (path.indexOf('/api/eda') === 0) {
      var pe = needProfile(q);
      var dse = DATASETS[pe.id], scope2 = scopeOf(q);
      var pop = S.filterArea(dse.rows, scope2.pv, scope2.amp, scope2.hos);
      var scoped = EN.applyScope(pop, pe);
      var level = (scope2.amp || scope2.hos) ? 'unit' : 'district';
      var areaRows = (scope2.amp && !scope2.hos) ? S.byUnit(pop, pe) : S.byDistrict(pop, pe);
      var ol = S.overviewSpec(pe);
      return Eda.build(pop, scoped, pe, areaRows, level, DICTIONARY,
                       {caries_free_label: ol.caries_free_label, dmft_label: ol.dmft_label});
    }

    if (path.indexOf('/api/report') === 0) {
      var pr = needProfile(q);
      var rep = S.report(DATASETS[pr.id], pr, scopeOf(q));
      saveLast(rep);
      return rep;
    }

    if (path.indexOf('/api/people') === 0 || path.indexOf('/api/pending') === 0) {
      var pp = needProfile(q);
      var kind = q.get('kind') || 'pending';
      var raw = q.get('raw') !== '0';
      var scope = scopeOf(q);
      var res, title, meta = null;

      if (kind === 'value') {
        var col = q.get('col') || '', selv = q.get('sel') || 'outlier';
        var numArg = function (k) {
          var v = q.get(k);
          return (v === null || v === '') ? null : parseFloat(v);
        };
        res = Eda.valueList(DATASETS[pp.id], pp, col, selv, {
          pv: scope.pv, amp: scope.amp, hos: scope.hos, raw: raw,
          lo: numArg('lo'), hi: numArg('hi'), hiExclusive: q.get('hix') === '1'
        });
        var lbl = '';
        Eda.NUMERIC_CANDIDATES.forEach(function (c) { if (c[0] === col) lbl = c[1]; });
        var what = Eda.VALUE_SELECTIONS[selv] || selv;
        meta = {label: lbl || col, column: col, sel: selv, what: what};
        title = (lbl || col) + ' — ' + what;
      } else if (kind === 'metric') {
        var no = q.get('table') || '', met = q.get('metric') || '', rowv = q.get('row') || null;
        res = S.metricList(DATASETS[pp.id], pp, no, met, rowv, scope, raw);
        var rowtxt = (rowv && rowv !== EN.TOTAL_LABEL) ? 'อายุ ' + rowv : 'ทุกอายุ';
        meta = {label: met, what: 'ตารางที่ ' + no + ' · ' + rowtxt, table: no, row: rowv};
        title = met + ' — ' + meta.what;
      } else {
        if (kind !== 'failed') kind = 'pending';
        res = S.personList(DATASETS[pp.id], pp, kind, scope, raw);
        title = S.PERSON_KINDS[kind];
      }

      var limit = parseInt(q.get('limit') || '500', 10);
      var cols = res.columns.filter(function (c) { return c !== '_bad'; });
      var head = res.rows.slice(0, limit).map(function (r) {
        var o = {};
        cols.forEach(function (c) { o[c] = r[c] === undefined ? null : r[c]; });
        o._bad = r._bad || [];
        return o;
      });
      return {
        kind: kind, title: title, meta: meta, total: res.rows.length,
        shown: Math.min(res.rows.length, limit), columns: cols,
        groups: S.personColumnGroups(DATASETS[pp.id], cols), rows: head
      };
    }

    throw new Error('ไม่รู้จักคำสั่ง: ' + path);
  }

  // ---- ส่งออกไฟล์ (แทนลิงก์ /api/table.xlsx เดิม) -----------------------------

  function frameOverview(rows, level, labels) {
    var unit = level === 'unit' ? 'หน่วยบริการ' : 'อำเภอ';
    var head = ['รหัส', unit, 'เป้าหมาย', 'ตรวจแล้ว', 'ร้อยละตรวจ', 'ยังไม่ตรวจ',
                'ผ่านเกณฑ์', 'ร้อยละผ่านเกณฑ์', labels.caries_free_label,
                'ร้อยละ' + labels.caries_free_label, labels.dmft_label];
    return [head].concat(rows.map(function (r) {
      return [r.code, r.name, r.target, r.examined, r.examined_pct, r.pending,
              r.qualified, r.qualified_pct, r.caries_free, r.caries_free_pct, r.dmft];
    }));
  }

  function frameTable(t) {
    var cols = t.columns.filter(function (c) { return c.indexOf('|รวมซี่') < 0; });
    var head = cols.map(function (c) {
      return c === 'row' ? (t.row_label || 'อายุ (ปี)') : c.replace('|', ' ');
    });
    return [head].concat(t.rows.map(function (r) {
      return cols.map(function (c) {
        var v = r[c];
        if (c === 'row') return (r._sub ? '  ↳ ' : '') + v;
        return v === undefined ? null : v;
      });
    }));
  }

  function stamp() {
    var d = new Date(), p = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate());
  }

  function scopeText(rep) {
    return rep.scope.hoscode || rep.scope.ampname || rep.scope.pvname || 'ทั้งหมด';
  }

  /** บันทึกรายงาน (ตัวเลขสรุปล้วน ไม่มีข้อมูลรายบุคคล) */
  function exportReport(rep, which, kind) {
    var name, sheets;
    if (which === 'all') {
      sheets = [{name: 'ภาพรวมรายพื้นที่',
                 rows: frameOverview(rep.level === 'unit' ? rep.units : rep.districts,
                                     rep.level, rep.overview_labels)}];
      rep.tables.forEach(function (t) {
        sheets.push({name: 'ตารางที่ ' + t.no, rows: frameTable(t)});
      });
      name = 'รายงานทั้งหมด_' + rep.profile.id + '_' + scopeText(rep) + '_' + stamp();
      Save.saveXlsx(sheets, name + '.xlsx');
      return;
    }
    var rows, label;
    if (which === 'overview') {
      rows = frameOverview(rep.level === 'unit' ? rep.units : rep.districts,
                           rep.level, rep.overview_labels);
      label = 'ภาพรวมรายพื้นที่';
    } else {
      var t = null;
      rep.tables.forEach(function (x) { if (String(x.no) === String(which)) t = x; });
      if (!t) return;
      rows = frameTable(t);
      label = 'ตารางที่ ' + t.no;
    }
    name = label + '_' + rep.profile.id + '_' + scopeText(rep) + '_' + stamp();
    if (kind === 'csv') Save.saveCsv(rows, name + '.csv');
    else Save.saveXlsx([{name: label, rows: rows}], name + '.xlsx');
  }

  /** ส่งออกรายชื่อเด็ก — ไฟล์นี้มีข้อมูลส่วนบุคคล */
  function exportPeople(data, kind) {
    var rows = [data.columns].concat(data.rows.map(function (r) {
      return data.columns.map(function (c) { return r[c]; });
    }));
    var name = (data.title || 'รายชื่อ').replace(/[\\\/:*?"<>|]/g, '-') + '_' + stamp();
    if (kind === 'csv') Save.saveCsv(rows, name + '.csv');
    else Save.saveXlsx([{name: 'รายชื่อ', rows: rows}], name + '.xlsx');
  }

  // ---- จำรายงานล่าสุด (ตัวเลขสรุปเท่านั้น) -------------------------------------

  function saveLast(rep) {
    try {
      localStorage.setItem(LAST_KEY, JSON.stringify({
        at: new Date().toISOString(),
        profile: rep.profile, scope: rep.scope, summary: rep.summary
      }));
    } catch (e) { /* โหมดส่วนตัวของเบราว์เซอร์เขียนไม่ได้ ไม่เป็นไร */ }
  }

  function loadLast() {
    try { return JSON.parse(localStorage.getItem(LAST_KEY) || 'null'); }
    catch (e) { return null; }
  }

  function clearLast() {
    try { localStorage.removeItem(LAST_KEY); } catch (e) { /* ไม่เป็นไร */ }
  }

  root.DX = {
    api: api, loadFiles: loadFiles, exportReport: exportReport,
    exportPeople: exportPeople, loadLast: loadLast, clearLast: clearLast,
    datasets: function () { return DATASETS; },
    profiles: function () { return PROFILES; },
    handles: function () { return HANDLES; },
    progress: progress
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
