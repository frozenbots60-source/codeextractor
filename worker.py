import requests
import socketio
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

@app.route('/')
def index():
    return "STAKE RELAY SERVER RUNNING (HEADLESS MODE)"

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
            # Keep connection alive and listen for disconnects
            data = ws.receive()
            if data is None:
                break
            
            # Simple heartbeat response if client sends 'ping'
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
# TOKEN MANAGER
# ==========================================

class TokenManager:
    def __init__(self):
        self.tokens = []
        self.provided_token = '0.xVtuTFJmRfr8oQQZquxI6c7vFKFu-LUXJfCwBenBjGX3c7gT8zI51H6O9ON2fsG9ZLHcGR92dPYHUfzrlxw3Nq0-NHlEQBParVzK_PVxoQq0fXMM-XSAsYX0D4nf2e0m9Er_vaDbLj_h7VL9xSOOVQXFZcVYUwq6FuPgTfxUypq3zZ5l9DvR9LMbyXvrA2bEr0HRJIj38bmuqkU49XtTpMk9qzt3vSJIGnpUe9T5BJsHwSYVEr6AlxPifpeZ6RpeGDeN538DLZYiNcNZAZT2N1zgHb9YPTTlJGb3FM0FalWm_e9B65VoflM8MX9D7dYbBbnk632q3s6fOnXbTyR4RSWgeYePOi3wvwG8NLEPdEp3k9qXWTzegVhKwxHd3Zb6b-HE8jPbReszggHjJGqpUR9xYPkQaEhF8PjwesJJ-c3wKOpFc_4oVrSI6rVcWKLaBRFPjAqUwz4ORdC7IC2fI0lRLdMg8pzSa4yFo9XP8TCVPZfeLBCgjxhQCiU3VbSCRhayoo29-vdltJXM1LN2gC7Q2h9NUO19kcUAPE3uPR1KwUQaRcqI9yNvWuCV18vAP8jQSlGE0HbzhLi0gys7pzMBQSHy8b-IVV-5ZjOlMkGyIf1WXD0olwyyTBuH-nrHs3MKrwA9_WK4ZmdZLOrx9gHiJ29ZQXmdMNmwqknluDKwgqX6YcwWs3hoPQbb1RLdIh1cY9GSXy9YnN3W5wKFrnd_tbnnKIvgK-JWV0LtaEZz2H_HLJ10dSVFfhFB7Tw0COa-L0l79oaVJS1lXuim7zWyjtVIRLZlZ6XXHILyvhPLLTaKsofqoaCoIWh6aPnRryoviuCNRmp6aBTa9uB5MEEHPar3kUDY0qH0f-F2A9xcf8kTttwbvEQw_slFedFH4.P-HMDFrGPaI5YxbKx5D1nA.b5283118b7f141996bc245f27ab18e363aff7f79f6d228d7ff323960473cd652'

    def initialize(self):
        self.tokens.append({'token': self.provided_token})

    def get_token(self):
        return self.tokens[0]['token'] if self.tokens else None

# ==========================================
# LISTENER BOT
# ==========================================

