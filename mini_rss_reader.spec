# mini_rss_reader.spec
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all
import sys
import os

block_cipher = None

# Define the path to your main script
main_script = 'mini_rss_reader.py'

# Collect data files (icons)
datas = [
    ('icons/*', 'icons'),  # Include all files in the 'icons' directory
]

# Analysis
a = Analysis(
    [main_script],
    pathex=[],  # Add paths if your modules are in different directories
    binaries=[],
    datas=datas,
    hiddenimports=[],  # Add any hidden imports here
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PYZ
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# EXE
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmallRSSReader',  # Name of the executable
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to False for a windowed app without console
    icon='icons/rss_icon.png'  # Path to your application icon
)

# COLLECT
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmallRSSReader'  # Name of the output directory
)

