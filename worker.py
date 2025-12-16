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

# Telegram forwarding configuration (raw HTTP API)
TELEGRAM_BOT_TOKEN = "7715850236:AAHOB1xV2CIsbeb9w_HX9pr478jtXq_rhq8"
TELEGRAM_CHAT_ID = "7618467489"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# Initialize urllib3 (keeps pool config explicit)
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

# Store connected raw WebSocket clients (list for safe iteration)
connected_clients = []
clients_lock = threading.Lock()

# Define the HTML template for simple viewing
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STAKE RELAY | PREMIUM SECURE</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>
        :root {
            --neon-green: #00ff41;
            --neon-dim: #008f11;
            --bg-dark: #050505;
            --glass: rgba(10, 20, 10, 0.7);
        }
        
        body {
            background-color: var(--bg-dark);
            color: var(--neon-green);
            font-family: 'Share Tech Mono', monospace;
            overflow: hidden; /* Prevent scrolling */
            user-select: none; /* Anti-select */
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            cursor: crosshair;
        }

        /* Matrix Background Animation */
        #matrix-bg {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
            opacity: 0.15;
            pointer-events: none;
        }

        .glass-panel {
            background: var(--glass);
            backdrop-filter: blur(10px);
            border: 1px solid var(--neon-dim);
            box-shadow: 0 0 15px rgba(0, 255, 65, 0.1);
        }

        .glow-text {
            text-shadow: 0 0 10px var(--neon-green);
        }

        /* Anti-Automation Canvas */
        #code-canvas {
            width: 100%;
            height: 120px;
            image-rendering: pixelated;
        }

        /* Scanline effect */
        .scanline {
            width: 100%;
            height: 100px;
            z-index: 10;
            background: linear-gradient(0deg, rgba(0,0,0,0) 0%, rgba(0, 255, 65, 0.1) 50%, rgba(0,0,0,0) 100%);
            opacity: 0.1;
            position: absolute;
            bottom: 100%;
            animation: scanline 10s linear infinite;
            pointer-events: none;
        }
        @keyframes scanline {
            0% { bottom: 100%; }
            100% { bottom: -100%; }
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ff0000;
            box-shadow: 0 0 5px #ff0000;
            transition: all 0.3s ease;
        }
        .status-dot.active {
            background: #00ff41;
            box-shadow: 0 0 10px #00ff41, 0 0 20px #00ff41;
        }

        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #000;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--neon-dim);
        }
    </style>
