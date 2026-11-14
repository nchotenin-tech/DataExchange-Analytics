/* =============================================================================
 * เขียนไฟล์ส่งออก — CSV และ Excel (.xlsx) โดยไม่ใช้ไลบรารีภายนอก
 *
 * .xlsx คือไฟล์ zip ที่ข้างในเป็น XML — เราเขียน zip แบบ "ไม่บีบอัด" (method 0)
 * จึงไม่ต้องมีตัวบีบอัด ไฟล์ใหญ่กว่าปกติบ้างแต่ Excel เปิดได้ปกติ
 * ========================================================================== */
(function (root) {
  'use strict';

  // ---- CRC32 ---------------------------------------------------------------
  var CRC_TABLE = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  var utf8 = function (s) { return new TextEncoder().encode(s); };

  /** สร้างไฟล์ zip แบบไม่บีบอัดจาก [{name, data:Uint8Array}] */
  function zipStore(entries) {
    var parts = [], central = [], offset = 0;

    function u16(v) { return [v & 0xFF, (v >> 8) & 0xFF]; }
    function u32(v) {
      return [v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF];
    }

    entries.forEach(function (e) {
      var name = utf8(e.name), data = e.data, crc = crc32(data);
      // ธง bit 11 = ชื่อไฟล์เป็น UTF-8
      var local = [].concat(u32(0x04034b50), u16(20), u16(0x0800), u16(0),
                            u16(0), u16(0), u32(crc), u32(data.length),
                            u32(data.length), u16(name.length), u16(0));
      parts.push(new Uint8Array(local), name, data);
      central.push([].concat(u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0),
                             u16(0), u16(0), u32(crc), u32(data.length), u32(data.length),
                             u16(name.length), u16(0), u16(0), u16(0), u16(0),
                             u32(0), u32(offset)));
      central[central.length - 1]._name = name;
      offset += local.length + name.length + data.length;
    });

    var cdStart = offset, cd = [];
    central.forEach(function (c) {
      cd.push(new Uint8Array(c), c._name);
      offset += c.length + c._name.length;
    });
    var end = [].concat(u32(0x06054b50), u16(0), u16(0), u16(entries.length),
                        u16(entries.length), u32(offset - cdStart), u32(cdStart), u16(0));

    var all = parts.concat(cd, [new Uint8Array(end)]);
    var total = all.reduce(function (n, a) { return n + a.length; }, 0);
    var out = new Uint8Array(total), at = 0;
    all.forEach(function (a) { out.set(a, at); at += a.length; });
    return out;
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      // อักขระควบคุมทำให้ Excel แจ้งว่าไฟล์เสีย
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
  }

  function colName(i) {
    var s = '';
    i += 1;
    while (i > 0) {
      var r = (i - 1) % 26;
      s = String.fromCharCode(65 + r) + s;
      i = Math.floor((i - 1) / 26);
    }
    return s;
  }

  function sheetXml(rows) {
    var out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
      '<sheetData>'];
    for (var r = 0; r < rows.length; r++) {
      out.push('<row r="' + (r + 1) + '">');
      var row = rows[r];
      for (var c = 0; c < row.length; c++) {
        var v = row[c];
        if (v === null || v === undefined || v === '') continue;
        var ref = colName(c) + (r + 1);
        if (typeof v === 'number' && isFinite(v)) {
          out.push('<c r="' + ref + '"><v>' + v + '</v></c>');
        } else {
          out.push('<c r="' + ref + '" t="inlineStr"><is><t xml:space="preserve">' +
                   esc(v) + '</t></is></c>');
        }
      }
      out.push('</row>');
    }
    out.push('</sheetData></worksheet>');
    return out.join('');
  }

  /** ชื่อชีตของ Excel ห้ามเกิน 31 ตัวและห้ามมีอักขระบางตัว */
  function safeSheetName(name, used) {
    var s = String(name || 'Sheet').replace(/[\\\/\?\*\[\]:]/g, '-').slice(0, 31) || 'Sheet';
    var base = s, n = 2;
    while (used[s]) { s = (base.slice(0, 28) + '_' + n).slice(0, 31); n++; }
    used[s] = 1;
    return s;
  }

  /** sheets = [{name, rows:[[...]]}] -> Uint8Array ของไฟล์ .xlsx */
  function buildXlsx(sheets) {
    var used = {};
    sheets = sheets.map(function (s) {
      return {name: safeSheetName(s.name, used), rows: s.rows};
    });

    var types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
      '<Default Extension="xml" ContentType="application/xml"/>',
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'];
    sheets.forEach(function (s, i) {
      types.push('<Override PartName="/xl/worksheets/sheet' + (i + 1) +
        '.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>');
    });
    types.push('</Types>');

    var wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"',
      ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'];
    sheets.forEach(function (s, i) {
      wb.push('<sheet name="' + esc(s.name) + '" sheetId="' + (i + 1) +
              '" r:id="rId' + (i + 1) + '"/>');
    });
    wb.push('</sheets></workbook>');

    var wbRels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'];
    sheets.forEach(function (s, i) {
      wbRels.push('<Relationship Id="rId' + (i + 1) +
        '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"' +
        ' Target="worksheets/sheet' + (i + 1) + '.xml"/>');
    });
    wbRels.push('</Relationships>');

    var files = [
      {name: '[Content_Types].xml', data: utf8(types.join(''))},
      {name: '_rels/.rels', data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
        '</Relationships>')},
      {name: 'xl/workbook.xml', data: utf8(wb.join(''))},
      {name: 'xl/_rels/workbook.xml.rels', data: utf8(wbRels.join(''))}
    ];
    sheets.forEach(function (s, i) {
      files.push({name: 'xl/worksheets/sheet' + (i + 1) + '.xml', data: utf8(sheetXml(s.rows))});
    });
    return zipStore(files);
  }

  function csvCell(v) {
    if (v === null || v === undefined) return '';
    var s = String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  /** CSV พร้อม BOM เพื่อให้ Excel ภาษาไทยเปิดแล้วไม่เป็นตัวต่างดาว */
  function buildCsv(rows) {
    return '﻿' + rows.map(function (r) {
      return r.map(csvCell).join(',');
    }).join('\r\n');
  }

  function download(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function saveXlsx(sheets, filename) {
    download(new Blob([buildXlsx(sheets)], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    }), filename);
  }

  function saveCsv(rows, filename) {
    download(new Blob([buildCsv(rows)], {type: 'text/csv;charset=utf-8'}), filename);
  }

  root.Save = {buildXlsx: buildXlsx, buildCsv: buildCsv, saveXlsx: saveXlsx,
               saveCsv: saveCsv, download: download, crc32: crc32, zipStore: zipStore};
})(typeof globalThis !== 'undefined' ? globalThis : this);
