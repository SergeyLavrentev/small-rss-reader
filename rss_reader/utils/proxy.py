from __future__ import annotations

import os
from typing import Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

from rss_reader.utils.settings import qsettings


def _split_userinfo(netloc: str) -> Tuple[Optional[str], Optional[str], str]:
    """Return (user, password, hostport) from netloc."""
    if '@' not in (netloc or ''):
        return None, None, netloc
    userinfo, hostport = netloc.rsplit('@', 1)
    if ':' in userinfo:
        u, p = userinfo.split(':', 1)
        return u or None, p or None, hostport
    return userinfo or None, None, hostport


def normalize_proxy_url(url: str, username: str = '', password: str = '') -> str:
    """Normalize proxy URL and optionally inject basic auth.

    Accepts URLs like:
    - http://host:port
    - https://host:port
    - host:port (scheme implied as http)

    If username/password are provided and URL has no userinfo, inject them.
    """
    u = (url or '').strip()
    if not u:
        return ''

    # If user passed host:port without scheme, assume http.
    if '://' not in u:
        u = 'http://' + u

    parts = urlsplit(u)
    scheme = parts.scheme or 'http'

    # urlsplit may treat bare "http://" weirdly; keep best-effort.
    netloc = parts.netloc or ''
    path = parts.path or ''
    query = parts.query or ''
    fragment = parts.fragment or ''

    existing_user, existing_pass, hostport = _split_userinfo(netloc)
    user = (existing_user or '').strip() or (username or '').strip()
    pwd = (existing_pass or '').strip() or (password or '').strip()

    if user and '@' not in netloc:
        u_enc = quote(user, safe='')
        if pwd:
            p_enc = quote(pwd, safe='')
            netloc = f"{u_enc}:{p_enc}@{hostport}"
        else:
            netloc = f"{u_enc}@{hostport}"

    return urlunsplit((scheme, netloc, path, query, fragment))


def apply_proxy_env_from_settings() -> None:
    """Apply proxy settings from QSettings into process environment.

    This lets `requests`, `urllib`, and other libraries automatically use the proxy.
    """
    s = qsettings()
    http_url = s.value('proxy_http', '', type=str) or ''
    https_url = s.value('proxy_https', '', type=str) or ''
    username = s.value('proxy_username', '', type=str) or ''
    password = s.value('proxy_password', '', type=str) or ''

    http_norm = normalize_proxy_url(http_url, username=username, password=password)
    https_norm = normalize_proxy_url(https_url, username=username, password=password)

    def _set_or_unset(key: str, value: str) -> None:
        try:
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        except Exception:
            pass

    # Uppercase and lowercase variants are both used by different stacks.
    _set_or_unset('HTTP_PROXY', http_norm)
    _set_or_unset('HTTPS_PROXY', https_norm)
    _set_or_unset('http_proxy', http_norm)
    _set_or_unset('https_proxy', https_norm)
