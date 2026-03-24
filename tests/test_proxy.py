import os

from rss_reader.utils.proxy import apply_proxy_env, resolve_proxy_urls


def test_resolve_proxy_urls_reuses_single_proxy_for_both_protocols():
    http_proxy, https_proxy = resolve_proxy_urls(
        enabled=True,
        http_url='proxy.example:8080',
        https_url='',
        username='user',
        password='p@ss',
    )

    assert http_proxy == 'http://user:p%40ss@proxy.example:8080'
    assert https_proxy == 'http://user:p%40ss@proxy.example:8080'


def test_apply_proxy_env_clears_env_when_disabled(monkeypatch):
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        monkeypatch.setenv(key, 'http://stale-proxy:9000')

    apply_proxy_env(enabled=False, http_url='proxy.example:8080')

    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        assert key not in os.environ
