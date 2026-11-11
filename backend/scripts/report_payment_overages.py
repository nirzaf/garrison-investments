"""List active invoices whose recorded payments exceed their totals."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.finance import Invoice, Payment


async def report_overages() -> None:
    paid = func.sum(Payment.amount).label("paid_total")
    query = (
        select(Invoice.id, Invoice.invoice_number, Invoice.total_amount, paid)
        .join(Payment, Payment.invoice_id == Invoice.id)
        .where(Invoice.deleted_at.is_(None), Payment.deleted_at.is_(None))
        .group_by(Invoice.id, Invoice.invoice_number, Invoice.total_amount)
        .having(paid > Invoice.total_amount)
        .order_by((paid - Invoice.total_amount).desc(), Invoice.id)
    )
    try:
        async with AsyncSessionLocal() as session:
            rows = await session.stream(query)
            async for invoice_id, invoice_number, invoice_total, paid_total in rows:
                print(
                    json.dumps(
                        {
                            "invoice_id": str(invoice_id),
                            "invoice_number": invoice_number,
                            "invoice_total": str(invoice_total),
                            "paid_total": str(paid_total),
                            "overage": str(paid_total - invoice_total),
                        }
                    )
                )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--i-understand", action="store_true", help="Allow the report to read production invoices."
    )
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Production reporting requires --i-understand.")
    asyncio.run(report_overages())


if __name__ == "__main__":
    main()
