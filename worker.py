import os
import time
import json
import asyncio
import tempfile
import numpy as np
import cv2
import websockets
import subprocess
from pyrogram import Client, filters, idle
from rapidocr_onnxruntime import RapidOCR
import re


# =======================================================
# CONFIG
# =======================================================

STRING_SESSION = "AQE1hZwAsACLds_UWzxBuXJrUqtxBHKWVN82FiIvZiNjcy-EtswSj3isV5Mhhjnerq5FITxUcynX0CP9IENrbxGU_kF8aHzNMELGIiser2uzf9zu9xPlHShb-eS0AqhYUogG2pnR5Pypurj6RgZA15q-MEigjhwoQBVLgQYhbWlb8fZQ7t_rNZalupbT9dZQoDYsEhI7Bu-ReTsNNrB8UvaCBzJVSQ4bm8BoMJUPKUzXCY1glpLEDKW72DKgTGEgOzqhZBSuEG0O17EjCFysRnngmqaf2L4Epya6eLjrDj2KqzkUkDuEmn6AMczvLkG7JolrsFzqpuOn3X7d6ZwMJr3ErZapGwAAAAHpJUc8AA"  # <<< PUT YOUR STRING SESSION HERE

CHANNELS = [
    -1003238942328,   # <<< CHANNEL 1
    -1001977383442    # <<< CHANNEL 2
]

WEBSOCKET_URL = "wss://your-broadcast-server.com/ws"  # <<< PUT YOUR WS URL
TARGET_SECOND = 4
# =======================================================

ocr_model = RapidOCR()
ws_conn = None


def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")


async def ws_connect():
    global ws_conn
    if ws_conn is None or ws_conn.closed:
        try:
            ws_conn = await websockets.connect(WEBSOCKET_URL, max_size=2**20)
        except:
            ws_conn = None
    return ws_conn


def extract_frame(video_path, start):
    log("Extracting frame via ffmpeg...", start)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-ss", str(TARGET_SECOND),
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "pipe:1"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    png_data, _ = proc.communicate(timeout=5)

    log(f"Frame extracted ({len(png_data)} bytes)", start)
    return png_data


def ocr_full_frame(png_bytes, start):
    log("Decoding PNG...", start)
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)

    if img is None:
        log("PNG decode failed!", start)
        return ""

    log("Resizing frame for faster OCR...", start)

    # NEW: resize to 50% for MUCH faster OCR with NO cropping
    h, w = img.shape[:2]
    img = cv2.resize(img, (w // 2, h // 2))

    log("Running OCR...", start)

    blocks, _ = ocr_model(img)
    log(f"OCR RAW RESULTS: {blocks}", start)

    best_code = ""
    best_conf = 0.0

    for region in blocks:
        coords, text, conf = region
        cleaned = text.strip()

        # stake code filter
        if re.fullmatch(r"[A-Za-z0-9]{6,20}", cleaned):
            if conf > best_conf:
                best_code = cleaned
                best_conf = conf

    if best_code == "":
        for region in blocks:
            coords, text, conf = region
            if conf > best_conf:
                best_code = text.strip()
                best_conf = conf

    return best_code



async def start_bot():
    app = Client("stake-worker", session_string=STRING_SESSION)

    @app.on_message(filters.chat(CHANNELS) & (filters.video | filters.document))
    async def video_handler(client, message):
        start = time.time()
        log("📩 New Telegram video message received", start)

        # document safety
        if message.document:
            if not message.document.mime_type.startswith("video"):
                log("Ignored non-video document", start)
                return

        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{message.id}.mp4")

        log("Downloading Telegram video...", start)
        await message.download(file_path)
        log("Download complete", start)

        png_bytes = extract_frame(file_path, start)

        code = ocr_full_frame(png_bytes, start)

        log(f"FINAL EXTRACTED CODE = '{code}'", start)

        ws = await ws_connect()
        if ws:
            payload = {
                "type": "stake_bonus_code",
                "code": code,
                "tg_message_id": message.id
            }
            try:
                await ws.send(json.dumps(payload))
                log("Code sent to WebSocket", start)
            except:
                log("WebSocket send failed", start)

        try:
            os.remove(file_path)
            log("Cleaned temp file", start)
        except:
            pass

        log("DONE.", start)

    await app.start()
    print(">> Worker Started <<")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(start_bot())
