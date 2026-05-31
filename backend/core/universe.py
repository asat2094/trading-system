"""Symbol universe helpers — Nifty 500 + FnO lists + Index universe.

Sources:
  - Nifty 500: NSE archives CSV (public, no auth)
  - FnO stocks: Kite NFO instruments list (futures underlyings)
  - Index universe: hardcoded NSE/BSE index list (segment=INDICES on Kite)
"""
from __future__ import annotations

import csv
import io
import urllib.request
from datetime import date
from functools import lru_cache
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# Index universe  (tradingsymbol, exchange) pairs
# QuestDB symbol = EXCHANGE_TRADINGSYMBOL_WITH_SPACES_AND_AMPERSAND_REPLACED
# e.g. ("NIFTY 50", "NSE") → "NSE_NIFTY_50"
#      ("BSE POWER & ENERGY", "BSE") → "BSE_BSE_POWER_AND_ENERGY"
# ──────────────────────────────────────────────────────────────────────────────

INDEX_UNIVERSE: list[tuple[str, str]] = [
    # NSE broad
    ("NIFTY 50",           "NSE"), ("NIFTY NEXT 50",     "NSE"),
    ("NIFTY 100",          "NSE"), ("NIFTY 200",          "NSE"),
    ("NIFTY 500",          "NSE"), ("NIFTY TOTAL MKT",    "NSE"),
    ("INDIA VIX",          "NSE"),
    # NSE size
    ("NIFTY MIDCAP 50",    "NSE"), ("NIFTY MIDCAP 100",   "NSE"),
    ("NIFTY MIDCAP 150",   "NSE"), ("NIFTY MID SELECT",   "NSE"),
    ("NIFTY SMLCAP 50",    "NSE"), ("NIFTY SMLCAP 100",   "NSE"),
    ("NIFTY SMLCAP 250",   "NSE"), ("NIFTY LARGEMID250",  "NSE"),
    ("NIFTY MICROCAP250",  "NSE"), ("NIFTY MIDSML 400",   "NSE"),
    # NSE sectoral
    ("NIFTY BANK",         "NSE"), ("NIFTY AUTO",          "NSE"),
    ("NIFTY FIN SERVICE",  "NSE"), ("NIFTY FMCG",          "NSE"),
    ("NIFTY IT",           "NSE"), ("NIFTY MEDIA",         "NSE"),
    ("NIFTY METAL",        "NSE"), ("NIFTY PHARMA",        "NSE"),
    ("NIFTY PSU BANK",     "NSE"), ("NIFTY PVT BANK",      "NSE"),
    ("NIFTY REALTY",       "NSE"), ("NIFTY ENERGY",        "NSE"),
    ("NIFTY INFRA",        "NSE"), ("NIFTY COMMODITIES",   "NSE"),
    ("NIFTY CONSUMPTION",  "NSE"), ("NIFTY CPSE",          "NSE"),
    ("NIFTY HEALTHCARE",   "NSE"), ("NIFTY OIL AND GAS",   "NSE"),
    ("NIFTY CONSR DURBL",  "NSE"), ("NIFTY MNC",           "NSE"),
    ("NIFTY PSE",          "NSE"), ("NIFTY SERV SECTOR",   "NSE"),
    # NSE thematic
    ("NIFTY IND DEFENCE",  "NSE"), ("NIFTY IND DIGITAL",   "NSE"),
    ("NIFTY INDIA MFG",    "NSE"), ("NIFTY DIV OPPS 50",   "NSE"),
    ("NIFTY HOUSING",      "NSE"), ("NIFTY CAPITAL MKT",   "NSE"),
    ("NIFTY MOBILITY",     "NSE"), ("NIFTY IND TOURISM",   "NSE"),
    # BSE
    ("SENSEX",             "BSE"), ("BANKEX",               "BSE"),
    ("SENSEX NEXT 30",     "BSE"), ("BSE100",               "BSE"),
    ("BSE200",             "BSE"), ("BSE500",               "BSE"),
    ("BSE IT",             "BSE"), ("BSE HC",               "BSE"),
    ("BSE CD",             "BSE"), ("BSE CG",               "BSE"),
    ("BSE PSU BANK",       "BSE"), ("BSE POWER & ENERGY",   "BSE"),
]


