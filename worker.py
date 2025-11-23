import os
import time
import json
import asyncio
import tempfile
import threading
import tempfile
import unicodedata
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import cv2
import urllib3
from pyrogram import Client, filters, idle
from rapidocr_onnxruntime import RapidOCR

# =======================================================
# CONFIG (keep these as-is)
# =======================================================
STRING_SESSION = "AQE1hZwAsACLds_UWzxBuXJrUqtxBHKWVN82FiIvZiNjcy-EtswSj3isV5Mhhjnerq5FITxUcynX0CP9IENrbxGU_kF8aHzNMELGIiser2uzf9zu9xPlHShb-eS0AqhYUogG2pnR5Pypurj6RgZA15q-MEigjhwoQBVLgQYhbWlb8fZQ7t_rNZalupbT9dZQoDYsEhI7Bu-ReTsNNrB8UvaCBzJVSQ4bm8BoMJUPKUzXCY1glpLEDKW72DKgTGEgOzqhZBSuEG0O17EjCFysRnngmqaf2L4Epya6eLjrDj2KqzkUkDuEmn6AMczvLkG7JolrsFzqpuOn3X7d6ZwMJr3ErZapGwAAAAHpJUc8AA"  # <<< PUT YOUR STRING SESSION HERE


# Channels to listen to (video/text/test)
CHANNEL_VIDEO_AND_BONUS = -1001977383442   # video + "Bonus Drop Alert" style text
CHANNEL_DROP_CODES = -1002772030545        # "Drop Codes" channel with "$X - code" style
CHANNEL_TEST = -1003238942328              # testing channel (you provided)

CHANNELS = [
    CHANNEL_VIDEO_AND_BONUS,
    CHANNEL_DROP_CODES,
    CHANNEL_TEST
]

TARGET_SECOND = 4

API_URL = "https://stake-codes-b8bf1e990ec3.herokuapp.com/send"

BOT_TOKEN = "8537156061:AAHIqcg2eaRXBya1ImmuCerK-EMd3V_1hnI"
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_DL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

FORWARD_TO = "kustcodebot"   # bot username to forward media to
# =======================================================

# HTTP pool
http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=3, read=15),
)

ocr_model = RapidOCR()

# dedupe store
DEDUPE_FILE = os.path.join(tempfile.gettempdir(), "sent_codes.json")
dedupe_lock = threading.Lock()
try:
    with open(DEDUPE_FILE, "r", encoding="utf-8") as f:
        SENT_CODES = set(json.load(f))
except Exception:
    SENT_CODES = set()


def persist_dedupe():
    try:
        with dedupe_lock:
            with open(DEDUPE_FILE, "w", encoding="utf-8") as f:
                json.dump(list(SENT_CODES), f)
    except Exception:
        pass


def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")


# -------------------------
# Video processing helpers
# -------------------------
def extract_frame(video_path, start):
    # fast: output MJPEG, scale down
    log("Extracting frame via ffmpeg...", start)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-ss", str(TARGET_SECOND),
        "-i", video_path,
        "-vf", "scale=iw/2:ih/2",
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    jpg_data, _ = proc.communicate(timeout=5)
    log(f"Frame extracted ({len(jpg_data)} bytes)", start)
    return jpg_data


def ocr_on_jpg_crop(jpg_bytes, start):
    log("Decoding JPEG...", start)
    img = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        log("JPEG decode failed!", start)
        return ""
    # crop bottom 35% where code usually sits
    h = img.shape[0]
    crop = img[int(h * 0.65):h, :]
    log("Running OCR on cropped region...", start)
    blocks, _ = ocr_model(crop)

    best_code = ""
    best_conf = 0.0
    for region in blocks:
        coords, text, conf = region
        cleaned = text.strip()
        if re.fullmatch(r"[A-Za-z0-9]{6,25}", cleaned):
            # prefer lowercase alnum codes
            if conf > best_conf:
                best_conf = conf
                best_code = cleaned.lower()

    if best_code == "":
        # fallback choose highest confidence text and normalize
        for region in blocks:
            coords, text, conf = region
            if conf > best_conf:
                best_conf = conf
                best_code = text.strip().lower()

    return best_code


# -------------------------
# Bot-file download helpers
# -------------------------
from concurrent.futures import ThreadPoolExecutor


def get_file_info(file_id, start):
    """
    Returns (file_path, file_size) or (None, None)
    """
    try:
        r = http.request("GET", f"{BOT_API}/getFile", fields={"file_id": file_id})
        data = json.loads(r.data.decode("utf-8"))
        if not data.get("ok"):
            log(f"getFile failed: {data}", start)
            return None, None
        file_path = data["result"]["file_path"]
        file_size = data["result"].get("file_size", None)
        return file_path, file_size
    except Exception as e:
        log(f"getFile exception: {e}", start)
        return None, None


