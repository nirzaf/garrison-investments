"""Keep CI shards isolated without changing ordinary local pytest runs."""

from collections import Counter
from pathlib import Path

import pytest


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

    # Keep each module together and preserve its collected order. Assign the
    # largest modules to the lighter shard first so every case runs exactly once.
    sizes = Counter(item.path.relative_to(config.rootpath) for item in items)
    assignments: dict[Path, int] = {}
    totals = [0, 0]
    for path, size in sorted(sizes.items(), key=lambda module: (-module[1], module[0])):
        slot = 0 if totals[0] <= totals[1] else 1
        assignments[path] = slot + 1
        totals[slot] += size

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        path = item.path.relative_to(config.rootpath)
        (selected if assignments[path] == shard else deselected).append(item)
    if not selected:
        raise pytest.UsageError(f"CI shard {shard} did not select any tests")
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
