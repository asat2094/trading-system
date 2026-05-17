from core.config import settings

SCANNER_DSL_VERSION = settings.SCANNER_DSL_VERSION


def build_dsl(scanner) -> dict:
    return {
        "version": SCANNER_DSL_VERSION,
        "source": scanner._source or {},
        "filters": scanner._filters,
        "conditions": [fn.__name__ if hasattr(fn, "__name__") else str(fn) for fn in getattr(scanner, "_conditions", [])],
        "analysis": scanner._analysis,
        "indicators": scanner._indicators,
        "sort": scanner._sort,
    }
