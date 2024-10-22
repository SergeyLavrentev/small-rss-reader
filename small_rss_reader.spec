# -*- mode: python ; coding: utf-8 -*-

datas = [
    ('icons/splash.png', 'icons'),
    ('icons/rss_icon.png', 'icons'),
    ('icons/rss_tray_icon.png', 'icons'),
    ('icons/rss_icon.icns', 'icons'),  # Ensure the .icns file is included
]

a = Analysis(
    ['small_rss_reader.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['PyQt5.QtWebEngineWidgets','PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets'],
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
    name='SmallRSSReader',  # Renamed to remove spaces
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
    name='SmallRSSReader',
)

app = BUNDLE(
    coll,
    name='SmallRSSReader.app',  # Changed to remove spaces
    icon='icons/rss_icon.icns',
    bundle_identifier='com.rocker.SmallRSSReader',  # Set correctly
)
