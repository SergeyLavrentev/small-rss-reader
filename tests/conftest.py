import os
import uuid
import sys


def pytest_configure(config):  # noqa: ANN001
    # Unique per test run to avoid leaking state between separate pytest invocations.
    os.environ.setdefault('SMALL_RSS_TEST_RUN_ID', uuid.uuid4().hex[:10])

    # Under QT_QPA_PLATFORM=offscreen, Qt/PyQt can occasionally trigger benign
    # unraisable exceptions during object finalization. Pytest's unraisable
    # exception formatting may recurse and fail the suite under output capture.
    # Install a minimal hook to keep the run stable.
    try:
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            def _safe_unraisablehook(unraisable):  # noqa: ANN001
                return

            sys.unraisablehook = _safe_unraisablehook  # type: ignore[attr-defined]
    except Exception:
        pass


def pytest_runtest_setup(item):  # noqa: ANN001
    # Provide a stable per-test identifier for isolating user data paths.
    # Some tests deliberately delete PYTEST_CURRENT_TEST to force full UI init,
    # so we can't rely on it for isolation.
    os.environ['SMALL_RSS_TEST_ID'] = item.nodeid


def pytest_runtest_teardown(item, nextitem):  # noqa: ANN001
    # Keep it tidy; next test will set its own value.
    os.environ.pop('SMALL_RSS_TEST_ID', None)
