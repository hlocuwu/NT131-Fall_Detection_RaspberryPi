from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from collections import deque
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv
from google.cloud import storage
import asyncio, base64, calendar, json, os, threading, time
import cv2, numpy as np, mediapipe as mp, requests

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Skipped — TOKEN or CHAT_ID not set")
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        print("[TELEGRAM] Sent" if resp.ok else f"[TELEGRAM] Failed: {resp.status_code}")
    except Exception as e:
        print(f"[TELEGRAM] Error: {e}")

# ── App & MediaPipe ───────────────────────────────────────────────────────────
app = FastAPI()
app.mount("/custom", StaticFiles(directory="custom"), name="custom")

mp_pose    = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
pose       = mp_pose.Pose(min_detection_confidence=0.6, min_tracking_confidence=0.6)

# ── State ─────────────────────────────────────────────────────────────────────
latest_frame:   bytes | None    = None
fall_frame:     bytes | None    = None
last_fall_time: float           = 0.0
fall_counter:   int             = 0
body_angle:     str             = "front"
metrics_data:   dict            = {"cpu": 0, "memory": 0}
hip_history:    deque           = deque(maxlen=4)
fall_log:       list[datetime]  = []

frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
web_clients: set           = set()

FALL_DETECTION_FRAMES = 3
FALL_COOLDOWN         = 5

# ── Storage ───────────────────────────────────────────────────────────────────
def log_fall_event(image_bytes: bytes, timestamp: float):
    label = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(timestamp))
    try:
        bucket = storage.Client().bucket("fall-log-data")
        bucket.blob(f"fall_events/{label}.jpg").upload_from_string(image_bytes, content_type="image/jpeg")
        bucket.blob(f"fall_events/{label}.json").upload_from_string(
            json.dumps({"event": "fall_detected", "timestamp": label}, indent=2),
            content_type="application/json",
        )
        print(f"[GCS] Uploaded {label}")
    except Exception:
        os.makedirs("fall_events", exist_ok=True)
        with open(f"fall_events/{label}.jpg", "wb") as f:
            f.write(image_bytes)
        print(f"[LOCAL] Saved fall_events/{label}.jpg")

# ── Fall detection ────────────────────────────────────────────────────────────
def determine_body_orientation(lm) -> str:
    shoulder_wide = abs(lm[11][0] - lm[12][0])
    s_h_high = abs((lm[23][1] + lm[24][1] - lm[11][1] - lm[12][1]) / 2)
    rate = shoulder_wide / s_h_high if s_h_high > 0 else 0
    if rate < 0.2: return "sideway whole"
    if rate < 0.4: return "sideway slight"
    return "front"

def detect_fall(lm) -> tuple[bool, str]:
    sh_y  = (lm[11][1] + lm[12][1]) / 2
    sh_x  = (lm[11][0] + lm[12][0]) / 2
    hip_y = (lm[23][1] + lm[24][1]) / 2
    hip_x = (lm[23][0] + lm[24][0]) / 2
    spine_len = np.sqrt((sh_x - hip_x)**2 + (sh_y - hip_y)**2)

    angle = np.degrees(np.arccos(np.clip(abs(sh_y - hip_y) / spine_len, 0, 1))) if spine_len > 0.01 else 0.0
    nose_near = lm[0][1] > hip_y - 0.05

    hip_history.append(hip_y)
    velocity = (hip_history[-1] - hip_history[0]) if len(hip_history) >= 2 else 0.0

    is_fall = (
        angle > 65
        or (angle > 45 and nose_near and velocity > 0.008)
        or (velocity > 0.025 and angle > 30)
    )
    status = f"Fall! {angle:.0f}deg v={velocity:.3f}" if is_fall else f"Normal {angle:.0f}deg"
    return is_fall, status

