import os
import time
import json
import asyncio
import tempfile
import numpy as np
import cv2
import subprocess
import re
from pyrogram import Client, filters, idle
from rapidocr_onnxruntime import RapidOCR
import urllib3
from concurrent.futures import ThreadPoolExecutor

http = urllib3.PoolManager(
    num_pools=20,
    maxsize=50,
    block=False,
    timeout=urllib3.util.Timeout(connect=2, read=8),
)

# =======================================================
# CONFIG
# =======================================================
STRING_SESSION = "AQE1hZwAsACLds_UWzxBuXJrUqtxBHKWVN82FiIvZiNjcy-EtswSj3isV5Mhhjnerq5FITxUcynX0CP9IENrbxGU_kF8aHzNMELGIiser2uzf9zu9xPlHShb-eS0AqhYUogG2pnR5Pypurj6RgZA15q-MEigjhwoQBVLgQYhbWlb8fZQ7t_rNZalupbT9dZQoDYsEhI7Bu-ReTsNNrB8UvaCBzJVSQ4bm8BoMJUPKUzXCY1glpLEDKW72DKgTGEgOzqhZBSuEG0O17EjCFysRnngmqaf2L4Epya6eLjrDj2KqzkUkDuEmn6AMczvLkG7JolrsFzqpuOn3X7d6ZwMJr3ErZapGwAAAAHpJUc8AA"  # <<< PUT YOUR STRING SESSION HERE

CHANNELS = [
    -1003238942328,   # <<< CHANNEL 1
    -1001977383442    # <<< CHANNEL 2
]

TARGET_SECOND = 4
API_URL = "https://stake-codes-b8bf1e990ec3.herokuapp.com/send"

BOT_TOKEN = "8537156061:AAHIqcg2eaRXBya1ImmuCerK-EMd3V_1hnI"
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_DL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

FORWARD_TO = "kustcodebot"
# =======================================================

ocr_model = RapidOCR()

def log(msg, start):
    ms = round((time.time() - start) * 1000, 2)
    print(f"[{ms} ms] {msg}")


# =======================================================
# FRAME EXTRACTION (FAST MJPEG)
# =======================================================
def extract_frame(video_path, start):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "quiet",
        "-ss", str(TARGET_SECOND),
        "-i", video_path,
        "-vf", "scale=iw/2:ih/2",
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    jpg_data, _ = proc.communicate(timeout=3)
    return jpg_data


# =======================================================
# OCR (CROPPED REGION)
# =======================================================
def ocr_fast(jpg_bytes):
    img = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    h = img.shape[0]
    crop = img[int(h * 0.65):h, :]

    blocks, _ = ocr_model(crop)

    best = ""
    best_conf = 0
    for coords, text, conf in blocks:
        cleaned = text.strip()
        if re.fullmatch(r"[A-Za-z0-9]{6,20}", cleaned) and conf > best_conf:
            best = cleaned
            best_conf = conf

    return best


# =======================================================
# GET FILE PATH + SIZE
# =======================================================
def get_file_info(file_id):
    r = http.request(
        "GET",
        f"{BOT_API}/getFile",
        fields={"file_id": file_id}
    )
    data = json.loads(r.data.decode("utf-8"))
    if not data.get("ok"):
        return None, None
    file_path = data["result"]["file_path"]
    file_size = data["result"].get("file_size", None)
    return file_path, file_size


# =======================================================
# 🔥 DOWNLOAD LAST 4–5 seconds OF VIDEO VIA RANGE REQUEST
# =======================================================
def download_tail(file_path, file_size, start):
    dl_url = f"{BOT_DL}/{file_path}"

    approx_bytes_per_second = 150000
    tail_bytes = approx_bytes_per_second * 5

    start_byte = max(file_size - tail_bytes, 0)

    headers = {
        "Range": f"bytes={start_byte}-",
        "Connection": "keep-alive",
        "TE": "identity",
        "Accept-Encoding": "identity"
    }

    log(f"Requesting RANGE bytes={start_byte}-{file_size}", start)

    # First try: normal range request
    r = http.request(
        "GET",
        dl_url,
        headers=headers,
        preload_content=False
    )

    # If Telegram respects range (206), just save it normally
    if r.status == 206:
        temp_fp = os.path.join(tempfile.gettempdir(), f"tail_{int(time.time())}.mp4")
        with open(temp_fp, "wb") as f:
            for chunk in r.stream(65536):
                f.write(chunk)

        r.release_conn()
        log("Partial download OK (206)", start)
        return temp_fp

    # If CDN IGNORED RANGE, we FORCE fast fallback using PARALLEL DOWNLOAD
    log(f"CDN IGNORED RANGE → status={r.status} → forcing parallel fallback...", start)
    r.release_conn()

    # ===========================
    # PARALLEL DOWNLOADING LOGIC
    # ===========================
    CHUNKS = 4
    CHUNK_SIZE = file_size // CHUNKS

    def fetch_part(i):
        # Compute byte range for part i
        part_start = i * CHUNK_SIZE
        part_end = part_start + CHUNK_SIZE - 1

        if i == CHUNKS - 1:
            part_end = file_size - 1  # last chunk ends at EOF

        part_headers = {
            "Range": f"bytes={part_start}-{part_end}",
            "Connection": "keep-alive",
            "Accept-Encoding": "identity"
        }

        rr = http.request(
            "GET",
            dl_url,
            headers=part_headers,
            preload_content=True
        )

        if rr.status not in (200, 206):
            log(f"Chunk {i} returned status {rr.status}", start)

        return (i, rr.data)

    # Download chunks in parallel
    with ThreadPoolExecutor(max_workers=CHUNKS) as ex:
        parts = list(ex.map(fetch_part, range(CHUNKS)))

    # Sort by chunk index before merging
    parts.sort(key=lambda x: x[0])

    temp_fp = os.path.join(tempfile.gettempdir(), f"tail_{int(time.time())}.mp4")

    # Assemble file sequentially
    with open(temp_fp, "wb") as f:
        for idx, data in parts:
            f.write(data)

    log("Parallel download complete", start)
    return temp_fp


# =======================================================
# MAIN BOT
# =======================================================
async def start_bot():
    app = Client("stake-worker", session_string=STRING_SESSION)

    @app.on_message(filters.chat(CHANNELS) & (filters.video | filters.document))
    async def handler(client, message):
        start = time.time()
        log("📩 New video", start)

        fwd = await message.forward(FORWARD_TO)

        file_id = fwd.video.file_id if fwd.video else fwd.document.file_id

        # get file path + file size
        file_path, file_size = get_file_info(file_id)
        if not file_path or not file_size:
            log("getFile failed", start)
            return

        # download only last 5 seconds of video
        temp_video = download_tail(file_path, file_size, start)

        # extract frame
        jpg = extract_frame(temp_video, start)

        # run OCR
        code = ocr_fast(jpg)

        # send to API
        payload = {
            "type": "stake_bonus_code",
            "code": code,
            "tg_message_id": message.id
        }

        http.request(
            "POST",
            API_URL,
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"}
        )

        try:
            os.remove(temp_video)
        except:
            pass

        log("DONE", start)

    await app.start()
    print(">> Worker Started <<")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(start_bot())
