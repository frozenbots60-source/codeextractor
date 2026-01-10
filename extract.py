import os
import sys
import subprocess
import importlib
import logging
import urllib.parse
import re
import asyncio

# --- DEPENDENCY INSTALLER ---
# Ensures core libs are installed in a local 'temp' folder if missing
LIB_PATH = os.path.join(os.getcwd(), "temp")

# Add the temp path to system path immediately so imports work
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

def install_and_import(package_name, import_name):
    """
    Checks if a module is importable. If not, installs it to LIB_PATH.
    """
    try:
        importlib.import_module(import_name)
    except ImportError:
        print(f"⚠️ {import_name} not found. Installing {package_name} to {LIB_PATH}...")
        try:
            os.makedirs(LIB_PATH, exist_ok=True)
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                "--target", LIB_PATH, 
                package_name
            ])
            importlib.invalidate_caches()
            importlib.import_module(import_name)
            print(f"✅ {package_name} installed successfully.")
        except Exception as e:
            print(f"❌ Failed to install {package_name}: {e}")

# Run checks for essential libraries only (No OCR/OpenCV)
install_and_import("requests", "requests")
install_and_import("telethon", "telethon")  # Switched to Telethon

# --- MAIN IMPORTS ---
import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Message, DocumentAttributeFilename

# --- CONFIGURATION ---
# Note: You must generate a NEW StringSession for Telethon. Pyrogram sessions will not work here.
ASSISTANT_SESSION = "AQHDLbkAnMM3bSPaxw0LKc6QyEJsXLLyHClFwzUHvi2QjAyqDGmBs-eePhG42807v0N_JlLLxUUHoKDqEKkkLyPblSrXfLip0EMsF8zgYdr8fniTLdRhvvKAppwGiSoVLJKhmNcEGYSqgsX8BkEHoArrMH3Xxey1zCiUsmDOY7O4xD35g-KJvaxrMgMiSj1kfdYZeqTj7ZVxNR2G4Uc-LNoocYjSQo67GiydC4Uki1-_-yhYkg3PGn_ge1hmTRWCyFEggvagGEymQQBSMnUS_IonAODOWMZtpk5DP-NERyPgE4DJmLn2LCY8fuZXF-A68u9DrEClFI7Pq9gncMvmqbhsu0i0ZgAAAAHp6LDMAA"
API_ID = 29568441
API_HASH = "b32ec0fb66d22da6f77d355fbace4f2a"

TARGET_CHAT_IDS = [-1002472636693, -1003594241974]
NOTIFICATION_USER_ID = 7618467489
BACKEND_URL = "https://winna-code-d844c5a1fd4e.herokuapp.com/manual-broadcast"
LLM_API_BASE = "https://kustx.kustbotsweb.workers.dev/api"

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize the Client (Telethon)
# We use StringSession so we don't need a .session file
try:
    assistant = TelegramClient(StringSession(ASSISTANT_SESSION), API_ID, API_HASH)
except Exception as e:
    logger.error(f"Failed to initialize Telethon. Ensure ASSISTANT_SESSION is a valid Telethon string session: {e}")
    sys.exit(1)

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
        
        # Basic validation: ensure it's not empty and looks alphanumeric
        if possible_code and possible_code.isalnum():
            return possible_code
            
    return None

def solve_code_with_llm(message_text):
    """
    Sends the text to the LLM API to fill in the missing characters.
    """
    try:
        # Construct a PROMPT engineered for this specific format
        prompt = (
            f"You are a code solver for 'Winna' promotions. "
            f"The user provides text with a puzzle code containing underscores (e.g., 'sp__-t__e-_').\n"
            f"RULES:\n"
            f"1. The code often matches the TITLE of the post (e.g., 'Spin Time' -> 'spin-time').\n"
            f"2. The code often ends with the DOLLAR VALUE amount (e.g., '$9 value' -> code ends in '-9').\n"
            f"3. You MUST fill in ALL underscores to complete the word.\n"
            f"4. Output ONLY the final completed code. No other text.\n\n"
            f"Example:\n"
            f"Input: 'Spin Time... $9 value... sp__-t__e-_'\n"
            f"Output: spin-time-9\n\n"
            f"Real Input:\n'''{message_text}'''\n\n"
            f"Output:"
        )
        
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"{LLM_API_BASE}?q={encoded_prompt}"
        
        logger.info("🧠 Asking LLM to solve the code...")
        response = requests.get(url, timeout=10)
        
        if response.ok:
            data = response.json()
            llm_response = data.get("raw", {}).get("response", "").strip()
            
            # Cleanup
            clean_code = llm_response.replace("`", "").replace("'", "").replace('"', "").strip()
            
            # If it returns a sentence, try to grab the last "word"
            if " " in clean_code:
                parts = clean_code.split()
                clean_code = parts[-1] 
            
            # Remove trailing punctuation (often LLM adds a period)
            clean_code = clean_code.rstrip(".")
            
            # Safety check: if code ends with a hyphen (e.g. 'spinte-'), try to strip it
            if clean_code.endswith("-"):
                clean_code = clean_code.rstrip("-")

            return clean_code
        else:
            logger.error(f"❌ LLM API Error: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ LLM Request Failed: {e}")
        return None

