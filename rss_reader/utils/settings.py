from __future__ import annotations

import os
import sys
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
        if '--debug' in (sys.argv or []):
            return True
    except Exception:
        pass
    return False


def qsettings() -> QSettings:
    """Return QSettings instance for the proper profile (dev/prod)."""
    if is_dev_mode():
        return QSettings(DEV_ORG, DEV_APP)
    return QSettings(PROD_ORG, PROD_APP)
