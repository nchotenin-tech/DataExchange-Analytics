/* =============================================================================
 * ชั้นบริการ — กรองพื้นที่ สรุปรายอำเภอ/หน่วยบริการ และรายชื่อเด็กที่ต้องติดตาม
 * พอร์ตจาก core/service.py
 *
 * ข้อมูลรายบุคคลอยู่ในหน่วยความจำเท่านั้น ไม่มีการบันทึกลงเครื่องจากชั้นนี้
 * ========================================================================== */
(function (root) {
  'use strict';

  var E = root.Expr, EN = root.Engine, D = root.DataIO;
  var TOTAL_LABEL = EN.TOTAL_LABEL;

  var SEX_LABEL = {'1': 'ชาย', '2': 'หญิง'};
  var PROVIDER_LABEL = {'02': 'ทันตแพทย์', '06': 'ทันตาภิบาล'};

  var PENDING_COLS = [
    ['hoscode', 'รหัสหน่วยบริการ'], ['hosname', 'หน่วยบริการ'], ['ampname', 'อำเภอ'],
    ['agegroup', 'กลุ่มอายุ'], ['pid', 'PID'], ['cid', 'เลขบัตรประชาชน'],
    ['name', 'ชื่อ'], ['lname', 'นามสกุล'], ['sex_label', 'เพศ'],
    ['birth_str', 'วันเกิด'], ['age_today', 'อายุปัจจุบัน (ปี)'],
    ['addr', 'บ้านเลขที่'], ['check_typearea', 'typearea'], ['tumbonname', 'ตำบล']
  ];

  var FAILED_COLS = [
    ['hoscode', 'รหัสหน่วยบริการ'], ['hosname', 'หน่วยบริการ'], ['ampname', 'อำเภอ'],
    ['fail_reason', 'สาเหตุที่ไม่ผ่านเกณฑ์'], ['pid', 'PID'],
    ['cid', 'เลขบัตรประชาชน'], ['name', 'ชื่อ'], ['lname', 'นามสกุล'],
    ['sex_label', 'เพศ'], ['birth_str', 'วันเกิด'], ['age', 'อายุขณะตรวจ (ปี)'],
    ['date_str', 'วันที่ตรวจ'], ['provider_label', 'ผู้ตรวจ'],
    ['pteeth', 'ฟันแท้ที่มี (ซี่)'], ['dteeth', 'ฟันน้ำนมที่มี (ซี่)'],
    ['addr', 'บ้านเลขที่'], ['tumbonname', 'ตำบล']
  ];

  var TREATMENT_COLS = [
    ['_problem', 'ปัญหาที่พบ / สิ่งที่ต้องทำ'],
    ['hoscode', 'รหัสหน่วยบริการ'], ['hosname', 'หน่วยบริการ'], ['ampname', 'อำเภอ'],
    ['pid', 'PID'], ['cid', 'เลขบัตรประชาชน'], ['name', 'ชื่อ'], ['lname', 'นามสกุล'],
    ['sex_label', 'เพศ'], ['birth_str', 'วันเกิด'], ['age', 'อายุขณะตรวจ (ปี)'],
    ['age_today', 'อายุปัจจุบัน (ปี)'], ['date_str', 'วันที่ตรวจ'],
    ['provider_label', 'ผู้ตรวจ'], ['gum_label', 'สภาวะปริทันต์'],
    ['pcaries', 'ฟันแท้ผุ (ซี่)'], ['pextract', 'ฟันแท้ถอน (ซี่)'],
    ['pfilling', 'ฟันแท้อุด (ซี่)'], ['dcaries', 'ฟันน้ำนมผุ (ซี่)'],
    ['dextract', 'ฟันน้ำนมถอน (ซี่)'], ['dfilling', 'ฟันน้ำนมอุด (ซี่)'],
    ['need_sealant', 'ต้องเคลือบหลุมร่องฟัน (ซี่)'],
    ['need_pfilling', 'ต้องอุดฟันแท้ (ซี่)'], ['need_dfilling', 'ต้องอุดฟันน้ำนม (ซี่)'],
    ['need_pextract', 'ต้องถอน/รักษารากฟันแท้ (ซี่)'],
    ['need_dextract', 'ต้องถอนฟันน้ำนม (ซี่)'],
    ['need_fluoride_label', 'ต้องทาฟลูออไรด์'],
    ['need_scaling_label', 'ต้องขูดหินน้ำลาย'],
    ['addr', 'บ้านเลขที่'], ['check_typearea', 'typearea'], ['tumbonname', 'ตำบล']
  ];

  var PROBLEM_RULES = [
    ['pcaries', 'ฟันแท้ผุ'], ['dcaries', 'ฟันน้ำนมผุ'],
    ['pextract', 'ฟันแท้ถอน/หลุด'], ['dextract', 'ฟันน้ำนมถอน'],
    ['need_sealant', 'ต้องเคลือบหลุมร่องฟัน'],
    ['need_pfilling', 'ต้องอุดฟันแท้'], ['need_dfilling', 'ต้องอุดฟันน้ำนม'],
    ['need_pextract', 'ต้องถอน/รักษารากฟันแท้'], ['need_dextract', 'ต้องถอนฟันน้ำนม']
  ];

  var AREA_COLS = ['pvcode', 'pvname', 'ampcode', 'ampname', 'tumcode', 'tumbonname',
                   'hostype', 'hosname_ref'];
  var CALC_COLS = ['age', 'age_month', 'band', 'examined', 'gum_status', 'gum_label',
                   'gum_sx_0', 'gum_sx_1', 'gum_sx_2', 'gum_sx_3', 'gum_sx_9',
                   'dmft_p', 'dmft_d'];
  var TEMP_COLS = ['age_today', 'birth_str', 'date_str', 'sex_label',
                   'provider_label', 'fail_reason'];

  // ฟิลด์ดิบบางตัวถูกแปลงเป็นคอลัมน์อ่านง่ายก่อนแสดง ต้องระบายสีคู่กัน
  var DISPLAY_ALIAS = {
    providertype: ['provider_label'], gum_status: ['gum_label'], sex: ['sex_label'],
    birth: ['birth_str'], date_serv: ['date_str'],
    need_fluoride: ['need_fluoride_label'], need_scaling: ['need_scaling_label']
  };

  function txt(v, dflt) {
    if (v === null || v === undefined) return dflt === undefined ? '' : dflt;
    var s = String(v).trim();
    return s === '' ? (dflt === undefined ? '' : dflt) : s;
  }

  function fmtDate(d) {
    if (!d) return null;
    var p = function (n) { return String(n).padStart(2, '0'); };
    return d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate());
  }

  /** โครงพื้นที่สำหรับไล่ดู: จังหวัด > อำเภอ > หน่วยบริการ */
  function areaTree(rows) {
    var tree = {};
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var pv = txt(r.pvname, 'ไม่ระบุ'), amp = txt(r.ampname, 'ไม่ระบุ');
      if (!tree[pv]) tree[pv] = {};
      if (!tree[pv][amp]) tree[pv][amp] = {};
      var code = txt(r.hoscode);
      if (code && !tree[pv][amp][code]) tree[pv][amp][code] = txt(r.hosname, code);
    }
    var out = {};
    Object.keys(tree).sort().forEach(function (pv) {
      out[pv] = {};
      Object.keys(tree[pv]).sort().forEach(function (amp) {
        out[pv][amp] = Object.keys(tree[pv][amp]).map(function (c) {
          return {code: c, name: tree[pv][amp][c]};
        }).sort(function (a, b) { return a.name < b.name ? -1 : 1; });
      });
    });
    return out;
  }

  function filterArea(rows, pv, amp, hos) {
    if (!pv && !amp && !hos) return rows;
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (pv && r.pvname !== pv) continue;
      if (amp && r.ampname !== amp) continue;
      if (hos && String(r.hoscode) !== String(hos)) continue;
      out.push(r);
    }
    return out;
  }

  function overviewSpec(profile) {
    var o = profile.overview || {};
    return {
      caries_free: o.caries_free || 'pcaries + pfilling + pextract == 0',
      dmft: o.dmft || 'pcaries + pfilling + pextract',
      caries_free_label: o.caries_free_label || 'ปราศจากฟันผุ',
      dmft_label: o.dmft_label || 'DMFT เฉลี่ย'
    };
  }

  function summary(scoped, profile) {
    var q = EN.qualityMask(scoped, profile), n = scoped.length, pass = 0, i;
    for (i = 0; i < n; i++) if (q[i]) pass++;
    var hos = {}, amp = {}, dmin = null, dmax = null;
    for (i = 0; i < n; i++) {
      var r = scoped[i];
      if (r.hoscode) hos[r.hoscode] = 1;
      if (r.ampname) amp[r.ampname] = 1;
      var d = fmtDate(r.date_serv);
      if (d) { if (dmin === null || d < dmin) dmin = d; if (dmax === null || d > dmax) dmax = d; }
    }
    return {
      examined: n, qualified: pass,
      qualified_pct: n ? EN.round(100 * pass / n, 2) : 0,
      hospitals: Object.keys(hos).length, districts: Object.keys(amp).length,
      date_min: dmin || '-', date_max: dmax || '-'
    };
  }

  /**
   * สรุปตามพื้นที่/หน่วยบริการ
   * pop = ประชากรเป้าหมายทั้งหมด (ยังไม่กรองว่าตรวจฟันหรือไม่) ใช้เป็นตัวหาร
   */
  function breakdown(pop, profile, byKey, codeKey, nameKey) {
    var spec = overviewSpec(profile);
    var scoped = EN.applyScope(pop, profile);
    var q = EN.qualityMask(scoped, profile);
    var sq = [];
    for (var i = 0; i < scoped.length; i++) if (q[i]) sq.push(scoped[i]);
    var cfMask = E.mask(sq, spec.caries_free);
    var dmVals = E.values(sq, spec.dmft);

    var acc = {};
    function slot(key) {
      var k = (key === null || key === undefined || key === '') ? 'ไม่ระบุ' : String(key);
      if (!acc[k]) acc[k] = {key: k, code: '', name: '', target: 0, examined: 0,
                             pending: 0, qualified: 0, cf: 0, dm: 0};
      return acc[k];
    }
    for (i = 0; i < pop.length; i++) {
      var r = pop[i], s = slot(r[byKey]);
      s.target++;
      if (!r.examined) s.pending++;
      if (!s.code) s.code = txt(codeKey === byKey ? r[byKey] : r[codeKey]);
      if (!s.name) s.name = txt(r[nameKey], s.key);
    }
    for (i = 0; i < scoped.length; i++) slot(scoped[i][byKey]).examined++;
    for (i = 0; i < sq.length; i++) {
      var t = slot(sq[i][byKey]);
      t.qualified++;
      if (cfMask[i]) t.cf++;
      var v = E.num(dmVals[i]);
      if (v !== null) t.dm += v;
    }

    var rows = Object.keys(acc).map(function (k) {
      var s = acc[k];
      return {
        key: s.key, code: s.code, name: s.name || s.key || 'ไม่ระบุ',
        target: s.target, examined: s.examined, pending: s.pending,
        failed: s.examined - s.qualified,
        examined_pct: s.target ? EN.round(100 * s.examined / s.target, 2) : null,
        qualified: s.qualified,
        qualified_pct: s.examined ? EN.round(100 * s.qualified / s.examined, 2) : null,
        caries_free: s.cf,
        caries_free_pct: s.qualified ? EN.round(100 * s.cf / s.qualified, 2) : null,
        dmft: s.qualified ? EN.round(s.dm / s.qualified, 2) : null
      };
    });
    rows.sort(function (a, b) {
      var ac = a.code || '￿', bc = b.code || '￿';
      return ac < bc ? -1 : ac > bc ? 1 : (a.name < b.name ? -1 : 1);
    });
    return rows;
  }

  function byDistrict(pop, profile) { return breakdown(pop, profile, 'ampname', 'ampcode', 'ampname'); }
  function byUnit(pop, profile) { return breakdown(pop, profile, 'hoscode', 'hoscode', 'hosname'); }

  // ---- รายชื่อเด็ก -----------------------------------------------------------

  function addPersonFields(r) {
    var today = new Date();
    var b = r.birth;
    if (b) {
      var yrs = today.getUTCFullYear() - b.getUTCFullYear();
      var before = (today.getUTCMonth() < b.getUTCMonth()) ||
        (today.getUTCMonth() === b.getUTCMonth() && today.getUTCDate() < b.getUTCDate());
      r.age_today = yrs - (before ? 1 : 0);
    } else r.age_today = null;
    r.birth_str = fmtDate(b);
    r.date_str = fmtDate(r.date_serv);
    if ('sex' in r) r.sex_label = SEX_LABEL[r.sex] || r.sex;
    if ('providertype' in r) {
      var p = r.providertype;
      r.provider_label = PROVIDER_LABEL[String(p)] ||
        (p === null || p === undefined ? 'ไม่ระบุ' : 'อื่น ๆ (' + p + ')');
    }
    return r;
  }

  function labelCols(r) {
    var yn = {1: 'ต้องทำ', 2: 'ไม่ต้อง', 0: 'ไม่ต้อง'};
    ['need_fluoride', 'need_scaling'].forEach(function (c) {
      if (c in r) {
        var v = E.num(r[c]);
        r[c + '_label'] = (v !== null && yn[v] !== undefined) ? yn[v] : 'ไม่ระบุ';
      }
    });
    return r;
  }

  /** ข้อความบอกว่าตกเกณฑ์ข้อไหนบ้าง */
  function failReasons(rows, profile) {
    var dflt = 'ไม่ผ่านเกณฑ์คุณภาพ';
    var checks = profile.quality_checks.map(function (c) {
      return {name: String(c.name), bands: c.bands || null, m: E.mask(rows, c.expr)};
    });
    return rows.map(function (r, i) {
      if (!checks.length) return dflt;
      var hit = [];
      for (var c = 0; c < checks.length; c++) {
        var chk = checks[c];
        if (chk.bands && chk.bands.indexOf(r.band) < 0) continue;
        if (!chk.m[i]) hit.push(chk.name);
      }
      return hit.length ? hit.join(' + ') : dflt;
    });
  }

  function headersFor(cols, spec) {
    var out = [];
    cols.forEach(function (c) {
      if (out.indexOf(c) < 0) out.push(c);
      [c].concat(DISPLAY_ALIAS[c] || []).forEach(function (src) {
        spec.forEach(function (pair) {
          if (pair[0] === src && out.indexOf(pair[1]) < 0) out.push(pair[1]);
        });
      });
    });
    return out;
  }

  /** ชื่อคอลัมน์ที่ทำให้แต่ละแถวตกเกณฑ์ (หน้าเว็บเอาไประบายสีแดง) */
  function failFields(rows, profile, spec, checks) {
    var list = (checks || profile.quality_checks).map(function (c) {
      var cols;
      try { cols = E.columns(c.expr); } catch (e) { cols = []; }
      return {bands: c.bands || null, m: E.mask(rows, c.expr),
              heads: headersFor(cols, spec)};
    });
    return rows.map(function (r, i) {
      var bad = {};
      for (var c = 0; c < list.length; c++) {
        var chk = list[c];
        if (chk.bands && chk.bands.indexOf(r.band) < 0) continue;
        if (!chk.m[i]) chk.heads.forEach(function (h) { bad[h] = 1; });
      }
      return Object.keys(bad).sort();
    });
  }

  function problemSummary(rows) {
    return rows.map(function (r) {
      var parts = [];
      PROBLEM_RULES.forEach(function (p) {
        var v = E.num(r[p[0]]);
        if (v !== null && v > 0) parts.push(p[1] + ' ' + Math.trunc(v) + ' ซี่');
      });
      if (E.num(r.need_fluoride) === 1) parts.push('ต้องทาฟลูออไรด์');
      if (E.num(r.need_scaling) === 1) parts.push('ต้องขูดหินน้ำลาย');
      var g = {'1': 'เหงือกมีเลือดออก', '2': 'เหงือกอักเสบ/มีหินน้ำลาย',
               '3': 'ปริทันต์อักเสบ', '9': 'ตรวจสภาวะปริทันต์ไม่ได้'}[r.gum_status];
      if (g) parts.push(g);
      return parts.length ? parts.join(' + ') : 'ไม่พบปัญหาที่ต้องตามต่อ';
    });
  }

  function rawColumns(header) {
    var skip = AREA_COLS.concat(CALC_COLS).concat(TEMP_COLS);
    return header.filter(function (c) {
      return c.charAt(0) !== '_' && skip.indexOf(c) < 0;
    });
  }

  /** เลือกคอลัมน์ตาม spec แล้วเปลี่ยนเป็นหัวตารางภาษาไทย */
  function select(rows, spec, sortKeys, rawHeader) {
    // ตัดคอลัมน์ที่ไม่มีอยู่จริงในข้อมูลชุดนี้ออก เช่น "กลุ่มอายุ" มีเฉพาะกลุ่ม 0-5 ปี
    // (ฝั่ง Python ทำแบบเดียวกันด้วย `c in out.columns`)
    var cols = rows.length
      ? spec.filter(function (p) { return p[0] in rows[0]; })
      : spec.slice();
    if (rawHeader) {
      rawColumns(rawHeader).forEach(function (c) { cols.push([c, c]); });
      CALC_COLS.forEach(function (c) { cols.push([c, c]); });
      cols.push(['_source_file', 'ไฟล์ต้นทาง']);
    }
    var seen = {}, uniq = [];
    cols.forEach(function (p) {
      if (!seen[p[1]]) { seen[p[1]] = 1; uniq.push(p); }
    });

    var out = rows.map(function (r) {
      var o = {};
      uniq.forEach(function (p) {
        var v = r[p[0]];
        if (v instanceof Date) v = fmtDate(v);
        o[p[1]] = v === undefined ? null : v;
      });
      if (r._bad) o._bad = r._bad;
      return o;
    });

    var order = uniq.filter(function (p) { return sortKeys.indexOf(p[0]) >= 0; })
                    .map(function (p) { return p[1]; });
    if (order.length) {
      out.sort(function (a, b) {
        for (var i = 0; i < order.length; i++) {
          var x = a[order[i]], y = b[order[i]];
          if (x === null || x === undefined) return 1;
          if (y === null || y === undefined) return -1;
          if (x < y) return -1;
          if (x > y) return 1;
        }
        return 0;
      });
    }
    return {columns: uniq.map(function (p) { return p[1]; }), rows: out};
  }

  /** ย้ายคอลัมน์ที่ทำให้ตกเกณฑ์ขึ้นมาไว้ต้นตาราง */
  function badFirst(res, after) {
    if (!res.rows.length) return res;
    var have = {};
    res.columns.forEach(function (c) { have[c] = 1; });
    var bad = {};
    res.rows.forEach(function (r) {
      r._bad = (r._bad || []).filter(function (h) { return have[h]; });
      r._bad.forEach(function (h) { bad[h] = 1; });
    });
    if (!Object.keys(bad).length) return res;
    var front = res.columns.slice(0, after)
      .concat(res.columns.filter(function (c) { return bad[c] && res.columns.indexOf(c) >= after; }));
    var rest = res.columns.filter(function (c) { return front.indexOf(c) < 0; });
    res.columns = front.concat(rest);
    return res;
  }

  var PERSON_KINDS = {
    pending: 'เด็กที่ยังไม่ได้ตรวจฟัน',
    failed: 'เด็กที่ตรวจแล้วไม่ผ่านเกณฑ์คุณภาพ',
    metric: 'รายชื่อเด็กที่ต้องติดตามจากตารางรายงาน'
  };

  function personList(ds, profile, kind, scope, raw) {
    var pop = filterArea(ds.rows, scope.pv, scope.amp, scope.hos);
    var i, out = [];
    if (kind === 'failed') {
      var scoped = EN.applyScope(pop, profile);
      var q = EN.qualityMask(scoped, profile);
      for (i = 0; i < scoped.length; i++) if (!q[i]) out.push(scoped[i]);
      var reasons = failReasons(out, profile);
      var bads = failFields(out, profile, FAILED_COLS);
      out.forEach(function (r, k) {
        r.fail_reason = reasons[k];
        r._bad = bads[k];
        addPersonFields(r);
      });
      return badFirst(select(out, FAILED_COLS, ['hoscode', 'date_serv', 'age'],
                             raw ? ds.header : null), 4);
    }
    for (i = 0; i < pop.length; i++) if (!pop[i].examined) out.push(Object.assign({}, pop[i]));
    out.forEach(addPersonFields);
    return select(out, PENDING_COLS, ['hoscode', 'age_today', 'birth_str'],
                  raw ? ds.header : null);
  }

  /** รายชื่อเด็กเบื้องหลังตัวเลขในตารางรายงาน (คลิกจากช่องในตาราง) */
  function metricList(ds, profile, tableNo, metric, rowLabel, scope, raw) {
    var spec = null;
    for (var t = 0; t < profile.tables.length; t++) {
      if (String(profile.tables[t].no) === String(tableNo)) { spec = profile.tables[t]; break; }
    }
    if (!spec) return {columns: [], rows: []};

    var scoped = EN.applyScope(filterArea(ds.rows, scope.pv, scope.amp, scope.hos), profile);
    var sub = scoped, i;
    if (rowLabel !== null && rowLabel !== undefined && rowLabel !== '' && rowLabel !== TOTAL_LABEL) {
      var want = String(rowLabel).trim();
      sub = scoped.filter(function (r) {
        if (spec.rows === 'age') return String(r.age) === want;
        return /^\d+$/.test(want) ? String(r.age) === want : r.band === want;
      });
    }

    var valueCol = null, badCheck = null, picked = [];
    if (spec.kind === 'quality') {
      var name = String(metric).split(':').pop().trim();
      var chk = null;
      for (i = 0; i < profile.quality_checks.length; i++) {
        if (profile.quality_checks[i].name === name) { chk = profile.quality_checks[i]; break; }
      }
      if (!chk) return {columns: [], rows: []};
      var cm = E.mask(sub, chk.expr);
      for (i = 0; i < sub.length; i++) {
        if (chk.bands && chk.bands.indexOf(sub[i].band) < 0) continue;
        if (!cm[i]) picked.push(sub[i]);
      }
      badCheck = chk;
    } else {
      var m = null;
      for (i = 0; i < spec.metrics.length; i++) {
        if (spec.metrics[i].name === metric) { m = spec.metrics[i]; break; }
      }
      if (!m) return {columns: [], rows: []};
      var denom = EN.denominatorMask(sub, spec, profile);
      if (spec.kind === 'mean') {
        var vals = E.values(sub, m.expr), keep = [];
        for (i = 0; i < sub.length; i++) {
          var v = E.num(vals[i]);
          if (denom[i] && v !== null && v > 0) { picked.push(sub[i]); keep.push(v); }
        }
        valueCol = keep;
      } else {
        var mm = E.mask(sub, m.expr);
        for (i = 0; i < sub.length; i++) if (denom[i] && mm[i]) picked.push(sub[i]);
      }
    }

    picked = picked.map(function (r) { return Object.assign({}, r); });
    picked.forEach(function (r) { labelCols(addPersonFields(r)); });
    var problems = problemSummary(picked);
    picked.forEach(function (r, k) { r._problem = problems[k]; });

    var cols = TREATMENT_COLS.slice();
    if (badCheck) {
      var bf = failFields(picked, profile, TREATMENT_COLS, [badCheck]);
      picked.forEach(function (r, k) { r._bad = bf[k]; });
    }
    if (valueCol) {
      picked.forEach(function (r, k) { r._value = valueCol[k]; });
      cols = [['_value', metric + ' (ซี่)']].concat(cols);
      var res = select(picked, cols, [], raw ? ds.header : null);
      var first = res.columns[0];
      res.rows.sort(function (a, b) { return (b[first] || 0) - (a[first] || 0); });
      return badFirst(res, 4);
    }
    return badFirst(select(picked, cols, ['hoscode', 'pid'], raw ? ds.header : null), 4);
  }

  function personColumnGroups(ds, columns) {
    var rawset = rawColumns(ds.header);
    return {
      main: columns.filter(function (c) { return rawset.indexOf(c) < 0 && CALC_COLS.indexOf(c) < 0; }),
      raw: columns.filter(function (c) { return rawset.indexOf(c) >= 0; }),
      calc: columns.filter(function (c) { return CALC_COLS.indexOf(c) >= 0; })
    };
  }

  /** รายงานเต็มของขอบเขตที่เลือก (ตัวเลขสรุปล้วน ไม่มีข้อมูลรายบุคคล) */
  function report(ds, profile, scope) {
    var pop = filterArea(ds.rows, scope.pv, scope.amp, scope.hos);
    var scoped = EN.applyScope(pop, profile);
    var s = summary(scoped, profile);
    s.target = pop.length;
    s.examined_pct = pop.length ? EN.round(100 * scoped.length / pop.length, 2) : null;
    var pending = 0;
    for (var i = 0; i < pop.length; i++) if (!pop[i].examined) pending++;
    s.pending = pending;
    s.out_of_range = pop.length - scoped.length - pending;

    var level = (scope.amp || scope.hos) ? 'unit' : 'district';
    var labels = overviewSpec(profile);
    return {
      profile: {id: profile.id, label: profile.label,
                age_min: profile.age_min, age_max: profile.age_max},
      scope: {pvname: scope.pv || null, ampname: scope.amp || null, hoscode: scope.hos || null},
      overview_labels: {caries_free_label: labels.caries_free_label,
                        dmft_label: labels.dmft_label},
      summary: s, level: level,
      districts: (scope.amp || scope.hos) ? [] : byDistrict(pop, profile),
      units: (scope.amp && !scope.hos) ? byUnit(pop, profile) : [],
      tables: EN.buildReport(scoped, profile)
    };
  }

  root.Service = {
    areaTree: areaTree, filterArea: filterArea, summary: summary,
    overviewSpec: overviewSpec, byDistrict: byDistrict, byUnit: byUnit,
    report: report, personList: personList, metricList: metricList,
    personColumnGroups: personColumnGroups, PERSON_KINDS: PERSON_KINDS,
    rawColumns: rawColumns, fmtDate: fmtDate
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
