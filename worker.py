import os
import time
import json
import asyncio
import tempfile
import numpy as np
import cv2
import subprocess
import re
import unicodedata
from pyrogram import Client, filters, idle
from rapidocr_onnxruntime import RapidOCR
import urllib3
from concurrent.futures import ThreadPoolExecutor

http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=2, read=8),
)

# =======================================================
# CONFIG
# =======================================================
STRING_SESSION = "AQE1hZwAsACLds_UWzxBuXJrUqtxBHKWVN82FiIvZiNjcy-EtswSj3isV5Mhhjnerq5FITxUcynX0CP9IENrbxGU_kF8aHzNMELGIiser2uzf9zu9xPlHShb-eS0AqhYUogG2pnR5Pypurj6RgZA15q-MEigjhwoQBVLgQYhbWlb8fZQ7t_rNZalupbT9dZQoDYsEhI7Bu-ReTsNNrB8UvaCBzJVSQ4bm8BoMJUPKUzXCY1glpLEDKW72DKgTGEgOzqhZBSuEG0O17EjCFysRnngmqaf2L4Epya6eLjrDj2KqzkUkDuEmn6AMczvLkG7JolrsFzqpuOn3X7d6ZwMJr3ErZapGwAAAAHpJUc8AA"  # <<< PUT YOUR STRING SESSION HERE

CHANNELS = [
    -1003238942328,   # <<< CHANNEL 1
    -1001977383442    # <<< CHANNEL 2
]

TARGET_SECOND = 4
API_URL = "https://serene-coast-95979-9dabd2155d8d.herokuapp.com/send"

BOT_TOKEN = "8537156061:AAHIqcg2eaRXBya1ImmuCerK-EMd3V_1hnI"
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_DL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

FORWARD_TO = "kustcodebot"
# =======================================================

ocr_model = RapidOCR()  # kept in case you want OCR later

ZERO_WIDTH_RE = re.compile(
    "[" +
    "\u200B" +  # zero width space
    "\u200C" +  # zero width non-joiner
    "\u200D" +  # zero width joiner
    "\uFEFF" +  # zero width no-break space
    "\uFE0F" +  # variation selector-16 (emoji-ish)
    "]"
)

# Basic homoglyph map for common Cyrillic/Greek -> Latin substitutions seen in spammed messages
HOMOGLYPHS = {
    # Cyrillic upper/lower -> Latin
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
    "а": "a", "в": "b", "с": "c", "е": "e", "н": "h", "к": "k", "м": "m", "о": "o", "р": "p", "т": "t",
    # Greek
    "Ο": "O", "ο": "o", "Ι": "I", "ι": "i", "Σ": "S", "σ": "s", "ϲ": "c",
    # Misc trick letters
    "ѕ": "s", "ј": "j", "і": "i", "ϵ": "e", "ԁ": "d"
}


def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")


def normalize_text(s: str) -> str:
    """
    Normalize incoming text to reduce obfuscation:
      - NFKC normalization
      - remove zero-width characters
      - replace common homoglyphs (Cyrillic/Greek -> Latin)
      - lowercase
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = ZERO_WIDTH_RE.sub("", s)

    # Replace homoglyphs
    if any(ch in s for ch in HOMOGLYPHS):
        s = "".join(HOMOGLYPHS.get(ch, ch) for ch in s)

    s = s.lower()
    return s


def extract_codes_from_text(text: str):
    """
    Extract likely coupon/bonus codes from normalized text.
    Strategy:
      1. Look for patterns after a hyphen: "- CODEHERE"
      2. Find alnum words 6-64 chars with at least one letter and one digit
      3. Deduplicate and return list
    """
    if not text:
        return []

    codes = set()

    # Pattern A: after hyphen/dash like "- stakecom6r1x8qvt"
    hyphen_matches = re.findall(r"[-–—]\s*([a-z0-9]{6,64})", text)
    for m in hyphen_matches:
        # ensure it's not a pure number
        if re.search(r"[a-z]", m) and re.search(r"\d", m):
            codes.add(m)

    # Pattern B: words that contain at least one letter and one digit and are 6-64 chars long
    word_matches = re.findall(r"\b(?=[a-z]*\d)(?=\d*[a-z])[a-z0-9]{6,64}\b", text)
    for m in word_matches:
        codes.add(m)

    # Pattern C: sometimes codes have small separators like '_' or '-' inside, capture those too
    mixed_matches = re.findall(r"\b(?=[a-z0-9_-]*\d)(?=[a-z0-9_-]*[a-z])[a-z0-9_-]{6,64}\b", text)
    for m in mixed_matches:
        clean = m.replace("_", "").replace("-", "")
        if len(clean) >= 6 and re.search(r"[a-z]", clean) and re.search(r"\d", clean):
            codes.add(clean)

    # Final filtering: remove obvious usernames that start with 'codes' or short org names if needed
    filtered = [c for c in codes if not c.startswith("codes") and not c.startswith("code")]

    return list(filtered)


# =======================================================
# MAIN BOT (text-based code extraction)
# =======================================================
async def start_bot():
    app = Client("stake-worker", session_string=STRING_SESSION)

    @app.on_message(filters.chat(CHANNELS) & (filters.text | filters.caption))
    async def handler(client, message):
        start = time.time()
        log("📩 New message (text/caption)", start)

        # Optionally forward to FORWARD_TO (keeps behavior similar to previous flow)
        try:
            await message.forward(FORWARD_TO)
        except Exception as e:
            # forwarding is non-critical; just log and continue
            print(f"Forward failed: {e}")

        # Compose text from message.text, message.caption, and entities (if any)
        raw_text = message.text or message.caption or ""
        # Also include message.reply_to_message text if present (some channels embed info there)
        if getattr(message, "reply_to_message", None) and (message.reply_to_message.text or message.reply_to_message.caption):
            raw_text += "\n" + (message.reply_to_message.text or message.reply_to_message.caption)

        normalized = normalize_text(raw_text)

        codes = extract_codes_from_text(normalized)

        if not codes:
            log("No codes found", start)
            return

        # Send each code to the API
        for code in codes:
            payload = {
                "type": "stake_bonus_code",
                "code": code,
                "tg_message_id": message.id
            }

            try:
                r = http.request(
                    "POST",
                    API_URL,
                    body=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                    timeout=urllib3.util.Timeout(connect=2.0, read=6.0)
                )
                # optional: check response and log
                try:
                    resp_text = r.data.decode("utf-8")
                except Exception:
                    resp_text = f"status={r.status}"
                log(f"Sent code '{code}' → status={r.status}", start)
            except Exception as e:
                print(f"Failed to POST code {code}: {e}")

        log("DONE", start)

    await app.start()
    print(">> Worker Started <<")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(start_bot())
