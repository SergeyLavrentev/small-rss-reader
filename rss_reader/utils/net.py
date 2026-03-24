import hashlib
import time
from typing import Mapping, Optional, Sequence, Tuple, Union


TimeoutSpec = Union[int, float, Tuple[int, int], Tuple[float, float]]
DEFAULT_FETCH_TIMEOUT_PLAN: Tuple[TimeoutSpec, ...] = ((2, 6), (4, 10), (6, 16))

def compute_article_id(entry: dict) -> str:
    unique_string = entry.get('id') or entry.get('guid') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))
    return hashlib.md5(unique_string.encode('utf-8')).hexdigest()


def fetch_url_text_with_retries(
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    allow_redirects: bool = True,
    timeout_plan: Optional[Sequence[TimeoutSpec]] = None,
) -> str:
    """Fetch text content with a few retries for slow sites.

    Raises the last exception if all attempts fail, or RuntimeError on repeated empty bodies.
    """
    plans = tuple(timeout_plan or DEFAULT_FETCH_TIMEOUT_PLAN)
    last_error: Optional[Exception] = None
    request_headers = dict(headers or {})

    for idx, timeout in enumerate(plans):
        try:
            import requests

            resp = requests.get(
                url,
                timeout=timeout,
                allow_redirects=allow_redirects,
                headers=request_headers,
            )
            text = getattr(resp, 'text', '') or ''
            if not isinstance(text, str):
                text = str(text)
            if text.strip():
                return text
            last_error = RuntimeError(f"Empty response body for {url}")
        except Exception as exc:
            last_error = exc

        if idx + 1 < len(plans):
            try:
                time.sleep(min(0.35 * (idx + 1), 0.9))
            except Exception:
                pass

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch text from {url}")
