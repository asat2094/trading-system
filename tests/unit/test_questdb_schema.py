import pathlib


def test_migration_sql_exists():
    path = pathlib.Path(__file__).parents[2] / "infra/questdb/migrations/001_initial.sql"
    assert path.exists(), "001_initial.sql not found"


def test_migration_sql_has_three_tables():
    path = pathlib.Path(__file__).parents[2] / "infra/questdb/migrations/001_initial.sql"
    sql = path.read_text()
    assert "ohlcv_1min" in sql
    assert "ohlcv_hourly" in sql
    assert "ohlcv_daily" in sql


def test_migration_sql_uses_wal_dedup():
    path = pathlib.Path(__file__).parents[2] / "infra/questdb/migrations/001_initial.sql"
    sql = path.read_text()
    # Count only the WAL keywords in CREATE TABLE statements (not the comment)
    create_tables = sql.split("CREATE TABLE")[1:]
    for table in create_tables:
        assert "WAL" in table, "All tables must use WAL"
        assert "DEDUP UPSERT KEYS" in table, "All tables must have DEDUP"


def test_migration_sql_uses_if_not_exists():
    path = pathlib.Path(__file__).parents[2] / "infra/questdb/migrations/001_initial.sql"
    sql = path.read_text()
    assert sql.count("IF NOT EXISTS") == 3, "All 3 tables must be idempotent (IF NOT EXISTS)"


def test_questdb_migrate_activity_importable():
    from workers.activities.questdb_migrate import activity_fn
    assert callable(activity_fn)


def test_ohlcv_daily_has_adjusted_close():
    path = pathlib.Path(__file__).parents[2] / "infra/questdb/migrations/001_initial.sql"
    sql = path.read_text()
    # adjusted_close only in daily table (intraday stores raw)
    daily_section = sql[sql.index("ohlcv_daily"):]
    assert "adjusted_close" in daily_section


def test_ohlcv_1min_no_adjusted_close():
    path = pathlib.Path(__file__).parents[2] / "infra/questdb/migrations/001_initial.sql"
    sql = path.read_text()
    min1_section = sql[sql.index("ohlcv_1min"):sql.index("ohlcv_hourly")]
    assert "adjusted_close" not in min1_section