def download_tail(file_path, file_size, start):
    """
    Try to download only the tail bytes (last ~5s). If server respects Range (206),
    save that partial response. If server returns full file or ignores range, fallback
    to parallel download of full file (split into chunks).
    Returns local temp file path (full or partial) or None.
    """
    dl_url = f"{BOT_DL}/{file_path}"

    approx_bytes_per_second = 150000
    tail_bytes = approx_bytes_per_second * 5

    # if file_size missing, default to downloading partial trailing chunk (request 700KB)
    if file_size is None:
        file_size = tail_bytes

    start_byte = max(file_size - tail_bytes, 0)

    headers = {
        "Range": f"bytes={start_byte}-",
        "Connection": "keep-alive",
        "TE": "identity",
        "Accept-Encoding": "identity"
    }

    log(f"Requesting RANGE bytes={start_byte}-{file_size}", start)

    try:
        r = http.request("GET", dl_url, headers=headers, preload_content=False)
    except Exception as e:
        log(f"Range request failed: {e}", start)
        r = None

    # If we got a valid partial response (206) -> use it
    if r and r.status == 206:
        temp_fp = os.path.join(tempfile.gettempdir(), f"tail_{int(time.time())}.mp4")
        with open(temp_fp, "wb") as f:
            for chunk in r.stream(65536):
                f.write(chunk)
        r.release_conn()
        log("Partial download OK (206)", start)
        return temp_fp

    # If partial not available or server ignored range -> fallback to parallel full-file download
    if r:
        try:
            log(f"CDN IGNORED RANGE → status={r.status} → forcing parallel fallback...", start)
            r.release_conn()
        except:
            pass
    else:
        log("No response for Range, forcing parallel fallback...", start)

    # If file_size is small and we requested tail from 0, still parallelize to speed up
    # Compute chunks
    try:
        CHUNKS = 4
        CHUNK_SIZE = max(1, file_size // CHUNKS)

        def fetch_part(i):
            part_start = i * CHUNK_SIZE
            part_end = part_start + CHUNK_SIZE - 1
            if i == CHUNKS - 1:
                part_end = file_size - 1 if file_size > 0 else part_end

            part_headers = {
                "Range": f"bytes={part_start}-{part_end}",
                "Connection": "keep-alive",
                "Accept-Encoding": "identity"
            }
            try:
                rr = http.request("GET", dl_url, headers=part_headers, preload_content=True)
                if rr.status not in (200, 206):
                    log(f"Chunk {i} returned status {rr.status}", start)
                data = rr.data
                return (i, data)
            except Exception as e:
                log(f"Chunk {i} exception: {e}", start)
                return (i, b"")

        with ThreadPoolExecutor(max_workers=CHUNKS) as ex:
            parts = list(ex.map(fetch_part, range(CHUNKS)))

        parts.sort(key=lambda x: x[0])

        temp_fp = os.path.join(tempfile.gettempdir(), f"tail_{int(time.time())}.mp4")
        with open(temp_fp, "wb") as f:
            for idx, data in parts:
                if data:
                    f.write(data)
        log("Parallel download complete", start)
        return temp_fp
    except Exception as e:
        log(f"Parallel fallback failed: {e}", start)
        return None


# -------------------------
# Text normalization & extractors
# -------------------------
def clean_text(s: str) -> str:
    # Normalize and remove zero-width / control unicode chars
    s = unicodedata.normalize("NFKC", s)
    # Remove common zero-width and bidi control chars
    s = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064]", "", s)
    # Remove weird invisible markers
    s = re.sub(r"[\uFEFF]", "", s)
    # Lowercase
    s = s.lower()
    return s


