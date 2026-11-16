<!-- internal-doc — เอกสารสำหรับผู้พัฒนา ไม่ต้องแพ็กไปกับ release -->

# เว็บแอป (HTML ไฟล์เดียว)

เวอร์ชันที่ทำงานในเบราว์เซอร์ทั้งหมด ไม่ต้องติดตั้ง ไม่ถูก Windows บล็อก

**ไม่ใช้ไลบรารีภายนอกเลยตอนรันจริง** — อ่าน `.xlsx` เองด้วย `DecompressionStream`
ที่มากับเบราว์เซอร์ (ยกมาจากโครงการพี่น้อง
[ohsp-data-ex](https://github.com/nchotenin-tech/ohsp-data-ex))

## โครงสร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `src/00-xlsx.js` | อ่านไฟล์ `.xlsx` (แตก zip + อ่าน XML แบบสตรีม) |
| `src/01-expr.js` | แปล expression ของ profile YAML — เขียนตัวแยกวิเคราะห์เอง เพราะ CSP ห้ามใช้ `eval` |
| `src/02-data.js` | ทำความสะอาดข้อมูล + คำนวณคอลัมน์ (อายุ, GUM, dmft) |
| `src/03-engine.js` | สร้างตารางที่ 1-7 จาก profile |
| `src/04-service.js` | ภาพรวมรายอำเภอ/หน่วยบริการ + รายชื่อเด็กที่ต้องติดตาม |
| `src/05-yaml.js` | อ่าน `profiles/*.yaml` (js-yaml, MIT) |
| `src/06-save.js` | เขียนไฟล์ `.xlsx` / `.csv` เอง (zip แบบไม่บีบอัด) |
| `src/08-eda.js` | สำรวจข้อมูล (EDA) — ค่าผิดปกติ 13 กฎ, boxplot, ความถี่, heatmap |
| `src/07-app.js` | ต่อหน้า dashboard เดิมเข้ากับการคำนวณในเครื่อง |

หน้าจอใช้ `templates/index.html` ของเวอร์ชัน `.exe` **ชุดเดิมทั้งหมด**
`build_webapp.py` แค่เปลี่ยน `api()` จากยิงไป Flask เป็นคำนวณในเครื่อง
และตัดแท็บถาม-ตอบ (AI) ออก

## คำสั่ง

```bash
python web/build_webapp.py        # -> dist/DentalDX-Dashboard-vX.Y.Z.html
python web/make_package.py        # -> dist/Dashboard-Exam-vX.Y.Z.zip
```

## การทดสอบ

**หัวใจคือ `parity_test.mjs`** — ตัวเลขฝั่งเว็บต้องตรงกับเวอร์ชัน Python ทุกค่า

```bash
cd web && npm install            # jsdom (ใช้เฉพาะตอนทดสอบ)

# สร้างข้อมูลตัวอย่าง (สมมติทั้งหมด) แล้วเทียบผล
python web/make_test_data.py /tmp/sample --rows 4000
DENTALDX_DATA=/tmp/sample python web/dump_python_ref.py /tmp/ref.json
node web/parity_test.mjs /tmp/sample profiles reference/hospitals.csv /tmp/ref.json

# ค่าผิดรูปแบบ + ไฟล์ใหญ่
python web/make_test_data.py /tmp/big --rows 40 --big 100000
SAMPLE_DIR=/tmp/big BIG_XLSX="/tmp/big/big/sample big.xlsx" node web/edge_test.mjs

# ไฟล์ HTML ที่ build แล้ว (DOM จำลอง)
cd web && DX_DATA=/tmp/sample node browser_test.mjs
```

ทดสอบกับข้อมูลจริงได้ด้วย (ข้อมูลจริง commit ไม่ได้)

```bash
python web/dump_python_ref.py /tmp/real.json
node web/parity_test.mjs data profiles reference/hospitals.csv /tmp/real.json
```

## กับดักที่เคยเจอ — อย่าพลาดซ้ำ

- **ห้ามอ่านค่าแปลกให้ "ฉลาดกว่า" ของเดิม** ค่าที่ `pandas` อ่านไม่ออกต้องเป็นค่าว่าง
  เหมือนกันเป๊ะ ไม่งั้นตัวเลขในรายงานราชการเปลี่ยนโดยไม่มีใครรู้ตัว
  (`"๒"` เลขไทย, `"20 ซี่"`, `"1,234"` → ค่าว่างทั้งหมด) — ค่าพวกนี้จะถูกนับไว้
  ใน `DataIO.issues()` เพื่อเตือนผู้ใช้แทน
- **`pandas` เดารูปแบบวันที่จากค่าแรกของคอลัมน์** แถวที่เขียนคนละแบบกลายเป็น `NaT`
  `normalizeRows()` จึงต้องทำแบบเดียวกัน ไม่ใช่แปลงทีละแถวอิสระ
- **`round()` ของ Python ปัดครึ่งไปหาเลขคู่** (66.625 → 66.62) ไม่ใช่ `Math.round`
  ที่ปัดขึ้นเสมอ และห้ามคูณ `10^d` ก่อนปัด (10.205 × 100 = 1020.4999…) —
  `Engine.round()` ปัดจากสตริงฐานสิบด้วย `BigInt`
- **ปี พ.ศ. ในคอลัมน์วันที่** ของเดิมได้ `NaT` (เกินขอบเขต `datetime64`) จึงต้องเป็น
  ค่าว่างเหมือนกัน ไม่แปลงเป็น ค.ศ. ให้เอง
- คอลัมน์ที่ไม่มีอยู่จริงในข้อมูลต้องไม่โผล่ในตารางรายชื่อ (เช่น "กลุ่มอายุ"
  มีเฉพาะกลุ่ม 0-5 ปี)
- **ข้อมูลที่ใช้เทียบผลต้องสร้างด้วย `--clean`** เพราะ pandas แต่ละเวอร์ชันตีความค่าที่
  เป็นไปไม่ได้ไม่เหมือนกัน เคยทำ CI ล้มมาแล้ว: ปี พ.ศ. `2564-03-05` เครื่องหนึ่งอ่านเป็น
  ค่าว่าง (เกินขอบเขต `datetime64[ns]`) อีกเครื่องอ่านเป็นปี ค.ศ. 2564 ทำให้ยอดกฎ
  "วันที่ตรวจก่อนวันเกิด" ต่างกัน 2 แถว แล้วลำดับกฎเพี้ยนตามไปทั้งชุด
  ค่าผิดรูปแบบไปทดสอบที่ `edge_test.mjs` แทน ซึ่งยืนยัน**พฤติกรรมที่เราเลือกเอง**
  ไม่ใช่ไปผูกกับพฤติกรรมของ pandas เวอร์ชันใดเวอร์ชันหนึ่ง
- กฎใน EDA เรียงตาม (จำนวนมาก→น้อย, ชื่อกฎ) ทั้งสองฝั่ง ถ้าเรียงด้วยจำนวนอย่างเดียว
  กฎที่นับได้เท่ากันจะสลับที่กันเอง
- **`eda.py` คำนวณบน `np.int64` จึงปัดเศษแบบ numpy** ซึ่งต่างจาก `round()` ของ Python
  (9.525 → numpy 9.52, Python 9.53) ใช้ `Engine.roundNp()` เฉพาะ `anomalies.pct`
- `value_counts()` ของ pandas ใช้ quicksort ค่าที่นับได้เท่ากันจึงสลับลำดับได้
  ทั้งสองฝั่งจึงเรียงซ้ำด้วย (จำนวนมาก→น้อย, ชื่อค่า)
- `KEYWORDS['constructor']` ชนกับ `Object.prototype` — `01-expr.js` จึงใช้ `indexOf`
  และเช็ก `hasOwnProperty` ก่อนอ่านคอลัมน์

## ข้อมูลส่วนบุคคล

ข้อมูลรายบุคคลอยู่ใน `DATASETS` ซึ่งเป็นตัวแปรในหน่วยความจำเท่านั้น
`localStorage` เก็บเฉพาะตัวเลขสรุปของรายงานล่าสุด (`07-app.js` → `saveLast`)
`browser_test.mjs` มีการตรวจข้อนี้ให้อัตโนมัติ
