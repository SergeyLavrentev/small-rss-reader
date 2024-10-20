# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['mini_rss_reader.py'],
    pathex=[],
    binaries=[],
    datas=[('icons/splash.png', 'icons'), ('icons/rss_icon.png', 'icons')],
    hiddenimports=['PyQt5.QtWebEngineWidgets'],
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
    [],
    exclude_binaries=True,
    name='Small RSS Reader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/rss_icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Small RSS Reader',
)
app = BUNDLE(
    coll,
    name='Small RSS Reader.app',
    icon='icons/rss_icon.icns',
    bundle_identifier=None,
)
