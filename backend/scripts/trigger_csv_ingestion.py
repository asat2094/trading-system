"""CLI to trigger CsvIngestionWorkflow on the Temporal cluster.

Usage:
    # Full ingest — all 502 symbols, concurrency 10:
    PYTHONPATH=. python scripts/trigger_csv_ingestion.py

    # Custom concurrency:
    PYTHONPATH=. python scripts/trigger_csv_ingestion.py --concurrency 15

    # Single symbol:
    PYTHONPATH=. python scripts/trigger_csv_ingestion.py --symbols RELIANCE

    # Wait for completion:
    PYTHONPATH=. python scripts/trigger_csv_ingestion.py --wait
"""
import argparse
import asyncio
import uuid
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)


async def main():
    parser = argparse.ArgumentParser(description="Trigger CSV ingestion workflow")
    parser.add_argument("--symbols", nargs="*", default=[],
                        help="NSE symbols (empty = all dirs in rawdata/1min)")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Parallel symbol workers (default: 10)")
    parser.add_argument("--wait", action="store_true",
                        help="Block until workflow completes and print result")
    args = parser.parse_args()

    from temporalio.client import Client
    from core.config import settings

    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    workflow_id = f"csv-ingestion-{uuid.uuid4().hex[:8]}"

    handle = await client.start_workflow(
        "CsvIngestionWorkflow",
        args=[args.symbols or None, args.concurrency],
        id=workflow_id,
        task_queue="trading-main",
    )

    symbols_desc = ", ".join(args.symbols) if args.symbols else "all symbols"
    print(f"✓ Workflow started")
    print(f"  ID:          {workflow_id}")
    print(f"  Symbols:     {symbols_desc}")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  UI:          http://localhost:8080/namespaces/{settings.TEMPORAL_NAMESPACE}/workflows/{workflow_id}")

    if args.wait:
        print("\nWaiting for completion...")
        result = await handle.result()
        print(f"\nResult: {result}")
    else:
        print("\nRunning in background. Check Temporal UI or run with --wait.")


if __name__ == "__main__":
    asyncio.run(main())