# ── Frame processing ──────────────────────────────────────────────────────────
def process_frame(img_bytes: bytes) -> tuple[bytes | None, bool]:
    global fall_counter, last_fall_time, fall_frame, body_angle

    np_img = np.frombuffer(img_bytes, np.uint8)
    img    = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
    if img is None:
        return None, False

    results      = pose.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    is_falling   = False
    current_time = time.time()
    status       = "No pose"

    if results.pose_landmarks:
        mp_drawing.draw_landmarks(img, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
        lm = [(p.x, p.y, p.z, p.visibility) for p in results.pose_landmarks.landmark]
        body_angle   = determine_body_orientation(lm)
        is_fall, status = detect_fall(lm)

        if is_fall:
            fall_counter += 1
            if fall_counter >= FALL_DETECTION_FRAMES and current_time - last_fall_time > FALL_COOLDOWN:
                is_falling     = True
                last_fall_time = current_time
                fall_counter   = 0
                fall_log.append(datetime.now())
                print(f"[FALL] {status}")
                _, buf = cv2.imencode(".jpg", img)
                fall_frame = buf.tobytes()
                threading.Thread(target=log_fall_event,      args=(fall_frame, current_time), daemon=True).start()
                threading.Thread(target=send_telegram_alert, args=("⚠️ CẢNH BÁO: Phát hiện ngã! Vui lòng kiểm tra ngay.",), daemon=True).start()
        else:
            fall_counter = max(0, fall_counter - 1)

    cv2.rectangle(img, (0, 0), (225, 130), (245, 117, 16), -1)
    cv2.putText(img, "Fall Counter",     (15,  12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0),       1, cv2.LINE_AA)
    cv2.putText(img, str(fall_counter),  (10,  65), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, body_angle,         (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, status,             (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0),     2, cv2.LINE_AA)

    _, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 65])
    return jpeg.tobytes(), is_falling

# ── Background AI worker ──────────────────────────────────────────────────────
async def ai_inference_worker():
    global latest_frame
    while True:
        try:
            img_bytes, pi_ws      = await frame_queue.get()
            processed, is_falling = await asyncio.to_thread(process_frame, img_bytes)
            if not processed:
                continue

            latest_frame = processed

            if is_falling and pi_ws:
                try:
                    await pi_ws.send_json({"event": "FALL"})
                except Exception as e:
                    print(f"[WS] Send to Pi failed: {e}")

            if web_clients:
                msg  = json.dumps({"image": base64.b64encode(processed).decode()})
                dead = set()
                for ws in web_clients:
                    try:    await ws.send_text(msg)
                    except: dead.add(ws)
                web_clients -= dead
        except Exception as e:
            print(f"[WORKER] {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(ai_inference_worker())

# ── WebSocket endpoints ───────────────────────────────────────────────────────
@app.websocket("/ws/pi")
async def ws_pi(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            if frame_queue.full():
                try: frame_queue.get_nowait()
                except asyncio.QueueEmpty: pass
            await frame_queue.put((data, websocket))
    except WebSocketDisconnect:
        print("[WS] Pi disconnected")

@app.websocket("/ws/web")
async def ws_web(websocket: WebSocket):
    await websocket.accept()
    web_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        web_clients.discard(websocket)

# ── HTTP endpoints ────────────────────────────────────────────────────────────
def _html(path: str) -> str:
    return open(path, encoding="utf-8").read()

@app.get("/",          response_class=HTMLResponse)
async def index():     return _html("templates/index.html")

@app.get("/login",     response_class=HTMLResponse)
async def login():     return _html("templates/login.html")

@app.get("/camera",    response_class=HTMLResponse)
async def camera():    return _html("templates/camera.html")

@app.get("/chart",     response_class=HTMLResponse)
async def chart():     return _html("templates/chart.html")

@app.get("/fallchart", response_class=HTMLResponse)
async def fallchart(): return _html("templates/fallchart.html")

@app.get("/trigger_feed")
async def trigger_feed():
    if fall_frame:
        return StreamingResponse(BytesIO(fall_frame), media_type="image/jpeg")
    blank = np.zeros((200, 300, 3), dtype=np.uint8)
    _, jpeg = cv2.imencode(".jpg", blank)
    return StreamingResponse(BytesIO(jpeg.tobytes()), media_type="image/jpeg")

@app.post("/metrics")
async def receive_metrics(data: dict):
    metrics_data.update(data)
    return {"status": "received"}

@app.get("/get_metrics")
async def get_metrics():
    return metrics_data

@app.get("/fall_stats")
async def fall_stats():
    now        = datetime.now()
    today      = now.date()
    this_month = (now.year, now.month)

    hourly        = {f"{h:02d}:00": 0 for h in range(24)}
    days_in_month = calendar.monthrange(*this_month)[1]
    daily         = {str(d): 0 for d in range(1, days_in_month + 1)}

    for ts in fall_log:
        if ts.date() == today:
            hourly[f"{ts.hour:02d}:00"] += 1
        if (ts.year, ts.month) == this_month:
            daily[str(ts.day)] += 1

    return {"hourly": hourly, "daily": daily, "total": len(fall_log)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
