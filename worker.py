import os
import cv2
import pytesseract
import logging
import threading
import json
import time
import asyncio
from flask import Flask, jsonify
from flask_sock import Sock
from pyrogram import Client, filters
from pyrogram.enums import MessageMediaType

# ==========================================
# CONFIGURATION
# ==========================================

ASSISTANT_SESSION = "AQHDLbkAnMM3bSPaxw0LKc6QyEJsXLLyHClFwzUHvi2QjAyqDGmBs-eePhG42807v0N_JlLLxUUHoKDqEKkkLyPblSrXfLip0EMsF8zgYdr8fniTLdRhvvKAppwGiSoVLJKhmNcEGYSqgsX8BkEHoArrMH3Xxey1zCiUsmDOY7O4xD35g-KJvaxrMgMiSj1kfdYZeqTj7ZVxNR2G4Uc-LNoocYjSQo67GiydC4Uki1-_-yhYkg3PGn_ge1hmTRWCyFEggvagGEymQQBSMnUS_IonAODOWMZtpk5DP-NERyPgE4DJmLn2LCY8fuZXF-A68u9DrEClFI7Pq9gncMvmqbhsu0i0ZgAAAAHp6LDMAA"
TARGET_CHAT_ID = 7618467489

# Windows Tesseract Path (Uncomment and adjust if on Windows)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==========================================
# FLASK & WEBSOCKET SETUP
# ==========================================

app = Flask(__name__)
sock = Sock(app)

# Store connected raw WebSocket clients
connected_clients = []
clients_lock = threading.Lock()

def broadcast_to_websockets(code_text):
    """
    Sends the extracted code to all connected WebSocket clients.
    """
    payload = json.dumps({
        "type": "code_drop", 
        "code": code_text, 
        "ts": int(time.time())
    })

    sent_count = 0
    dead = []
    
    with clients_lock:
        for client in list(connected_clients):
            try:
                client.send(payload)
                sent_count += 1
            except Exception as e:
                logger.debug(f"[BROADCAST] failed to send to client: {e}")
                dead.append(client)

        # Cleanup dead clients
        for d in dead:
            try:
                connected_clients.remove(d)
            except ValueError:
                pass

    if sent_count > 0:
        logger.info(f"[BROADCAST] Sent code '{code_text}' to {sent_count} clients.")

