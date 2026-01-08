import os
import sys
import subprocess
import importlib
import logging
import asyncio

# --- DEPENDENCY INSTALLER ---
# This ensures OCR and other libs are installed in a local 'temp' folder if missing
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
            # Create the temp directory if it doesn't exist
            os.makedirs(LIB_PATH, exist_ok=True)
            # Install package to the specific target directory
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                "--target", LIB_PATH,
                package_name
            ])
            # Refresh import mechanism
            importlib.invalidate_caches()
            # Try importing again to verify
            importlib.import_module(import_name)
            print(f"✅ {package_name} installed successfully.")
        except Exception as e:
            print(f"❌ Failed to install {package_name}: {e}")

# Run checks and installs
install_and_import("requests", "requests")
install_and_import("pyrogram", "pyrogram")
install_and_import("tgcrypto", "tgcrypto")  # Optimization for Pyrogram
install_and_import("pytesseract", "pytesseract")
install_and_import("numpy", "numpy")
# Use opencv-python-headless for servers (smaller, no GUI dependencies)
install_and_import("opencv-python-headless", "cv2")

# --- MAIN IMPORTS ---
import cv2
import pytesseract
import requests
from pyrogram import Client, filters
from pyrogram.enums import MessageMediaType

# --- CONFIGURATION ---
ASSISTANT_SESSION = "AQHDLbkAnMM3bSPaxw0LKc6QyEJsXLLyHClFwzUHvi2QjAyqDGmBs-eePhG42807v0N_JlLLxUUHoKDqEKkkLyPblSrXfLip0EMsF8zgYdr8fniTLdRhvvKAppwGiSoVLJKhmNcEGYSqgsX8BkEHoArrMH3Xxey1zCiUsmDOY7O4xD35g-KJvaxrMgMiSj1kfdYZeqTj7ZVxNR2G4Uc-LNoocYjSQo67GiydC4Uki1-_-yhYkg3PGn_ge1hmTRWCyFEggvagGEymQQBSMnUS_IonAODOWMZtpk5DP-NERyPgE4DJmLn2LCY8fuZXF-A68u9DrEClFI7Pq9gncMvmqbhsu0i0ZgAAAAHp6LDMAA"

# Ensure IDs are integers
TARGET_CHAT_IDS = [-1002472636693, 7618467489]

BACKEND_URL = "https://winna-code-d844c5a1fd4e.herokuapp.com/manual-broadcast"

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize the Client
assistant = Client("assistant_account", session_string=ASSISTANT_SESSION)

# --- CUSTOM FILTER TO FIX "PEER ID INVALID" CRASH ---
# This bypasses Pyrogram's internal peer resolution by simply checking the ID integer.
async def target_chat_filter(_, __, message):
    if not message.chat:
        return False
    return message.chat.id in TARGET_CHAT_IDS

target_chat = filters.create(target_chat_filter)

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

        # ROI: Focus on Center-Right area based on your previous image
        y_start = int(height * 0.4)
        y_end = int(height * 0.7)
        x_start = int(width * 0.4)
        x_end = int(width * 0.95)

        cropped_frame = frame[y_start:y_end, x_start:x_end]

        # Convert to grayscale
        gray = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2GRAY)

        # Thresholding (White text on dark background)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

        # OCR
        try:
            text = pytesseract.image_to_string(thresh, config='--psm 6').strip()
            # Clean text
            text = text.replace(" ", "").replace("\n", "")
            if text:
                extracted_text = text
        except Exception as e:
            logger.error(f"OCR Library Error: {e}")

    cap.release()
    return extracted_text

# --- HANDLER 1: DEBUG LOGGER (Captures EVERYTHING from target chats) ---
@assistant.on_message(target_chat, group=1)
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
@assistant.on_message(target_chat & (filters.video | filters.animation), group=0)
async def handle_media_dm(client, message):
    logger.info(f"Media (Video/Animation) detected in chat: {message.chat.id}. Starting processing...")

    # Determine if it's a video or animation object
    media_obj = message.video if message.video else message.animation

    file_name = getattr(media_obj, "file_name", None)
    final_code = None

    # --- STEP 1: Try Filename Extraction ---
    logger.info(f"Processing filename: {file_name}")
    filename_code = extract_code_from_filename(file_name)

    if filename_code:
        logger.info(f"SUCCESS: Code found from filename: {filename_code}")
        final_code = filename_code
    else:
        logger.info("Filename extraction failed or format not matched. Proceeding to OCR...")

        # --- STEP 2: OCR Extraction ---
        file_path = None
        try:
            logger.info("Downloading media for OCR...")
            file_path = await message.download()
            logger.info("Download complete. Starting OCR processing...")

            ocr_code = extract_code_via_ocr(file_path)

            if ocr_code:
                logger.info(f"SUCCESS: Code found via OCR: {ocr_code}")
                final_code = ocr_code
            else:
                logger.warning("FAILED: OCR could not detect the code.")

        except Exception as e:
            logger.error(f"Error during OCR processing: {e}")

        finally:
            # Cleanup
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info("Cleaned up downloaded file.")
                except Exception:
                    pass

    # --- Final Result Handling ---
    if final_code:
        # LOG IT LOUDLY
        logger.info(f"✅✅✅ FINAL EXTRACTED CODE: {final_code} ✅✅✅")

        # REPLY TO THE CHAT SO YOU SEE IT IN TELEGRAM
        try:
            await message.reply_text(f"✅ Extracted Code: `{final_code}`")
        except Exception as e:
            logger.error(f"Could not reply to chat: {e}")

        # --- SEND TO BACKEND ---
        logger.info(f"🚀 Sending code to backend: {BACKEND_URL}")
        try:
            payload = {
                "type": "code_drop",
                "code": final_code
            }

            # Use run_in_executor to avoid blocking the async loop with requests
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: requests.post(BACKEND_URL, json=payload, timeout=5))

            if response.ok:
                logger.info(f"🚀 Backend Response: SUCCESS ({response.status_code})")
                try:
                    await message.reply_text(f"🚀 Code forwarded to Backend successfully!")
                except: pass
            else:
                logger.error(f"❌ Backend Error: {response.status_code} - {response.text}")
                try:
                    await message.reply_text(f"❌ Backend failed: {response.status_code}")
                except: pass

        except Exception as e:
            logger.error(f"❌ Could not reach backend: {e}")
            try:
                await message.reply_text(f"❌ Network Error sending to Backend")
            except: pass

if __name__ == "__main__":
    print(f"Assistant is running and listening to chats {TARGET_CHAT_IDS}...")
    assistant.run()