</head>
<body class="h-screen w-screen flex flex-col items-center justify-center p-4" oncontextmenu="return false;">
    <canvas id="matrix-bg"></canvas>
    <div class="scanline"></div>

    <!-- Main Container -->
    <div class="glass-panel rounded-xl p-1 w-full max-w-2xl relative overflow-hidden">
        <!-- Header -->
        <div class="flex justify-between items-center p-4 border-b border-green-900/50 bg-black/40">
            <div class="flex items-center gap-3">
                <div id="connection-dot" class="status-dot"></div>
                <h1 class="text-2xl font-bold font-['Orbitron'] tracking-wider text-white">STAKE<span class="text-[#00ff41]">RELAY</span></h1>
            </div>
            <div class="text-xs text-green-500 font-bold px-2 py-1 border border-green-900 rounded bg-black/50">
                SECURE STREAM V6.3
            </div>
        </div>

        <!-- Code Display Area (Canvas for Anti-Scrape) -->
        <div class="p-6 flex flex-col items-center justify-center bg-black/60 relative group">
            <div class="text-green-600 text-xs mb-2 tracking-[0.2em] uppercase">Incoming Transmission</div>
            
            <!-- The Magic Canvas: Code is drawn here, not standard text -->
            <div class="relative w-full border border-green-800/50 rounded-lg bg-black/80 overflow-hidden shadow-[0_0_30px_rgba(0,255,65,0.05)]">
                <canvas id="code-canvas" width="600" height="120"></canvas>
                <!-- Fake Overlay to prevent drag/drop -->
                <div class="absolute inset-0 z-20" onmousedown="return false"></div>
            </div>

            <div id="timestamp" class="mt-3 text-xs text-gray-500 font-mono">WAITING FOR SIGNAL...</div>
        </div>

        <!-- Log Area -->
        <div class="bg-black/40 border-t border-green-900/50 p-4">
            <h3 class="text-xs font-bold text-gray-400 mb-3 uppercase tracking-wider">Transmission History</h3>
            <div id="log-container" class="h-48 overflow-y-auto space-y-2 pr-2 font-mono text-sm">
                <!-- Logs injected here -->
            </div>
        </div>
    </div>

    <!-- Audio Element -->
    <audio id="alert-sound" src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.m4a" preload="auto"></audio>

    <script>
        // --- Anti-Automation & Security ---
        document.addEventListener('keydown', function(e) {
            // Prevent F12, Ctrl+Shift+I, Ctrl+C, Ctrl+U
            if(e.keyCode == 123 || 
               (e.ctrlKey && e.shiftKey && e.keyCode == 73) || 
               (e.ctrlKey && e.keyCode == 67) || 
               (e.ctrlKey && e.keyCode == 85)) {
                e.preventDefault();
                return false;
            }
        });

        // --- Canvas Rendering Logic (The "Code Grabber" Protection) ---
        const codeCanvas = document.getElementById('code-canvas');
        const ctx = codeCanvas.getContext('2d');

        function drawWaiting() {
            ctx.fillStyle = '#050505';
            ctx.fillRect(0, 0, codeCanvas.width, codeCanvas.height);
            ctx.font = '20px Share Tech Mono';
            ctx.fillStyle = '#004400';
            ctx.textAlign = 'center';
            ctx.fillText("/// SYSTEM READY ///", codeCanvas.width/2, codeCanvas.height/2 + 5);
        }

        function drawCode(code) {
            // Clear
            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, codeCanvas.width, codeCanvas.height);
            
            // Add noise background
            for(let i=0; i<100; i++) {
                ctx.fillStyle = `rgba(0, 255, 65, ${Math.random() * 0.1})`;
                ctx.fillRect(Math.random() * codeCanvas.width, Math.random() * codeCanvas.height, 2, 2);
            }

            // Draw Code
            ctx.font = 'bold 50px Orbitron';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            
            // Glitch effect shadow
            ctx.fillStyle = 'rgba(255, 0, 0, 0.3)';
            ctx.fillText(code, (codeCanvas.width/2) + 2, (codeCanvas.height/2) + 2);
            ctx.fillStyle = 'rgba(0, 0, 255, 0.3)';
            ctx.fillText(code, (codeCanvas.width/2) - 2, (codeCanvas.height/2) - 2);
            
            // Main text
            ctx.fillStyle = '#00ff41';
            ctx.shadowColor = '#00ff41';
            ctx.shadowBlur = 15;
            ctx.fillText(code, codeCanvas.width/2, codeCanvas.height/2);
            
            // Reset shadow
            ctx.shadowBlur = 0;

            // Interference lines (Anti-OCR)
            ctx.beginPath();
            for(let i=0; i<5; i++) {
                ctx.moveTo(0, Math.random() * codeCanvas.height);
                ctx.lineTo(codeCanvas.width, Math.random() * codeCanvas.height);
            }
            ctx.strokeStyle = 'rgba(0, 255, 65, 0.2)';
            ctx.stroke();
        }

        // --- Matrix Background ---
        const matrixCvs = document.getElementById('matrix-bg');
        const mCtx = matrixCvs.getContext('2d');
        let mWidth, mHeight;
        
        function resizeMatrix() {
            mWidth = matrixCvs.width = window.innerWidth;
            mHeight = matrixCvs.height = window.innerHeight;
        }
        window.onresize = resizeMatrix;
        resizeMatrix();

        const cols = Math.floor(window.innerWidth / 20);
        const ypos = Array(cols).fill(0);

        function stepMatrix() {
            mCtx.fillStyle = 'rgba(0, 0, 0, 0.05)';
            mCtx.fillRect(0, 0, mWidth, mHeight);
            mCtx.fillStyle = '#0f0';
            mCtx.font = '15px monospace';
            
            ypos.forEach((y, ind) => {
                const text = String.fromCharCode(Math.random() * 128);
                const x = ind * 20;
                mCtx.fillText(text, x, y);
                if (y > mHeight && Math.random() > 0.99) ypos[ind] = 0;
                else ypos[ind] = y + 20;
            });
        }
        setInterval(stepMatrix, 50);
        drawWaiting();

        // --- WebSocket Logic ---
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
        const logContainer = document.getElementById('log-container');
        const statusDot = document.getElementById('connection-dot');
        const audio = document.getElementById('alert-sound');

        ws.onopen = function() {
            console.log('[SECURE] Uplink Established');
            statusDot.classList.add('active');
            logEntry('SYSTEM', 'Secure uplink established successfully.');
        };

        ws.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                
                if (data.type === 'stake_bonus_code') {
                    // Play sound
                    audio.currentTime = 0;
                    audio.play().catch(e => console.log('Audio blocked'));

                    // Render to Canvas (Secure)
                    drawCode(data.code);
                    
                    // Update Timestamp
                    document.getElementById('timestamp').innerText = 'RECEIVED: ' + new Date().toLocaleTimeString();
                    
                    // Add to log (Masked partially or full)
                    logEntry('CODE', `Captured: ${data.code}`);
                    
                } else if (data.type === 'ping') {
                    // Heartbeat silent
                } else {
                    // Unknown message log
                    logEntry('MSG', 'Data received');
                }
            } catch(e) {
                console.error(e);
            }
        };

        ws.onclose = function() {
            statusDot.classList.remove('active');
            logEntry('SYSTEM', 'Connection lost. Reconnecting...');
            drawWaiting();
            setTimeout(function() {
                window.location.reload();
            }, 3000);
        }

        function logEntry(type, msg) {
            const div = document.createElement('div');
            div.className = 'flex items-center gap-2 text-xs opacity-0 animate-[fadeIn_0.5s_forwards]';
            div.innerHTML = `
                <span class="text-gray-500">[${new Date().toLocaleTimeString()}]</span>
                <span class="text-green-400 font-bold">${type}:</span>
                <span class="text-gray-300 truncate">${msg}</span>
            `;
            logContainer.insertBefore(div, logContainer.firstChild);
            
            // Limit history
            if(logContainer.children.length > 50) {
                logContainer.removeChild(logContainer.lastChild);
            }
        }
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
    """
    Each incoming browser websocket connection runs here.
    We:
      - register client
      - spawn a reader thread to detect client messages/closure
      - use a server-side periodic ping to keep connection alive (Heroku)
      - on exit, clean up client list safely
    """
    client_id = id(ws)
    with clients_lock:
        connected_clients.append(ws)
    logging.info(f"[SERVER] New Client Connected. Total: {len(connected_clients)} (client_id={client_id})")

    stop_event = threading.Event()

    # reader thread: listens for incoming messages and detects close
    def reader():
        try:
            while not stop_event.is_set():
                try:
                    data = ws.receive()
                except Exception as e:
                    # receive failed (client likely closed); break and cleanup
                    logging.debug(f"[WS READ] recv exception for client {client_id}: {e}")
                    break

                if data is None:
                    # connection closed from client side
                    logging.debug(f"[WS READ] None received (closed) for client {client_id}")
                    break

                # handle simple ping/pong or any incoming messages (if needed)
                try:
                    # many clients won't send anything; handle 'ping' raw string for compatibility
                    if isinstance(data, str) and data.strip().lower() == 'ping':
                        try:
                            ws.send('pong')
                        except Exception:
                            pass
                    else:
                        logging.debug(f"[WS INCOMING] client {client_id}: {data}")
                except Exception as e:
                    logging.debug(f"[WS HANDLE] error processing incoming message from {client_id}: {e}")
        finally:
            stop_event.set()

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    # server-side keepalive ping: regular small messages to prevent Heroku idle timeout (H15)
    try:
        while not stop_event.is_set():
            try:
                # send a lightweight ping message every 20 seconds
                ws.send(json.dumps({"type": "ping", "ts": int(time.time())}))
            except Exception as e:
                logging.debug(f"[WS PING] send failed for client {client_id}: {e}")
                break

            # sleep in small increments so we can exit quickly when stop_event set
            for _ in range(20):
                if stop_event.is_set():
                    break
                time.sleep(1)
    except Exception as e:
        logging.debug(f"[WS MAIN LOOP] error for client {client_id}: {e}")
    finally:
        # cleanup
        stop_event.set()
        try:
            reader_thread.join(timeout=1.0)
        except Exception:
            pass
        with clients_lock:
            try:
                connected_clients.remove(ws)
            except ValueError:
                pass
        logging.info(f"[SERVER] Client Disconnected. Total: {len(connected_clients)} (client_id={client_id})")

