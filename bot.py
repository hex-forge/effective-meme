import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from ocr import solve_image

import requests
import ssl
from requests.adapters import HTTPAdapter
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
#bot.py

# ============================================================
# JOURNEY CONFIGURATION
# ============================================================

# Train number and name we want to monitor
TRAIN_NO = "07097 - HYB MAQ SPL"
TRAIN_NAME = "HYB MAQ SPL"
SOURCE = "ERODE JN. - ED"
DESTINATION = "KANHANGAD - KZE"

CLASS_CODE = "3A"
QUOTA = "GN"

# Railway station codes


# Date format used when sending the request to Indian Railways
JOURNEY_DATE = "18-11-2026"

# Date format used inside the Railway JSON response
TARGET_DATE = "2026-11-18"

# Class and quota


# Send an alert when availability falls by 10 or more
# from the last notification baseline
DROP_THRESHOLD = 10


# ============================================================
# LOCAL FILES
# ============================================================

# Stores the previous availability/baseline
STATE_FILE = Path("state.json")

# Temporary CAPTCHA image downloaded from Railway
CAPTCHA_FILE = Path("captcha.png")

# Saves the last Railway JSON response for debugging
RESPONSE_FILE = Path("last_response.json")


# ============================================================
# INDIAN RAILWAYS URLs
# ============================================================

BASE_URL = "https://www.indianrail.gov.in/enquiry"

# Main seat availability page
SEAT_PAGE_URL = (
    f"{BASE_URL}/SEAT/SeatAvailability.html?locale=en"
)

# Railway endpoint that provides CAPTCHA configuration
CAPTCHA_CONFIG_URL = f"{BASE_URL}/CaptchaConfig"

# Railway CAPTCHA image endpoint
CAPTCHA_IMAGE_URL = f"{BASE_URL}/captchaDraw.png"

# Endpoint used by the Railway page to submit the
# manually entered CAPTCHA and request availability
COMMON_CAPTCHA_URL = f"{BASE_URL}/CommonCaptcha"


# ============================================================
# HTTP SESSION
# ============================================================
class LegacyTLSAdapter(HTTPAdapter):#new testing class.
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4  # allow legacy server connect
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def is_maintenance_window():
    now = datetime.now(ZoneInfo("Asia/Kolkata")).time()

    # Skip midnight through 1:09 AM IST
    return dt_time(0, 0) <= now < dt_time(1, 10)
    
def create_session():
    """
    Create one HTTP session.

    Using the same session throughout the process allows
    cookies/session information received from Railway to be
    reused for the subsequent requests.
    """

    session = requests.Session()

    # Identify the request with a normal browser-like User-Agent
    # and provide the language expected by the Railway website.
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.mount("https://", LegacyTLSAdapter())#testing
    return session


# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_state():
    """
    Load the previous monitoring state from state.json.

    On the first run there will be no state.json, so we
    create an empty baseline.
    """

    if not STATE_FILE.exists():
        return {
            "last_available": None,
            "last_notified": None,
            "history": []
        }

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    """
    Save the current monitoring state to state.json.
    """

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ============================================================
# GET CAPTCHA
# ============================================================

def get_captcha(session):
    """
    Load the Railway page and download its CAPTCHA image.

    The CAPTCHA is intentionally NOT solved by the program.
    You will enter the CAPTCHA answer manually.
    """

    # First load the actual Railway seat availability page.
    # This also establishes the initial session/cookies.
    response = session.get(
        SEAT_PAGE_URL,
        timeout=30
    )

    response.raise_for_status()

    # Request the CAPTCHA configuration using the same session.
    session.get(
        CAPTCHA_CONFIG_URL,
        timeout=30
    )

    # Add a timestamp so the browser/server doesn't accidentally
    # give us an old cached CAPTCHA image.
    params = {
        "_": int(time.time() * 1000)
    }

    # Download the CAPTCHA image.
    response = session.get(
        CAPTCHA_IMAGE_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    # Save the CAPTCHA image locally so you can open it.
    CAPTCHA_FILE.write_bytes(response.content)


# ==================================s==========================
# REQUEST AVAILABILITY
# ============================================================

def request_availability(session, captcha):
    """
    Send the manually entered CAPTCHA and journey details
    to the Indian Railways CommonCaptcha endpoint.
    """

    # Parameters used by the official Railway JavaScript.
    params = {
        "inputCaptcha": captcha,
        "trainNo": TRAIN_NO,
        "dt": JOURNEY_DATE,
        "sourceStation": SOURCE,
        "destinationStation": DESTINATION,
        "classc": CLASS_CODE,
        "quota": QUOTA,
        "inputPage": "SEAT",
        "language": "en"
    }

    # The Railway webpage makes this as an AJAX request.
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SEAT_PAGE_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }

    response = session.get(
        COMMON_CAPTCHA_URL,
        params=params,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    # Convert Railway's JSON response to a Python dictionary.
    data = response.json()

    # Keep the raw response for debugging.
    with open(
        RESPONSE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)

    # If Railway rejected the request, show its actual message.
    if data.get("errorMessage"):
        raise RuntimeError(
            data["errorMessage"]
        )

    return data

# ============================================================
# EXTRACT AVAILABLE SEATS
# ============================================================

def get_available(response):
    """
    Find the requested journey date in avlDayList and extract
    the number from a status such as:

        AVAILABLE-0187

    Result:

        187
    """

    # Railway can return an error message instead of availability.
    if response.get("errorMessage"):
        raise RuntimeError(
            response["errorMessage"]
        )

    # Get the list of availability entries.
    days = response.get(
        "avlDayList",
        []
    )

    # Look for our specific journey date.
    for item in days:

        if item.get("availablityDate") != TARGET_DATE:
            continue

        # Example:
        # "AVAILABLE-0187"
        status = item.get(
            "availablityStatus",
            ""
        )

        # Extract only the number after AVAILABLE-
        match = re.search(
            r"AVAILABLE-(\d+)",
            status
        )

        if match:
            return int(match.group(1))

        # The date exists, but its status isn't
        # a normal AVAILABLE-xxxx value.
        return None

    # The requested date wasn't found in Railway's response.
    raise RuntimeError(
        "Target date not found in response."
    )


# ============================================================
# TELEGRAM NOTIFICATION
# ============================================================

def send_telegram(message):
    """
    Send an alert through Telegram.

    The bot token and chat ID are read from environment variables,
    so they don't have to be written into this Python file.
    """

    # Read Telegram credentials from environment variables.
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    # If Telegram isn't configured, simply don't send anything.
    if not token or not chat_id:
        return

    # Telegram Bot API endpoint.
    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    # Send the notification.
    response = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": message
        },
        timeout=30
    )

    # Raise an exception if Telegram rejected the request.
    response.raise_for_status()


