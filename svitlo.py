#!/usr/bin/env python3
"""Графік відключень ДТЕК -> Telegram.

  python svitlo.py          # бот: /svitlo з айфона + автоперевірка кожні N хв
  python svitlo.py --test   # разова перевірка без Telegram: друкує текст, зберігає result.png
"""
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "").strip()
URL = os.getenv("URL", "https://www.dtek-krem.com.ua/ua/shutdowns")
CITY = os.getenv("CITY", "")
STREET = os.getenv("STREET", "")
HOUSE = os.getenv("HOUSE", "")
LINE = os.getenv("LINE", "")  # напр. "Лінія 2"; порожньо, якщо вкладок ліній немає
INTERVAL = int(os.getenv("CHECK_INTERVAL_MIN", "30")) * 60
HEADLESS = os.getenv("HEADLESS", "1") == "1"
RESULT_SEL = os.getenv("RESULT_SELECTOR", "#discon-fact")
ADDRESS = f"{CITY}, {STREET}, {HOUSE}"

STATE = BASE / "state.json"
DEBUG_PNG = BASE / "debug.png"
API = f"https://api.telegram.org/bot{TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(BASE / "svitlo.log"), logging.StreamHandler()],
)
log = logging.getLogger("svitlo")


# ---------- Telegram ----------
KB = json.dumps({"keyboard": [[{"text": "💡 Світло"}]], "resize_keyboard": True, "is_persistent": True})  # та сама кнопка, що в worker/


def tg(method, **kw):
    r = requests.post(f"{API}/{method}", timeout=60, **kw)
    r.raise_for_status()
    return r.json()


def send_text(chat, text):
    tg("sendMessage", data={"chat_id": chat, "text": text})


def send_photo(chat, png, caption):
    tg("sendPhoto", data={"chat_id": chat, "caption": caption[:1024], "reply_markup": KB},
       files={"photo": ("svitlo.png", png)})


# ---------- Сайт ----------
def close_popups(page):
    for sel in (".modal__close", "button.modal__close", ".popup__close", "[data-dismiss='modal']"):
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass


def pick(page, sel, value):
    """Вводить значення в поле з автодоповненням і обирає варіант зі списку."""
    page.wait_for_function(
        "s => { const e = document.querySelector(s); return e && !e.disabled; }",
        arg=sel, timeout=20000)
    inp = page.locator(sel).first  # на сторінці дві форми з однаковими id
    inp.click()
    inp.fill("")
    inp.press_sequentially(value, delay=80)
    items = page.locator(f"{sel}autocomplete-list > div")
    items.first.wait_for(state="visible", timeout=15000)
    match = items.filter(has_text=value)
    (match.first if match.count() else items.first).click()
    page.wait_for_timeout(700)


def fetch():
    """Повертає (текст таблиці, png-скріншот таблиці)."""
    DEBUG_PNG.unlink(missing_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_context(**p.devices["iPhone 13"], locale="uk-UA").new_page()  # мобільна верстка: таблиця читабельніша
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            close_popups(page)
            pick(page, "#city", CITY)
            pick(page, "#street", STREET)
            pick(page, "#house_num", HOUSE)
            if LINE:  # складна схема підключення: перемикаємось на потрібну лінію
                tab = page.get_by_text(LINE, exact=True)
                tab.first.wait_for(state="visible", timeout=10000)
                tab.first.click()
                page.wait_for_timeout(700)
            res = page.locator(RESULT_SEL)
            res.wait_for(state="visible", timeout=30000)
            page.add_style_tag(content=".header-block, .contacts-us-btn { display: none !important }")  # липка шапка і кнопка чату перекривають таблицю
            page.wait_for_timeout(1500)
            return res.inner_text(), res.screenshot()
        except Exception:
            try:
                page.screenshot(path=str(DEBUG_PNG), full_page=True)
            except Exception:
                pass
            raise
        finally:
            browser.close()


# ---------- Логіка ----------
def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st))


def fingerprint(text):
    # рядок "Дата оновлення..." змінюється постійно, ігноруємо його
    lines = [l.strip() for l in text.splitlines() if l.strip() and "оновлен" not in l.lower()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def check(chat, manual=False):
    st = load_state()
    try:
        text, png = fetch()
    except Exception as e:
        log.exception("fetch failed")
        st["fails"] = st.get("fails", 0) + 1
        save_state(st)
        if manual or st["fails"] == 3:  # автоперевірка не спамить: пише на 3-й поспіль невдачі
            msg = f"❌ Не вдалося отримати графік: {type(e).__name__}: {e}"[:1000]
            if DEBUG_PNG.exists():
                send_photo(chat, DEBUG_PNG.read_bytes(), msg)
                DEBUG_PNG.unlink(missing_ok=True)
            else:
                send_text(chat, msg)
        return

    h = fingerprint(text)
    changed = h != st.get("hash")
    st.update(hash=h, fails=0)
    save_state(st)
    log.info("ok, changed=%s", changed)
    if manual or changed:
        title = "⚡ Графік змінився" if changed else "💡 Графік відключень"
        send_photo(chat, png, f"{title}\n{ADDRESS}\n{datetime.now():%d.%m %H:%M}")


def run_test():
    text, png = fetch()
    (BASE / "result.png").write_bytes(png)
    print(text)
    print("\nСкріншот: result.png")


def main():
    if not (TOKEN and CITY and STREET and HOUSE):
        sys.exit("Заповни BOT_TOKEN, CITY, STREET, HOUSE у .env")
    log.info("start, %s", ADDRESS)
    offset, last = None, 0.0
    while True:
        try:
            updates = tg("getUpdates", data={"timeout": 25, "offset": offset})["result"]
        except Exception:
            log.exception("getUpdates failed")
            time.sleep(10)
            continue

        for u in updates:
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            chat = str(m.get("chat", {}).get("id", ""))
            txt = (m.get("text") or "").strip()
            if not chat:
                continue
            try:
                if not CHAT_ID:
                    send_text(chat, f"Твій CHAT_ID: {chat}\nВпиши його в .env і перезапусти.")
                elif chat == CHAT_ID and txt.startswith(("/svitlo", "/start")):
                    send_text(chat, "Шукаю графік…")
                    check(chat, manual=True)
            except Exception:
                log.exception("handler failed")

        if CHAT_ID and time.time() - last >= INTERVAL:
            last = time.time()
            try:
                check(CHAT_ID)
            except Exception:
                log.exception("periodic check failed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    elif "--once" in sys.argv:  # для cron/Actions: одна перевірка і вихід (--manual = слати завжди)
        check(CHAT_ID, manual="--manual" in sys.argv)
    else:
        main()
