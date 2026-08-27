# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/13631/Documents/GitHub/AirSim_Hybrid_Avoidance/AirSim Hybrid Avoidance_v1/web/webview_app.py'],
    pathex=['C:/Users/13631/Documents/GitHub/AirSim_Hybrid_Avoidance/AirSim Hybrid Avoidance_v1'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'scipy', 'pygame', 'pandas', 'matplotlib', 'gymnasium', 'tqdm'],
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
    name='AirSim控制台',
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
