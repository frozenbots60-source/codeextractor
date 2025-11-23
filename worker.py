import os
import time
import json
import asyncio
import tempfile
import numpy as np
import cv2
import subprocess
from pyrogram import Client, filters, idle
from rapidocr_onnxruntime import RapidOCR
import re
import aiohttp
from aiohttp import web


# =======================================================
# CONFIG
# =======================================================

STRING_SESSION = "AQE1hZwAsACLds_UWzxBuXJrUqtxBHKWVN82FiIvZiNjcy-EtswSj3isV5Mhhjnerq5FITxUcynX0CP9IENrbxGU_kF8aHzNMELGIiser2uzf9zu9xPlHShb-eS0AqhYUogG2pnR5Pypurj6RgZA15q-MEigjhwoQBVLgQYhbWlb8fZQ7t_rNZalupbT9dZQoDYsEhI7Bu-ReTsNNrB8UvaCBzJVSQ4bm8BoMJUPKUzXCY1glpLEDKW72DKgTGEgOzqhZBSuEG0O17EjCFysRnngmqaf2L4Epya6eLjrDj2KqzkUkDuEmn6AMczvLkG7JolrsFzqpuOn3X7d6ZwMJr3ErZapGwAAAAHpJUc8AA"

CHANNELS = [-1003238942328, -1001977383442]

# Now this should point to your SSE broadcaster's /send endpoint
# Example: "https://your-heroku-app.herokuapp.com/send"
BROADCAST_WS_URL = "http://127.0.0.1:8080/send"

TARGET_SECOND = 4

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))
# =======================================================


ocr_model = RapidOCR()
connected_ws_clients = set()


def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")


def extract_frame(video_path, start):
    log("Extracting frame via ffmpeg...", start)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
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


async def send_to_broadcast(payload, start):
    """
    Send the extracted code to the SSE broadcaster via HTTP POST.
    BROADCAST_WS_URL should be your /send endpoint.
    """
    if not BROADCAST_WS_URL:
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                BROADCAST_WS_URL,
                json=payload,
                timeout=3
            ) as resp:
                if resp.status != 200:
                    log(f"Broadcast HTTP failed with status {resp.status}", start)
    except Exception as e:
        log(f"Broadcast HTTP error: {e}", start)


# ========================
# HTTP INDEX + CORS
# ========================
async def http_index(request):
    resp = web.Response(text="Stake Worker Running", content_type="text/plain")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# ========================
# OPTIONS PRE-FLIGHT
# ========================
async def ws_options(request):
    resp = web.Response(text="OK")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "*"
    return resp


# ========================
# WEBSOCKET SERVER
# (unchanged - you can still use this locally if you want)
# ========================
async def websocket_handler(request):
    ws = web.WebSocketResponse(autoping=True, heartbeat=15)
    await ws.prepare(request)

    ws.headers["Access-Control-Allow-Origin"] = "*"

    connected_ws_clients.add(ws)
    print("[WS] Client connected")

    try:
        async for msg in ws:
            pass
    finally:
        connected_ws_clients.remove(ws)
        print("[WS] Client disconnected")

    return ws


# ========================
# START HTTP + WS SERVER
# ========================
async def start_http_ws_server():
    app = web.Application()

    app.router.add_get("/", http_index)

    # WS endpoints
    app.router.add_route("GET", "/ws", websocket_handler)
    app.router.add_route("OPTIONS", "/ws", ws_options)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)

    print(f"\n===== Local Servers Running =====")
    print(f"HTTP Server     : http://{HOST}:{PORT}/")
    print(f"WebSocket Server: ws://{HOST}:{PORT}/ws")
    print(f"Broadcast URL   : {BROADCAST_WS_URL}\n")

    await site.start()


# ========================
# TELEGRAM BOT
# ========================
async def start_bot():
    app = Client("stake-worker", session_string=STRING_SESSION)

    @app.on_message(filters.chat(CHANNELS) & (filters.video | filters.document))
    async def video_handler(client, message):
        start = time.time()
        log("📩 New Telegram video message received", start)

        if message.document:
            if not message.document.mime_type.startswith("video"):
                log("Ignored non-video document", start)
                return

        tmp = tempfile.gettempdir()
        file_path = os.path.join(tmp, f"{message.id}.mp4")

        log("Downloading Telegram video...", start)
        await message.download(file_path)
        log("Download complete", start)

        png_bytes = extract_frame(file_path, start)
        code = ocr_full_frame(png_bytes, start)

        log(f"FINAL EXTRACTED CODE = '{code}'", start)

        payload = {
            "type": "stake_bonus_code",
            "code": code,
            "tg_message_id": message.id
        }

        # Send to SSE broadcaster via HTTP POST
        await send_to_broadcast(payload, start)

        try:
            os.remove(file_path)
        except:
            pass

        log("DONE.", start)

    await app.start()
    print(">> Worker Started <<")
    await idle()
    await app.stop()


# ========================
# MAIN ENTRY
# ========================
async def main():
    asyncio.create_task(start_http_ws_server())
    await start_bot()


if __name__ == "__main__":
    asyncio.run(main())
