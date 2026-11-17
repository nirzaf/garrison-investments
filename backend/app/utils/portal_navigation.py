import json
from pathlib import Path
from typing import TypedDict, cast

from app.utils.permissions import permissions_for_role


class NavigationRule(TypedDict):
    any_permissions: list[str]
    excluded_roles: list[str]


NAVIGATION_POLICY_PATH = Path(__file__).resolve().parents[1] / "portal_navigation.json"
NAVIGATION_POLICY = cast(
    dict[str, NavigationRule], json.loads(NAVIGATION_POLICY_PATH.read_text(encoding="utf-8"))
)


def navigation_visibility(role: str) -> dict[str, bool]:
    permissions = set(permissions_for_role(role))
    return {
        route_id: role not in rule["excluded_roles"]
        and (not rule["any_permissions"] or not permissions.isdisjoint(rule["any_permissions"]))
        for route_id, rule in NAVIGATION_POLICY.items()
    }
