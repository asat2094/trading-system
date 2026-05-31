"""CLI to trigger Kite1MinBackfillWorkflow on the Temporal cluster.

Usage:
    # Today only (single symbol):
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --symbols CDSL

    # Today for full universe:
    PYTHONPATH=. python scripts/trigger_kite_backfill.py

    # Custom date range:
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --from 2025-01-01 --to 2025-12-31

    # Full backfill since Jan 2024:
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --from 2024-01-01 --workers 5

    # Watch status:
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --wait --symbols CDSL

Examples:
    # Single day
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --from 2026-05-19 --to 2026-05-19

    # This week
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --from 2026-05-12

    # Full backfill all symbols
    PYTHONPATH=. python scripts/trigger_kite_backfill.py --from 2024-01-01 --workers 5
"""
import argparse
import asyncio
import uuid
from datetime import date, timedelta
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)


async def main():
    parser = argparse.ArgumentParser(description="Trigger Kite 1-min backfill workflow")
    parser.add_argument("--symbols",  nargs="*", default=[],
                        help="NSE symbols (empty = full universe)")
    parser.add_argument("--from",  dest="from_date",
                        default=date.today().isoformat(),
                        help="Start date YYYY-MM-DD (default: today)")
    parser.add_argument("--to",    dest="to_date",
                        default=date.today().isoformat(),
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--workers", type=int, default=3,
                        help="Parallel symbol workers (default: 3)")
    parser.add_argument("--wait",  action="store_true",
                        help="Block until workflow completes and print result")
    args = parser.parse_args()

    from temporalio.client import Client
    from core.config import settings

    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    workflow_id = f"kite1min-backfill-{args.from_date}-{args.to_date}-{uuid.uuid4().hex[:6]}"

    handle = await client.start_workflow(
        "Kite1MinBackfillWorkflow",
        args=[args.symbols, args.from_date, args.to_date, args.workers],
        id=workflow_id,
        task_queue="trading-main",
    )

    symbols_desc = ", ".join(args.symbols) if args.symbols else "full universe"
    print(f"✓ Workflow started")
    print(f"  ID:      {workflow_id}")
    print(f"  Symbols: {symbols_desc}")
    print(f"  Range:   {args.from_date} → {args.to_date}")
    print(f"  Workers: {args.workers}")
    print(f"  UI:      http://localhost:8080/namespaces/{settings.TEMPORAL_NAMESPACE}/workflows/{workflow_id}")

    if args.wait:
        print("\nWaiting for completion...")
        result = await handle.result()
        print(f"\nResult: {result}")
    else:
        print("\nRunning in background. Check Temporal UI or run with --wait.")


if __name__ == "__main__":
    asyncio.run(main())
