from temporalio import activity
from core.logging import get_logger
from scanner.signals.loader import load_signals

log = get_logger(__name__)


@activity.defn(name="run_scanner_presets")
async def activity_fn(presets: list[str] | None = None) -> dict:
    signals = load_signals()
    target = set(presets) if presets else {s.name for s in signals}
    ran = 0

    for sig in signals:
        if sig.name not in target:
            continue
        log.info("scanner_preset_run", name=sig.name)
        ran += 1

    log.info("run_scanner_presets_complete", ran=ran)
    return {"presets_run": ran}
