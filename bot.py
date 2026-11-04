import json
import os
import re
import ssl
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter

from ocr import solve_image

# ============================================================
# JOURNEY CONFIGURATION
# ============================================================

TRAIN_NO = "07097 - HYB MAQ SPL"
TRAIN_NAME = "HYB MAQ SPL"
SOURCE = "ERODE JN. - ED"
DESTINATION = "KANHANGAD - KZE"
CLASS_CODE = "3A"
QUOTA = "GN"

# Date format used when sending the request to Indian Railways
JOURNEY_DATE = "18-11-2026"
# Date format used inside the Railway JSON response
TARGET_DATE = "2026-11-18"

# Alert when availability falls by this much or more
# from the last notification baseline
DROP_THRESHOLD = 10

# When available seats are at or below this number,
# alert on EVERY single drop
LOW_SEAT_LIMIT = 10

# ============================================================
# LOCAL FILES
# ============================================================

STATE_FILE = Path("state.json")
CAPTCHA_FILE = Path("captcha.png")
RESPONSE_FILE = Path("last_response.json")

# ============================================================
# INDIAN RAILWAYS URLs
# ============================================================

BASE_URL = "https://www.indianrail.gov.in/enquiry"
SEAT_PAGE_URL = f"{BASE_URL}/SEAT/SeatAvailability.html?locale=en"
CAPTCHA_CONFIG_URL = f"{BASE_URL}/CaptchaConfig"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/captchaDraw.png"
COMMON_CAPTCHA_URL = f"{BASE_URL}/CommonCaptcha"


# ============================================================
# HTTP SESSION
# ============================================================

class LegacyTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4  # allow legacy server connect
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def is_maintenance_window():
    """Skip midnight through 12:30 AM IST (railway site downtime)."""
    now = datetime.now(ZoneInfo("Asia/Kolkata")).time()
    return dt_time(0, 0) <= now < dt_time(0, 30)


def create_session():
    """One HTTP session so cookies are reused across requests."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.mount("https://", LegacyTLSAdapter())
    return session


# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_state():
    """Load state.json, or create an empty baseline on first run."""
    if not STATE_FILE.exists():
        return {
            "last_available": None,
            "last_notified": None,
            "history": [],
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ============================================================
# GET CAPTCHA
# ============================================================

def get_captcha(session):
    """Load the Railway page and download its CAPTCHA image."""
    response = session.get(SEAT_PAGE_URL, timeout=30)
    response.raise_for_status()

    session.get(CAPTCHA_CONFIG_URL, timeout=30)

    # Timestamp avoids getting a cached CAPTCHA image
    params = {"_": int(time.time() * 1000)}
    response = session.get(CAPTCHA_IMAGE_URL, params=params, timeout=30)
    response.raise_for_status()

    CAPTCHA_FILE.write_bytes(response.content)


# ============================================================
# REQUEST AVAILABILITY
# ============================================================

def request_availability(session, captcha):
    """Send the solved CAPTCHA + journey details to Railway."""
    params = {
        "inputCaptcha": captcha,
        "trainNo": TRAIN_NO,
        "dt": JOURNEY_DATE,
        "sourceStation": SOURCE,
        "destinationStation": DESTINATION,
        "classc": CLASS_CODE,
        "quota": QUOTA,
        "inputPage": "SEAT",
        "language": "en",
    }

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SEAT_PAGE_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    response = session.get(
        COMMON_CAPTCHA_URL,
        params=params,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    # Keep the raw response for debugging
    with open(RESPONSE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    if data.get("errorMessage"):
        raise RuntimeError(data["errorMessage"])

    return data


# ============================================================
# EXTRACT AVAILABLE SEATS
# ============================================================

def get_available(response):
    """
    Find TARGET_DATE in avlDayList and extract the number from
    a status like "AVAILABLE-0187" -> 187.
    Returns None if the status is not a normal AVAILABLE value.
    """
    if response.get("errorMessage"):
        raise RuntimeError(response["errorMessage"])

    for item in response.get("avlDayList", []):
        if item.get("availablityDate") != TARGET_DATE:
            continue

        status = item.get("availablityStatus", "")
        match = re.search(r"AVAILABLE-(\d+)", status)
        if match:
            return int(match.group(1))

        return None

    raise RuntimeError("Target date not found in response.")


# ============================================================
# TELEGRAM NOTIFICATION
# ============================================================

def send_telegram(message):
    """Send an alert via Telegram (credentials from env variables)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": chat_id, "text": message},
        timeout=30,
    )
    response.raise_for_status()


# ============================================================
# ALERT LOGIC
# ============================================================

def is_big_drop(previous, current):
    """True if seats fell by DROP_THRESHOLD or more since the last notification."""
    return previous is not None and previous - current >= DROP_THRESHOLD


def is_low_seat_drop(last_seen, current):
    """True if seats are <= LOW_SEAT_LIMIT and went down since the last check."""
    return (
        last_seen is not None
        and current <= LOW_SEAT_LIMIT
        and current < last_seen
    )


def build_alert_message(reason, current, drop):
    """Build the Telegram message text."""
    return (
        "🚆 Indian Railways Seat Alert\n"
        f"{reason}\n\n"
        f"Train: {TRAIN_NO} - {TRAIN_NAME}\n"
        f"Route: {SOURCE} → {DESTINATION}\n"
        "Date: 18 Nov 2026\n"
        f"Class: {CLASS_CODE}\n"
        f"Quota: {QUOTA}\n\n"
        f"Available: {current}\n"
        f"Drop: {drop}"
    )


def check_and_notify(state, current):
    """
    Decide whether to alert, send it, and update last_notified.
    The low-seat rule takes priority over the big-drop rule.
    Must run BEFORE update_history so last_available is still the old value.
    """
    previous = state.get("last_notified")
    last_seen = state.get("last_available")

    if is_low_seat_drop(last_seen, current):
        drop = last_seen - current
        reason = f"⚠️ LOW SEATS - only {current} left"
    elif is_big_drop(previous, current):
        drop = previous - current
        reason = "Big drop"
    else:
        if previous is None:  # first run: set baseline, no alert
            state["last_notified"] = current
        return

    send_telegram(build_alert_message(reason, current, drop))
    state["last_notified"] = current


def update_history(state, current):
    """Record the latest availability. Returns True if it changed."""
    if current == state.get("last_available"):
        return False

    state["last_available"] = current
    state.setdefault("history", []).append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "available": current,
    })
    state["history"] = state["history"][-100:]
    return True


# ============================================================
# MAIN BOT
# ============================================================

def main():
    if is_maintenance_window():
        print("Scheduled website downtime. Skipping this run.")
        return

    state = load_state()
    session = create_session()

    # STEP 1: download the CAPTCHA
    get_captcha(session)

    # STEP 2: solve it with OCR
    captcha = solve_image("captcha.png")
    if not captcha:
        raise ValueError("CAPTCHA cannot be empty.")

    # STEP 3: ask Indian Railways for availability
    response = request_availability(session, captcha)

    # STEP 4: extract the number of available seats
    current = get_available(response)
    if current is None:
        print("Availability is not currently AVAILABLE.")
        return

    # STEP 5: alert logic (low-seat rule + big-drop rule)
    check_and_notify(state, current)

    # STEP 6: remember latest availability
    update_history(state, current)
    save_state(state)  # always save, so last_notified is never lost

    print(current)


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":
    main()
