import os
import sys
import subprocess
import importlib
import logging
import urllib.parse
import re

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
install_and_import("pyrogram", "pyrogram")
install_and_import("tgcrypto", "tgcrypto")  # Optimization for Pyrogram

# --- MAIN IMPORTS ---
import requests
from pyrogram import Client, filters
from pyrogram.enums import MessageMediaType

# --- CONFIGURATION ---
ASSISTANT_SESSION = "AQHDLbkAnMM3bSPaxw0LKc6QyEJsXLLyHClFwzUHvi2QjAyqDGmBs-eePhG42807v0N_JlLLxUUHoKDqEKkkLyPblSrXfLip0EMsF8zgYdr8fniTLdRhvvKAppwGiSoVLJKhmNcEGYSqgsX8BkEHoArrMH3Xxey1zCiUsmDOY7O4xD35g-KJvaxrMgMiSj1kfdYZeqTj7ZVxNR2G4Uc-LNoocYjSQo67GiydC4Uki1-_-yhYkg3PGn_ge1hmTRWCyFEggvagGEymQQBSMnUS_IonAODOWMZtpk5DP-NERyPgE4DJmLn2LCY8fuZXF-A68u9DrEClFI7Pq9gncMvmqbhsu0i0ZgAAAAHp6LDMAA"
TARGET_CHAT_ID = 7618467489
BACKEND_URL = "https://winna-code-d844c5a1fd4e.herokuapp.com/manual-broadcast"
LLM_API_BASE = "https://kustx.kustbotsweb.workers.dev/api"

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize the Client
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
        # explicitly telling it to map Title -> Code and Value -> Number suffix
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
            # This happens if LLM missed the number. Usually better to submit partial than broken.
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
    """
    if not code: return

    logger.info(f"✅✅✅ FINAL CODE TO SEND: {code} ✅✅✅")
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

# --- HANDLER 1: DEBUG LOGGER (Captures EVERYTHING from target chat) ---
@assistant.on_message(filters.chat(TARGET_CHAT_ID), group=2)
async def debug_logger(client, message):
    """
    This handler runs for every message in the chat to prove connectivity.
    """
    try:
        msg_type = message.media if message.media else "TEXT"
        logger.info(f"--- DEBUG: Message Received ---")
        logger.info(f"Chat ID: {message.chat.id}")
        logger.info(f"Message ID: {message.id}")
        logger.info(f"Type: {msg_type}")
        if message.text:
            logger.info(f"Content: {message.text[:50]}...")
        elif message.caption:
            logger.info(f"Caption: {message.caption[:50]}...")
        logger.info("-------------------------------")
    except Exception as e:
        logger.error(f"Debug logger error: {e}")

# --- HANDLER 2: TEXT/CAPTION PROCESSOR (Solves Puzzles via LLM) ---
@assistant.on_message(filters.chat(TARGET_CHAT_ID) & (filters.text | filters.caption), group=0)
async def handle_text_puzzles(client, message):
    text = message.text or message.caption
    if not text: return

    # Check for keywords indicating a puzzle code (e.g., underscores, "BONUS CODE")
    if "_" in text and ("BONUS CODE" in text.upper() or "code" in text.lower()):
        logger.info(f"🧩 Detected potential puzzle code in message {message.id}. Invoking LLM...")
        
        solved_code = solve_code_with_llm(text)
        
        if solved_code:
            logger.info(f"🧠 LLM Solved Code: {solved_code}")
            await send_to_backend(solved_code)
        else:
            logger.warning("⚠️ LLM could not solve the code.")

# --- HANDLER 3: MEDIA PROCESSOR (Video Filenames) ---
@assistant.on_message(filters.chat(TARGET_CHAT_ID) & (filters.video | filters.animation), group=1)
async def handle_media_dm(client, message):
    logger.info(f"Media (Video/Animation) detected in chat: {message.chat.id}. Checking filename...")
    
    # Determine if it's a video or animation object
    media_obj = message.video if message.video else message.animation
    
    # Get the file name from the media object
    file_name = getattr(media_obj, "file_name", None)
    
    logger.info(f"Processing filename: {file_name}")
    final_code = extract_code_from_filename(file_name)

    # --- Final Result Handling ---
    if final_code:
        await send_to_backend(final_code)
    else:
        # Fallback: if filename fails, the caption might have a puzzle code handled by Handler 2
        logger.warning("⚠️ No code found in filename.")

if __name__ == "__main__":
    print(f"Assistant is running and listening to chat {TARGET_CHAT_ID}...")
    assistant.run()
