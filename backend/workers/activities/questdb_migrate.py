import pathlib
import psycopg2
from temporalio import activity
from core.config import settings
from core.logging import get_logger

log = get_logger(__name__)

@activity.defn(name="questdb_migrate")
async def activity_fn() -> None:
    """Run QuestDB DDL migrations. Idempotent — uses IF NOT EXISTS."""
    sql_path = (
        pathlib.Path(__file__).parents[3]
        / "infra"
        / "questdb"
        / "migrations"
        / "001_initial.sql"
    )
    sql = sql_path.read_text()

    import asyncio

    def _run_migration():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                cur.execute(stmt)
        conn.close()
        log.info("questdb_migrate_complete")

    await asyncio.get_event_loop().run_in_executor(None, _run_migration)
