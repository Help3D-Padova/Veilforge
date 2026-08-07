# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\_JDR_Ressources\\Veilforge 2.7.0\\Veilforge-main\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\_JDR_Ressources\\Veilforge 2.7.0\\Veilforge-main\\assets', 'assets'), ('D:\\_JDR_Ressources\\Veilforge 2.7.0\\Veilforge-main\\HELP_README.md', '.'), ('D:\\_JDR_Ressources\\Veilforge 2.7.0\\Veilforge-main\\LICENSE.md', '.')],
    hiddenimports=['fitz', 'pymupdf'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Veilforge 2.7.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
