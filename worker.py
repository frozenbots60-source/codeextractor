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
from flask import Flask, render_template_string
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

# Initialize urllib3
http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=2, read=8),
)

# ==========================================
# FLASK SERVER + RAW WEBSOCKET SETUP
# ==========================================

app = Flask(__name__)
sock = Sock(app)

# Store connected raw WebSocket clients
connected_clients = set()
clients_lock = threading.Lock()

# Define the HTML template for simple viewing
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Stake Code Relay</title>
    <style>
        body { font-family: monospace; background: #0f0f0f; color: #00ff00; padding: 20px; }
        #log { border: 1px solid #333; padding: 10px; height: 90vh; overflow-y: scroll; }
        .new-code { color: #fff; background: #004400; padding: 2px; }
    </style>
</head>
<body>
    <h3>Received Codes (Raw WebSocket):</h3>
    <div id="log"></div>
    <script>
        // Connect to the raw WebSocket at the current domain /ws
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
        
        ws.onopen = function() {
            document.getElementById('log').innerHTML += '<div>[SYSTEM] Connected to Relay Server</div>';
        };
        
        ws.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                if (data.type === 'stake_bonus_code') {
                    var entry = '<div class="new-code">[' + new Date().toLocaleTimeString() + '] CODE: ' + data.code + '</div>';
                    document.getElementById('log').innerHTML = entry + document.getElementById('log').innerHTML;
                }
            } catch(e) {
                console.log('Received:', event.data);
            }
        };
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# This is the endpoint your claim.js is trying to connect to: /ws
@sock.route('/ws')
def ws_endpoint(ws):
    with clients_lock:
        connected_clients.add(ws)
    logging.info(f"[SERVER] New Client Connected. Total: {len(connected_clients)}")
    
    try:
        while True:
            # Keep the connection open and listen for pings
            data = ws.receive()
            if data == 'ping':
                ws.send('pong')
    except Exception:
        pass
    finally:
        with clients_lock:
            connected_clients.remove(ws)
        logging.info(f"[SERVER] Client Disconnected. Total: {len(connected_clients)}")

def broadcast_code(code):
    """Sends the code to all connected WebSocket clients"""
    payload = json.dumps({
        "type": "stake_bonus_code",
        "code": code,
        "source": "heroku_relay"
    })
    
    with clients_lock:
        dead_clients = []
        for client in list(connected_clients):
            try:
                client.send(payload)
            except:
                dead_clients.append(client)
        
        # Cleanup dead connections
        for dead in dead_clients:
            connected_clients.discard(dead)
            
    if connected_clients:
        logging.info(f"[BROADCAST] Sent code '{code}' to {len(connected_clients)} clients")

# ==========================================
# TOKEN MANAGER CLASS
# ==========================================

class TokenManager:
    def __init__(self):
        self.tokens = []
        self.provided_token = '0.xVtuTFJmRfr8oQQZquxI6c7vFKFu-LUXJfCwBenBjGX3c7gT8zI51H6O9ON2fsG9ZLHcGR92dPYHUfzrlxw3Nq0-NHlEQBParVzK_PVxoQq0fXMM-XSAsYX0D4nf2e0m9Er_vaDbLj_h7VL9xSOOVQXFZcVYUwq6FuPgTfxUypq3eGG3WRELdJvWdkwHjMFo4tsLt-U-LdppK8p_yEwp3_zZ5l9DvR9LMbyXvrA2bEr0HRJIj38bmuqkU49XtTpMk9qzt3vSJIGnpUe9T5BJsHwSYVEr6AlxPifpeZ6RpeGDeN538DLZYiNcNZAZT2N1zgHb9YPTTlJGb3FM0FalWm_e9B65VoflM8MX9D7dYbBbnk632q3s6fOnXbTyR4RSWgeYePOi3wvwG8NLEPdEp3k9qXWTzegVhKwxHd3Zb6b-HE8jPbReszggHjJGqpUR9xYPkQaEhF8PjwesJJ-c3wKOpFc_4oVrSI6rVcWKLaBRFPjAqUwz4ORdC7IC2fI0lRLdMg8pzSa4yFo9XP8TCVPZfeLBCgjxhQCiU3VbSCRhayoo29-vdltJXM1LN2gC7Q2h9NUO19kcUAPE3uPR1KwUQaRcqI9yNvWuCV18vAP8jQSlGE0HbzhLi0gys7pzMBQSHy8b-IVV-5ZjOlMkGyIf1WXD0olwyyTBuH-nrHs3MKrwA9_WK4ZmdZLOrx9gHiJ29ZQXmdMNmwqknluDKwgqX6YcwWs3hoPQbb1RLdIh1cY9GSXy9YnN3W5wKFrnd_tbnnKIvgK-JWV0LtaEZz2H_HLJ10dSVFfhFB7Tw0COa-L0l79oaVJS1lXuim7zWyjtVIRLZlZ6XXHILyvhPLLTaKsofqoaCoIWh6aPnRryoviuCNRmp6aBTa9uB5MEEHPar3kUDY0qH0f-F2A9xcf8kTttwbvEQw_slFedFH4.P-HMDFrGPaI5YxbKx5D1nA.b5283118b7f141996bc245f27ab18e363aff7f79f6d228d7ff323960473cd652'

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
            self.connected = True
            
        @self.sio.event
        def disconnect(data):
            logging.info("[BOT] Disconnected from upstream")
            self.connected = False
            
        @self.sio.on('message')
        def on_message(data):
            self.handle_socket_message(data)

    def handle_socket_message(self, data):
        """Handle incoming socket messages"""
        if data.get('type') == 'sub_code_v2':
            code = data['msg']['code'].strip()
            logging.info(f"[RECEIVED] Code: {code}")
            
            # --- BROADCAST TO EXTERNAL CLIENTS ---
            # Using the new helper function for raw websockets
            broadcast_code(code)

    def connect_to_server(self):
        try:
            logging.info("[BOT] Authenticating...")
            auth_response = requests.post(
                f"{self.config['server_url']}/api/login",
                headers=self.get_stake_headers(),
                json={
                    'username': self.config['username'],
                    'platform': 'stake.com',
                    'version': self.config['version']
                },
                timeout=10
            )
            
            if not auth_response.ok:
                logging.error(f"Auth failed: {auth_response.status_code}")
                return

            auth_token = auth_response.json()['data']
            
            self.sio.connect(
                self.config['server_url'],
                auth={
                    'token': auth_token,
                    'version': self.config['version'],
                    'locale': self.config['locale']
                },
                transports=['websocket', 'polling']
            )
            
        except Exception as e:
            logging.error(f"[BOT ERROR] Connection failed: {e}")
            self.connected = False

    def start_heartbeat(self):
        def heartbeat():
            while self.running:
                time.sleep(30)
                if self.connected and self.sio.connected:
                    try:
                        self.sio.emit('ping')
                    except:
                        pass
        threading.Thread(target=heartbeat, daemon=True).start()

    def run(self):
        """Main loop for the bot"""
        self.start_heartbeat()
        self.connect_to_server()
        
        while self.running:
            if not self.connected and not self.sio.connected:
                # Simple reconnect logic if disconnected
                time.sleep(10)
                try:
                    self.connect_to_server()
                except:
                    pass
            time.sleep(1)

# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # 1. Start the Bot in a background thread
    bot = CodeDisplayDashboard()
    
    bot_thread = threading.Thread(target=bot.run)
    bot_thread.daemon = True
    bot_thread.start()
    
    # 2. Start the Flask Server (Local Testing Only)
    # Heroku uses Gunicorn to run 'app' directly, so this block only runs on PC
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"[SERVER] Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)
