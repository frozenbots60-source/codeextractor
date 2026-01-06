import os
import sys
import subprocess
import importlib
import logging

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

# Run checks for remaining essential libraries
install_and_import("requests", "requests")
install_and_import("pyrogram", "pyrogram")
install_and_import("tgcrypto", "tgcrypto")  # Optimization for Pyrogram

# --- MAIN IMPORTS ---
import requests
from pyrogram import Client, filters

# --- CONFIGURATION ---
ASSISTANT_SESSION = "AQHDLbkAnMM3bSPaxw0LKc6QyEJsXLLyHClFwzUHvi2QjAyqDGmBs-eePhG42807v0N_JlLLxUUHoKDqEKkkLyPblSrXfLip0EMsF8zgYdr8fniTLdRhvvKAppwGiSoVLJKhmNcEGYSqgsX8BkEHoArrMH3Xxey1zCiUsmDOY7O4xD35g-KJvaxrMgMiSj1kfdYZeqTj7ZVxNR2G4Uc-LNoocYjSQo67GiydC4Uki1-_-yhYkg3PGn_ge1hmTRWCyFEggvagGEymQQBSMnUS_IonAODOWMZtpk5DP-NERyPgE4DJmLn2LCY8fuZXF-A68u9DrEClFI7Pq9gncMvmqbhsu0i0ZgAAAAHp6LDMAA"
TARGET_CHAT_ID = -1002472636693
BACKEND_URL = "https://winna-code-d844c5a1fd4e.herokuapp.com/manual-broadcast"

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

# --- HANDLER 1: DEBUG LOGGER (Captures EVERYTHING from target chat) ---
@assistant.on_message(filters.chat(TARGET_CHAT_ID), group=1)
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
            logger.info(f"Content: {message.text}")
        elif message.caption:
            logger.info(f"Caption: {message.caption}")
        logger.info("-------------------------------")
    except Exception as e:
        logger.error(f"Debug logger error: {e}")

# --- HANDLER 2: MAIN MEDIA PROCESSOR (Captures VIDEO and ANIMATION) ---
@assistant.on_message(filters.chat(TARGET_CHAT_ID) & (filters.video | filters.animation), group=0)
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
        # LOG IT LOUDLY
        logger.info(f"✅✅✅ FINAL EXTRACTED CODE: {final_code} ✅✅✅")
        
        # --- SEND TO BACKEND ---
        logger.info(f"🚀 Sending code to backend: {BACKEND_URL}")
        try:
            payload = {
                "type": "code_drop",
                "code": final_code
            }
            
            # Using requests (synchronous)
            response = requests.post(BACKEND_URL, json=payload, timeout=5)
            
            if response.ok:
                logger.info(f"🚀 Backend Response: SUCCESS ({response.status_code})")
            else:
                logger.error(f"❌ Backend Error: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"❌ Could not reach backend: {e}")
    else:
        logger.warning("⚠️ No code found in filename. Ignoring media.")

if __name__ == "__main__":
    print(f"Assistant is running and listening to chat {TARGET_CHAT_ID}...")
    assistant.run()
