from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from PyQt5.QtCore import QSettings


PROD_ORG = 'rocker'
PROD_APP = 'SmallRSSReader'
DEV_ORG = 'rocker-dev'
DEV_APP = 'SmallRSSReader-Dev'


def is_dev_mode() -> bool:
    """Return True if we should use a separate dev profile for QSettings.

    Enabled when:
    - SMALL_RSS_DEV=1 environment variable is set
    - Running under pytest (PYTEST_CURRENT_TEST)
    - Process argv contains '--debug'
    """
    try:
        if os.environ.get('SMALL_RSS_DEV') == '1':
            return True
        if os.environ.get('PYTEST_CURRENT_TEST'):
            return True
        # Some tests deliberately remove PYTEST_CURRENT_TEST to exercise the full UI,
        # but we still want an isolated settings profile under pytest.
        if 'pytest' in (sys.modules or {}):
            return True
        if '--debug' in (sys.argv or []):
            return True
    except Exception:
        pass
    return False


def qsettings() -> QSettings:
    """Return QSettings instance for the proper profile (dev/prod)."""
    # Under pytest/tests we must not touch real user settings.
    try:
        if os.environ.get('SMALL_RSS_TESTS') or os.environ.get('PYTEST_CURRENT_TEST') or ('pytest' in (sys.modules or {})):
            test_id = os.environ.get('SMALL_RSS_TEST_ID') or os.environ.get('PYTEST_CURRENT_TEST') or f"pid-{os.getpid()}"
            run_id = os.environ.get('SMALL_RSS_TEST_RUN_ID') or f"pid-{os.getpid()}"
            digest = hashlib.sha1(str(test_id).encode('utf-8', errors='ignore')).hexdigest()[:12]
            base = os.path.join(tempfile.gettempdir(), 'SmallRSSReaderTests', run_id, 'qsettings')
            try:
                os.makedirs(base, exist_ok=True)
            except Exception:
                pass
            ini_path = os.path.join(base, f'settings-{digest}.ini')
            return QSettings(ini_path, QSettings.IniFormat)
    except Exception:
        pass

    if is_dev_mode():
        return QSettings(DEV_ORG, DEV_APP)
    return QSettings(PROD_ORG, PROD_APP)
