from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import time, cv2, numpy as np, mediapipe as mp, json, asyncio
from io import BytesIO
from google.cloud import storage
from collections import defaultdict
from datetime import datetime
import calendar, os, base64

app = FastAPI()
app.mount("/custom", StaticFiles(directory="custom"), name="custom")

# Pose configuration
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
pose = mp_pose.Pose(min_detection_confidence=0.6, min_tracking_confidence=0.6)

# Global States
latest_frame = None
fall_frame = None
last_fall_time = 0
fall_counter = 0
body_angle = 'front'
metrics_data = {"cpu": 0, "memory": 0}

# Drop-frame Buffer Queue (size 1)
frame_queue = asyncio.Queue(maxsize=1)
# Active Web UI connections
web_clients = set()

# Utility functions (Same as before)
PARA_S_H_1, PARA_S_H_2, PARA_H_F = 1.15, 0.85, 0.6
FALL_DETECTION_FRAMES, fall_cooldown = 5, 5

def log_fall_event_to_gcs(image_bytes: bytes, timestamp: float):
    readable_time = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(timestamp))
    try:
        client = storage.Client()
        bucket = client.bucket("fall-log-data") 
        bucket.blob(f"fall_events/{readable_time}.jpg").upload_from_string(image_bytes, content_type="image/jpeg")
        bucket.blob(f"fall_events/{readable_time}.json").upload_from_string(json.dumps({"event": "fall_detected", "timestamp": readable_time}, indent=2), content_type="application/json")
        print(f"[GCS] Uploaded fall image at {readable_time}")
    except Exception as e:
        if not os.path.exists("fall_events"): os.makedirs("fall_events")
        with open(f"fall_events/{readable_time}.jpg", "wb") as f: f.write(image_bytes)
        print(f"[LOCAL] Saved fall image locally")

def determine_body_orientation(landmarks):
    shoulder_wide = abs(landmarks[11][0] - landmarks[12][0])
    s_h_high = abs((landmarks[23][1] + landmarks[24][1] - landmarks[11][1] - landmarks[12][1]) / 2)
    rate1 = shoulder_wide / s_h_high if s_h_high > 0 else 0
    if 0.2 < rate1 < 0.4: return "sideway slight"
    elif rate1 < 0.2: return "sideway whole"
    return "front"

def detect_fall(landmarks):
    s_h_high = abs((landmarks[23][1] + landmarks[24][1] - landmarks[11][1] - landmarks[12][1]) / 2)
    s_h_long = np.sqrt(((landmarks[23][1] + landmarks[24][1] - landmarks[11][1] - landmarks[12][1]) / 2)**2 + 
                       ((landmarks[23][0] + landmarks[24][0] - landmarks[11][0] - landmarks[12][0]) / 2)**2)
    h_f_high = ((landmarks[28][1] + landmarks[27][1] - landmarks[24][1] - landmarks[23][1]) / 2)
    h_f_long = np.sqrt(((landmarks[28][1] + landmarks[27][1] - landmarks[24][1] - landmarks[23][1]) / 2)**2 + 
                       ((landmarks[28][0] + landmarks[27][0] - landmarks[24][0] - landmarks[23][0]) / 2)**2)
    
    if s_h_high < s_h_long * PARA_S_H_1 and s_h_high > s_h_long * PARA_S_H_2: return False, "Not Fall"
    elif h_f_high < PARA_H_F * h_f_long: return True, "Fall Detected"
    return False, "Bend Over"

