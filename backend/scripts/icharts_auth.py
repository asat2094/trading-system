"""
icharts.in auth harvester — uses Playwright to capture live session credentials.
Writes to auth.json. Script runs headed for first login, then headless for refresh.

Usage:
    .venv/bin/python icharts_auth.py          # interactive login → save auth
    .venv/bin/python icharts_auth.py --check  # validate existing auth.json
"""

import json
import sys
import time
from pathlib import Path

AUTH_FILE = Path(__file__).parent / "auth.json"
LOGIN_URL = "https://www.icharts.in/opt/FnOCharts.php"
TEST_URL_TEMPLATE = (
    "https://www.icharts.in/opt/getdataFNO_Chart_TV_Charts_Daily_v2.php"
    "?symbol=NIFTY26MAY26&resolution=1&from=2026-05-28&to=2026-05-29"
    "&u={email}&sid={sid}&DataRequest=2&firstDataRequest=true&countback=10"
)


def harvest(headless: bool = False) -> dict:
    """Open browser, wait for user to log in, capture credentials from network."""
    from playwright.sync_api import sync_playwright

    captured = {}

    def on_request(request):
        url = request.url
        if "getdataFNO_Chart_TV_Charts_Daily_v2.php" in url and "sid=" in url:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(url).query)
            captured["sid"] = qs.get("sid", [""])[0]
            captured["email"] = qs.get("u", [""])[0]
            headers = request.headers
            captured["api_key"] = headers.get("x-api-key", "")
            captured["cookie"] = headers.get("cookie", "")
            captured["user_agent"] = headers.get("user-agent", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.on("request", on_request)

        print(f"Opening {LOGIN_URL} ...")
        page.goto(LOGIN_URL, timeout=30000)

        if not headless:
            print("Log in and load any F&O chart. Waiting for data request...")

        # Wait up to 120s for a data request to be intercepted
        deadline = time.time() + 120
        while not captured.get("sid") and time.time() < deadline:
            try:
                page.wait_for_timeout(1000)
            except Exception:
                break

        browser.close()

    if not captured.get("sid"):
        raise RuntimeError("No data request captured. Did you load a chart after login?")

    captured["harvested_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return captured


def save_auth(creds: dict):
    AUTH_FILE.write_text(json.dumps(creds, indent=2))
    print(f"Auth saved → {AUTH_FILE}")


def load_auth() -> dict:
    if not AUTH_FILE.exists():
        raise FileNotFoundError(f"{AUTH_FILE} not found. Run: python icharts_auth.py")
    return json.loads(AUTH_FILE.read_text())


def check_auth(creds: dict) -> bool:
    """Fire a test request and return True if session is valid."""
    import requests
    url = TEST_URL_TEMPLATE.format(email=creds["email"], sid=creds["sid"])
    headers = {
        "User-Agent": creds.get("user_agent", "Mozilla/5.0"),
        "Referer": "https://www.icharts.in/opt/FnOCharts.php",
        "x-api-key": creds.get("api_key", ""),
        "Cookie": creds.get("cookie", ""),
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.status_code == 200 and "Invalid Session" not in r.text and r.text.strip().startswith("{")
    except Exception:
        return False


def ensure_auth(auto_refresh: bool = True) -> dict:
    """Load auth.json; if invalid, re-harvest (headed). Returns valid creds."""
    try:
        creds = load_auth()
        if check_auth(creds):
            return creds
        print("Existing auth expired.")
    except FileNotFoundError:
        print("No auth.json found.")

    if not auto_refresh:
        raise RuntimeError("Auth invalid and auto_refresh=False")

    print("Opening browser for re-login...")
    creds = harvest(headless=False)
    save_auth(creds)
    return creds


if __name__ == "__main__":
    if "--check" in sys.argv:
        try:
            creds = load_auth()
            ok = check_auth(creds)
            print(f"Session {'VALID' if ok else 'EXPIRED'} (sid={creds.get('sid','?')[:12]}...)")
        except FileNotFoundError as e:
            print(e)
    else:
        creds = harvest(headless=False)
        save_auth(creds)
        print(f"SID: {creds['sid']}")
        print(f"API key: {creds['api_key']}")
