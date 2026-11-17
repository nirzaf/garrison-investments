"""Report inventory balances that need reconciliation against reservation and movement records."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Select, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.approval import Approval
from app.models.inventory import (
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestLine,
)

INBOUND_MOVEMENT_TYPES = ("receive", "return", "adjustment")
OUTBOUND_MOVEMENT_TYPES = ("issue", "consume", "wastage", "damaged")


def _reconciliation_queries() -> dict[str, Select[Any]]:
    stock = InventoryLocationStock
    request = MaterialRequest
    approval = Approval
    line = MaterialRequestLine
    movement = InventoryMovement
    active_reservation = (
        line.deleted_at.is_(None),
        request.deleted_at.is_(None),
        request.status.in_(["approved", "partially_reserved", "reserved", "partially_issued"]),
    )
    line_remaining = func.greatest(0, line.quantity - line.issued_quantity)
    open_requests = (
        select(
            line.item_id,
            request.from_location_id.label("location_id"),
            func.sum(line.reserved_quantity).label("recorded"),
            func.sum(line_remaining).label("remaining"),
        )
        .join(request, request.id == line.request_id)
        .where(*active_reservation)
        .group_by(line.item_id, request.from_location_id)
        .subquery()
    )
    recorded = func.coalesce(open_requests.c.recorded, 0)
    remaining = func.coalesce(open_requests.c.remaining, 0)
    manual_reserves = (
        select(func.coalesce(func.sum(movement.quantity), 0))
        .where(
            movement.item_id == stock.item_id,
            movement.from_location_id == stock.location_id,
            movement.movement_type == "reserve",
            movement.reference_type.is_distinct_from("material_request"),
            movement.deleted_at.is_(None),
        )
        .correlate(stock)
        .scalar_subquery()
    )
    expected = recorded + manual_reserves
    stock_drift = (
        select(
            stock.item_id,
            stock.location_id,
            stock.on_hand_qty,
            stock.reserved_qty,
            recorded.label("recorded_request_reservations"),
            remaining.label("remaining_request_quantity"),
            manual_reserves.label("manual_reserve_quantity"),
            expected.label("expected_reserved_quantity"),
        )
        .outerjoin(
            open_requests,
            (open_requests.c.item_id == stock.item_id)
            & (open_requests.c.location_id == stock.location_id),
        )
        .where(
            stock.deleted_at.is_(None),
            or_(
                stock.on_hand_qty < 0,
                stock.reserved_qty < 0,
                stock.reserved_qty > stock.on_hand_qty,
                stock.reserved_qty != expected,
                recorded > remaining,
            ),
        )
        .order_by(stock.location_id, stock.item_id)
    )
    inbound = (
        select(
            movement.item_id,
            movement.to_location_id.label("location_id"),
            func.sum(
                case(
                    (
                        movement.movement_type.in_((*INBOUND_MOVEMENT_TYPES, "transfer")),
                        movement.quantity,
                    ),
                    else_=0,
                )
            ).label("inbound_qty"),
        )
        .where(movement.deleted_at.is_(None), movement.to_location_id.is_not(None))
        .group_by(movement.item_id, movement.to_location_id)
        .subquery()
    )
    outbound = (
        select(
            movement.item_id,
            movement.from_location_id.label("location_id"),
            func.sum(
                case(
                    (
                        movement.movement_type.in_((*OUTBOUND_MOVEMENT_TYPES, "transfer")),
                        movement.quantity,
                    ),
                    else_=0,
                )
            ).label("outbound_qty"),
        )
        .where(movement.deleted_at.is_(None), movement.from_location_id.is_not(None))
        .group_by(movement.item_id, movement.from_location_id)
        .subquery()
    )
    movement_net = func.coalesce(inbound.c.inbound_qty, 0) - func.coalesce(
        outbound.c.outbound_qty, 0
    )
    movement_drift = (
        select(
            stock.item_id,
            stock.location_id,
            stock.on_hand_qty,
            movement_net.label("derived_movement_on_hand_qty"),
            (stock.on_hand_qty - movement_net).label("movement_delta"),
        )
        .outerjoin(
            inbound,
            (inbound.c.item_id == stock.item_id) & (inbound.c.location_id == stock.location_id),
        )
        .outerjoin(
            outbound,
            (outbound.c.item_id == stock.item_id) & (outbound.c.location_id == stock.location_id),
        )
        .where(
            stock.deleted_at.is_(None),
            stock.on_hand_qty != movement_net,
        )
        .order_by(stock.location_id, stock.item_id)
    )
    cancelled_approvals = (
        select(request.id.label("request_id"), approval.id.label("approval_id"), approval.status)
        .join(approval, approval.request_id == request.id)
        .where(
            request.status == "cancelled",
            request.deleted_at.is_(None),
            approval.request_type == "material_request",
            approval.status.in_(["pending", "delegated", "escalated"]),
            approval.deleted_at.is_(None),
        )
        .order_by(request.id, approval.id)
    )
    cancelled_reservations = (
        select(request.id.label("request_id"), line.id.label("line_id"), line.reserved_quantity)
        .join(line, line.request_id == request.id)
        .where(
            request.status == "cancelled",
            request.deleted_at.is_(None),
            line.deleted_at.is_(None),
            line.reserved_quantity != 0,
        )
        .order_by(request.id, line.id)
    )
    open_lines = (
        select(
            line.request_id,
            line.id.label("line_id"),
            line.item_id,
            request.from_location_id.label("location_id"),
            line.reserved_quantity,
            line_remaining.label("remaining_quantity"),
        )
        .select_from(line)
        .join(request, request.id == line.request_id)
        .where(*active_reservation)
        .order_by(request.id, line.id)
    )
    reservations_without_stock = open_lines.outerjoin(
        stock,
        (stock.item_id == line.item_id)
        & (stock.location_id == request.from_location_id)
        & stock.deleted_at.is_(None),
    ).where(stock.id.is_(None), line.reserved_quantity > 0)
    excess_line_reservations = open_lines.where(line.reserved_quantity > line_remaining)
    return {
        "stock_reservation_drift": stock_drift,
        "movement_balance_drift": movement_drift,
        "cancelled_request_with_open_approval": cancelled_approvals,
        "cancelled_request_with_reserved_line": cancelled_reservations,
        "open_reservation_without_stock": reservations_without_stock,
        "open_reservation_over_remaining": excess_line_reservations,
    }


async def collect_stock_reconciliation(session: AsyncSession) -> dict[str, Any]:
    """Read-only reconciliation report across stock balances, reservations, and movements."""
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    stock_rows = int(
        await session.scalar(
            select(func.count())
            .select_from(InventoryLocationStock)
            .where(InventoryLocationStock.deleted_at.is_(None))
        )
        or 0
    )
    movement_rows = int(
        await session.scalar(
            select(func.count())
            .select_from(InventoryMovement)
            .where(InventoryMovement.deleted_at.is_(None))
        )
        or 0
    )
    findings: dict[str, list[dict[str, Any]]] = {}
    for name, statement in _reconciliation_queries().items():
        rows = (await session.execute(statement)).all()
        findings[name] = [
            {key: str(value) if value is not None else None for key, value in row._mapping.items()}
            for row in rows
        ]
    body = {
        "read_only": True,
        "stock_row_count": stock_rows,
        "movement_row_count": movement_rows,
        "finding_counts": {name: len(items) for name, items in findings.items()},
        "findings": findings,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**body, "report_sha256": digest}


async def report_drift(*, summary: bool = False) -> None:
    queries = _reconciliation_queries()

    async def print_rows(
        session: AsyncSession, finding: str, statement: Select[Any]
    ) -> None:
        async for row in await session.stream(statement):
            print(json.dumps({"finding": finding, **row._mapping}, default=str))

    try:
        async with AsyncSessionLocal() as session:
            if summary:
                print(json.dumps(await collect_stock_reconciliation(session), sort_keys=True))
                return
            await session.execute(text("SET TRANSACTION READ ONLY"))
            for finding, statement in queries.items():
                if finding == "movement_balance_drift":
                    continue
                await print_rows(session, finding, statement)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--i-understand", action="store_true", help="Allow the report to read production balances."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Emit a single JSON report with counts and SHA-256."
    )
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Production reporting requires --i-understand.")
    asyncio.run(report_drift(summary=args.summary))


if __name__ == "__main__":
    main()
