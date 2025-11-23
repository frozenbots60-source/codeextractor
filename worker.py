import os
import time
import json
import asyncio
import tempfile
import numpy as np
import cv2
import websockets
import subprocess
from rapidocr_onnxruntime import RapidOCR
import re
from aiohttp import web
import aiohttp


# =======================================================
# CONFIG
# =======================================================

# This should point to the local /send endpoint or your deployed /send endpoint.
# Example for local testing: "http://127.0.0.1:8080/send"
# Example for Heroku: "https://your-app.herokuapp.com/send"
BROADCAST_WS_URL = "http://127.0.0.1:8080/send"

TARGET_SECOND = 4

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))

# Optional auth for POST /send (set as env BROADCAST_AUTH or leave empty)
BROADCAST_AUTH = os.environ.get("BROADCAST_AUTH", "")

# Keepalive for SSE (ms)
SSE_KEEPALIVE_MS = 15000
# =======================================================


ocr_model = RapidOCR()
external_ws = None

connected_ws_clients = set()
sse_clients = set()


def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")


async def ws_broadcast_connect():
    global external_ws
    if external_ws is None or getattr(external_ws, "closed", True):
        try:
            external_ws = await websockets.connect(BROADCAST_WS_URL, max_size=2**20)
        except:
            external_ws = None
    return external_ws


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
# WEBSOCKET SERVER (unchanged)
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
# SSE: GET /stream
# ========================
async def sse_handler(request):
    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await resp.prepare(request)

    try:
        await resp.write(b": connected\n\n")
    except:
        try: await resp.write_eof()
        except: pass
        return resp

    sse_clients.add(resp)
    print(f"[SSE] Client connected — total: {len(sse_clients)}")

    async def keep_alive():
        try:
            while True:
                await asyncio.sleep(SSE_KEEPALIVE_MS / 1000)
                try:
                    await resp.write(b": ping\n\n")
                except:
                    break
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(keep_alive())

    try:
        await task
    finally:
        task.cancel()
        sse_clients.discard(resp)
        print(f"[SSE] Client disconnected — total: {len(sse_clients)}")
        try: await resp.write_eof()
        except: pass

    return resp


# ========================
# POST /send (broadcast)
# ========================
async def send_handler(request):
    if BROADCAST_AUTH:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != BROADCAST_AUTH:
            return web.json_response({"error": "unauthorized"}, status=401)

    try:
        payload = await request.json()
    except:
        return web.json_response({"error": "invalid json"}, status=400)

    data = f"data: {json.dumps(payload)}\n\n".encode()

    for client in list(sse_clients):
        try:
            await client.write(data)
        except:
            try: sse_clients.discard(client)
            except: pass

    print(f"[SEND] Broadcast to {len(sse_clients)} clients: {payload}")
    return web.json_response({"ok": True, "clients": len(sse_clients)})


# ========================
# START HTTP + WS + SSE SERVER
# ========================
async def start_http_ws_server():
    app = web.Application()

    app.router.add_get("/", http_index)

    app.router.add_route("GET", "/ws", websocket_handler)
    app.router.add_route("OPTIONS", "/ws", ws_options)

    app.router.add_get("/stream", sse_handler)
    app.router.add_post("/send", send_handler)

    async def send_options(request):
        resp = web.Response(text="OK")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp

    app.router.add_route("OPTIONS", "/send", send_options)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)

    print(f"\n===== Local Servers Running =====")
    print(f"HTTP Server     : http://{HOST}:{PORT}/")
    print(f"WebSocket Server: ws://{HOST}:{PORT}/ws")
    print(f"SSE Stream URL  : http://{HOST}:{PORT}/stream")
    print(f"Broadcast POST  : {BROADCAST_WS_URL}\n")

    await site.start()


# ========================
# MAIN ENTRY
# ========================
async def main():
    await start_http_ws_server()
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
