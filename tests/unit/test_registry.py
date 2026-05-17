import pytest


def test_registry_registers_valid_activity(tmp_path):
    activity_file = tmp_path / "test_activity.py"
    activity_file.write_text(
        "from temporalio import activity\n\n"
        "@activity.defn(name='test_activity')\n"
        "async def activity_fn():\n"
        "    pass\n"
    )

    from workers.registry import _load_activity_from_path
    fn, name = _load_activity_from_path(activity_file)
    assert name == "test_activity"
    assert callable(fn)


def test_registry_rejects_missing_activity_fn(tmp_path):
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def not_activity_fn(): pass\n")

    from workers.registry import _load_activity_from_path
    with pytest.raises(AttributeError, match="activity_fn"):
        _load_activity_from_path(bad_file)


def test_registry_rejects_duplicate_names(tmp_path):
    f1 = tmp_path / "a1.py"
    f2 = tmp_path / "a2.py"
    code = (
        "from temporalio import activity\n\n"
        "@activity.defn(name='duplicate_name')\n"
        "async def activity_fn():\n"
        "    pass\n"
    )
    f1.write_text(code)
    f2.write_text(code)

    from workers.registry import _collect_activities
    with pytest.raises(ValueError, match="Duplicate activity name"):
        _collect_activities(tmp_path)


def test_registry_propagates_syntax_error(tmp_path):
    bad_file = tmp_path / "bad_syntax.py"
    bad_file.write_text("def broken(\n")  # invalid syntax

    from workers.registry import _load_activity_from_path
    with pytest.raises(SyntaxError):
        _load_activity_from_path(bad_file)
