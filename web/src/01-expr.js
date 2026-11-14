/* =============================================================================
 * ตัวแปล expression ของ profile YAML
 *
 * ฝั่ง Python ใช้ pandas.eval ได้เลย แต่ในเบราว์เซอร์เราใช้ eval ไม่ได้
 * เพราะ CSP ปิด 'unsafe-eval' ไว้ (ตั้งใจ — กันโค้ดแปลกปลอมรันจากข้อมูล)
 * จึงต้องเขียนตัวแยกวิเคราะห์เอง รองรับเฉพาะไวยากรณ์ที่ profile ใช้จริง:
 *
 *   dcaries + dfilling + dextract == 0
 *   providertype in ['02','06']
 *   dteeth >= 1 and dteeth <= 20
 *   not (pteeth > 0)
 *
 * ข้อดีที่ตามมา: ไฟล์ profile ที่ผู้ใช้แก้เองจะสั่งอะไรนอกเหนือจากนี้ไม่ได้เลย
 * ========================================================================== */
(function (root) {
  'use strict';

  // ใช้ indexOf ไม่ใช่ object lookup — ไม่งั้น KEYWORDS['constructor'] จะชนกับ
  // Object.prototype แล้วคอลัมน์ชื่อ constructor/toString/valueOf จะแปลผิด
  var KEYWORDS = ['and', 'or', 'not', 'in', 'True', 'False', 'None'];
  var isKeyword = function (w) { return KEYWORDS.indexOf(w) >= 0; };
  var owns = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };

  function tokenize(src) {
    var out = [], i = 0, s = String(src);
    while (i < s.length) {
      var c = s[i];
      if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i++; continue; }
      if (c === '#') { while (i < s.length && s[i] !== '\n') i++; continue; }

      // ข้อความในเครื่องหมายคำพูด เช่น '02'
      if (c === "'" || c === '"') {
        var q = c, buf = '';
        i++;
        while (i < s.length && s[i] !== q) {
          if (s[i] === '\\' && i + 1 < s.length) { buf += s[i + 1]; i += 2; }
          else buf += s[i++];
        }
        if (i >= s.length) throw new Error('ข้อความไม่ปิดเครื่องหมายคำพูด');
        i++;
        out.push({t: 'str', v: buf});
        continue;
      }

      if (c >= '0' && c <= '9') {
        var j = i;
        while (j < s.length && /[0-9.]/.test(s[j])) j++;
        out.push({t: 'num', v: parseFloat(s.slice(i, j))});
        i = j;
        continue;
      }

      if (/[A-Za-z_]/.test(c)) {
        var k = i;
        while (k < s.length && /[A-Za-z0-9_]/.test(s[k])) k++;
        var w = s.slice(i, k);
        out.push({t: isKeyword(w) ? w : 'name', v: w});
        i = k;
        continue;
      }

      var two = s.substr(i, 2);
      if (two === '==' || two === '!=' || two === '>=' || two === '<=') {
        out.push({t: 'op', v: two}); i += 2; continue;
      }
      if ('+-*/%<>()[],'.indexOf(c) >= 0) {
        out.push({t: 'op', v: c}); i++; continue;
      }
      if (c === '&') { out.push({t: 'and'}); i++; continue; }
      if (c === '|') { out.push({t: 'or'}); i++; continue; }
      if (c === '~') { out.push({t: 'not'}); i++; continue; }
      throw new Error('ไม่รู้จักอักขระ "' + c + '" ใน expression');
    }
    return out;
  }

  // ---- ไวยากรณ์ (ไล่จากผูกหลวมไปผูกแน่น) -----------------------------------
  //   or -> and -> not -> comparison -> add -> mul -> unary -> primary
  function parse(src) {
    var toks = tokenize(src), pos = 0;

    function peek() { return toks[pos]; }
    function eat(t, v) {
      var x = toks[pos];
      if (!x || x.t !== t || (v !== undefined && x.v !== v)) return null;
      pos++;
      return x;
    }
    function expect(t, v) {
      var x = eat(t, v);
      if (!x) throw new Error('คาดว่าจะเจอ "' + (v || t) + '" ใน expression');
      return x;
    }

    function parseOr() {
      var left = parseAnd();
      while (eat('or')) left = {k: 'or', a: left, b: parseAnd()};
      return left;
    }
    function parseAnd() {
      var left = parseNot();
      while (eat('and')) left = {k: 'and', a: left, b: parseNot()};
      return left;
    }
    function parseNot() {
      if (eat('not')) return {k: 'not', a: parseNot()};
      return parseCmp();
    }
    function parseCmp() {
      var left = parseAdd();
      for (;;) {
        if (eat('in')) {
          expect('op', '[');
          var items = [];
          if (!eat('op', ']')) {
            do { items.push(parseAdd()); } while (eat('op', ','));
            expect('op', ']');
          }
          left = {k: 'in', a: left, list: items};
          continue;
        }
        var o = peek();
        if (o && o.t === 'op' && ['==', '!=', '>=', '<=', '>', '<'].indexOf(o.v) >= 0) {
          pos++;
          left = {k: 'cmp', op: o.v, a: left, b: parseAdd()};
          continue;
        }
        return left;
      }
    }
    function parseAdd() {
      var left = parseMul();
      for (;;) {
        var o = peek();
        if (o && o.t === 'op' && (o.v === '+' || o.v === '-')) {
          pos++;
          left = {k: 'bin', op: o.v, a: left, b: parseMul()};
        } else return left;
      }
    }
    function parseMul() {
      var left = parseUnary();
      for (;;) {
        var o = peek();
        if (o && o.t === 'op' && (o.v === '*' || o.v === '/' || o.v === '%')) {
          pos++;
          left = {k: 'bin', op: o.v, a: left, b: parseUnary()};
        } else return left;
      }
    }
    function parseUnary() {
      if (eat('op', '-')) return {k: 'neg', a: parseUnary()};
      if (eat('op', '+')) return parseUnary();
      return parsePrimary();
    }
    function parsePrimary() {
      if (eat('op', '(')) {
        var e = parseOr();
        expect('op', ')');
        return e;
      }
      var n = eat('num');
      if (n) return {k: 'num', v: n.v};
      var s2 = eat('str');
      if (s2) return {k: 'str', v: s2.v};
      if (eat('True')) return {k: 'num', v: 1};
      if (eat('False')) return {k: 'num', v: 0};
      if (eat('None')) return {k: 'null'};
      var id = eat('name');
      if (id) return {k: 'col', v: id.v};
      throw new Error('อ่าน expression ไม่ออกที่ตำแหน่ง ' + pos);
    }

    var ast = parseOr();
    if (pos !== toks.length) throw new Error('มีส่วนเกินท้าย expression');
    return ast;
  }

  // ---- ประเมินผล -----------------------------------------------------------
  // null = ค่าว่าง (เทียบเท่า NaN ของ pandas) — เปรียบเทียบกับค่าว่างได้ false
  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'number') return isNaN(v) ? null : v;
    if (typeof v === 'boolean') return v ? 1 : 0;
    var n = Number(v);
    return isNaN(n) ? null : n;
  }

  function cmp(op, a, b) {
    // เทียบข้อความกับข้อความ เช่น providertype == '02'
    if (typeof a === 'string' || typeof b === 'string') {
      var A = a === null || a === undefined ? null : String(a);
      var B = b === null || b === undefined ? null : String(b);
      if (A === null || B === null) return false;
      switch (op) {
        case '==': return A === B;
        case '!=': return A !== B;
        case '>': return A > B;
        case '<': return A < B;
        case '>=': return A >= B;
        case '<=': return A <= B;
      }
    }
    var x = num(a), y = num(b);
    if (x === null || y === null) return false;
    switch (op) {
      case '==': return x === y;
      case '!=': return x !== y;
      case '>': return x > y;
      case '<': return x < y;
      case '>=': return x >= y;
      case '<=': return x <= y;
    }
    return false;
  }

  function evalNode(node, row) {
    switch (node.k) {
      case 'num': return node.v;
      case 'str': return node.v;
      case 'null': return null;
      case 'col': {
        // ต้องเช็ก hasOwnProperty ไม่งั้นคอลัมน์ชื่อ toString จะได้ฟังก์ชันมา
        if (!owns(row, node.v)) return null;
        var v = row[node.v];
        return v === undefined ? null : v;
      }
      case 'neg': {
        var n0 = num(evalNode(node.a, row));
        return n0 === null ? null : -n0;
      }
      case 'bin': {
        var x = num(evalNode(node.a, row)), y = num(evalNode(node.b, row));
        if (x === null || y === null) return null;
        switch (node.op) {
          case '+': return x + y;
          case '-': return x - y;
          case '*': return x * y;
          case '/': return y === 0 ? null : x / y;
          case '%': return y === 0 ? null : x % y;
        }
        return null;
      }
      case 'cmp': return cmp(node.op, evalNode(node.a, row), evalNode(node.b, row));
      case 'in': {
        var a = evalNode(node.a, row);
        if (a === null || a === undefined) return false;
        var as = String(a);
        for (var i = 0; i < node.list.length; i++) {
          var b = evalNode(node.list[i], row);
          if (b !== null && b !== undefined && String(b) === as) return true;
        }
        return false;
      }
      case 'and': return !!evalNode(node.a, row) && !!evalNode(node.b, row);
      case 'or': return !!evalNode(node.a, row) || !!evalNode(node.b, row);
      case 'not': return !evalNode(node.a, row);
    }
    return null;
  }

  var _cache = Object.create(null);

  function compile(expr) {
    if (expr === null || expr === undefined) return function () { return true; };
    if (typeof expr === 'boolean') return function () { return expr; };
    var key = String(expr);
    if (!_cache[key]) {
      var ast = parse(key);
      _cache[key] = function (row) { return evalNode(ast, row); };
    }
    return _cache[key];
  }

  /** ค่าของ expression ทุกแถว (อาจเป็นตัวเลขหรือ true/false) */
  function values(rows, expr) {
    var f = compile(expr), out = new Array(rows.length);
    for (var i = 0; i < rows.length; i++) out[i] = f(rows[i]);
    return out;
  }

  /** mask แบบ boolean — ค่าว่างนับเป็น false (เหมือน .fillna(False) ฝั่ง pandas) */
  function mask(rows, expr) {
    var f = compile(expr), out = new Uint8Array(rows.length);
    for (var i = 0; i < rows.length; i++) out[i] = f(rows[i]) ? 1 : 0;
    return out;
  }

  /** ชื่อคอลัมน์ที่ expression นี้อ้างถึง (ใช้ไฮไลต์ช่องที่ทำให้ตกเกณฑ์) */
  function columns(expr) {
    var out = [];
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (n.k === 'col' && out.indexOf(n.v) < 0) out.push(n.v);
      ['a', 'b'].forEach(function (k) { if (n[k]) walk(n[k]); });
      if (n.list) n.list.forEach(walk);
    })(parse(String(expr)));
    return out;
  }

  root.Expr = {parse: parse, compile: compile, values: values, mask: mask,
               columns: columns, num: num};
})(typeof globalThis !== 'undefined' ? globalThis : this);