# ============================================================
# MAIN BOT
# ============================================================

def main():
    if is_maintenance_window():#checking maintianance/facnum error
        print("Scheduled website downtime. Skipping this run.")
        return


    # Load the previous seat availability state.
    state = load_state()

    # Create one persistent Railway HTTP session.
    session = create_session()

    # --------------------------------------------------------
    # STEP 1
    # Download the CAPTCHA
    # --------------------------------------------------------

    get_captcha(session)

    # --------------------------------------------------------
    # STEP 2
    # YOU manually enter the CAPTCHA
    # --------------------------------------------------------

    captcha = solve_image("captcha.png")

    if not captcha:
        raise ValueError(
            "CAPTCHA cannot be empty."
        )

    # --------------------------------------------------------
    # STEP 3
    # Ask Indian Railways for availability
    # --------------------------------------------------------

    response = request_availability(
        session,
        captcha
    )

    # --------------------------------------------------------
    # STEP 4
    # Extract the number of available seats
    # --------------------------------------------------------

    current = get_available(response)

    # If Railway didn't return a numeric availability,
    # don't modify our monitoring baseline.
    if current is None:
        print(
            "Availability is not currently AVAILABLE."
        )
        return

    # --------------------------------------------------------
    # STEP 5
    # Compare with previous notification baseline
    # --------------------------------------------------------

    previous = state.get(
        "last_notified"
    )

    # Alert only when availability has decreased by
    # DROP_THRESHOLD or more.
    alert = (
        previous is not None
        and previous - current >= DROP_THRESHOLD
    )

    # --------------------------------------------------------
    # STEP 6
    # Send Telegram alert if threshold is reached
    # --------------------------------------------------------

    if alert:

        # Calculate how many seats disappeared.
        drop = previous - current

        message = (
            "🚆 Indian Railways Seat Alert\n\n"
            f"Train: {TRAIN_NO} - {TRAIN_NAME}\n"
            f"Route: {SOURCE} → {DESTINATION}\n"
            f"Date: 18 Nov 2026\n"
            f"Class: {CLASS_CODE}\n"
            f"Quota: {QUOTA}\n\n"
            f"Available: {current}\n"
            f"Drop: {drop}"
        )

        send_telegram(message)

        # IMPORTANT:
        # After sending an alert, the current value becomes
        # the new notification baseline.
        state["last_notified"] = current

    # --------------------------------------------------------
    # STEP 7
    # First successful run
    # --------------------------------------------------------

    elif previous is None:

        # On the first run, establish the initial baseline.
        # No alert is sent.
        state["last_notified"] = current

    # --------------------------------------------------------
    # STEP 8
    # Always remember the latest availability
    # --------------------------------------------------------

    state["last_available"] = current

    # Add this check to the history.
    state.setdefault(
        "history",
        []
    )

    state["history"].append({
        "timestamp": datetime.now().isoformat(
            timespec="seconds"
        ),
        "available": current
    })

    # Keep only the most recent 100 checks.
    state["history"] = state["history"][-100:]

    # Save everything for the next run.
    save_state(state)

    # One useful output only.
    print(
        f"Available: {current}"
    )


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":
    main()
