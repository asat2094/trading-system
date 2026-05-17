import importlib.util
import pathlib


def test_migration_001_has_upgrade_and_downgrade():
    path = pathlib.Path(__file__).parents[2] / "infra/alembic/versions/001_initial.py"
    spec = importlib.util.spec_from_file_location("migration_001", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
    assert mod.revision == "001"
    assert mod.down_revision is None


def test_migration_creates_all_required_tables():
    """Verify all expected table names appear in the upgrade() source."""
    import inspect
    import pathlib

    path = pathlib.Path(__file__).parents[2] / "infra/alembic/versions/001_initial.py"
    source = path.read_text()

    required_tables = [
        "stocks", "stock_attributes", "scan_results", "trading_calendar",
        "agent_activities", "market_event_types", "market_events",
        "data_quality_alerts", "adjustment_factors",
    ]
    for table in required_tables:
        assert f'"{table}"' in source or f"'{table}'" in source, \
            f"Table '{table}' not found in migration 001"
