"""Keep CI shards isolated without changing ordinary local pytest runs."""

from collections import Counter
from pathlib import Path

import pytest

# Module test times from both backend reports in CI run 43902036278, rounded
# to the nearest 100 ms. Keep measured weights for modules above three seconds.
SLOW_MODULE_MS = {
    "tests/test_capture_recovery_wrapper.py": 168_500,
    "tests/test_hr.py": 37_800,
    "tests/test_release_rollback.py": 25_800,
    "tests/test_scope_authorization.py": 23_500,
    "tests/test_authorization_matrix.py": 22_300,
    "tests/test_daily_reports.py": 15_500,
    "tests/test_auth.py": 12_200,
    "tests/test_photos.py": 10_800,
    "tests/test_session_revocation.py": 10_400,
    "tests/test_inventory.py": 8_800,
    "tests/test_idempotency.py": 8_200,
    "tests/test_projects.py": 7_400,
    "tests/test_report_payment_concurrency.py": 6_400,
    "tests/test_garrisonctl.py": 5_000,
    "tests/test_repair_offline_duplicates.py": 4_900,
    "tests/test_documents.py": 4_900,
    "tests/test_release_contract.py": 4_200,
    "tests/test_inventory_accounting.py": 4_200,
    "tests/test_delegation_guards.py": 3_900,
    "tests/test_supervisor_updates.py": 3_300,
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
