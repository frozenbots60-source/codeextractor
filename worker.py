import requests
import json
import time
import threading
from datetime import datetime
import sys
import urllib3
import logging
import os
import cv2
import pytesseract
from flask import Flask, request, jsonify
from flask_sock import Sock
from pyrogram import Client, filters
from pyrogram.enums import MessageMediaType

# ==========================================
# CONFIGURATION & LOGGING
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Telegram Forwarding Config (For sending results to your channel via Bot API) ---
TELEGRAM_BOT_TOKEN = "7715850236:AAHOB1xV2CIsbeb9w_HX9pr478jtXq_rhq8"
TELEGRAM_FORWARD_CHAT_ID = "7618467489"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# --- Pyrogram Listener Config (For reading messages/OCR) ---
ASSISTANT_SESSION = "AQHDLbkAnMM3bSPaxw0LKc6QyEJsXLLyHClFwzUHvi2QjAyqDGmBs-eePhG42807v0N_JlLLxUUHoKDqEKkkLyPblSrXfLip0EMsF8zgYdr8fniTLdRhvvKAppwGiSoVLJKhmNcEGYSqgsX8BkEHoArrMH3Xxey1zCiUsmDOY7O4xD35g-KJvaxrMgMiSj1kfdYZeqTj7ZVxNR2G4Uc-LNoocYjSQo67GiydC4Uki1-_-yhYkg3PGn_ge1hmTRWCyFEggvagGEymQQBSMnUS_IonAODOWMZtpk5DP-NERyPgE4DJmLn2LCY8fuZXF-A68u9DrEClFI7Pq9gncMvmqbhsu0i0ZgAAAAHp6LDMAA"
TARGET_LISTEN_CHAT_ID = 7618467489

# Initialize urllib3
http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=2, read=8),
)

# Windows Tesseract Path (Uncomment and adjust if on Windows)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# ==========================================
# FLASK SERVER & BROADCAST LOGIC
# ==========================================

app = Flask(__name__)
sock = Sock(app)

# Store connected raw WebSocket clients
connected_clients = []
clients_lock = threading.Lock()

def broadcast_raw(raw_data):
    """
    1. Sends the exact server response (raw_data) to all connected WebSocket clients.
    2. After clients are served, forwards the payload to Telegram via Bot API.
    """
    # Prepare payload as exact JSON string representation
    try:
        if isinstance(raw_data, str):
            payload_str = raw_data
        else:
            payload_str = json.dumps(raw_data, ensure_ascii=False)
    except Exception:
        payload_str = str(raw_data)

    # --- STEP 1: Broadcast to WebSocket Clients ---
    dead = []
    sent_count = 0
    with clients_lock:
        for client in list(connected_clients):
            try:
                client.send(payload_str)
                sent_count += 1
            except Exception as e:
                logging.debug(f"[BROADCAST] failed to send to client {id(client)}: {e}")
                dead.append(client)

        # Cleanup dead clients
        for d in dead:
            try:
                connected_clients.remove(d)
            except ValueError:
                pass

    if sent_count:
        logging.info(f"[BROADCAST] Sent payload to {sent_count} clients")

    # --- STEP 2: Forward to Telegram (Bot API) ---
    try:
        text_to_send = f"🚀 Broadcasted:\n{payload_str}"
        if len(text_to_send) > 4000:
            text_to_send = text_to_send[:3990] + "\n\n(Truncated)"
            
        resp = requests.post(
            TELEGRAM_API_URL,
            data={
                "chat_id": TELEGRAM_FORWARD_CHAT_ID,
                "text": text_to_send
            },
            timeout=8
        )
        if not resp.ok:
            logging.error(f"[TELEGRAM] Failed: {resp.status_code} {resp.text[:300]}")
    except Exception as e:
        logging.error(f"[TELEGRAM] Exception: {e}")

def server_keepalive():
    """
    Background thread that sends a ping to all clients every 20 seconds.
    This prevents Heroku H15 (Idle Connection) timeouts.
    """
    while True:
        time.sleep(20) 
        try:
            ping_payload = json.dumps({"type": "ping", "ts": int(time.time())})
            
            with clients_lock:
                dead_clients = []
                for client in connected_clients:
                    try:
                        client.send(ping_payload)
                    except Exception:
                        dead_clients.append(client)
                
                for d in dead_clients:
                    try:
                        connected_clients.remove(d)
                    except ValueError:
                        pass
        except Exception as e:
            logging.error(f"[KEEPALIVE] Error: {e}")

@app.route('/')
def index():
    return "STAKE RELAY SERVER RUNNING (OCR INTEGRATED)"

@app.route('/manual-broadcast', methods=['POST'])
def manual_broadcast():
    """Manually broadcast payload via API."""
    try:
        if request.is_json:
            payload = request.get_json(force=True, silent=True)
            if payload is None:
                return jsonify({"error": "invalid_json"}), 400
        else:
            payload = request.get_data(as_text=True)

        broadcast_raw(payload)
        return jsonify({"ok": True}), 200

    except Exception as e:
        logging.error(f"[MANUAL] Error: {e}")
        return jsonify({"error": "failed"}), 500

