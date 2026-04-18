from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Comment


DISALLOWED_TAGS = (
    'script',
    'style',
    'noscript',
    'svg',
    'iframe',
    'object',
    'embed',
    'form',
    'button',
    'input',
    'meta',
    'link',
)

ALLOWED_ATTRS = {
    'href',
    'src',
    'alt',
    'title',
    'width',
    'height',
    'colspan',
    'rowspan',
    'controls',
    'poster',
}

URL_ATTRS = {'href', 'src', 'poster'}


def remove_selectors(root: Any, selectors: Sequence[str]) -> None:
    if not selectors:
        return
    for selector in selectors:
        try:
            for node in root.select(selector):
                node.decompose()
        except Exception:
            pass


def remove_noisy_nodes(root: Any, noisy_pattern: Any) -> None:
    if noisy_pattern is None:
        return
    for node in list(root.find_all(True)):
        try:
            classes = ' '.join(node.get('class') or [])
            node_id = node.get('id') or ''
            if noisy_pattern.search(classes) or noisy_pattern.search(node_id):
                node.decompose()
        except Exception:
            pass


def sanitize_soup_tree(root: Any, *, base_url: str = '') -> None:
    try:
        for comment in list(root.find_all(string=lambda value: isinstance(value, Comment))):
            try:
                comment.extract()
            except Exception:
                pass
    except Exception:
        pass

    try:
        for tag in list(root.find_all(DISALLOWED_TAGS)):
            try:
                tag.decompose()
            except Exception:
                pass
    except Exception:
        pass

    for node in list(root.find_all(True)):
        try:
            attrs = dict(node.attrs or {})
            kept = {}
            for key, value in attrs.items():
                attr_name = str(key).lower()
                if attr_name.startswith('on'):
                    continue
                if attr_name not in ALLOWED_ATTRS:
                    continue
                normalized = _normalize_attr_value(attr_name, value, base_url=base_url)
                if normalized is None:
                    continue
                kept[attr_name] = normalized
            node.attrs = kept
        except Exception:
            pass


def sanitize_html_fragment(html: str, *, base_url: str = '') -> str:
    if not html:
        return ''
    try:
        soup = BeautifulSoup(html, 'html.parser')
        sanitize_soup_tree(soup, base_url=base_url)
        if soup.body is not None:
            return ''.join(str(child) for child in soup.body.contents)
        return ''.join(str(child) for child in soup.contents)
    except Exception:
        return html


def _normalize_attr_value(attr_name: str, value: Any, *, base_url: str = '') -> str | None:
    if attr_name in URL_ATTRS:
        return _normalize_url(value, base_url=base_url, attr_name=attr_name)

    if attr_name == 'controls':
        return 'controls'

    if isinstance(value, (list, tuple)):
        text = ' '.join(str(part).strip() for part in value if str(part).strip())
    else:
        text = str(value).strip()
    return text or None


def _normalize_url(value: Any, *, base_url: str = '', attr_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]

    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()

    if lower.startswith(('javascript:', 'vbscript:')):
        return None

    if attr_name == 'href':
        if lower.startswith('#') or lower.startswith('mailto:'):
            return text
        if lower.startswith('data:'):
            return None
    else:
        if lower.startswith('data:image/'):
            return text
        if lower.startswith('data:'):
            return None

    if lower.startswith('//'):
        return 'https:' + text
    if lower.startswith(('http://', 'https://')):
        return text

    if base_url:
        try:
            return urljoin(base_url, text)
        except Exception:
            pass

    return text