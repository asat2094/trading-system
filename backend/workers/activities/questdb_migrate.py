import asyncio
import pathlib

import psycopg2
from temporalio import activity

from core.config import settings
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="questdb_migrate")
async def activity_fn() -> None:
    sql_path = pathlib.Path(__file__).parents[3] / "infra" / "questdb" / "migrations" / "001_initial.sql"
    sql = sql_path.read_text()

    await asyncio.to_thread(_run_migration, sql)
    log.info("questdb_migrate_complete")


def _run_migration(sql: str) -> None:
    conn = psycopg2.connect(settings.QUESTDB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        statements = [s.strip() for s in sql.split(";")]
        for i, stmt in enumerate(statements):
            # Skip blank lines and comment-only blocks
            non_comment = "\n".join(
                line for line in stmt.splitlines() if not line.strip().startswith("--")
            ).strip()
            if not non_comment:
                continue
            log.info("questdb_migrate_statement", index=i, preview=non_comment[:60])
            cur.execute(stmt)
    finally:
        cur.close()
        conn.close()