def broadcast_raw(raw_data):
    """
    Sends the exact server response (raw_data) to all connected WebSocket clients
    and then forwards the same exact data to the configured Telegram chat using raw HTTP API.
    """
    # Prepare payload as exact JSON string representation of the received data
    try:
        payload_str = json.dumps(raw_data, ensure_ascii=False)
    except Exception:
        # Fallback: best-effort string conversion
        payload_str = str(raw_data)

    dead = []
    sent_count = 0
    with clients_lock:
        for client in list(connected_clients):
            try:
                # send the exact JSON string — clients expecting JSON can parse it back to original structure
                client.send(payload_str)
                sent_count += 1
            except Exception as e:
                logging.debug(f"[BROADCAST_RAW] failed to send to client {id(client)}: {e}")
                dead.append(client)

        # cleanup dead clients
        for d in dead:
            try:
                connected_clients.remove(d)
            except ValueError:
                pass

    if sent_count:
        logging.info(f"[BROADCAST_RAW] Sent raw payload to {sent_count} clients")
    else:
        logging.info(f"[BROADCAST_RAW] No active clients to send raw payload")

    # Now forward the exact payload to Telegram using raw HTTP API
    try:
        text_to_send = payload_str
        # Telegram has a message length limit (~4096). Truncate if necessary to avoid errors.
        if isinstance(text_to_send, str) and len(text_to_send) > 4000:
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
            logging.info(f"[TELEGRAM] Forwarded raw payload to chat {TELEGRAM_CHAT_ID}")
        else:
            logging.error(f"[TELEGRAM] Failed to forward raw payload: {resp.status_code} {resp.text[:300]}")
    except Exception as e:
        logging.error(f"[TELEGRAM] Exception while forwarding raw payload: {e}")

