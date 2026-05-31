"""Register (or update) all Temporal schedules for the trading system.

All timing settings come from core.config.Settings — never hardcoded here.
Schedule cron expressions are interpreted in settings.TIMEZONE (IST).

Run once to create schedules. Safe to re-run — updates existing schedules.

Usage:
    cd backend && PYTHONPATH=. .venv/bin/python scripts/register_schedules.py

    # List all registered schedules:
    PYTHONPATH=. .venv/bin/python scripts/register_schedules.py --list

    # Trigger a schedule immediately (e.g. after system restart):
    PYTHONPATH=. .venv/bin/python scripts/register_schedules.py --trigger daily-1min-refresh

    # Delete a schedule:
    PYTHONPATH=. .venv/bin/python scripts/register_schedules.py --delete daily-1min-refresh
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

from core.config import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
)
from temporalio.common import RetryPolicy


# ─────────────────────────────────────────────────────────────────────────────
# Schedule definitions — all times expressed in settings.TIMEZONE
# ─────────────────────────────────────────────────────────────────────────────

def build_schedules() -> list[dict]:
    """Build schedule definitions from config. Called at runtime so config is live."""
    return [
        {
            "id": "daily-1min-refresh",
            "workflow": "DailyRefreshWorkflow",
            "args": [],   # workflow reads gap_days/concurrency from settings
            "note": (
                f"Daily 1-min OHLCV refresh + gap fill via Kite MCP. "
                f"Cron in {settings.TIMEZONE}: {settings.DAILY_REFRESH_CRON}. "
                f"Catch-up window: {settings.DAILY_REFRESH_CATCHUP_HOURS}h. "
                f"Workflow skips automatically if already ran today or it's a weekend."
            ),
        },
        {
            "id": "daily-index-1min-refresh",
            "workflow": "DailyIndexRefreshWorkflow",
            "args": [],
            "note": (
                f"Daily 1-min OHLCV refresh for NSE/BSE index symbols. "
                f"Cron in {settings.TIMEZONE}: {settings.DAILY_REFRESH_CRON}. "
                f"Catch-up window: {settings.DAILY_REFRESH_CATCHUP_HOURS}h. "
                f"Shares rate limiter (180 RPM) with equity refresh."
            ),
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def get_client() -> Client:
    return await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )


def _make_schedule(sched: dict) -> Schedule:
    action = ScheduleActionStartWorkflow(
        sched["workflow"],
        *sched.get("args", []),
        id=f"{sched['id']}-run",
        task_queue="trading-main",
        execution_timeout=timedelta(hours=12),
        retry_policy=RetryPolicy(maximum_attempts=1),  # no auto-retry; workflow has its own guards
    )
    spec = ScheduleSpec(
        cron_expressions=[settings.DAILY_REFRESH_CRON],
        time_zone_name=settings.TIMEZONE,   # cron times interpreted in IST, not UTC
    )
    policy = SchedulePolicy(
        overlap=ScheduleOverlapPolicy.SKIP,          # skip if already running
        catchup_window=timedelta(hours=settings.DAILY_REFRESH_CATCHUP_HOURS),
        pause_on_failure=False,
    )
    state = ScheduleState(note=sched.get("note", ""))
    return Schedule(action=action, spec=spec, policy=policy, state=state)


async def register_all(client: Client) -> None:
    for sched in build_schedules():
        schedule_id = sched["id"]
        schedule    = _make_schedule(sched)
        try:
            await client.create_schedule(schedule_id, schedule)
            print(
                f"[register] Created  {schedule_id!r}\n"
                f"           cron={settings.DAILY_REFRESH_CRON!r}  "
                f"tz={settings.TIMEZONE!r}  "
                f"catchup={settings.DAILY_REFRESH_CATCHUP_HOURS}h"
            )
        except ScheduleAlreadyRunningError:
            handle = client.get_schedule_handle(schedule_id)
            await handle.update(lambda s, _sch=schedule: ScheduleUpdate(schedule=_sch))
            print(
                f"[register] Updated  {schedule_id!r}\n"
                f"           cron={settings.DAILY_REFRESH_CRON!r}  "
                f"tz={settings.TIMEZONE!r}  "
                f"catchup={settings.DAILY_REFRESH_CATCHUP_HOURS}h"
            )
        except Exception as exc:
            print(f"[register] ERROR    {schedule_id!r}: {exc}")
            raise


async def list_schedules(client: Client) -> None:
    print(f"\n{'ID':<35} {'CRON':<25} {'TZ':<20} {'NEXT RUN (UTC)'}")
    print("─" * 100)
    async for sched in await client.list_schedules():
        spec = sched.schedule.spec
        cron = spec.cron_expressions[0] if spec.cron_expressions else "—"
        tz   = getattr(spec, "time_zone_name", None) or getattr(spec, "timezone", "UTC") or "UTC"
        nxt  = sched.info.next_action_times[0] if sched.info.next_action_times else "—"
        print(f"{sched.id:<35} {cron:<25} {tz:<20} {nxt}")


async def trigger_schedule(client: Client, schedule_id: str) -> None:
    handle = client.get_schedule_handle(schedule_id)
    await handle.trigger()
    print(
        f"[trigger] Triggered {schedule_id!r}\n"
        f"          Check Temporal UI → http://localhost:8080"
    )


async def delete_schedule(client: Client, schedule_id: str) -> None:
    handle = client.get_schedule_handle(schedule_id)
    await handle.delete()
    print(f"[delete] Deleted {schedule_id!r}")


# ─────────────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    client = await get_client()

    if args.list:
        await list_schedules(client)
    elif args.trigger:
        await trigger_schedule(client, args.trigger)
    elif args.delete:
        await delete_schedule(client, args.delete)
    else:
        await register_all(client)
        print(f"\nDone. View at http://localhost:8080/namespaces/{settings.TEMPORAL_NAMESPACE}/schedules")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Register Temporal schedules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--list",    action="store_true",   help="List all schedules")
    parser.add_argument("--trigger", metavar="ID",          help="Trigger a schedule immediately")
    parser.add_argument("--delete",  metavar="ID",          help="Delete a schedule")
    asyncio.run(main(parser.parse_args()))
