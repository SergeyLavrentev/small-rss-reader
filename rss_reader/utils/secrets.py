import os
from typing import Optional
from rss_reader.utils.settings import qsettings
import re


SERVICE = "com.rocker.SmallRSSReader"
ACCOUNT_OMDB = "omdb_api_key"


def _use_keyring() -> bool:
    """Return True if we should try keyring. Skip in tests to avoid backend issues."""
    if os.environ.get("SMALL_RSS_TESTS"):
        return False
    return True


def _get_qsettings_value(key: str, default: str = "") -> str:
    try:
        return qsettings().value(key, default, type=str) or default
    except Exception:
        return default


def _set_qsettings_value(key: str, value: str) -> None:
    try:
        qsettings().setValue(key, value)
    except Exception:
        pass


def sanitize_omdb_api_key(value: str) -> str:
    """Normalize an OMDb API key by removing whitespace and invisible chars.

    - Strips leading/trailing whitespace
    - Removes all Unicode whitespace characters inside the string
    - Removes common zero-width/invisible code points (ZWSP/ZWNJ/ZWJ/BOM)
    """
    if not value:
        return ""
    s = value.strip()
    # remove all whitespace characters
    s = re.sub(r"\s+", "", s)
    # remove common invisible characters
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return s


def get_omdb_api_key() -> str:
    """Get OMDb API key from Keychain if available, else from QSettings."""
    if _use_keyring():
        try:
            import keyring  # type: ignore
            val: Optional[str] = keyring.get_password(SERVICE, ACCOUNT_OMDB)
            if val:
                return sanitize_omdb_api_key(val)
        except Exception:
            # Fall back to QSettings silently
            pass
    return sanitize_omdb_api_key(_get_qsettings_value('omdb_api_key', ''))


def set_omdb_api_key(value: str) -> None:
    """Store OMDb API key in Keychain when possible; otherwise QSettings. Always clear plaintext copy if Keychain used."""
    value = sanitize_omdb_api_key(value)
    stored_in_keychain = False
    if _use_keyring():
        try:
            import keyring  # type: ignore
            if value:
                keyring.set_password(SERVICE, ACCOUNT_OMDB, value)
                # verify we can read it back
                try:
                    check = keyring.get_password(SERVICE, ACCOUNT_OMDB)
                except Exception:
                    check = None
                if check != value:
                    # treat as failure to ensure fallback persistence
                    stored_in_keychain = False
                else:
                    stored_in_keychain = True
            else:
                # Delete if empty provided
                try:
                    keyring.delete_password(SERVICE, ACCOUNT_OMDB)
                except Exception:
                    pass
                stored_in_keychain = True
        except Exception:
            stored_in_keychain = False

    if stored_in_keychain:
        # Clear plaintext copy when we successfully used Keychain
        _set_qsettings_value('omdb_api_key', '')
    else:
        # Fallback: store in QSettings to persist between runs
        _set_qsettings_value('omdb_api_key', value)


def migrate_omdb_key_from_qsettings() -> None:
    """One-time migration: if Keychain is empty but QSettings has a value, move it to Keychain and clear QSettings."""
    if not _use_keyring():
        return
    try:
        import keyring  # type: ignore
        current = keyring.get_password(SERVICE, ACCOUNT_OMDB)
        if current:
            return
        qv = sanitize_omdb_api_key(_get_qsettings_value('omdb_api_key', ''))
        if qv:
            try:
                keyring.set_password(SERVICE, ACCOUNT_OMDB, qv)
                _set_qsettings_value('omdb_api_key', '')
            except Exception:
                # leave value in QSettings if Keychain fails
                pass
    except Exception:
        # No keyring, nothing to migrate
        pass