async def send_to_backend(code):
    """
    Helper function to send the extracted/solved code to the backend.
    AND notifies the user via DM.
    """
    if not code: return

    logger.info(f"✅✅✅ FINAL CODE FOUND: {code} ✅✅✅")
    
    # --- NOTIFICATION STEP ---
    try:
        logger.info(f"🔔 Notifying user {NOTIFICATION_USER_ID}...")
        await assistant.send_message(
            entity=NOTIFICATION_USER_ID,
            message=f"🚀 **New Code Found:** `{code}`"
        )
    except Exception as e:
        logger.error(f"❌ Failed to notify user: {e}")

    # --- BACKEND STEP ---
    logger.info(f"🚀 Sending code to backend: {BACKEND_URL}")
    try:
        payload = {
            "type": "code_drop",
            "code": code
        }
        
        # Using requests (synchronous)
        response = requests.post(BACKEND_URL, json=payload, timeout=5)
        
        if response.ok:
            logger.info(f"🚀 Backend Response: SUCCESS ({response.status_code})")
        else:
            logger.error(f"❌ Backend Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"❌ Could not reach backend: {e}")

# --- MESSAGE PROCESSING LOGIC ---
async def process_message(message: Message):
    """
    Unified function to process incoming messages (Text or Media).
    """
    if not message: return
    
    # 1. DEBUG LOGGING
    try:
        msg_type = "MEDIA" if message.media else "TEXT"
        logger.info(f"--- DEBUG: Message Received ---")
        logger.info(f"Chat ID: {message.chat_id}")
        logger.info(f"Message ID: {message.id}")
        logger.info(f"Type: {msg_type}")
        if message.text:
            logger.info(f"Content: {message.text[:50]}...")
        logger.info("-------------------------------")
    except Exception as e:
        logger.error(f"Debug logger error: {e}")

    # 2. CHECK FOR TEXT PUZZLES
    text_content = message.text or "" # Telethon puts caption in .text automatically usually, or use .message
    if not text_content and message.message:
        text_content = message.message

    if text_content:
        # Check for keywords indicating a puzzle code
        if "_" in text_content and ("BONUS CODE" in text_content.upper() or "code" in text_content.lower()):
            logger.info(f"🧩 Detected potential puzzle code in message {message.id}. Invoking LLM...")
            solved_code = solve_code_with_llm(text_content)
            if solved_code:
                logger.info(f"🧠 LLM Solved Code: {solved_code}")
                await send_to_backend(solved_code)
            else:
                logger.warning("⚠️ LLM could not solve the code.")

    # 3. CHECK FOR MEDIA FILENAMES
    if message.file:
        file_name = message.file.name # Telethon convenience property
        if file_name:
            logger.info(f"Processing filename: {file_name}")
            final_code = extract_code_from_filename(file_name)
            if final_code:
                await send_to_backend(final_code)
            else:
                logger.warning("⚠️ No code found in filename.")

# --- LONG POLLING LOOP ---
async def long_poll_channels():
    logger.info("🔄 Starting Long Polling Loop (Interval: 0.5s)...")
    
    # Dictionary to store the last known message ID for each channel
    last_message_ids = {}

    # Initial Pass: Get the current latest message ID to establish a baseline
    # We do NOT process these, just mark them as "seen" so we only process NEW ones
    for chat_id in TARGET_CHAT_IDS:
        try:
            # limit=1 gets the newest message
            messages = await assistant.get_messages(chat_id, limit=1)
            if messages:
                last_message_ids[chat_id] = messages[0].id
                logger.info(f"✅ Initialized {chat_id} at Message ID: {messages[0].id}")
            else:
                last_message_ids[chat_id] = 0
                logger.info(f"✅ Initialized {chat_id} (No messages found)")
        except Exception as e:
            logger.error(f"❌ Failed to initialize chat {chat_id}: {e}")
            last_message_ids[chat_id] = 0

    while True:
        for chat_id in TARGET_CHAT_IDS:
            try:
                # Fetch the single latest message
                messages = await assistant.get_messages(chat_id, limit=1)
                
                if messages:
                    latest_msg = messages[0]
                    current_last_id = last_message_ids.get(chat_id, 0)

                    # If the latest message ID is greater than what we have stored, it's new
                    if latest_msg.id > current_last_id:
                        logger.info(f"🆕 New Message detected in {chat_id} (ID: {latest_msg.id})")
                        
                        # PROCESS THE MESSAGE
                        await process_message(latest_msg)
                        
                        # Update the last seen ID
                        last_message_ids[chat_id] = latest_msg.id
            
            except Exception as e:
                logger.error(f"⚠️ Polling error for {chat_id}: {e}")

        # Wait 0.5 seconds before next poll cycle
        await asyncio.sleep(0.5)

async def main():
    print(f"Assistant is connecting...")
    await assistant.start()
    print("✅ Assistant Connected.")
    print(f"📡 Polling Chats: {TARGET_CHAT_IDS}")
    
    # Start the polling loop
    await long_poll_channels()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
