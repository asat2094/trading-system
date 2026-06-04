# backend/journal/parsers/base.py
from abc import ABC, abstractmethod
from ..models import Trade

class BaseParser(ABC):
    broker: str = "unknown"

    @abstractmethod
    def parse(self, rows: list[list[str | None]], text: str = "", source_file: str = "") -> list[Trade]:
        ...
