# backend/journal/parsers/pdf.py
import io
import pdfplumber
from pathlib import Path
from ..models import Trade

def _open_pdf(file_bytes: bytes, password: str | None = None):
    """Open PDF, optionally with password. Returns pdfplumber PDF object."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            if not password:
                raise ValueError("PDF is encrypted. Provide password (usually your PAN).")
            if not reader.decrypt(password):
                raise ValueError("Wrong password for encrypted PDF.")
    except ImportError:
        pass  # pypdf not installed, let pdfplumber try
    return pdfplumber.open(io.BytesIO(file_bytes), password=password)

def _extract_text(file_bytes: bytes, password: str | None = None) -> str:
    with _open_pdf(file_bytes, password) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages[:2])
    if not text.strip():
        raise ValueError("Unparseable PDF — no text layer")
    return text

def _extract_tables(file_bytes: bytes, password: str | None = None) -> list[list[str | None]]:
    rows = []
    with _open_pdf(file_bytes, password) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                rows.extend(table)
    return rows

def detect_broker(text: str) -> str:
    if "Mirae Asset" in text or "mstock" in text.lower(): return "mstock"
    if "NU Investors" in text or "lemonn" in text.lower(): return "lemonn"
    if "Zerodha" in text: return "zerodha"
    if "Upstox" in text: return "upstox"
    return "zerodha"  # safe fallback

async def parse_pdf_contract_note(
    file_bytes: bytes,
    broker: str = "auto",
    source_file: str = "",
    password: str | None = None,
) -> list[Trade]:
    text = _extract_text(file_bytes, password)
    detected = broker if broker != "auto" else detect_broker(text)
    rows = _extract_tables(file_bytes, password)

    from . import mstock, lemonn, zerodha
    _PARSERS = {
        "mstock": mstock.parse,
        "lemonn": lemonn.parse,
        "zerodha": zerodha.parse,
        "pdf": zerodha.parse,
    }
    return _PARSERS.get(detected, zerodha.parse)(rows, text=text, source_file=source_file)