class CodeDisplayDashboard:
    def __init__(self):
        self.config = {
            'server_url': 'https://code.hh123.site',
            'stake_url': 'https://stake.com',
            'stake_referer': 'https://stake.com/settings/offers',
            'username': 'Iqooz9KK',
            'version': '6.3.0',
            'locale': 'en',
        }

        # Use polling transport
        self.sio = socketio.Client(
            logger=False,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=10,
            reconnection_delay=5
        )

        self.token_manager = TokenManager()
        self.token_manager.initialize()
        self.running = True
        self.connected = False
        self.lock = threading.Lock()
        self.setup_socket_handlers()

    def get_stake_headers(self):
        return {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': self.config['stake_url'],
            'Referer': self.config['stake_referer'],
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    def setup_socket_handlers(self):
        @self.sio.event
        def connect():
            logging.info("[BOT] Connected to upstream code server")
            with self.lock:
                self.connected = True

        @self.sio.event
        def disconnect():
            logging.info("[BOT] Disconnected from upstream")
            with self.lock:
                self.connected = False

        @self.sio.on('message')
        def on_message(data):
            try:
                self.handle_socket_message(data)
            except Exception as e:
                logging.debug(f"[BOT] error handling message: {e}")

        @self.sio.on('sub_code_v2')
        def on_sub_code_v2(data):
            try:
                # Wrap it to preserve the event type context if needed, 
                # or just pass data if you want raw event data.
                # Here we wrap to maintain consistency with previous logic,
                # but broadcast_raw will send this structure exactly.
                self.handle_socket_message({'type': 'sub_code_v2', 'msg': data})
            except Exception as e:
                logging.debug(f"[BOT] error handling sub_code_v2: {e}")

    def handle_socket_message(self, data):
        """
        Receives data from the bot's socket and forwards it RAW to our clients and Telegram.
        """
        if not data:
            return

        # Optional: Parse purely for logging purposes
        code = None
        try:
            # Check if it contains a code (just for console logging)
            if isinstance(data, dict):
                msg = data.get('msg', {})
                if isinstance(msg, dict):
                    code = msg.get('code') or (msg.get('data') and msg['data'].get('code'))
                if not code:
                    code = data.get('code')
        except Exception:
            pass

        if code:
            logging.info(f"[RECEIVED] Code Detected: {code}")
        
        # --- CRITICAL: Send RAW data to WS and then Telegram ---
        broadcast_raw(data)

    def connect_to_server(self):
        try:
            logging.info("[BOT] Authenticating...")
            auth_response = requests.post(
                f"{self.config['server_url'].rstrip('/')}/api/login",
                headers=self.get_stake_headers(),
                json={
                    'username': self.config['username'],
                    'platform': 'stake.com',
                    'version': self.config['version']
                },
                timeout=10
            )

            if not auth_response.ok:
                logging.error(f"[BOT] Auth failed: {auth_response.status_code}")
                return

            resp_json = auth_response.json()
            auth_token = None
            if isinstance(resp_json, dict):
                auth_token = resp_json.get('data') or resp_json.get('token') or resp_json.get('auth')
            
            if not auth_token:
                logging.error(f"[BOT] No token in response")
                return

            try:
                self.sio.connect(
                    self.config['server_url'],
                    auth={
                        'token': auth_token,
                        'version': self.config['version'],
                        'locale': self.config['locale']
                    },
                    transports=['polling'], 
                    namespaces=['/'] 
                )
            except Exception as e:
                logging.error(f"[BOT] Connect failed: {e}")
                with self.lock:
                    self.connected = False
                return

            try:
                self.sio.emit('auth', {'token': auth_token, 'username': self.config['username']})
            except Exception:
                pass

            with self.lock:
                self.connected = True

        except Exception as e:
            logging.error(f"[BOT] Connection Exception: {e}")
            with self.lock:
                self.connected = False

    def start_heartbeat(self):
        def heartbeat():
            while self.running:
                time.sleep(25)
                try:
                    if self.sio and self.sio.connected:
                        try:
                            self.sio.emit('ping_from_bot', {'ts': int(time.time())})
                        except Exception:
                            pass
                except Exception:
                    pass
        threading.Thread(target=heartbeat, daemon=True).start()

    def run(self):
        self.start_heartbeat()
        self.connect_to_server()
        retry_backoff = 5

        while self.running:
            try:
                with self.lock:
                    is_connected = self.connected and getattr(self.sio, 'connected', False)

                if not is_connected:
                    logging.info("[BOT] Reconnecting...")
                    try:
                        self.connect_to_server()
                    except Exception:
                        pass
                    time.sleep(retry_backoff)
                    retry_backoff = min(60, retry_backoff * 2)
                else:
                    retry_backoff = 5
                    time.sleep(1)
            except KeyboardInterrupt:
                self.running = False
            except Exception:
                time.sleep(2)

        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass

# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # 1. Start Bot Thread
    bot = CodeDisplayDashboard()
    bot_thread = threading.Thread(target=bot.run, name="CodeDisplayDashboard", daemon=True)
    bot_thread.start()

    # 2. Start Flask Server
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"[SERVER] Starting headless server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