def server_keepalive():
    """
    Background thread that sends a ping to all clients every 20 seconds.
    Prevents idle connection timeouts.
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
                
                # Cleanup dead clients
                for d in dead_clients:
                    try:
                        connected_clients.remove(d)
                    except ValueError:
                        pass
                        
        except Exception as e:
            logger.error(f"[KEEPALIVE] Error: {e}")

@app.route('/')
def index():
    return "TELEGRAM CODE EXTRACTOR & BROADCASTER RUNNING"

@sock.route('/ws')
def ws_endpoint(ws):
    """
    WebSocket endpoint for clients.
    """
    with clients_lock:
        connected_clients.append(ws)
    logger.info(f"[SERVER] Client Connected. Total: {len(connected_clients)}")

    try:
        while True:
            # Block waiting for message (keepalive handles traffic)
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
        logger.info(f"[SERVER] Client Disconnected. Total: {len(connected_clients)}")

# ==========================================
# PYROGRAM & EXTRACTION LOGIC
# ==========================================

assistant = Client("assistant_account", session_string=ASSISTANT_SESSION)

def extract_code_from_filename(file_name):
    """
    Attempts to parse the code from the filename.
    Expected format: "Code Drop - Telegram Winter_flakex15.mp4"
    Target extraction: "flakex15"
    """
    if not file_name:
        return None
    
    # Remove file extension (e.g., .mp4)
    name_without_ext = os.path.splitext(file_name)[0]
    
    # Logic: Split by underscore '_' and take the last part
    if "_" in name_without_ext:
        parts = name_without_ext.rsplit('_', 1)
        possible_code = parts[-1]
        
        # Basic validation
        if possible_code and possible_code.isalnum():
            return possible_code
            
    return None

def extract_code_via_ocr(video_path):
    """
    Extracts frame at exactly 3 seconds and performs OCR.
    """
    cap = cv2.VideoCapture(video_path)
    
    # Jump to exactly 3 seconds (3000 ms)
    cap.set(cv2.CAP_PROP_POS_MSEC, 3000)
    
    success, frame = cap.read()
    extracted_text = None
    
    if success:
        # Image Processing
        height, width, _ = frame.shape
        
        # ROI: Focus on Center-Right area
        y_start = int(height * 0.4)
        y_end = int(height * 0.7)
        x_start = int(width * 0.4) 
        x_end = int(width * 0.95)
        
        cropped_frame = frame[y_start:y_end, x_start:x_end]
        
        # Convert to grayscale
        gray = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2GRAY)
        
        # Thresholding
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # OCR
        text = pytesseract.image_to_string(thresh, config='--psm 6').strip()
        
        # Clean text
        text = text.replace(" ", "").replace("\n", "")
        if text:
            extracted_text = text

    cap.release()
    return extracted_text

# --- HANDLER: MAIN MEDIA PROCESSOR ---
@assistant.on_message(filters.chat(TARGET_CHAT_ID) & (filters.video | filters.animation))
async def handle_media_dm(client, message):
    logger.info(f"Media detected in chat: {message.chat.id}. Processing...")
    
    media_obj = message.video if message.video else message.animation
    file_name = getattr(media_obj, "file_name", None)
    final_code = None

    # 1. Try Filename
    logger.info(f"Checking filename: {file_name}")
    filename_code = extract_code_from_filename(file_name)

    if filename_code:
        logger.info(f"SUCCESS: Code from filename: {filename_code}")
        final_code = filename_code
    else:
        logger.info("Filename failed. Starting OCR...")
        file_path = await message.download()
        
        try:
            ocr_code = extract_code_via_ocr(file_path)
            if ocr_code:
                logger.info(f"SUCCESS: Code from OCR: {ocr_code}")
                final_code = ocr_code
            else:
                logger.warning("FAILED: OCR could not detect code.")
        except Exception as e:
            logger.error(f"OCR Error: {e}")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    # 2. Handle Result
    if final_code:
        logger.info(f"✅✅✅ FINAL CODE: {final_code} ✅✅✅")
        
        # A) Reply to Telegram
        try:
            await message.reply_text(f"✅ Extracted Code: `{final_code}`")
        except Exception as e:
            logger.error(f"Telegram Reply Error: {e}")

        # B) Broadcast to WebSockets
        broadcast_to_websockets(final_code)

def run_pyrogram():
    """
    Runs the Pyrogram client in a separate thread using a fresh event loop.
    Avoids 'assistant.run()' because it attempts to handle signals (Ctrl+C)
    which fails in a non-main thread.
    """
    try:
        # 1. Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 2. Define the async entry point
        async def start_client():
            logger.info("Starting Pyrogram Client...")
            await assistant.start()
            logger.info("Pyrogram Client Started & Listening...")
            # Keep this coroutine alive forever
            while True:
                await asyncio.sleep(3600)

        # 3. Run the loop
        loop.run_until_complete(start_client())
        
    except Exception as e:
        logger.error(f"Pyrogram Thread Crashed: {e}")

# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # 1. Start Pyrogram Thread (Non-blocking mode)
    pyrogram_thread = threading.Thread(target=run_pyrogram, name="PyrogramThread", daemon=True)
    pyrogram_thread.start()

    # 2. Start Keepalive Thread
    keepalive_thread = threading.Thread(target=server_keepalive, name="KeepAliveThread", daemon=True)
    keepalive_thread.start()

    # 3. Start Flask Server (Blocking Main Thread)
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"[SERVER] Starting server on port {port}")
    
    # Disable reloader/debug to prevent thread duplication and signal issues
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False, debug=False)