def process_frame(img_bytes):
    global fall_counter, last_fall_time, fall_frame, body_angle
    
    try:
        np_img = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        if img is None: 
            print("Failed to decode frame")
            return None, False
        
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = pose.process(img_rgb)
        
        is_falling_now = False
        current_time = time.time()
        status_message = "Normal"
        
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(img, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            lst = [(i.x, i.y, i.z, i.visibility) for i in results.pose_landmarks.landmark]
            body_angle = determine_body_orientation(lst)
            is_fall, fall_status = detect_fall(lst)
            status_message = fall_status
            
            if is_fall:
                fall_counter += 1
                if fall_counter >= FALL_DETECTION_FRAMES and current_time - last_fall_time > fall_cooldown:
                    is_falling_now = True
                    last_fall_time = current_time
                    print(f"!!! FALL DETECTED !!! - {fall_status}")
                    _, jpeg_fall = cv2.imencode('.jpg', img)
                    fall_frame = jpeg_fall.tobytes()
                    # Run GCS upload async in background
                    asyncio.get_event_loop().run_in_executor(None, log_fall_event_to_gcs, fall_frame, current_time)
                    fall_counter = 0
            else:
                fall_counter = max(0, fall_counter - 1)

        cv2.rectangle(img, (0, 0), (225, 130), (245, 117, 16), -1)
        cv2.putText(img, 'Fall Counter', (15, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(img, str(fall_counter), (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, str(body_angle), (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, status_message, (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

        _, jpeg = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
        return jpeg.tobytes(), is_falling_now
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, False

# ---------- BACKGROUND AI WORKER ----------
async def ai_inference_worker():
    global latest_frame
    while True:
        try:
            # Get frame from queue
            img_bytes, pi_ws = await frame_queue.get()
            # Run Heavy AI logic in thread so event loop doesn't block
            processed_bytes, is_falling = await asyncio.to_thread(process_frame, img_bytes)
            
            if processed_bytes:
                latest_frame = processed_bytes
                
                # Send alert to Pi
                if is_falling and pi_ws:
                    try:
                        await pi_ws.send_json({"event": "FALL"})
                    except Exception as e:
                        print(f"Error sending to Pi: {e}")
                        
                # Broadcast to Web UI via WebSockets
                if web_clients:
                    b64_img = base64.b64encode(processed_bytes).decode('utf-8')
                    msg = json.dumps({"image": b64_img})
                    dead_clients = set()
                    for web_ws in web_clients:
                        try:
                            await web_ws.send_text(msg)
                        except:
                            dead_clients.add(web_ws)
                    for d in dead_clients:
                        web_clients.discard(d)
        except Exception as e:
            print(f"AI Worker Crash Guard: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(ai_inference_worker())

# ---------- WEBSOCKET ENDPOINTS ----------
@app.websocket("/ws/pi")
async def ws_pi(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            # Drop frame policy
            if frame_queue.full():
                try: frame_queue.get_nowait()
                except asyncio.QueueEmpty: pass
            await frame_queue.put((data, websocket))
    except WebSocketDisconnect:
        print("Pi disconnected")

@app.websocket("/ws/web")
async def ws_web(websocket: WebSocket):
    await websocket.accept()
    web_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        web_clients.remove(websocket)

# HTML pages and metrics (Same as before)
@app.get("/", response_class=HTMLResponse)
async def index(): return open('templates/index.html', encoding='utf-8').read()

@app.get("/login", response_class=HTMLResponse)
async def login_page(): return open('templates/login.html', encoding='utf-8').read()

@app.get("/camera", response_class=HTMLResponse)
async def camera_page(): return open('templates/camera.html', encoding='utf-8').read()

@app.get("/chart", response_class=HTMLResponse)
async def chart(): return open('templates/chart.html', encoding='utf-8').read()

@app.get("/fallchart", response_class=HTMLResponse)
async def fallchart(): return open('templates/fallchart.html', encoding='utf-8').read()

@app.get("/trigger_feed")
async def trigger_feed():
    if fall_frame: return StreamingResponse(BytesIO(fall_frame), media_type="image/jpeg")
    blank = np.zeros((200, 300, 3), dtype=np.uint8)
    _, jpeg = cv2.imencode('.jpg', blank)
    return StreamingResponse(BytesIO(jpeg.tobytes()), media_type="image/jpeg")

@app.post("/metrics")
async def receive_metrics(data: dict):
    metrics_data.update(data)
    return {"status": "received"}

@app.get("/get_metrics")
async def get_metrics(): return metrics_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
