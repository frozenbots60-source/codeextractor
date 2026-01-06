import requests
import json
import time
import threading
from datetime import datetime
import sys
import urllib3
import logging
import os
from flask import Flask, request, jsonify
from flask_sock import Sock

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

# Telegram configuration
TELEGRAM_BOT_TOKEN = "7715850236:AAHOB1xV2CIsbeb9w_HX9pr478jtXq_rhq8"
TELEGRAM_CHAT_ID = "7618467489"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# Initialize urllib3
http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=2, read=8),
)

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
    2. After clients are served, forwards the payload to Telegram.
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

    # --- STEP 2: Forward to Telegram ---
    try:
        text_to_send = payload_str
        # Telegram has a message limit (~4096 chars)
        if len(text_to_send) > 4000:
            text_to_send = text_to_send[:3990] + "\n\n(Truncated)"
            
        resp = requests.post(
            TELEGRAM_API_URL,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text_to_send
            },
            timeout=8
        )
        if resp.ok:
            logging.info(f"[TELEGRAM] Forwarded payload to chat {TELEGRAM_CHAT_ID}")
        else:
            logging.error(f"[TELEGRAM] Failed: {resp.status_code} {resp.text[:300]}")
    except Exception as e:
        logging.error(f"[TELEGRAM] Exception: {e}")

def server_keepalive():
    """
    Background thread that sends a ping to all clients every 20 seconds.
    This prevents Heroku H15 (Idle Connection) timeouts.
    """
    while True:
        time.sleep(20) # Heroku timeout is 55s, so 20s is safe
        try:
            # Create a simple JSON ping payload
            ping_payload = json.dumps({"type": "ping", "ts": int(time.time())})
            
            with clients_lock:
                dead_clients = []
                for client in connected_clients:
                    try:
                        client.send(ping_payload)
                    except Exception:
                        dead_clients.append(client)
                
                # Cleanup dead clients found during ping
                for d in dead_clients:
                    try:
                        connected_clients.remove(d)
                    except ValueError:
                        pass
                        
            # Optional: Log keepalive if you want to verify it's working
            # logging.info(f"[KEEPALIVE] Sent ping to {len(connected_clients)} clients")
            
        except Exception as e:
            logging.error(f"[KEEPALIVE] Error: {e}")

@app.route('/')
def index():
    return "WEBSOCKET BROADCAST SERVER RUNNING"

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
    """
    WebSocket endpoint for clients.
    """
    client_id = id(ws)
    with clients_lock:
        connected_clients.append(ws)
    logging.info(f"[SERVER] Client Connected. Total: {len(connected_clients)} (id={client_id})")

    try:
        while True:
            # Block waiting for message. 
            # The 'server_keepalive' thread handles the traffic generation to keep connection open.
            data = ws.receive()
            if data is None:
                break
            
            # Simple heartbeat response if client sends 'ping' manually
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
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # 1. Start Keepalive Thread (Prevents H15 errors)
    keepalive_thread = threading.Thread(target=server_keepalive, name="ServerKeepalive", daemon=True)
    keepalive_thread.start()

    # 2. Start Flask Server
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"[SERVER] Starting WebSocket Server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
