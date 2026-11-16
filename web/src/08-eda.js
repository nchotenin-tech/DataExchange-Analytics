/* =============================================================================
 * สำรวจข้อมูลเบื้องต้น (EDA) — พอร์ตจาก core/eda.py
 *
 *   1. anomalies    ค่าที่ผิดปกติหรือขัดแย้งกันเอง
 *   2. numeric      การกระจายของค่าตัวเลข (histogram + สถิติแบบ boxplot)
 *   3. categorical  ความถี่ของตัวแปรหมวดหมู่ พร้อมคำอธิบายรหัส
 *   4. heatmap      ตัวชี้วัดหลักเทียบข้ามพื้นที่
 * ========================================================================== */
(function (root) {
  'use strict';

  var E = root.Expr, EN = root.Engine, S = root.Service;

  var NUMERIC_CANDIDATES = [
    ['age', 'อายุขณะตรวจ (ปี)'],
    ['pteeth', 'ฟันแท้ที่มีอยู่ (ซี่)'],
    ['pcaries', 'ฟันแท้ผุ (ซี่)'],
    ['pfilling', 'ฟันแท้อุด (ซี่)'],
    ['pextract', 'ฟันแท้ถอน/หลุด (ซี่)'],
    ['dmft_p', 'ฟันแท้ผุถอนอุด DMFT (ซี่)'],
    ['dteeth', 'ฟันน้ำนมที่มีอยู่ (ซี่)'],
    ['dcaries', 'ฟันน้ำนมผุ (ซี่)'],
    ['dfilling', 'ฟันน้ำนมอุด (ซี่)'],
    ['dextract', 'ฟันน้ำนมถอน (ซี่)'],
    ['dmft_d', 'ฟันน้ำนมผุถอนอุด dmft (ซี่)'],
    ['need_sealant', 'ต้องเคลือบหลุมร่องฟัน (ซี่)'],
    ['need_pfilling', 'ต้องอุดฟันแท้ (ซี่)'],
    ['need_dfilling', 'ต้องอุดฟันน้ำนม (ซี่)'],
    ['need_pextract', 'ต้องถอน/รักษารากฟันแท้ (ซี่)'],
    ['need_dextract', 'ต้องถอนฟันน้ำนม (ซี่)']
  ];

  var CATEGORICAL_CANDIDATES = [
    ['providertype', 'ประเภทผู้ตรวจ'], ['denttype', 'กลุ่มผู้รับบริการ'],
    ['servplace', 'สถานที่ให้บริการ'], ['gum_status', 'สภาวะปริทันต์ (สรุปจาก GUM)'],
    ['sex', 'เพศ'], ['agegroup', 'กลุ่มอายุในไฟล์'], ['class', 'ระดับการศึกษา'],
    ['schooltype', 'สังกัดสถานศึกษา'], ['check_typearea', 'typearea'],
    ['nation', 'สัญชาติ'], ['need_fluoride', 'ความจำเป็นทาฟลูออไรด์'],
    ['need_scaling', 'ความจำเป็นขูดหินน้ำลาย'], ['result', 'ผลตามเกณฑ์ (จาก HDC)']
  ];

  var SEX_LABEL = {'1': 'ชาย', '2': 'หญิง'};
  var GUM_STATUS_LABEL = {'0': 'ปกติ', '1': 'เลือดออก/เหงือกอักเสบ',
                          '2': 'มีหินน้ำลาย', '3': 'ปริทันต์อักเสบ', '9': 'ตรวจไม่ได้'};
  var MAX_CATEGORIES = 12, HIST_BINS = 12;

  var num = E.num;
  var round2 = function (v) { return EN.round(v, 2); };

  /** แปลง DESCRIPTION แบบ "1=ในหน่วยบริการ, 2=นอกหน่วยบริการ" เป็น map */
  function codeLabels(dictionary) {
    var out = {};
    for (var name in dictionary) {
      if (!Object.prototype.hasOwnProperty.call(dictionary, name)) continue;
      var desc = String((dictionary[name] || {}).description || '');
      var pairs = {}, n = 0, re = /(\w+)\s*=\s*([^,;]+)/g, m;
      while ((m = re.exec(desc))) { pairs[m[1].trim()] = m[2].trim(); n++; }
      if (n >= 2) out[String(name).toLowerCase()] = pairs;
    }
    if (!out.sex) out.sex = SEX_LABEL;
    out.gum_status = GUM_STATUS_LABEL;
    return out;
  }

  // ---- 1. ค่าผิดปกติ / ขัดแย้งกันเอง ----------------------------------------

  var TOOTH_COLS = ['pteeth', 'pcaries', 'pfilling', 'pextract',
                    'dteeth', 'dcaries', 'dfilling', 'dextract',
                    'need_sealant', 'need_pfilling', 'need_dfilling',
                    'need_pextract', 'need_dextract'];

  function ruleMasks(rows, profile) {
    var have = {}, out = [], i;
    if (rows.length) for (var k in rows[0]) have[k] = 1;
    var n = rows.length;

    function add(name, desc, fn) {
      var m = new Uint8Array(n);
      for (var j = 0; j < n; j++) m[j] = fn(rows[j]) ? 1 : 0;
      out.push({name: name, desc: desc, mask: m});
    }

    var teeth = TOOTH_COLS.filter(function (c) { return have[c]; });
    if (teeth.length) {
      add('จำนวนซี่ฟันติดลบ', 'ค่าในช่องนับซี่ฟัน < 0 (เป็นไปไม่ได้)', function (r) {
        for (var t = 0; t < teeth.length; t++) {
          var v = num(r[teeth[t]]);
          if (v !== null && v < 0) return true;
        }
        return false;
      });
    }
    if (have.pteeth) {
      add('ฟันแท้เกิน 32 ซี่', 'pteeth > 32',
          function (r) { var v = num(r.pteeth); return v !== null && v > 32; });
    }
    if (have.dteeth) {
      add('ฟันน้ำนมเกิน 20 ซี่', 'dteeth > 20',
          function (r) { var v = num(r.dteeth); return v !== null && v > 20; });
    }
    if (have.pcaries && have.pfilling && have.pteeth) {
      add('ฟันแท้ผุ+อุด มากกว่าฟันที่มีอยู่', 'pcaries + pfilling > pteeth', function (r) {
        var t = num(r.pteeth);
        return t !== null && (num(r.pcaries) || 0) + (num(r.pfilling) || 0) > t;
      });
    }
    if (have.dcaries && have.dfilling && have.dteeth) {
      add('ฟันน้ำนมผุ+อุด มากกว่าฟันที่มีอยู่', 'dcaries + dfilling > dteeth', function (r) {
        var t = num(r.dteeth);
        return t !== null && (num(r.dcaries) || 0) + (num(r.dfilling) || 0) > t;
      });
    }
    if (have.gum) {
      add('รหัส GUM ไม่ใช่ 6 หลัก', 'ต้องเป็นตัวเลข 0-3 หรือ 9 จำนวน 6 ตัว', function (r) {
        return r.gum !== null && r.gum !== undefined && !/^[0-39]{6}$/.test(String(r.gum));
      });
    }
    if (have.date_serv && have.birth) {
      add('วันที่ตรวจก่อนวันเกิด', 'date_serv < birth', function (r) {
        return !!(r.date_serv && r.birth && r.date_serv < r.birth);
      });
      var today = new Date();
      add('วันที่ตรวจอยู่ในอนาคต', 'date_serv > วันนี้', function (r) {
        return !!(r.date_serv && r.date_serv > today);
      });
    }
    if (have.age && profile) {
      var note = profile.age_clamp
        ? 'คำนวณจาก date_serv - birth (ปรับเข้าช่วงให้แล้ว ยังนับในรายงาน)'
        : 'คำนวณจาก date_serv - birth';
      add('อายุขณะตรวจนอกช่วง ' + profile.age_min + '-' + profile.age_max + ' ปี', note,
        function (r) {
          var a = num(r.age);
          return !!r.examined && a !== null && (a < profile.age_min || a > profile.age_max);
        });
    }
    if (have.providertype) {
      add('ผู้ตรวจไม่ใช่ทันตแพทย์/ทันตาภิบาล', 'providertype ไม่ใช่ 02 หรือ 06', function (r) {
        var p = r.providertype;
        return !!r.examined && p !== null && p !== undefined &&
               String(p) !== '02' && String(p) !== '06';
      });
    }
    if (have.agegroup && have.age) {
      add('อายุไม่ตรงกับ agegroup ในไฟล์', 'เช่น agegroup=a0-2 แต่คำนวณได้ 3 ปี', function (r) {
        var m2 = /(\d+)\s*-\s*(\d+)/.exec(String(r.agegroup || ''));
        if (!m2) return false;
        var a = num(r.age);
        return !!r.examined && a !== null && (a < +m2[1] || a > +m2[2]);
      });
    }
    // ตรวจคนซ้ำ: ใช้ CID ได้เฉพาะเมื่อไม่ได้ถูกปิดบัง (HDC มักส่งมาเป็น 1369901xxxx****)
    if (have.cid) {
      var masked = 0, withCid = 0;
      for (i = 0; i < n; i++) {
        var c = rows[i].cid;
        if (c === null || c === undefined) continue;
        withCid++;
        if (String(c).indexOf('*') >= 0) masked++;
      }
      if (n && masked / n < 0.5) {
        var cidCount = {};
        for (i = 0; i < n; i++) {
          var cv = rows[i].cid;
          if (cv === null || cv === undefined) continue;
          cidCount[cv] = (cidCount[cv] || 0) + 1;
        }
        add('เลขบัตรประชาชนซ้ำ', 'อาจเป็นคนเดียวกันถูกบันทึกหลายครั้ง', function (r) {
          return r.cid !== null && r.cid !== undefined && cidCount[r.cid] > 1;
        });
      }
    }
    if (have.hoscode && have.pid) {
      var keyCount = {};
      for (i = 0; i < n; i++) keyCount[rows[i].hoscode + '|' + rows[i].pid] =
        (keyCount[rows[i].hoscode + '|' + rows[i].pid] || 0) + 1;
      add('PID ซ้ำในหน่วยบริการเดียวกัน',
          'hoscode + pid ซ้ำ — อาจเป็นคนเดียวกันถูกบันทึกหลายครั้ง',
          function (r) { return keyCount[r.hoscode + '|' + r.pid] > 1; });
    }
    return out;
  }

  function anomalies(rows, profile) {
    var n = rows.length, anyBad = new Uint8Array(n), rules = [];
    ruleMasks(rows, profile).forEach(function (r) {
      var cnt = 0;
      for (var i = 0; i < n; i++) if (r.mask[i]) { cnt++; anyBad[i] = 1; }
      rules.push({name: r.name, desc: r.desc, count: cnt,
                  pct: n ? round2(100 * cnt / n) : null});
    });
    // จำนวนเท่ากันให้เรียงตามชื่อ ลำดับจะได้คงที่ทุกครั้ง
    rules.sort(function (a, b) {
      return b.count - a.count || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var bad = 0;
    for (var i = 0; i < n; i++) if (anyBad[i]) bad++;
    // ฝั่ง Python ค่านี้คำนวณบน np.int64 จึงปัดเศษแบบ numpy (ดู Engine.roundNp)
    return {rules: rules, rows_with_issue: bad, rows_total: n,
            pct: n ? EN.roundNp(100 * bad / n, 2) : null};
  }

  // ---- 2. การกระจายของค่าตัวเลข ---------------------------------------------

  /** quantile แบบเดียวกับ pandas (interpolation = linear) */
  function quantile(sorted, q) {
    var n = sorted.length;
    if (!n) return null;
    var pos = (n - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    if (lo === hi) return sorted[lo];
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  function numericProfile(rows) {
    var out = [];
    NUMERIC_CANDIDATES.forEach(function (pair) {
      var col = pair[0], label = pair[1];
      if (!rows.length || !(col in rows[0])) return;
      var s = [];
      for (var i = 0; i < rows.length; i++) {
        var v = num(rows[i][col]);
        if (v !== null) s.push(v);
      }
      if (!s.length) return;
      s.sort(function (a, b) { return a - b; });

      var q1 = quantile(s, 0.25), med = quantile(s, 0.5), q3 = quantile(s, 0.75);
      var iqr = q3 - q1, loF = q1 - 1.5 * iqr, hiF = q3 + 1.5 * iqr;
      var lo = s[0], hi = s[s.length - 1];

      var inside = [], outHi = 0, outLo = 0, zero = 0, neg = 0, extreme = 0, inIqr = 0;
      var sum = 0;
      for (i = 0; i < s.length; i++) {
        var v2 = s[i];
        sum += v2;
        if (v2 > hiF) outHi++;
        else if (v2 < loF) outLo++;
        else inside.push(v2);
        if (v2 === 0) zero++;
        if (v2 < 0) neg++;
        if (v2 === lo || v2 === hi) extreme++;
        if (v2 >= q1 && v2 <= q3) inIqr++;
      }
      var mean = sum / s.length, varsum = 0;
      for (i = 0; i < s.length; i++) varsum += (s[i] - mean) * (s[i] - mean);
      var sd = s.length > 1 ? Math.sqrt(varsum / s.length) : 0.0;   // ddof=0

      var hist;
      if (hi > lo) {
        var span = hi - lo;
        var bins = Number.isInteger(span) ? Math.min(HIST_BINS, span + 1) : HIST_BINS;
        bins = Math.max(1, bins);
        var counts = new Array(bins).fill(0), width = span / bins;
        for (i = 0; i < s.length; i++) {
          var idx = Math.floor((s[i] - lo) / width);
          if (idx >= bins) idx = bins - 1;             // ขอบบนสุดรวมอยู่แท่งสุดท้าย
          if (idx < 0) idx = 0;
          counts[idx]++;
        }
        hist = counts.map(function (c, j) {
          return {from: round2(lo + width * j), to: round2(lo + width * (j + 1)), count: c};
        });
      } else {
        hist = [{from: lo, to: hi, count: s.length}];
      }

      out.push({
        column: col, label: label, n: s.length, mean: round2(mean), sd: round2(sd),
        min: lo, q1: round2(q1), median: round2(med), q3: round2(q3), max: hi,
        whisker_lo: inside.length ? inside[0] : lo,
        whisker_hi: inside.length ? inside[inside.length - 1] : hi,
        outliers_hi: outHi, outliers_lo: outLo,
        outlier_pct: round2(100 * (outHi + outLo) / s.length),
        outlier_n: outHi + outLo,
        zero_pct: EN.round(100 * zero / s.length, 1), zero_n: zero,
        neg_n: neg, extreme_n: extreme, iqr_n: inIqr, hist: hist
      });
    });
    return out;
  }

  // ---- 3. ความถี่ของตัวแปรหมวดหมู่ ------------------------------------------

  function categoricalProfile(rows, labels) {
    var n = rows.length, out = [];
    CATEGORICAL_CANDIDATES.forEach(function (pair) {
      var col = pair[0], label = pair[1];
      if (!n || !(col in rows[0])) return;
      var counts = {}, order = [], missing = 0;
      for (var i = 0; i < n; i++) {
        var v = rows[i][col];
        if (v === null || v === undefined || v === '') { missing++; continue; }
        var key = String(v);
        if (counts[key] === undefined) { counts[key] = 0; order.push(key); }
        counts[key]++;
      }
      if (!order.length) return;
      // เรียงจำนวนมาก->น้อย ถ้าเท่ากันเรียงตามชื่อค่า (ให้ตรงกับฝั่ง Python
      // ซึ่ง value_counts ใช้ quicksort ลำดับของค่าที่เท่ากันจึงไม่คงที่)
      order.sort(function (a, b) {
        return counts[b] - counts[a] || (a < b ? -1 : a > b ? 1 : 0);
      });
      var lut = labels[col] || {}, items = [];
      order.slice(0, MAX_CATEGORIES).forEach(function (v) {
        items.push({value: v, label: lut[v] || '', count: counts[v],
                    pct: n ? round2(100 * counts[v] / n) : null});
      });
      var rest = 0;
      order.slice(MAX_CATEGORIES).forEach(function (v) { rest += counts[v]; });
      if (rest) {
        items.push({value: 'อื่น ๆ (' + (order.length - MAX_CATEGORIES) + ' ค่า)',
                    label: '', count: rest, pct: n ? round2(100 * rest / n) : null});
      }
      out.push({column: col, label: label, distinct: order.length, missing: missing,
                missing_pct: n ? round2(100 * missing / n) : null, items: items});
    });
    return out;
  }

  // ---- 4. heatmap เทียบพื้นที่ ------------------------------------------------

  function heatmap(areaRows, level, labels) {
    var cf = (labels || {}).caries_free_label || 'ปราศจากฟันผุ';
    var metrics = [
      {key: 'examined_pct', label: '%ได้รับการตรวจ', good: 'high', unit: '%'},
      {key: 'qualified_pct', label: '%ผ่านเกณฑ์คุณภาพ', good: 'high', unit: '%'},
      {key: 'caries_free_pct', label: '%' + cf, good: 'high', unit: '%'},
      {key: 'dmft', label: 'ผุถอนอุดเฉลี่ย', good: 'low', unit: ''}
    ];
    var data = areaRows.filter(function (r) { return (r.examined || 0) > 0; });
    if (!data.length) return {metrics: [], rows: []};

    metrics.forEach(function (m) {
      var vals = data.map(function (r) { return r[m.key]; })
                     .filter(function (v) { return typeof v === 'number'; });
      m.min = vals.length ? round2(Math.min.apply(null, vals)) : null;
      m.max = vals.length ? round2(Math.max.apply(null, vals)) : null;
    });

    return {
      level: level, metrics: metrics,
      rows: data.map(function (r) {
        return {
          code: r.code || '', name: r.name || '', target: r.target,
          cells: metrics.map(function (m) {
            var v = r[m.key], score = null;
            if (typeof v === 'number' && m.min !== null && m.max !== null && m.max !== m.min) {
              var t = (v - m.min) / (m.max - m.min);
              score = EN.round(m.good === 'high' ? t : 1 - t, 3);
            }
            return {value: v, score: score};
          })
        };
      })
    };
  }

  function build(pop, scoped, profile, areaRows, level, dictionary, overviewLabels) {
    var labels = codeLabels(dictionary || {});
    return {
      n_pop: pop.length, n_scoped: scoped.length,
      anomalies: anomalies(pop, profile),
      numeric: numericProfile(scoped),
      categorical: categoricalProfile(scoped, labels),
      heatmap: heatmap(areaRows, level, overviewLabels)
    };
  }

  // ---- รายชื่อเบื้องหลังตัวเลขในหน้าสำรวจข้อมูล ------------------------------

  var VALUE_COLS = [
    ['_value', 'ค่าที่เลือก'],
    ['hoscode', 'รหัสหน่วยบริการ'], ['hosname', 'หน่วยบริการ'], ['ampname', 'อำเภอ'],
    ['pid', 'PID'], ['cid', 'เลขบัตรประชาชน'], ['name', 'ชื่อ'], ['lname', 'นามสกุล'],
    ['sex_label', 'เพศ'], ['birth_str', 'วันเกิด'], ['age', 'อายุขณะตรวจ (ปี)'],
    ['date_str', 'วันที่ตรวจ'], ['provider_label', 'ผู้ตรวจ'],
    ['pteeth', 'ฟันแท้ที่มี (ซี่)'], ['dteeth', 'ฟันน้ำนมที่มี (ซี่)'],
    ['addr', 'บ้านเลขที่'], ['tumbonname', 'ตำบล']
  ];

  var VALUE_SELECTIONS = {
    all: 'ทุกแถวที่มีค่า',
    outlier: 'ค่าที่หลุดออกนอกหนวด (outlier)',
    zero: 'ค่าที่เป็นศูนย์',
    neg: 'ค่าที่ติดลบ (เป็นไปไม่ได้)',
    extreme: 'ค่าต่ำสุดและสูงสุด',
    iqr: 'ค่าที่อยู่ในกล่อง Q1–Q3',
    range: 'ค่าที่อยู่ในช่วงที่เลือกจากกราฟ'
  };

  /** ต้องใช้ข้อมูลชุดเดียวกับ eda() และคำนวณ IQR วิธีเดียวกัน ยอดจึงตรงกันเสมอ */
  function valueList(ds, profile, col, sel, opts) {
    opts = opts || {};
    var scoped = EN.applyScope(S.filterArea(ds.rows, opts.pv, opts.amp, opts.hos), profile);
    if (!scoped.length || !(col in scoped[0])) return {columns: [], rows: []};

    var vals = scoped.map(function (r) { return num(r[col]); });
    var present = vals.filter(function (v) { return v !== null; }).sort(function (a, b) { return a - b; });
    if (!present.length) return {columns: [], rows: []};

    var lo = present[0], hi = present[present.length - 1];
    var q1 = quantile(present, 0.25), q3 = quantile(present, 0.75), iqr = q3 - q1;
    var keep;

    if (sel === 'zero') keep = function (v) { return v === 0; };
    else if (sel === 'neg') keep = function (v) { return v < 0; };
    else if (sel === 'extreme') keep = function (v) { return v === lo || v === hi; };
    else if (sel === 'outlier') keep = function (v) { return v < q1 - 1.5 * iqr || v > q3 + 1.5 * iqr; };
    else if (sel === 'iqr') keep = function (v) { return v >= q1 && v <= q3; };
    else if (sel === 'range') {
      keep = function (v) {
        if (opts.lo !== null && opts.lo !== undefined && v < +opts.lo) return false;
        if (opts.hi === null || opts.hi === undefined) return true;
        // แท่งกราฟใช้ขอบบนแบบไม่รวม (ยกเว้นแท่งสุดท้าย) ไม่งั้นค่าตรงขอบถูกนับซ้ำ 2 แท่ง
        return opts.hiExclusive ? v < +opts.hi : v <= +opts.hi;
      };
    } else keep = function () { return true; };

    var picked = [];
    for (var i = 0; i < scoped.length; i++) {
      if (vals[i] === null || !keep(vals[i])) continue;
      var r = Object.assign({}, scoped[i]);
      r._value = vals[i];
      picked.push(r);
    }
    picked.forEach(function (r) { S.addPersonFields(r); });
    var res = S.select(picked, VALUE_COLS, [], opts.raw ? ds.header : null);
    var first = res.columns[0];
    var asc = sel === 'neg';
    res.rows.sort(function (a, b) {
      return asc ? (a[first] - b[first]) : (b[first] - a[first]);
    });
    return res;
  }

  root.Eda = {
    build: build, anomalies: anomalies, numericProfile: numericProfile,
    categoricalProfile: categoricalProfile, heatmap: heatmap, codeLabels: codeLabels,
    valueList: valueList, quantile: quantile,
    NUMERIC_CANDIDATES: NUMERIC_CANDIDATES, VALUE_SELECTIONS: VALUE_SELECTIONS
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
