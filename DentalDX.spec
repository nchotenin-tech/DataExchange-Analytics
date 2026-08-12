# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — สร้าง exe เดียว
#   สำคัญ: bundle เฉพาะ templates/static เท่านั้น
#   profiles/, data/, reference/ ต้องอยู่ "นอก" exe เพื่อให้ผู้ใช้แก้/วางไฟล์เองได้

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=[
        'openpyxl', 'openpyxl.cell._writer',
        'yaml',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # ตัดของหนักที่ไม่ได้ใช้ออก เพื่อให้ exe เล็กลง
        'pyarrow',                       # cache จะใช้ .pkl แทน
        'matplotlib', 'scipy', 'numpy.f2py',
        'IPython', 'jupyter', 'notebook', 'nbformat',
        'tkinter', 'PyQt5', 'PySide2', 'PIL',
        'sqlalchemy', 'pytest', 'setuptools._distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DentalDX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # แสดงหน้าต่าง console ไว้ปิดโปรแกรม (เปลี่ยนเป็น False ถ้าไม่ต้องการ)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
