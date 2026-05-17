import importlib.util
import pathlib
import sys

from core.logging import get_logger

log = get_logger(__name__)

ACTIVITIES_DIR = pathlib.Path(__file__).parent / "activities"


def _load_activity_from_path(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"workers.activities.{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    fn = getattr(module, "activity_fn", None)
    if fn is None:
        raise AttributeError(f"activity_fn not found in {path.name}")

    definition = getattr(fn, "__temporal_activity_definition", None)
    if definition is None:
        raise AttributeError(f"activity_fn in {path.name} missing @activity.defn decorator")

    name = definition.name
    return fn, name


def _collect_activities(activities_dir: pathlib.Path) -> list[tuple]:
    seen: set[str] = set()
    collected = []

    for path in sorted(activities_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            fn, name = _load_activity_from_path(path)
            if name in seen:
                raise ValueError(f"Duplicate activity name '{name}' in {path.name}")
            seen.add(name)
            collected.append((fn, name, path.stem))
        except ValueError:
            raise
        except Exception as exc:
            log.error("activity_load_failed", file=path.stem, error=str(exc))
            raise

    return collected


def register_all() -> list[tuple]:
    """Collect all valid activities from ACTIVITIES_DIR. Returns list of (fn, name, stem)."""
    return _collect_activities(ACTIVITIES_DIR)
