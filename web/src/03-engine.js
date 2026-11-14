/* =============================================================================
 * Engine กลาง — อ่าน spec จาก profile YAML แล้วคำนวณตารางรายงาน
 * พอร์ตตรงจาก core/engine.py  (ตัวเลขต้องออกมาเท่ากันทุกช่อง)
 * ========================================================================== */
(function (root) {
  'use strict';

  var TOTAL_LABEL = 'รวม';
  var E = root.Expr;

  function Profile(d) {
    this.id = d.id;
    this.label = d.label || d.id;
    this.data_folder = d.data_folder || d.id;
    this.age_min = parseInt(d.age_range[0], 10);
    this.age_max = parseInt(d.age_range[1], 10);
    this.row_filter = d.row_filter === undefined ? null : d.row_filter;
    this.quality_filter = d.quality_filter;
    this.quality_checks = d.quality_checks || [];
    this.quality_extra = d.quality_extra || {};
    this.overview = d.overview || {};
    this.filename_columns = d.filename_columns || [];
    this.data_help = d.data_help || [];
    this.age_clamp = (d.age_clamp === undefined || d.age_clamp === null ||
                      d.age_clamp === '' || d.age_clamp === false)
      ? null : String(d.age_clamp).toLowerCase();
    this.bands = (d.bands || []).map(function (b) {
      return {label: String(b.label), min: parseInt(b.min, 10),
              max: parseInt(b.max, 10), split: !!b.split};
    });
    this.tables = (d.tables || []).map(function (t) {
      return {
        no: String(t.no === undefined ? '' : t.no),
        title: t.title || '',
        kind: t.kind || 'count_pct',
        rows: t.rows || 'age',
        denominator: t.denominator || 'qualified',
        conditions: t.conditions || [],
        decimals: t.decimals === undefined ? 2 : t.decimals,
        metrics: (t.metrics || []).map(function (m) {
          return {name: m.name, expr: m.expr, kind: m.kind || 'count',
                  denominator: m.denominator || null, note: m.note || '',
                  followup: !!m.followup};
        })
      };
    });
  }

  Profile.prototype.bandOf = function (age) {
    for (var i = 0; i < this.bands.length; i++) {
      var b = this.bands[i];
      if (age >= b.min && age <= b.max) return b.label;
    }
    return null;
  };

  /** เกณฑ์คุณภาพ = เงื่อนไขหลัก + เงื่อนไขเพิ่มเติมเฉพาะบางช่วงอายุ */
  function qualityMask(rows, profile) {
    var m = E.mask(rows, profile.quality_filter);
    var extra = profile.quality_extra || {};
    for (var label in extra) {
      if (!Object.prototype.hasOwnProperty.call(extra, label)) continue;
      var sub = E.mask(rows, extra[label]);
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].band === label && !sub[i]) m[i] = 0;
      }
    }
    return m;
  }

  /** อายุที่ใช้จริงในรายงาน — ปรับเข้าช่วงตาม age_clamp */
  function clampedAge(row, profile) {
    var age = E.num(row.age);
    if (age === null) return null;
    if (profile.age_clamp === 'max' || profile.age_clamp === 'both') {
      age = Math.min(age, profile.age_max);
    }
    if (profile.age_clamp === 'min' || profile.age_clamp === 'both') {
      age = Math.max(age, profile.age_min);
    }
    return age;
  }

  /**
   * กรองให้เหลือเฉพาะแถวที่ตรวจฟันและอยู่ในช่วงอายุ
   * คืน "แถวสำเนา" เสมอ — ห้ามแก้ค่า age ของข้อมูลต้นทาง
   * (บั๊กคลาสสิกฝั่ง Python: แก้ mask ทับ แล้วยอดที่คำนวณหลังจากนั้นผิดหมด)
   */
  function applyScope(rows, profile) {
    var rowFilter = profile.row_filter ? E.mask(rows, profile.row_filter) : null;
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!row.examined) continue;
      if (rowFilter && !rowFilter[i]) continue;
      var age = clampedAge(row, profile);
      if (age === null || age < profile.age_min || age > profile.age_max) continue;
      var copy = Object.assign({}, row);
      copy.age = Math.round(age);
      if (profile.bands.length) copy.band = profile.bandOf(copy.age);
      copy._i = i;
      out.push(copy);
    }
    return out;
  }

  /** [{label, idx[], parent}] โดยมีแถว "รวม" ต่อท้ายเสมอ */
  function groups(rows, spec, profile) {
    var out = [], i;
    function pick(fn) {
      var idx = [];
      for (i = 0; i < rows.length; i++) if (fn(rows[i])) idx.push(i);
      return idx;
    }
    if (spec.rows === 'age') {
      for (var a = profile.age_min; a <= profile.age_max; a++) {
        out.push({label: a, idx: pick(function (r) { return r.age === this.a; }.bind({a: a})), parent: null});
      }
    } else if (spec.rows === 'bands' || spec.rows === 'band') {
      for (var b = 0; b < profile.bands.length; b++) {
        var band = profile.bands[b];
        out.push({label: band.label,
                  idx: pick(function (r) { return r.band === this.l; }.bind({l: band.label})),
                  parent: null});
        if (band.split) {
          for (var s = band.min; s <= band.max; s++) {
            out.push({label: s,
                      idx: pick(function (r) { return r.age === this.a; }.bind({a: s})),
                      parent: band.label});
          }
        }
      }
    }
    var all = [];
    for (i = 0; i < rows.length; i++) all.push(i);
    out.push({label: TOTAL_LABEL, idx: all, parent: null});
    return out;
  }

  function rowLabel(spec) {
    return {age: 'อายุ (ปี)', bands: 'กลุ่มอายุ (ปี)',
            band: 'กลุ่มอายุ (ปี)'}[spec.rows] || 'รายการ';
  }

  function pct(n, d, decimals) {
    if (!d) return null;
    return round(100 * n / d, decimals === undefined ? 2 : decimals);
  }

  /**
   * ปัดเศษให้เหมือน round() ของ Python — "ปัดครึ่งไปหาเลขคู่"
   * ไม่ใช่ Math.round ของ JS ที่ปัดครึ่งขึ้นเสมอ
   *
   *   66.625 -> Python 66.62 (เพราะ 2 เป็นเลขคู่) แต่ Math.round ให้ 66.63
   *
   * ต่างกันแค่หลักสตางค์ แต่ทำให้ร้อยละในรายงานไม่ตรงกับเวอร์ชันเดิม
   */
  function round(v, d) {
    if (v === null || v === undefined || isNaN(v) || !isFinite(v)) return null;
    var neg = v < 0, a = Math.abs(v);

    // ดูทศนิยมของค่าจริงที่เก็บในเครื่อง (ไม่คูณ 10^d เพราะจะคลาดเคลื่อน
    // เช่น 10.205 * 100 ได้ 1020.4999999999999 แล้วปัดลงผิด)
    var s = a.toFixed(Math.min(100, d + 17));
    var dot = s.indexOf('.');
    var intPart = dot < 0 ? s : s.slice(0, dot);
    var frac = dot < 0 ? '' : s.slice(dot + 1);
    var keep = frac.slice(0, d), rest = frac.slice(d);

    var n = BigInt(intPart + keep);
    var half = '5' + '0'.repeat(Math.max(0, rest.length - 1));
    if (rest > half) n += 1n;
    else if (rest === half && (n % 2n) === 1n) n += 1n;   // ครึ่งพอดี -> ไปเลขคู่

    var out = Number(n) / Math.pow(10, d);
    return neg ? -out : out;
  }

  /**
   * ปัดเศษแบบ numpy (คูณ 10^d แล้ว rint) — ต่างจาก round() ของ Python
   *
   *   9.525 -> Python 9.53 แต่ numpy 9.52 (เพราะ 9.525*100 = 952.4999999999999)
   *
   * ฝั่ง eda.py คำนวณบน np.int64 ผลจึงไปทาง numpy ต้องใช้ตัวนี้ให้ตรงกัน
   */
  function roundNp(v, d) {
    if (v === null || v === undefined || isNaN(v) || !isFinite(v)) return null;
    var f = Math.pow(10, d), x = v * f;
    var frac = x - Math.floor(x);
    var r = (frac === 0.5) ? 2 * Math.round(x / 2) : Math.round(x);
    return r / f;
  }

  function denominatorMask(rows, spec, profile) {
    if (spec.kind === 'quality') return ones(rows.length);
    if (spec.denominator === 'qualified') return qualityMask(rows, profile);
    if (spec.denominator === 'examined') return ones(rows.length);
    return E.mask(rows, spec.denominator);
  }

  function ones(n) {
    var a = new Uint8Array(n);
    a.fill(1);
    return a;
  }

  function buildQualityTable(rows, spec, profile) {
    var qual = qualityMask(rows, profile);
    var gs = groups(rows, spec, profile), out = [];
    var checkMasks = profile.quality_checks.map(function (c) {
      return {chk: c, m: E.mask(rows, c.expr)};
    });

    for (var g = 0; g < gs.length; g++) {
      var idx = gs[g].idx, n = idx.length, pass = 0, i;
      for (i = 0; i < n; i++) if (qual[idx[i]]) pass++;
      var row = {
        row: gs[g].label, _sub: !!gs[g].parent, _parent: gs[g].parent,
        'จำนวนที่ตรวจ': n,
        'จำนวนที่ผ่านเกณฑ์คุณภาพ': pass,
        'ร้อยละ': pct(pass, n, spec.decimals)
      };
      for (var c = 0; c < checkMasks.length; c++) {
        var chk = checkMasks[c].chk, m = checkMasks[c].m;
        var only = chk.bands || null, fail = 0, base = 0;
        for (i = 0; i < n; i++) {
          var r = rows[idx[i]];
          if (only && only.indexOf(r.band) < 0) continue;
          base++;
          if (!m[idx[i]]) fail++;
        }
        row['ไม่ผ่าน: ' + chk.name] = fail;
        row['ร้อยละไม่ผ่าน: ' + chk.name] = pct(fail, base, spec.decimals);
      }
      out.push(row);
    }
    var cols = out.length ? Object.keys(out[0]).filter(function (c) {
      return c !== '_sub' && c !== '_parent';
    }) : ['row'];
    return {
      no: spec.no, title: spec.title, kind: spec.kind, row_label: rowLabel(spec),
      columns: cols, rows: out, conditions: spec.conditions,
      followup: profile.quality_checks.map(function (c) { return 'ไม่ผ่าน: ' + c.name; })
    };
  }

  function buildCountPctTable(rows, spec, profile) {
    var denom = denominatorMask(rows, spec, profile);
    var gs = groups(rows, spec, profile), out = [];
    var metricMasks = spec.metrics.map(function (m) { return E.mask(rows, m.expr); });

    for (var g = 0; g < gs.length; g++) {
      var idx = gs[g].idx, base = 0, i;
      for (i = 0; i < idx.length; i++) if (denom[idx[i]]) base++;
      var row = {row: gs[g].label, _sub: !!gs[g].parent, _parent: gs[g].parent, 'ฐาน': base};
      for (var m = 0; m < spec.metrics.length; m++) {
        var hit = 0, mm = metricMasks[m];
        for (i = 0; i < idx.length; i++) if (mm[idx[i]] && denom[idx[i]]) hit++;
        row[spec.metrics[m].name + '|จำนวน'] = hit;
        row[spec.metrics[m].name + '|ร้อยละ'] = pct(hit, base, spec.decimals);
      }
      out.push(row);
    }
    var cols = ['row', 'ฐาน'];
    spec.metrics.forEach(function (m) {
      cols.push(m.name + '|จำนวน'); cols.push(m.name + '|ร้อยละ');
    });
    return {
      no: spec.no, title: spec.title, kind: spec.kind, row_label: rowLabel(spec),
      columns: cols, rows: out, conditions: spec.conditions,
      metric_names: spec.metrics.map(function (m) { return m.name; }),
      followup: spec.metrics.filter(function (m) { return m.followup; })
                            .map(function (m) { return m.name; })
    };
  }

  function buildMeanTable(rows, spec, profile) {
    var denom = denominatorMask(rows, spec, profile);
    var gs = groups(rows, spec, profile), out = [];
    var metricVals = spec.metrics.map(function (m) { return E.values(rows, m.expr); });

    for (var g = 0; g < gs.length; g++) {
      var idx = gs[g].idx, base = 0, i;
      for (i = 0; i < idx.length; i++) if (denom[idx[i]]) base++;
      var row = {row: gs[g].label, _sub: !!gs[g].parent, _parent: gs[g].parent, 'ฐาน': base};
      for (var m = 0; m < spec.metrics.length; m++) {
        var vals = metricVals[m], total = 0;
        for (i = 0; i < idx.length; i++) {
          if (!denom[idx[i]]) continue;
          var v = E.num(vals[idx[i]]);
          if (v !== null) total += v;
        }
        row[spec.metrics[m].name] = base ? round(total / base, spec.decimals) : null;
        row[spec.metrics[m].name + '|รวมซี่'] = total;
      }
      out.push(row);
    }
    var cols = ['row', 'ฐาน'].concat(spec.metrics.map(function (m) { return m.name; }));
    return {
      no: spec.no, title: spec.title, kind: spec.kind, row_label: rowLabel(spec),
      columns: cols, rows: out, conditions: spec.conditions,
      metric_names: spec.metrics.map(function (m) { return m.name; }),
      followup: spec.metrics.filter(function (m) { return m.followup; })
                            .map(function (m) { return m.name; })
    };
  }

  var BUILDERS = {
    quality: buildQualityTable,
    count_pct: buildCountPctTable,
    mean: buildMeanTable
  };

  /** คำนวณทุกตารางใน profile — rows ต้องผ่าน applyScope มาแล้ว */
  function buildReport(rows, profile) {
    return profile.tables.map(function (spec) {
      var b = BUILDERS[spec.kind];
      if (!b) throw new Error('ไม่รู้จัก table kind: ' + spec.kind);
      return b(rows, spec, profile);
    });
  }

  root.Engine = {
    TOTAL_LABEL: TOTAL_LABEL, Profile: Profile, qualityMask: qualityMask,
    clampedAge: clampedAge, applyScope: applyScope, buildReport: buildReport,
    denominatorMask: denominatorMask, groups: groups, pct: pct, round: round,
    roundNp: roundNp,
    ones: ones
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