@sock.route('/ws')
def ws_endpoint(ws):
    """WebSocket endpoint for clients."""
    client_id = id(ws)
    with clients_lock:
        connected_clients.append(ws)
    logging.info(f"[SERVER] Client Connected. Total: {len(connected_clients)} (id={client_id})")

    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            
            # Simple heartbeat response
            if isinstance(data, str) and data.strip().lower() == 'ping':
                try:
                    ws.send('pong')
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        with clients_lock:
            try:
                connected_clients.remove(ws)
            except ValueError:
                pass
        logging.info(f"[SERVER] Client Disconnected. Total: {len(connected_clients)}")

# ==========================================
# CODE EXTRACTION LOGIC (OCR & UTILS)
# ==========================================

def extract_code_from_filename(file_name):
    """
    Attempts to parse the code from the filename.
    Target extraction: "Code Drop - Telegram Winter_flakex15.mp4" -> "flakex15"
    """
    if not file_name:
        return None
    
    name_without_ext = os.path.splitext(file_name)[0]
    
    # Logic: Split by underscore '_' and take the last part
    if "_" in name_without_ext:
        parts = name_without_ext.rsplit('_', 1)
        possible_code = parts[-1]
        
        if possible_code and possible_code.isalnum():
            return possible_code
            
    return None

def extract_code_via_ocr(video_path):
    """
    Extracts frame at exactly 3 seconds and performs OCR.
    """
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, 3000)
    
    success, frame = cap.read()
    extracted_text = None
    
    if success:
        # Image Processing
        height, width, _ = frame.shape
        y_start = int(height * 0.4)
        y_end = int(height * 0.7)
        x_start = int(width * 0.4) 
        x_end = int(width * 0.95)
        
        cropped_frame = frame[y_start:y_end, x_start:x_end]
        gray = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        text = pytesseract.image_to_string(thresh, config='--psm 6').strip()
        text = text.replace(" ", "").replace("\n", "")
        if text:
            extracted_text = text

    cap.release()
    return extracted_text

# ==========================================
# PYROGRAM ASSISTANT (LISTENER)
# ==========================================

assistant = Client("assistant_account", session_string=ASSISTANT_SESSION)

@assistant.on_message(filters.chat(TARGET_LISTEN_CHAT_ID), group=1)
async def debug_logger(client, message):
    """Logs incoming messages to console for verification."""
    try:
        msg_type = message.media if message.media else "TEXT"
        logger.info(f"[LISTENER] Msg ID: {message.id} | Type: {msg_type}")
    except Exception as e:
        logger.error(f"Debug logger error: {e}")

@assistant.on_message(filters.chat(TARGET_LISTEN_CHAT_ID) & (filters.video | filters.animation), group=0)
async def handle_media_dm(client, message):
    logger.info(f"Media detected. Processing...")
    
    media_obj = message.video if message.video else message.animation
    file_name = getattr(media_obj, "file_name", None)
    final_code = None

    # --- STEP 1: Try Filename Extraction ---
    filename_code = extract_code_from_filename(file_name)
    if filename_code:
        logger.info(f"SUCCESS: Code found from filename: {filename_code}")
        final_code = filename_code
    else:
        # --- STEP 2: OCR Extraction ---
        logger.info("Proceeding to OCR...")
        try:
            file_path = await message.download()
            ocr_code = extract_code_via_ocr(file_path)
            
            if ocr_code:
                logger.info(f"SUCCESS: Code found via OCR: {ocr_code}")
                final_code = ocr_code
            else:
                logger.warning("FAILED: OCR could not detect the code.")
                
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.error(f"Error during OCR processing: {e}")

    # --- BROADCAST RESULT ---
    if final_code:
        logger.info(f"✅✅✅ FINAL EXTRACTED CODE: {final_code} ✅✅✅")
        
        # 1. Prepare JSON Payload for WebSocket Clients
        payload = {
            "code": final_code,
            "source": "telegram_ocr",
            "timestamp": int(time.time())
        }
        
        # 2. TRIGGER BROADCAST TO WEBSOCKETS
        broadcast_raw(payload)
        
        # 3. Reply to Telegram (Optional feedback)
        try:
            await message.reply_text(f"✅ Extracted & Broadcasted: `{final_code}`")
        except Exception:
            pass

# ==========================================
# MAIN EXECUTION
# ==========================================

def start_pyrogram():
    """Starts the Pyrogram client in a thread."""
    logger.info("[STARTUP] Starting Pyrogram Assistant...")
    assistant.run()

if __name__ == "__main__":
    # 1. Start Pyrogram Listener Thread (The "Input")
    # We use a thread because app.run() below is blocking
    telegram_thread = threading.Thread(target=start_pyrogram, name="PyrogramListener", daemon=True)
    telegram_thread.start()

    # 2. Start Keepalive Thread (Prevents H15 errors)
    keepalive_thread = threading.Thread(target=server_keepalive, name="ServerKeepalive", daemon=True)
    keepalive_thread.start()

    # 3. Start Flask Server (The "Output" / Websocket)
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"[SERVER] Starting headless server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
