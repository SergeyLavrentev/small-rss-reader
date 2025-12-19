import os
import uuid


def pytest_configure(config):  # noqa: ANN001
    # Unique per test run to avoid leaking state between separate pytest invocations.
    os.environ.setdefault('SMALL_RSS_TEST_RUN_ID', uuid.uuid4().hex[:10])


def pytest_runtest_setup(item):  # noqa: ANN001
    # Provide a stable per-test identifier for isolating user data paths.
    # Some tests deliberately delete PYTEST_CURRENT_TEST to force full UI init,
    # so we can't rely on it for isolation.
    os.environ['SMALL_RSS_TEST_ID'] = item.nodeid


def pytest_runtest_teardown(item, nextitem):  # noqa: ANN001
    # Keep it tidy; next test will set its own value.
    os.environ.pop('SMALL_RSS_TEST_ID', None)