def index_to_questdb(tradingsymbol: str, exchange: str) -> str:
    """Convert Kite index (tradingsymbol, exchange) to QuestDB symbol name.

    ("NIFTY 50", "NSE")         → "NSE_NIFTY_50"
    ("BSE POWER & ENERGY", "BSE") → "BSE_BSE_POWER_AND_ENERGY"
    """
    key = f"{exchange}:{tradingsymbol}"
    return key.replace(":", "_").replace(" ", "_").replace("&", "AND")


# Reverse lookup: QuestDB symbol → (tradingsymbol, exchange)
_QUESTDB_TO_INDEX: dict[str, tuple[str, str]] = {
    index_to_questdb(sym, ex): (sym, ex)
    for sym, ex in INDEX_UNIVERSE
}


def questdb_to_index(questdb_symbol: str) -> tuple[str, str] | None:
    """Reverse map QuestDB symbol back to (tradingsymbol, exchange) for Kite API."""
    return _QUESTDB_TO_INDEX.get(questdb_symbol)


def get_index_questdb_symbols() -> list[str]:
    """Return all index symbols in QuestDB naming format."""
    return [index_to_questdb(sym, ex) for sym, ex in INDEX_UNIVERSE]


# ──────────────────────────────────────────────────────────────────────────────
# Nifty 500
# ──────────────────────────────────────────────────────────────────────────────

NIFTY500_CSV_URL = (
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
)

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/",
}