def broadcast_code(code):
    """Sends the code to all connected WebSocket clients (thread-safe)."""
    payload = json.dumps({
        "type": "stake_bonus_code",
        "code": code,
        "source": "heroku_relay",
        "ts": int(time.time())
    })

    dead = []
    sent_count = 0
    with clients_lock:
        # iterate over a copy to avoid modification during iteration
        for client in list(connected_clients):
            try:
                client.send(payload)
                sent_count += 1
            except Exception as e:
                logging.debug(f"[BROADCAST] failed to send to client {id(client)}: {e}")
                dead.append(client)

        # cleanup dead clients
        for d in dead:
            try:
                connected_clients.remove(d)
            except ValueError:
                pass

    if sent_count:
        logging.info(f"[BROADCAST] Sent code '{code}' to {sent_count} clients")
    else:
        logging.info(f"[BROADCAST] No active clients to send code '{code}'")

# ==========================================
# TOKEN MANAGER CLASS
# ==========================================

class TokenManager:
    def __init__(self):
        self.tokens = []
        # Provided token (kept as-is)
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

        # Use polling transport only to avoid dependency on websocket-client
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

        # Generic message event
        @self.sio.on('message')
        def on_message(data):
            try:
                self.handle_socket_message(data)
            except Exception as e:
                logging.debug(f"[BOT] error handling message: {e}")

        # Some upstreams use custom event names; add a direct handler
        @self.sio.on('sub_code_v2')
        def on_sub_code_v2(data):
            # If server emits this event with embedded structure, handle it
            try:
                self.handle_socket_message({'type': 'sub_code_v2', 'msg': data})
            except Exception as e:
                logging.debug(f"[BOT] error handling sub_code_v2: {e}")

        # Fallback for any event to inspect raw payloads
        @self.sio.on('*')
        def catch_all(event, data):
            # socketio wildcard support requires server side; keep safe
            logging.debug(f"[BOT] wildcard event {event} data={data}")

    def handle_socket_message(self, data):
        """
        Handle incoming socket messages (both 'message' and custom events).
        We expect a structure that contains 'type' / 'msg' / 'code'.
        """
        if not data:
            return

        # If data is string, try parse JSON
        original_raw = data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                # Not JSON — forward the raw string as-is to websocket clients and telegram
                logging.debug(f"[BOT] non-json message received (forwarding raw string)")
                try:
                    # broadcast exact raw string by wrapping as plain string (so clients receive exactly what server sent)
                    broadcast_raw(original_raw)
                except Exception as e:
                    logging.debug(f"[BOT] error broadcasting non-json raw string: {e}")
                return

        # If event is 'sub_code_v2' inside message
        try:
            typ = data.get('type') if isinstance(data, dict) else None
            # some payloads might be nested: { 'msg': { 'code': '...' }, 'type': 'sub_code_v2' }
            if typ == 'sub_code_v2' or (isinstance(data.get('msg'), dict) and 'code' in data.get('msg')):
                msg = data.get('msg', {})
                code = None
                if isinstance(msg, dict):
                    code = msg.get('code') or (msg.get('data') and msg['data'].get('code'))
                # fallback to top-level code
                if not code:
                    code = data.get('code')

                # First: forward the exact server response (the unmodified parsed JSON) to sockets + Telegram
                try:
                    broadcast_raw(data)
                except Exception as e:
                    logging.debug(f"[BOT] error broadcasting raw data: {e}")

                if code:
                    code = str(code).strip()
                    logging.info(f"[RECEIVED] Code: {code}")
                    # Broadcast code-specific payload to external websocket clients as before
                    broadcast_code(code)
                else:
                    logging.debug(f"[BOT] received sub_code_v2 without code: {data}")
            else:
                # Not a code event — forward the exact server payload to sockets + Telegram for debugging/visibility
                try:
                    broadcast_raw(data)
                except Exception as e:
                    logging.debug(f"[BOT] error broadcasting non-code raw data: {e}")
                # Not a code event — log for debugging
                logging.debug(f"[BOT] received non-code socket message: {data}")
        except Exception as e:
            logging.debug(f"[BOT] error parsing incoming socket message: {e}")

    def connect_to_server(self):
        """
        Authenticate to the upstream API and then connect via socketio client.
        Uses HTTP-based polling transport (Engine.IO polling) to avoid requiring websocket-client.
        """
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
                logging.error(f"[BOT] Auth failed: {auth_response.status_code} - {auth_response.text[:200]}")
                return

            # upstream might return { "data": "<token>" } or more structured payload
            resp_json = auth_response.json()
            auth_token = None
            if isinstance(resp_json, dict):
                auth_token = resp_json.get('data') or resp_json.get('token') or resp_json.get('auth')
            if not auth_token:
                logging.error(f"[BOT] Unexpected auth response: {resp_json}")
                return

            # Connect using polling transport — robust in environments without websocket-client
            try:
                self.sio.connect(
                    self.config['server_url'],
                    auth={
                        'token': auth_token,
                        'version': self.config['version'],
                        'locale': self.config['locale']
                    },
                    transports=['polling'],  # force polling to avoid websocket-client dependency
                    namespaces=['/']  # connect default namespace
                )
            except Exception as e:
                logging.error(f"[BOT ERROR] socketio connect failed: {e}")
                with self.lock:
                    self.connected = False
                return

            # After connect, optionally emit a subscribe/auth event based on upstream expectations
            try:
                # Some servers expect an 'auth' emit after connect
                self.sio.emit('auth', {'token': auth_token, 'username': self.config['username']})
            except Exception as e:
                logging.debug(f"[BOT] emit auth failed: {e}")

            with self.lock:
                self.connected = True

        except Exception as e:
            logging.error(f"[BOT ERROR] Connection failed during auth/connect: {e}")
            with self.lock:
                self.connected = False

    def start_heartbeat(self):
        def heartbeat():
            while self.running:
                time.sleep(25)
                try:
                    if self.sio and self.sio.connected:
                        # Use engine-level ping by emitting a small event — some servers expect 'ping' events
                        try:
                            self.sio.emit('ping_from_bot', {'ts': int(time.time())})
                        except Exception:
                            # fallback to engineio ping (socketio ping/pong handled internally)
                            pass
                except Exception as e:
                    logging.debug(f"[BOT] heartbeat error: {e}")
        threading.Thread(target=heartbeat, daemon=True).start()

    def run(self):
        """Main loop for the bot"""
        # launch heartbeat
        self.start_heartbeat()

        # attempt initial connect
        self.connect_to_server()
        retry_backoff = 5

        while self.running:
            try:
                with self.lock:
                    is_connected = self.connected and getattr(self.sio, 'connected', False)

                if not is_connected:
                    logging.info("[BOT] Not connected — attempting reconnect")
                    try:
                        self.connect_to_server()
                    except Exception as e:
                        logging.debug(f"[BOT] reconnect attempt failed: {e}")

                    # backoff to avoid tight loop
                    time.sleep(retry_backoff)
                    retry_backoff = min(60, retry_backoff * 2)
                else:
                    # reset backoff on successful connection
                    retry_backoff = 5
                    # keep loop light — socketio client runs its internal background threads
                    time.sleep(1)
            except KeyboardInterrupt:
                logging.info("[BOT] KeyboardInterrupt received — stopping")
                self.running = False
            except Exception as e:
                logging.debug(f"[BOT] main loop exception: {e}")
                time.sleep(2)

        # clean shutdown
        try:
            if self.sio and self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass

# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # 1. Start the Bot in a background thread
    bot = CodeDisplayDashboard()

    bot_thread = threading.Thread(target=bot.run, name="CodeDisplayDashboard", daemon=True)
    bot_thread.start()

    # 2. Start the Flask Server (Local Testing Only)
    # Heroku uses Gunicorn to run 'app' directly, so this block only runs on PC
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"[SERVER] Starting Flask server on port {port}")
    # use threaded=True to allow concurrent Sock handlers; disable reloader to avoid double threads in dev
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
