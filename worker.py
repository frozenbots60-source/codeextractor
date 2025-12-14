import requests
import socketio
import json
import time
import threading
from datetime import datetime
import sys
import urllib3
from concurrent.futures import ThreadPoolExecutor
import logging
import os

# Configure minimal logging - only log codes received and sent
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    handlers=[
        logging.FileHandler('codes.log'),
        logging.StreamHandler()
    ]
)

# Initialize urllib3 pool manager
http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=2, read=8),
)

class CodeDisplayDashboard:
    def __init__(self):
        self.config = {
            'server_url': 'https://code.hh123.site',
            'stake_url': 'https://stake.com',
            'stake_referer': 'https://stake.com/settings/offers',
            'username': 'Iqooz9KK',
            'version': '6.3.0',
            'locale': 'en',
            'debug': False  # Disabled debug
        }
        
        # API configuration
        self.api_url = "https://serene-coast-95979-9dabd2155d8d.herokuapp.com/send"
        
        self.socket_client = None
        self.auth_token = None
        self.received_codes = []
        self.token_manager = None
        self.connected = False
        self.running = True
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        
        # Initialize token manager
        self.token_manager = TokenManager()
        self.token_manager.initialize()
        
        # Initialize socket client with proper configuration
        self.sio = socketio.Client(
            logger=False,  # Disabled logging
            engineio_logger=False,  # Disabled logging
            reconnection=True,
            reconnection_attempts=self.max_reconnect_attempts,
            reconnection_delay=self.reconnect_delay,
            reconnection_delay_max=30
        )
        self.setup_socket_handlers()
        
    def get_stake_headers(self):
        """Simulate CORS headers to make requests appear from stake.com"""
        return {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/json',
            'Origin': self.config['stake_url'],
            'Referer': self.config['stake_referer'],
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    
    def setup_socket_handlers(self):
        """Set up event handlers for socket.io"""
        @self.sio.event
        def connect():
            logging.info("[STATUS] Connected to server")
            self.connected = True
            self.reconnect_attempts = 0
            
        @self.sio.event
        def disconnect(data):
            logging.info("[STATUS] Disconnected from server")
            self.connected = False
            
        @self.sio.event
        def connect_error(data):
            logging.info("[STATUS] Connection error")
            self.connected = False
            
        @self.sio.on('message')
        def on_message(data):
            self.handle_socket_message(data)
    
    def send_code_to_api(self, code):
        """Send the received code to the API"""
        start = time.time()
        
        payload = {
            "type": "stake_bonus_code",
            "code": code,
            "source": "code_dashboard"
        }

        try:
            r = http.request(
                "POST",
                self.api_url,
                body=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=urllib3.util.Timeout(connect=2.0, read=6.0)
            )

            ms = round((time.time() - start) * 1000, 2)
            logging.info(f"[SENT] Code '{code}' sent to API in {ms}ms")
            
            # Save to file for backup
            with open('sent_codes.txt', 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {code}\n")
            
            return True

        except Exception as e:
            return False
    
    def handle_socket_message(self, data):
        """Handle incoming socket messages"""
        if data.get('type') == 'sub_code_v2':
            code = data['msg']['code'].strip()
            logging.info(f"[RECEIVED] Code: {code}")
            
            code_data = {
                'code': code,
                'amount': float(data['msg']['amount']) if data['msg'].get('amount') else None,
                'type': data['msg'].get('type', 'OtherDrops'),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self.received_codes.append(code_data)
            
            # Save to file for backup
            with open('received_codes.json', 'a') as f:
                f.write(json.dumps(code_data) + '\n')
            
            # Send the code to the API
            self.send_code_to_api(code)
    
    def connect_to_server(self):
        """Connect to the backend server"""
        try:
            logging.info("[STATUS] Connecting to server...")
            # First, authenticate with the server
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
                raise Exception(f"Authentication failed: {auth_response.status_code}")
            
            auth_data = auth_response.json()
            if not auth_data.get('success'):
                raise Exception(auth_data.get('message', 'Authentication failed'))
            
            self.auth_token = auth_data['data']
            
            # Connect to socket with both transports (websocket and polling)
            self.sio.connect(
                self.config['server_url'],
                auth={
                    'token': self.auth_token,
                    'version': self.config['version'],
                    'locale': self.config['locale']
                },
                transports=['websocket', 'polling']  # Allow both transports
            )
            
            logging.info("[STATUS] Listening for codes...")
            
        except Exception as e:
            self.connected = False
    
    def disconnect_from_server(self):
        """Disconnect from the server"""
        if self.sio.connected:
            self.sio.disconnect()
            self.connected = False
    
    def start_heartbeat(self):
        """Start a heartbeat thread to keep the connection alive"""
        def heartbeat():
            while self.running:
                time.sleep(30)
                if self.connected and self.sio.connected:
                    try:
                        self.sio.emit('ping')
                    except:
                        pass
        
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
    
    def run(self):
        """Main application loop"""
        # Start heartbeat
        self.start_heartbeat()
        
        # Connect to server
        self.connect_to_server()
        
        try:
            # Keep the application running
            while self.running:
                time.sleep(1)
                    
        except KeyboardInterrupt:
            pass
        except Exception:
            pass
        finally:
            self.running = False
            self.disconnect_from_server()


class TokenManager:
    """Manages Turnstile tokens"""
    
    def __init__(self):
        self.tokens = []
        self.initialized = False
        self.provided_token = '0.xVtuTFJmRfr8oQQZquxI6c7vFKFu-LUXJfCwBenBjGX3c7gT8zI51H6O9ON2fsG9ZLHcGR92dPYHUfzrlxw3Nq0-NHlEQBParVzK_PVxoQq0fXMM-XSAsYX0D4nf2e0m9Er_vaDbLj_h7VL9xSOOVQXFZcVYUwq6FuPgTfxUypq3eGG3WRELdJvWdkwHjMFo4tsLt-U-LdppK8p_yEwp3_zZ5l9DvR9LMbyXvrA2bEr0HRJIj38bmuqkU49XtTpMk9qzt3vSJIGnpUe9T5BJsHwSYVEr6AlxPifpeZ6RpeGDeN538DLZYiNcNZAZT2N1zgHb9YPTTlJGb3FM0FalWm_e9B65VoflM8MX9D7dYbBbnk632q3s6fOnXbTyR4RSWgeYePOi3wvwG8NLEPdEp3k9qXWTzegVhKwxHd3Zb6b-HE8jPbReszggHjJGqpUR9xYPkQaEhF8PjwesJJ-c3wKOpFc_4oVrSI6rVcWKLaBRFPjAqUwz4ORdC7IC2fI0lRLdMg8pzSa4yFo9XP8TCVPZfeLBCgjxhQCiU3VbSCRhayoo29-vdltJXM1LN2gC7Q2h9NUO19kcUAPE3uPR1KwUQaRcqI9yNvWuCV18vAP8jQSlGE0HbzhLi0gys7pzMBQSHy8b-IVV-5ZjOlMkGyIf1WXD0olwyyTBuH-nrHs3MKrwA9_WK4ZmdZLOrx9gHiJ29ZQXmdMNmwqknluDKwgqX6YcwWs3hoPQbb1RLdIh1cY9GSXy9YnN3W5wKFrnd_tbnnKIvgK-JWV0LtaEZz2H_HLJ10dSVFfhFB7Tw0COa-L0l79oaVJS1lXuim7zWyjtVIRLZlZ6XXHILyvhPLLTaKsofqoaCoIWh6aPnRryoviuCNRmp6aBTa9uB5MEEHPar3kUDY0qH0f-F2A9xcf8kTttwbvEQw_slFedFH4.P-HMDFrGPaI5YxbKx5D1nA.b5283118b7f141996bc245f27ab18e363aff7f79f6d228d7ff323960473cd652'
    
    def initialize(self):
        """Initialize the token manager"""
        if self.initialized:
            return
            
        self.initialized = True
        
        # Add the provided token
        self.add_provided_token()
    
    def add_provided_token(self):
        """Add the provided token to the cache"""
        token_data = {
            'token': self.provided_token,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'provided'
        }
        
        self.tokens.append(token_data)
    
    def get_token(self):
        """Get a token from the cache"""
        if self.tokens:
            return self.tokens[0]['token']
        return None
    
    def destroy(self):
        """Destroy the token manager"""
        self.tokens = []
        self.initialized = False


if __name__ == "__main__":
    # Check for required packages
    try:
        import requests
        import socketio
        import urllib3
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("Please install with: pip install requests python-socketio urllib3 websocket-client")
        sys.exit(1)
    
    # Create and run the dashboard
    dashboard = CodeDisplayDashboard()
    dashboard.run()
