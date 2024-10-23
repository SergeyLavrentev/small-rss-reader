from setuptools import setup
import sys
import os
from PyQt5 import QtCore

APP = ['small_rss_reader.py']
DATA_FILES = [
    ('icons', [
        'icons/splash.png',
        'icons/rss_icon.png',
        'icons/rss_tray_icon.png',
        'icons/rss_icon.icns',
    ]),
]

# Locate Qt plugins (if needed)
qt_plugins_dir = os.path.join(QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.PluginsPath))

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icons/rss_icon.icns',
    'packages': ['PyQt5'],
    'includes': [
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
    ],
    'excludes': ['packaging', 'python_dateutil'],
    'plist': {
        'CFBundleName': 'SmallRSSReader',
        'CFBundleIdentifier': 'com.rocker.SmallRSSReader',
        'CFBundleIconFile': 'rss_icon.icns',
        'LSUIElement': True,
        'CFBundleVersion': '4.1.0',
        'LSUIElement': False,  # Set to False so that the app appears in the Dock
        'NSPrincipalClass': 'NSApplication'
    },
    'verbose': True,
    'compressed': True
}

setup(
    app=APP,
    name='SmallRSSReader',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