def extract_codes_by_channel(chat_id: int, text: str):
    """
    Returns list of extracted candidate codes (lowercase alnum).
    Channel-specific filtering:
      - CHANNEL_VIDEO_AND_BONUS: look for "- code: <code>" or "code: <code>"
      - CHANNEL_DROP_CODES: look for "code: $X - <code>" or "code: <code>"
      - CHANNEL_TEST: accept ANY [a-z0-9]{6,25}
    """
    codes = []

    # generic candidates - lowercase alnum strings 6-25 chars
    generic = re.findall(r"[a-z0-9]{6,25}", text)

    if chat_id == CHANNEL_VIDEO_AND_BONUS:
        # prefer lines that start with "- code:" or contain "code:" near them
        m = re.findall(r"-\s*code:\s*([a-z0-9]{6,25})", text)
        if m:
            codes.extend(m)
        else:
            m2 = re.findall(r"code:\s*([a-z0-9]{6,25})", text)
            if m2:
                codes.extend(m2)
            else:
                # fallback: only accept generic if message contains word "code" or "drop"
                if re.search(r"\b(code|drop|bonus)\b", text):
                    codes.extend(generic)

    elif chat_id == CHANNEL_DROP_CODES:
        # these messages often contain "$X - CODE" format
        m = re.findall(r"code:\s*\$\d+(?:\.\d+)?\s*-\s*([a-z0-9]{6,25})", text)
        if m:
            codes.extend(m)
        else:
            # fallback to 'code: <code>' lines
            m2 = re.findall(r"code:\s*([a-z0-9]{6,25})", text)
            if m2:
                codes.extend(m2)
            else:
                if re.search(r"\b(code|drop|daily|stream|kick|secret)\b", text):
                    codes.extend(generic)

    elif chat_id == CHANNEL_TEST:
        # testing channel accepts anything
        codes.extend(generic)

    else:
        # unknown channel - fallback conservative
        if re.search(r"\b(code|drop|bonus)\b", text):
            codes.extend(generic)

    # dedupe order preserving
    seen = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def try_send_code(code: str, tg_message_id: int, start: float):
    """
    Check global dedupe and POST to API if new.
    """
    if not code:
        return False
    normalized = code.lower()
    with dedupe_lock:
        if normalized in SENT_CODES:
            log(f"Code already sent (dedupe) -> {normalized}", start)
            return False
        # mark as sent immediately to avoid race
        SENT_CODES.add(normalized)
        persist_dedupe()

    payload = {
        "type": "stake_bonus_code",
        "code": normalized,
        "tg_message_id": tg_message_id
    }
    try:
        http.request("POST", API_URL, body=json.dumps(payload), headers={"Content-Type": "application/json"})
        log(f"Sent CODE to API -> {normalized}", start)
        return True
    except Exception as e:
        log(f"Failed to POST code: {e}", start)
        return False


# -------------------------
# Main bot app
# -------------------------
async def start_bot():
    app = Client("stake-worker", session_string=STRING_SESSION)

    # VIDEO handler: receives video or document, forwards to bot, downloads via bot, OCR, send code
    @app.on_message(filters.chat(CHANNELS) & (filters.video | filters.document))
    async def video_handler(client, message):
        start = time.time()
        log("📩 New Telegram video message received", start)

        # document safety
        if message.document:
            if not message.document.mime_type.startswith("video"):
                log("Ignored non-video document", start)
                return

        # Forward to bot (fast path)
        log("Forwarding to @kustcodebot ...", start)
        fwd = await message.forward(FORWARD_TO)

        # Extract bot-side file_id
        if fwd.video:
            bot_file_id = fwd.video.file_id
        else:
            bot_file_id = fwd.document.file_id

        log(f"BOT FILE ID = {bot_file_id}", start)

        # Get file path + size
        file_path, file_size = get_file_info(bot_file_id, start)
        if not file_path:
            log("getFile failed", start)
            return

        # Download (tail or parallel fallback)
        file_local = download_tail(file_path, file_size, start)
        if not file_local:
            log("Download failed", start)
            return

        # Extract frame and OCR
        jpg = extract_frame(file_local, start)
        code = ocr_on_jpg_crop(jpg, start)

        log(f"FINAL EXTRACTED CODE = '{code}'", start)

        # Try to send code (global dedupe enforced inside)
        try_send_code(code, message.id, start)

        # cleanup
        try:
            os.remove(file_local)
            log("Cleaned temp file", start)
        except:
            pass

        log("DONE (video)", start)

    # TEXT handler: for the channels, normalize and apply channel-specific regex
    @app.on_message(filters.chat(CHANNELS) & filters.text)
    async def text_handler(client, message):
        start = time.time()
        log("📩 New TEXT message", start)

        raw = message.text or message.caption or ""
        cleaned = clean_text(raw)
        log(f"Cleaned text: {cleaned}", start)

        codes = extract_codes_by_channel(message.chat.id, cleaned)
        if not codes:
            log("No valid code found in text", start)
            return

        # Behavior: send first unseen code only (global dedupe prevents repeats)
        for candidate in codes:
            sent = try_send_code(candidate, message.id, start)
            if sent:
                # send only the first code per message to avoid spam
                break

        log("DONE (text)", start)

    await app.start()
    print(">> Worker Started <<")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(start_bot())