def fetch_nifty500() -> list[str]:
    """Return list of Nifty 500 trading symbols (NSE).

    Falls back to cached list on network failure.
    """
    try:
        req = urllib.request.Request(NIFTY500_CSV_URL, headers=_NSE_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        symbols = [row["Symbol"].strip() for row in reader if row.get("Symbol")]
        if len(symbols) >= 450:   # sanity check
            return symbols
    except Exception as exc:
        print(f"[universe] Nifty500 fetch failed: {exc} — using fallback")

    return _NIFTY500_FALLBACK


# ──────────────────────────────────────────────────────────────────────────────
# FnO (via Kite instruments — NFO futures underlyings)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_fno_symbols(kite) -> list[str]:
    """Return list of NSE symbols that have active F&O contracts.

    Uses Kite's NFO instruments list, filters for FUT contracts with
    expiry >= today, returns unique underlying symbols.
    """
    today = date.today()
    instruments = kite.instruments("NFO")
    symbols: set[str] = set()
    for inst in instruments:
        if inst.get("instrument_type") == "FUT":
            expiry = inst.get("expiry")
            # expiry is a date object from kiteconnect
            if expiry and expiry >= today:
                # Underlying is the name field, tradingsymbol has expiry suffix
                # e.g. tradingsymbol = "RELIANCE26MAYFUT", name = "RELIANCE"
                underlying = inst.get("name", "").strip()
                if underlying:
                    symbols.add(underlying)
    result = sorted(symbols)
    print(f"[universe] FnO symbols: {len(result)}")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Combined universe
# ──────────────────────────────────────────────────────────────────────────────

def build_trading_universe(kite=None) -> list[str]:
    """Return sorted union of Nifty 500 + FnO symbols.

    Pass kite client to include live FnO list. Without kite, returns
    Nifty 500 only.
    """
    nifty500 = set(fetch_nifty500())
    print(f"[universe] Nifty 500: {len(nifty500)} symbols")

    fno: set[str] = set()
    if kite is not None:
        fno = set(fetch_fno_symbols(kite))

    universe = sorted(nifty500 | fno)
    print(f"[universe] Combined (N500 ∪ FnO): {len(universe)} symbols")
    return universe


# ──────────────────────────────────────────────────────────────────────────────
# Fallback Nifty 500 list (as of May 2025 — update periodically)
# Used only when NSE CSV is unreachable
# ──────────────────────────────────────────────────────────────────────────────

_NIFTY500_FALLBACK: list[str] = [
    "20MICRONS", "21STCENMGM", "360ONE", "3MINDIA", "5PAISA",
    "AADHARHFC", "AARTIDRUGS", "AARTIIND", "AARTISURF", "AAVAS",
    "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ABSL",
    "ACC", "ACCELYA", "ACMESOLAR", "ADANIENT", "ADANIGREEN",
    "ADANIPORTS", "ADANIPOWER", "ADANITRANS", "AIAENG", "AJANTPHARM",
    "AKZOINDIA", "ALKEM", "ALKYLAMINE", "ALLCARGO", "ALLDIGI",
    "AMARAJABAT", "AMBIKCO", "AMBUJACEM", "ANANDRATHI", "ANGELONE",
    "ANURAS", "APARINDS", "APOLLOHOSP", "APOLLOTYRE", "ARVINDFASN",
    "ARVINDLTD", "ASAHIINDIA", "ASHOKLEY", "ASIANPAINT", "ASTERDM",
    "ASTRAL", "ATGL", "ATUL", "AUBANK", "AUROPHARMA",
    "AVANTIFEED", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
    "BALKRISIND", "BALMLAWRIE", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA",
    "BANKINDIA", "BAYERCROP", "BDL", "BEL", "BEML",
    "BERGEPAINT", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON",
    "BIRLACORPN", "BKTYRE", "BLUESTARCO", "BPCL", "BRIGADE",
    "BRITANNIA", "BSE", "BSOFT", "BSESENSEX", "CAMS",
    "CANBANK", "CANFINHOME", "CAPLIPOINT", "CARBORUNIV", "CASTROLIND",
    "CEATLTD", "CENTRALBK", "CENTURYTEX", "CESC", "CGPOWER",
    "CHALET", "CHAMBLFERT", "CHOLAFIN", "CHOLAHLDNG", "CIPLA",
    "CIL", "CLEAN", "COALINDIA", "COFORGE", "COLPAL",
    "CONCORDBIO", "COROMANDEL", "CROMPTON", "CSBBANK", "CUMMINSIND",
    "CYIENT", "DABUR", "DALBHARAT", "DATAPATTNS", "DCMSHRIRAM",
    "DEEPAKNTR", "DELHIVERY", "DELTACORP", "DEVYANI", "DHANUKA",
    "DIVISLAB", "DIXON", "DLF", "DMART", "DRREDDY",
    "EASEMYTRIP", "EDELWEISS", "ELGIEQUIP", "EMAMILTD", "ENGINERSIN",
    "EPL", "ERIS", "ESCORTS", "EXIDEIND", "FACT",
    "FINCABLES", "FINPIPE", "FLUOROCHEM", "FMGOETZE", "FSL",
    "GAIL", "GALAXYSURF", "GARFIBRES", "GLAND", "GLAXO",
    "GLENMARK", "GMRAIRPORT", "GMRINFRA", "GNFC", "GODAWARI",
    "GODREJCP", "GODREJIND", "GODREJPROP", "GREAVESCOT", "GRASIM",
    "GREENPANEL", "GRINFRA", "GSFC", "GSPL", "GTPL",
    "GUJAPOLLO", "GUJGASLTD", "GULFOILLUB", "HAL", "HAPPSTMNDS",
    "HATHWAY", "HCC", "HCLTECH", "HDFCAMC", "HDFCBANK",
    "HDFCLIFE", "HERITGFOOD", "HEROMOTOCO", "HFCL", "HIKAL",
    "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "HINDZINC",
    "HONASA", "HONAUT", "HUDCO", "HYUNDAI",
    "IBREALEST", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDBI",
    "IDEA", "IDFCFIRSTB", "IEX", "IGL", "IIFL",
    "IIFLTRADE", "INDIGOPNTS", "INDHOTEL", "INDIAMART", "INDIGO",
    "INDUSINDBK", "INDUSTOWER", "INFY", "INGERRAND", "INTELLECT",
    "IOB", "IOC", "IPCALAB", "IRB", "IRCTC",
    "IRFC", "ITC", "ITI", "ITILTD", "J&KBANK",
    "JBCHEPHARM", "JBMA", "JINDALPOLY", "JINDALSAW", "JINDALSTEL",
    "JKCEMENT", "JKLAKSHMI", "JKPAPER", "JMFINANCIL", "JSWENERGY",
    "JSWINFRA", "JSWSTEEL", "JUBLFOOD", "JUBLINDS", "JUBLINGREA",
    "JUSTDIAL", "JYOTHYLAB", "KAJARIACER", "KALPATPOWR", "KANSAINER",
    "KARURVYSYA", "KAYNES", "KFINTECH", "KIRLOSIND", "KIRLPNU",
    "KNRCON", "KOTAKBANK", "KPIL", "KRBL", "KSCL",
    "L&TFH", "LALPATHLAB", "LAURUSLABS", "LAXMIMACH", "LICHSGFIN",
    "LICI", "LINDEINDIA", "LT", "LTIM", "LTTS",
    "LUPIN", "LUXIND", "M&M", "M&MFIN", "MAHABANK",
    "MAHINDCIE", "MARICO", "MARUTI", "MASTEK", "MAXHEALTH",
    "MCX", "METROPOLIS", "MFSL", "MGL", "MIDHANI",
    "MINDAIND", "MINDTREE", "MMTC", "MOIL", "MPHASIS",
    "MRF", "MRPL", "MTARTECH", "MUTHOOTFIN", "NATCOPHARM",
    "NAUKRI", "NAVINFLUOR", "NBCC", "NCC", "NESTLEIND",
    "NETWORK18", "NFL", "NH", "NHPC", "NIACL",
    "NLCINDIA", "NMDC", "NOCIL", "NPTC", "NTPC",
    "NUVOCO", "OAL", "OBEROIRLTY", "OFSS", "OIL",
    "ONGC", "ORIENTELEC", "PAGEIND", "PEL", "PERSISTENT",
    "PETRONET", "PFC", "PFIZER", "PHOENIXLTD", "PIDILITIND",
    "PIIND", "PNB", "POLYCAB", "POLYMED", "POONAWALLA",
    "POWERGRID", "PRESTIGE", "PRINCEPIPE", "PRIVISCL", "PSPPROJECT",
    "PTC", "PVRINOX", "RADICO", "RAILTEL", "RAINBOW",
    "RAJESHEXPO", "RALLIS", "RAMCOCEM", "RAMCOSYS", "RATNAMANI",
    "RBA", "RECLTD", "REDINGTON", "RELAXO", "RELIANCE",
    "RENUKA", "RITES", "ROSSARI", "ROUTE", "RPOWER",
    "SANOFI", "SAPPHIRE", "SAREGAMA", "SBCL", "SBICARD",
    "SBILIFE", "SBIN", "SCHAEFFLER", "SEQUENT", "SFL",
    "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SIGNATURE", "SJVN",
    "SKFINDIA", "SOBHA", "SOLARA", "SONACOMS", "SRTRANSFIN",
    "STAR", "STARHEALTH", "STICL", "SUDARSCHEM", "SUMICHEM",
    "SUNPHARMA", "SUNTV", "SUPREMEIND", "SUZLON", "SWANENERGY",
    "SYMPHONY", "SYNGENE", "TANLA", "TASTYBITE", "TATACHEM",
    "TATACOMM", "TATACONSUM", "TATAELXSI", "TATAMOTORS", "TATAMTRDVR",
    "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TEJASNET",
    "TITAN", "TORNTPHARM", "TORNTPOWER", "TRENT", "TRIDENT",
    "TRIVENI", "TTML", "TV18BRDCST", "TVSMOTOR", "UBL",
    "ULTRACEMCO", "UNIONBANK", "UNITDSPR", "UPL", "UTIAMC",
    "VAIBHAVGBL", "VBL", "VEDL", "VIJAYA", "VINATIORGA",
    "VIPIND", "VOLTAS", "VSTIND", "WELCORP", "WELSPUNIND",
    "WHIRLPOOL", "WIPRO", "WOCKPHARMA", "XPROINDIA", "YESBANK",
    "ZEEL", "ZENSARTECH", "ZOMATO", "ZYDUSLIFE", "ZYDUSWELL",
]
