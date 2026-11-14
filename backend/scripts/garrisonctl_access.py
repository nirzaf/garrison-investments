"""User and project access commands backed by the portal API."""

from __future__ import annotations

import argparse
from typing import Any

from pydantic import ValidationError

from app.schemas.users import UserCreateRequest, UserUpdateRequest
from scripts.garrisonctl_auth import prompt_secret
from scripts.garrisonctl_common import (
    AUTH,
    CONFLICT,
    FAILED,
    CLIError,
    Context,
    Registry,
    Result,
    checked_plan,
    mode,
    uuid_arg,
    verified,
)

USERS = "/api/v1/users"
PROJECTS = "/api/v1/projects"
MANAGE = "users:manage"
PROJECT_MANAGE = "projects:manage"


def query(args: argparse.Namespace, *names: str) -> dict[str, Any]:
    return {name: getattr(args, name) for name in names if getattr(args, name) is not None}


def page(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)


def get_user(ctx: Context, args: argparse.Namespace) -> dict[str, Any]:
    if args.user_id:
        return ctx.request("GET", f"{USERS}/{args.user_id}")
    candidates = ctx.request("GET", USERS, params={"email": args.email, "limit": 2})["items"]
    matches = [row for row in candidates if row["email"].casefold() == args.email.casefold()]
    if len(matches) != 1:
        raise CLIError("No unique exact email match. Use --user-id for a known user.", CONFLICT)
    return ctx.request("GET", f"{USERS}/{matches[0]['id']}")


def roles(args: argparse.Namespace, ctx: Context) -> Any:
    if args.command_name == "roles permissions" and not args.role:
        me = ctx.identity()
        return {"role": me["role"], "permissions": me["permissions"]}
    rows = ctx.request("GET", f"{USERS}/roles")["items"]
    if args.command_name == "roles list":
        return {"roles": [row["role"] for row in rows]}
    for row in rows:
        if row["role"] == args.role:
            return row
    raise CLIError("Role was not found.", CONFLICT)


def require_preview_permission(ctx: Context, permission: str) -> None:
    if permission not in ctx.identity().get("permissions", []):
        raise CLIError("The authenticated account lacks the required permission.", AUTH)


def validate_role(ctx: Context, role: str) -> str:
    normalized = role.strip().lower()
    rows = ctx.request("GET", f"{USERS}/roles")["items"]
    if normalized not in {row["role"] for row in rows}:
        raise CLIError("Unknown role. See roles list.")
    return normalized


def validate_payload(schema: Any, values: dict[str, Any]) -> dict[str, Any]:
    values = values.copy()
    for field in ("full_name", "employee_code", "phone", "designation"):
        if isinstance(values.get(field), str):
            values[field] = values[field].strip()
            if field == "designation" and not values[field]:
                values[field] = None
    if isinstance(values.get("email"), str):
        values["email"] = values["email"].strip().lower()
    try:
        return schema.model_validate(values).model_dump(mode="json", exclude_unset=True)
    except ValidationError as error:
        fields = [str(item["loc"][0]) for item in error.errors() if item["loc"]]
        raise CLIError("Invalid user fields.", details={"fields": fields}) from None


