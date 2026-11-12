"""Keep CI shards isolated without changing ordinary local pytest runs."""

from collections import Counter
from pathlib import Path

import pytest

# Rounded module runtimes in milliseconds from CI run 43287367122.
SLOW_MODULE_MS = {
    "tests/test_capture_recovery_wrapper.py": 16_000,
    "tests/test_authorization_matrix.py": 10_000,
    "tests/test_daily_reports.py": 10_000,
    "tests/test_scope_authorization.py": 10_000,
    "tests/test_session_revocation.py": 9_000,
    "tests/test_auth.py": 8_000,
    "tests/test_photos.py": 5_000,
    "tests/test_idempotency.py": 4_000,
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--garrison-shard",
        type=int,
        choices=(1, 2),
        help="Run one of two CI shards. Each needs its own database, Redis and S3 services.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    shard = config.getoption("--garrison-shard")
    if shard is None:
        return

    # Keep each module together and preserve its collected order. Use case
    # counts for modules without a measured runtime.
    sizes = Counter(item.path.relative_to(config.rootpath) for item in items)
    costs = {path: SLOW_MODULE_MS.get(path.as_posix(), count * 50) for path, count in sizes.items()}
    assignments: dict[Path, int] = {}
    totals = [0, 0]
    for path, cost in sorted(costs.items(), key=lambda module: (-module[1], module[0])):
        slot = 0 if totals[0] <= totals[1] else 1
        assignments[path] = slot + 1
        totals[slot] += cost

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        path = item.path.relative_to(config.rootpath)
        (selected if assignments[path] == shard else deselected).append(item)
    if not selected:
        raise pytest.UsageError(f"CI shard {shard} did not select any tests")
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
