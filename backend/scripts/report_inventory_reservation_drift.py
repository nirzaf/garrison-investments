"""Report inventory balances that need reconciliation against reservation records."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Select, func, or_, select, text
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


async def report_drift() -> None:
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
    query = (
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

    async def print_rows(
        session: AsyncSession, finding: str, statement: Select[*tuple[Any, ...]]
    ) -> None:
        async for row in await session.stream(statement):
            print(json.dumps({"finding": finding, **row._mapping}, default=str))

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await print_rows(session, "stock_reservation_drift", query)
            await print_rows(session, "cancelled_request_with_open_approval", cancelled_approvals)
            await print_rows(
                session, "cancelled_request_with_reserved_line", cancelled_reservations
            )
            await print_rows(session, "open_reservation_without_stock", reservations_without_stock)
            await print_rows(session, "open_reservation_over_remaining", excess_line_reservations)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--i-understand", action="store_true", help="Allow the report to read production balances."
    )
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Production reporting requires --i-understand.")
    asyncio.run(report_drift())


if __name__ == "__main__":
    main()