def create_user(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, MANAGE)
    values = query(args, "email", "full_name", "employee_code", "phone", "designation", "role")
    values["role"] = validate_role(ctx, values["role"])
    fields = validate_payload(UserCreateRequest, {**values, "temporary_password": "preview-only"})
    del fields["temporary_password"]
    matches = ctx.request("GET", USERS, params={"email": fields["email"], "limit": 2})["items"]
    if any(row["email"].casefold() == fields["email"].casefold() for row in matches):
        raise CLIError("A user already has that email.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "expected": "email_available",
            "proposed": fields,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    password = prompt_secret("Temporary password: ")
    ctx.secrets.add(password)
    payload = validate_payload(UserCreateRequest, {**fields, "temporary_password": password})
    created = ctx.request("POST", USERS, json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{USERS}/{created['id']}"),
        lambda row: all(row.get(key) == value for key, value in fields.items()),
    )


def update_user(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, MANAGE)
    user = get_user(ctx, args)
    operation = args.command_name.split()[-1]
    fields: dict[str, Any] = {}
    if operation == "update":
        fields = query(args, "full_name", "employee_code", "phone", "designation")
        if args.clear_designation:
            fields["designation"] = None
        if not fields:
            raise CLIError("Provide at least one field to update.")
        fields = validate_payload(UserUpdateRequest, fields)
    if operation == "set-role":
        fields = {"role": validate_role(ctx, args.role)}
    if operation in {"activate", "deactivate"}:
        fields = {"is_active": operation == "activate"}
    self_change = user["id"] == ctx.identity()["id"]
    if self_change and operation in {"deactivate", "reset-password"}:
        raise CLIError("The API prohibits this operation on your own account.", AUTH)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "user_id": user["id"],
            "expected_updated_at": user["updated_at"],
            "current": {key: user.get(key) for key in fields},
            "proposed": fields or {"operation": "reset credentials and invalidate sessions"},
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    path = f"{USERS}/{user['id']}"
    precondition = {"expected_updated_at": user["updated_at"]}
    if operation == "reset-password":
        password = prompt_secret("New temporary password: ")
        ctx.secrets.add(password)
        ctx.request(
            "POST",
            f"{path}/reset-password",
            write=True,
            json={**precondition, "new_password": password},
        )
    elif all(user.get(key) == value for key, value in fields.items()):
        return Result(user, outcome="unchanged")
    elif operation == "deactivate":
        ctx.request("DELETE", path, params=precondition, write=True)
    else:
        updated = ctx.request("PATCH", path, json={**fields, **precondition}, write=True)
        if self_change and operation == "set-role":
            # The role change invalidates the session before a second API call can authenticate.
            if updated.get("role") != fields["role"]:
                raise CLIError("The committed role did not match the plan.", FAILED, changed=None)
            return Result({"user": updated, "verification": "committed_api_response"}, changed=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: (
            row.get("must_change_password") is True
            if operation == "reset-password"
            else all(row.get(key) == value for key, value in fields.items())
        ),
    )


def project_members(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PROJECT_MANAGE)
    path = f"{PROJECTS}/{args.project_id}"
    detail = ctx.request("GET", path)
    operation = args.command_name.split()[-1]
    members = [member for member in detail["members"] if member["user_id"] == args.user_id]
    if detail.get("is_read_only"):
        raise CLIError("The project is read-only.", CONFLICT)
    if (operation == "assign" and members) or (operation == "revoke" and not members):
        raise CLIError("The current membership does not support this operation.", CONFLICT)
    revision = detail["revision"]
    label = getattr(args, "role_in_project", None) or None
    if operation == "assign":
        user = ctx.request("GET", f"{USERS}/{args.user_id}")
        if user.get("is_active") is not True:
            raise CLIError("Only an active user can be assigned.", CONFLICT)
        if label and len(label) > 50:
            raise CLIError("The project role label cannot exceed 50 characters.")
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "project_id": args.project_id,
            "user_id": args.user_id,
            "role_in_project": label,
            "expected_revision": revision,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if operation == "assign":
        ctx.request(
            "POST",
            f"{path}/members",
            write=True,
            json={
                "user_id": args.user_id,
                "role_in_project": label,
                "expected_revision": revision,
            },
        )
    else:
        ctx.request(
            "DELETE",
            f"{path}/members/{args.user_id}",
            write=True,
            params={"expected_revision": revision},
        )

    def read() -> dict[str, Any]:
        detail = ctx.request("GET", path)
        return {
            "project_id": args.project_id,
            "user_id": args.user_id,
            "revision": detail["revision"],
            "membership": next(
                (member for member in detail["members"] if member["user_id"] == args.user_id),
                None,
            ),
        }

    return verified(
        ctx,
        read,
        lambda observed: (
            observed["revision"] > revision
            and (
                observed["membership"] is None
                if operation == "revoke"
                else observed["membership"] is not None
                and observed["membership"].get("role_in_project") == label
            )
        ),
    )


def user_target(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id", type=uuid_arg)
    target.add_argument("--email")


def register(registry: Registry) -> None:
    registry.add("roles list", roles, permission="users:read")
    parser = registry.add(
        "roles permissions", roles, permission="authenticated (own role), users:read (other roles)"
    )
    parser.add_argument("--role")
    parser = registry.add(
        "users list",
        lambda a, c: c.request(
            "GET",
            USERS,
            params=query(
                a,
                "search",
                "role",
                "active",
                "limit",
                "offset",
            ),
        ),
        permission="users:read",
    )
    for field in ("search", "role"):
        parser.add_argument(f"--{field}")
    parser.add_argument("--active", action=argparse.BooleanOptionalAction)
    page(parser)
    parser = registry.add("users show", lambda a, c: get_user(c, a), permission="users:read")
    user_target(parser)
    parser = registry.add(
        "users create", create_user, permission=MANAGE, mutates=True, preview=True, approval=True
    )
    for field in ("email", "full-name", "employee-code", "phone", "role"):
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--designation")
    mode(parser)
    for operation in ("update", "set-role", "activate", "deactivate", "reset-password"):
        parser = registry.add(
            f"users {operation}",
            update_user,
            permission=MANAGE,
            mutates=True,
            preview=True,
            approval=True,
        )
        user_target(parser)
        mode(parser)
        if operation == "update":
            for field in ("full-name", "employee-code", "phone"):
                parser.add_argument(f"--{field}")
            designation = parser.add_mutually_exclusive_group()
            designation.add_argument("--designation")
            designation.add_argument("--clear-designation", action="store_true")
        if operation == "set-role":
            parser.add_argument("--role", required=True)
    parser = registry.add(
        "projects list",
        lambda a, c: c.request(
            "GET",
            PROJECTS,
            params=query(
                a,
                "search",
                "status",
                "limit",
                "offset",
            ),
        ),
        permission="projects:read",
    )
    parser.add_argument("--search")
    parser.add_argument("--status")
    page(parser)
    for command, suffix in (("show", ""), ("members list", "/members")):

        def read(a: argparse.Namespace, c: Context, route: str = suffix) -> Any:
            return c.request("GET", f"{PROJECTS}/{a.project_id}{route}")

        parser = registry.add(f"projects {command}", read, permission="projects:read")
        parser.add_argument("--project-id", type=uuid_arg, required=True)
    for operation in ("assign", "revoke"):
        parser = registry.add(
            f"projects members {operation}",
            project_members,
            permission=PROJECT_MANAGE,
            mutates=True,
            preview=True,
            approval=True,
        )
        parser.add_argument("--project-id", type=uuid_arg, required=True)
        parser.add_argument("--user-id", type=uuid_arg, required=True)
        if operation == "assign":
            parser.add_argument("--role-in-project", type=str.strip)
        mode(parser)
