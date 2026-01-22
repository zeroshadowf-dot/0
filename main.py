#!/usr/bin/env python3
"""
keepalive_daemon.py
- يحاكي الضغط على زر Sandbox عبر إضافة الكوكي (بدون متصفح)
- يزور alert.php ثم keepalive.php
- retries ذكية مع exponential backoff
- يسجل في ملف log ويطبع للمُخرَج
- يرسل إشعارات عبر Telegram (اختياري)
- يدعم تحميل إعدادات من .env أو متغيرات بيئة
- افتراضي: يعمل كل 5 دقائق (300 ثانية)
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

# Try to load .env if present (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---------------------------
# Config عبر متغيرات بيئة (أمنية)
BOT_TOKEN = os.getenv("8388065369:AAE3EZqsE75nh-Kdv0Zx88F_UzcAAG8_YtQ")        # ضع التوكن في متغير بيئة أو في .env
CHAT_ID   = os.getenv("7700185632")          # ضع chat id في متغير بيئة أو في .env

ALERT_URL      = os.getenv("ALERT_URL", "https://dev-vnk.pantheonsite.io/alert.php")
KEEPALIVE_URL  = os.getenv("KEEPALIVE_URL", "https://dev-vnk.pantheonsite.io/keepalive.php")
INTERVAL_SECS  = int(os.getenv("INTERVAL_SECS", "300"))   # الآن 300 ثانية = 5 دقائق

LOG_FILE = os.getenv("LOG_FILE", "keepalive.log")

# Retry config
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "5"))
BASE_BACKOFF = float(os.getenv("BASE_BACKOFF", "2.0"))  # بالثواني (exponential)

# HTTP
HEADERS = {
    "User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114 Safari/537.36")
}
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "12"))


# ---------------------------
# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("keepalive")

# ---------------------------
# Helper: send telegram (safe)
def send_telegram(msg: str, silent_fail: bool = True) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        logger.debug("BOT_TOKEN or CHAT_ID not set — skipping telegram")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.get(url, params={"chat_id": CHAT_ID, "text": msg}, timeout=8)
        if r.status_code == 200:
            logger.debug("Telegram sent")
            return True
        else:
            logger.warning(f"Telegram returned {r.status_code}: {r.text}")
            return False
    except Exception as e:
        logger.exception("Exception sending telegram")
        return False if silent_fail else None

# ---------------------------
# Core: simulate click by setting cookie and requesting pages
def simulate_click_and_keepalive(session: requests.Session) -> bool:
    """
    1) يضيف cookie Deterrence-Bypass=1 للـ domain
    2) يزور alert.php
    3) يزور keepalive.php
    يرجع True لو كل شيء تمام
    """
    try:
        # set cookie like JS cont()
        session.cookies.set(
            name="Deterrence-Bypass",
            value="1",
            domain="dev-vnk.pantheonsite.io",
            path="/"
        )
        logger.debug("Cookie Deterrence-Bypass set in session")

        r1 = session.get(ALERT_URL, timeout=TIMEOUT)
        logger.info(f"GET {ALERT_URL} -> {r1.status_code}")

        if r1.status_code != 200:
            logger.warning(f"alert.php returned {r1.status_code}")
            return False

        # small pause to mimic realistic behaviour
        time.sleep(0.5)

        r2 = session.get(KEEPALIVE_URL, timeout=TIMEOUT)
        logger.info(f"GET {KEEPALIVE_URL} -> {r2.status_code}")

        if r2.status_code == 200:
            return True
        else:
            logger.warning(f"keepalive returned {r2.status_code}")
            return False

    except Exception as e:
        logger.exception("Exception during simulate_click_and_keepalive")
        return False

# ---------------------------
# Robust wrapper with retries + exponential backoff
def robust_attempt(session: requests.Session) -> bool:
    attempt = 0
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        ok = simulate_click_and_keepalive(session)
        if ok:
            logger.info(f"Success on attempt {attempt}")
            if attempt > 1:
                send_telegram(f"✅ الموقع عاد للعمل بعد {attempt} محاولات.")
            return True
        else:
            backoff = BASE_BACKOFF ** attempt
            logger.warning(f"Attempt {attempt}/{MAX_ATTEMPTS} failed — sleeping {backoff:.1f}s then retry")
            time.sleep(backoff)
    # reached max attempts
    logger.error("All attempts failed")
    send_telegram(f"❌ فشل الحفاظ على الموقع بعد {MAX_ATTEMPTS} محاولة. المرجو التحقق.")
    return False

# ---------------------------
# Main loop (daemon-style)
def main_loop():
    logger.info("Starting keepalive daemon")
    session = requests.Session()
    session.headers.update(HEADERS)

    # keep running indefinitely
    while True:
        start = datetime.now(timezone.utc)
        logger.info("Running cycle")
        try:
            success = robust_attempt(session)
            ts = datetime.now(timezone.utc).isoformat()
            if success:
                logger.info(f"Cycle success @ {ts}")
            else:
                logger.warning(f"Cycle failed @ {ts}")
        except Exception as e:
            logger.exception("Unhandled exception in main loop")
            send_telegram(f"❌ Unhandled exception in keepalive daemon: {e}")
        # compute elapsed and sleep remaining to respect INTERVAL_SECS
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        sleep_for = max(1, INTERVAL_SECS - elapsed)
        logger.info(f"Sleeping {sleep_for:.1f}s until next cycle")
        time.sleep(sleep_for)

# ---------------------------
if __name__ == "__main__":
    # quick self-check: env vars
    logger.info(f"CONFIG: INTERVAL_SECS={INTERVAL_SECS}, MAX_ATTEMPTS={MAX_ATTEMPTS}, BASE_BACKOFF={BASE_BACKOFF}")
    main_loop()
