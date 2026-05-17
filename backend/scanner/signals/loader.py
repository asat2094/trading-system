import pathlib
import yaml
from scanner.signals.models import SignalConfig
from core.logging import get_logger

log = get_logger(__name__)

_DEFAULT_PATH = pathlib.Path(__file__).parents[2] / "workers" / "config" / "signals.yaml"


def load_signals(path: str | None = None) -> list[SignalConfig]:
    yaml_path = pathlib.Path(path) if path else _DEFAULT_PATH
    raw = yaml.safe_load(yaml_path.read_text())
    signals = []
    for item in raw.get("signals", []):
        try:
            signals.append(SignalConfig(**item))
        except Exception as exc:
            log.error("signal_yaml_invalid", name=item.get("name"), error=str(exc))
            raise
    log.info("signals_loaded", count=len(signals))
    return signals
