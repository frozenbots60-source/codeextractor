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
from telethon import TelegramClient, events
from telethon.sessions import StringSession
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
STRING_SESSION = "1AZWarzgBu3fzgheMCV2Dk31CXXHgZyCqvVlJWWlarjt5qjy3L8njeVHbMs5EcywTwkQj-GUxpRMc3Dhr-O7vLA-CRLoPg5paI9IZjUFhYDcR6JbkfcOfcnAdcwvWrhivsGDZtLefWgNAuaIOuA08UlftkXPpI03-0HlHmCEn_M3zSFgofrYnzjeOVHcALU_lIu7aNSq8cRJ5nN-Op4pduYkz1nerT1zPHg2tmV4LfN6rZ-U37Y8jSHkwBKeSpy1JbV5g-0nLS-V9wUxGWu9hjKzm41k3k6JyD8AsyBzY8viqcI7c277bJPmsNfxYjwuRaTir_hl7S1Br7_Y1Rw56Bz3lc4EZKJQ="

API_ID = 1234567
API_HASH = "0123456789abcdef0123456789abcdef"

CHANNELS = [
    -1002772030545,
    -1001977383442,
    -1003238942328
]

TARGET_SECOND = 4
API_URL = "https://serene-coast-95979-9dabd2155d8d.herokuapp.com/send"

BOT_TOKEN = "8537156061:AAHIqcg2eaRXBya1ImmuCerK-EMd3V_1hnI"
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_DL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

FORWARD_TO = "kustcodebot"

LOG_DM_ID = 7618467489   # <<< YOUR PRIVATE DM FOR LOGGING
# =======================================================

ocr_model = RapidOCR()

ZERO_WIDTH_RE = re.compile(
    "[" +
    "\u200B" +
    "\u200C" +
    "\u200D" +
    "\uFEFF" +
    "\uFE0F" +
    "]"
)

HOMOGLYPHS = {
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
    "а": "a", "в": "b", "с": "c", "е": "e", "н": "h", "к": "k", "м": "m", "о": "o", "р": "p", "т": "t",
    "Ο": "O", "ο": "o", "Ι": "I", "ι": "i", "Σ": "S", "σ": "s", "ϲ": "c",
    "ѕ": "s", "ј": "j", "і": "i", "ϵ": "e", "ԁ": "d"
}

def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = ZERO_WIDTH_RE.sub("", s)
    if any(ch in s for ch in HOMOGLYPHS):
        s = "".join(HOMOGLYPHS.get(ch, ch) for ch in s)
    return s.lower()

def extract_codes_from_text(text: str):
    if not text:
        return []
    codes = set()

    hyphen_matches = re.findall(r"[-–—]\s*([a-z0-9]{6,64})", text)
    for m in hyphen_matches:
        if re.search(r"[a-z]", m) and re.search(r"\d", m):
            codes.add(m)

    word_matches = re.findall(r"\b(?=[a-z]*\d)(?=\d*[a-z])[a-z0-9]{6,64}\b", text)
    for m in word_matches:
        codes.add(m)

    mixed_matches = re.findall(r"\b(?=[a-z0-9_-]*\d)(?=[a-z0-9_-]*[a-z])[a-z0-9_-]{6,64}\b", text)
    for m in mixed_matches:
        clean = m.replace("_", "").replace("-", "")
        if len(clean) >= 6 and re.search(r"[a-z]", clean) and re.search(r"\d", clean):
            codes.add(clean)

    return [c for c in codes if not c.startswith("codes") and not c.startswith("code")]

# =======================================================
# MAIN BOT
# =======================================================
async def main():
    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

    @client.on(events.NewMessage(chats=CHANNELS))
    async def handler(event):
        start = time.time()
        log("📩 New message", start)

        message = event.message

        try:
            await client.forward_messages(FORWARD_TO, message)
        except Exception as e:
            print(f"Forward failed: {e}")

        raw_text = message.message or ""

        try:
            caption = getattr(message, "caption", None)
            if caption:
                raw_text = (raw_text + "\n" + caption) if raw_text else caption
        except Exception:
            pass

        try:
            if message.reply_to_msg_id:
                reply = await event.get_reply_message()
                if reply:
                    reply_text = reply.message or getattr(reply, "caption", "") or ""
                    if reply_text:
                        raw_text += "\n" + reply_text
        except Exception:
            pass

        normalized = normalize_text(raw_text)
        codes = extract_codes_from_text(normalized)

        if not codes:
            log("No codes found", start)
            return

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

                log(f"Sent code '{code}' → status={r.status}", start)

                # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
                # LOG TO YOUR DM IMMEDIATELY AFTER BROADCAST
                await client.send_message(
                    LOG_DM_ID,
                    f"✅ CODE SENT\n\nCode: `{code}`\nChannel: `{event.chat_id}`\nMsg ID: `{message.id}`"
                )
                # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

            except Exception as e:
                print(f"Failed to POST code {code}: {e}")

        log("DONE", start)

    await client.start()
    print(">> Telethon Worker Started <<")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
