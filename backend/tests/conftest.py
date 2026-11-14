"""Keep CI shards isolated without changing ordinary local pytest runs."""

from collections import Counter
from pathlib import Path

import pytest

# Median module runtimes in milliseconds from CI runs 43293023176,
# 43359757307, 43375671327, and 43379155322, rounded to the nearest 100 ms.
# The capture wrapper entry below is refreshed from runs 43587573918 and 43599068234.
SLOW_MODULE_MS = {
    "tests/test_capture_recovery_wrapper.py": 177_200,
    "tests/test_scope_authorization.py": 12_500,
    "tests/test_daily_reports.py": 11_800,
    "tests/test_authorization_matrix.py": 11_500,
    "tests/test_session_revocation.py": 8_900,
    "tests/test_auth.py": 8_700,
    "tests/test_delegation_guards.py": 6_300,
    "tests/test_photos.py": 5_900,
    "tests/test_idempotency.py": 5_600,
    "tests/test_finance.py": 5_200,
    "tests/test_report_payment_concurrency.py": 4_400,
    "tests/test_inventory.py": 4_000,
    "tests/test_projects.py": 3_900,
    "tests/test_repair_offline_duplicates.py": 2_900,
    "tests/test_documents.py": 2_800,
    "tests/test_inventory_accounting.py": 2_700,
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
