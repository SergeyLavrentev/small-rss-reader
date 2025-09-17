import pytest

from rss_reader.app import _parse_habr_metrics_from_html


def test_habr_comments_parsing_new_markup():
    html = (
        '<title>Комментарии</title>'
        '<svg><use xlink:href="/img/megazord-v28.ac2e86a7..svg#counter-comments"></use></svg>'
        '<span class="value value--contrasted" data-v-a853f3bf> Комментарии 34 </span>'
    )
    data = _parse_habr_metrics_from_html(html)
    assert isinstance(data, dict)
    assert data.get('comments') == 34
    # Rating may be absent in snippet; ensure safe defaults
    assert 'rating' in data
    assert 'rating_text' in data
