"""Report inventory balances that need reconciliation against reservation records."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, or_, select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.inventory import (
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestLine,
)


async def report_drift() -> None:
    stock = InventoryLocationStock
    request = MaterialRequest
    line = MaterialRequestLine
    movement = InventoryMovement
    open_requests = (
        select(
            line.item_id,
            request.from_location_id.label("location_id"),
            func.sum(line.reserved_quantity).label("recorded"),
            func.sum(func.greatest(0, line.quantity - line.issued_quantity)).label("remaining"),
        )
        .join(request, request.id == line.request_id)
        .where(
            line.deleted_at.is_(None),
            request.deleted_at.is_(None),
            request.status.in_(["reserved", "partially_issued"]),
        )
        .group_by(line.item_id, request.from_location_id)
        .subquery()
    )
    recorded = func.coalesce(open_requests.c.recorded, 0)
    remaining = func.coalesce(open_requests.c.remaining, 0)
    manual_reserves = (
        select(func.count())
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
    query = (
        select(
            stock.item_id,
            stock.location_id,
            stock.on_hand_qty,
            stock.reserved_qty,
            recorded.label("recorded_request_reservations"),
            remaining.label("remaining_request_quantity"),
            manual_reserves.label("manual_reserve_movements"),
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
                stock.reserved_qty != remaining,
                recorded != remaining,
            ),
        )
        .order_by(stock.location_id, stock.item_id)
    )
    try:
        async with AsyncSessionLocal() as session:
            async for row in await session.stream(query):
                print(json.dumps(dict(row._mapping), default=str))
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
