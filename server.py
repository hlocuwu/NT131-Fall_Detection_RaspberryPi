from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import time
import cv2
import numpy as np
import mediapipe as mp
from io import BytesIO
from google.cloud import storage
import json
from collections import defaultdict
from datetime import datetime
import calendar

app = FastAPI()

# Cung cấp thư mục static
app.mount("/custom", StaticFiles(directory="custom"), name="custom")

# Load pose detection
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
pose = mp_pose.Pose(min_detection_confidence=0.6, min_tracking_confidence=0.6)

# Shared states
latest_frame = None
fall_frame = None
last_fall_time = 0
metrics_data = {"cpu": 0, "memory": 0}

fall_cooldown = 5
body_angle = 'front'
fall_counter = 0

# History tracking for falling detection
pose_history = {}
frame_counter = 0

VISIBILITY_THRESHOLD = 0.6
FALL_DETECTION_FRAMES = 5
FALLING_DETECTION_FRAMES = 3

PARA_S_H_1 = 1.15
PARA_S_H_2 = 0.85
PARA_H_F = 0.6
FRAME_INTERVAL = 30

def log_fall_event_to_gcs(image_bytes: bytes, timestamp: float):
    client = storage.Client()
    bucket = client.bucket("fall-log-data") 

    readable_time = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(timestamp))
    image_filename = f"fall_events/{readable_time}.jpg"
    json_filename = f"fall_events/{readable_time}.json"

    image_blob = bucket.blob(image_filename)
    image_blob.upload_from_string(image_bytes, content_type="image/jpeg")

    event_info = {
        "event": "fall_detected",
        "timestamp": readable_time,
    }
    json_blob = bucket.blob(json_filename)
    json_blob.upload_from_string(json.dumps(event_info, indent=2), content_type="application/json")

    print(f"[GCS] Uploaded fall image and metadata at {readable_time}")

@app.get("/", response_class=HTMLResponse)
async def index():
    with open('templates/index.html') as f:
        return f.read()

@app.get("/camera", response_class=HTMLResponse)
async def camera_page():
    with open('templates/camera.html') as f:
        return f.read()

@app.get("/chart", response_class=HTMLResponse)
async def chart_page():
    with open('templates/chart.html') as f:
        return f.read()

@app.get("/fallchart", response_class=HTMLResponse)
async def setting_page():
    with open('templates/fallchart.html') as f:
        return f.read()

def generate():
    global latest_frame
    while True:
        if latest_frame is not None:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + latest_frame + b'\r\n'
            )
        time.sleep(1/18)

@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

def determine_body_orientation(landmarks):
    shoulder_wide = abs(landmarks[11][0] - landmarks[12][0])
    
    s_h_high = abs((landmarks[23][1] + landmarks[24][1] - landmarks[11][1] - landmarks[12][1]) / 2)
    
    rate1 = shoulder_wide / s_h_high if s_h_high > 0 else 0
    
    if 0.2 < rate1 < 0.4:
        return "sideway slight"
    elif rate1 < 0.2:
        return "sideway whole"
    else:
        return "front"

def detect_fall(landmarks):
    s_h_high = abs((landmarks[23][1] + landmarks[24][1] - landmarks[11][1] - landmarks[12][1]) / 2)
    
    s_h_long = np.sqrt(((landmarks[23][1] + landmarks[24][1] - landmarks[11][1] - landmarks[12][1]) / 2)**2 + 
                       ((landmarks[23][0] + landmarks[24][0] - landmarks[11][0] - landmarks[12][0]) / 2)**2)
    
    h_f_high = ((landmarks[28][1] + landmarks[27][1] - landmarks[24][1] - landmarks[23][1]) / 2)
    
    h_f_long = np.sqrt(((landmarks[28][1] + landmarks[27][1] - landmarks[24][1] - landmarks[23][1]) / 2)**2 + 
                       ((landmarks[28][0] + landmarks[27][0] - landmarks[24][0] - landmarks[23][0]) / 2)**2)
    
    # Fall detection logic
    if s_h_high < s_h_long * PARA_S_H_1 and s_h_high > s_h_long * PARA_S_H_2:
        return False, "Not Fall"
    
    elif h_f_high < PARA_H_F * h_f_long:
        return True, "Fall Detected"
    
    else:
        return False, "Bend Over"

# def detect_falling(history, current_frame_id):
#     if current_frame_id < 6 or str(current_frame_id - 6) not in history:
#         return False, "Not enough history"
    
#     now_lst = history[str(current_frame_id)]
#     pre_lst = history[str(current_frame_id - 6)]

#     para_falling_s_h_1 = 1.15
#     para_falling_s_h_2 = 0.85
#     para_v_1 = 0.5
    
#     s_h_high = (pre_lst[23][1] - pre_lst[11][1] + pre_lst[24][1] - pre_lst[12][1]) / 2
#     s_h_long = np.sqrt(((pre_lst[23][1] + pre_lst[24][1] - pre_lst[11][1] - pre_lst[12][1]) / 2)**2 + 
#                        ((pre_lst[23][0] + pre_lst[24][0] - pre_lst[11][0] - pre_lst[12][0]) / 2)**2)
    
#     if s_h_high < s_h_long * para_falling_s_h_1 and s_h_high > s_h_long * para_falling_s_h_2:
#         return False, "Not falling"
    
#     elif now_lst[0][1] < para_v_1 * ((pre_lst[11][1] + pre_lst[12][1]) / 2):
#         return True, "Falling detected"
    
#     return False, "Not falling"

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    global latest_frame, fall_frame, last_fall_time, fall_counter, pose_history, frame_counter, body_angle

    start_time = time.time()

    content = await file.read()
    np_img = np.frombuffer(content, np.uint8)
    img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    if img is None:
        return {"message": "Image decode error"}

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = pose.process(img_rgb)

    detected_fall_this_frame = False
    current_time = time.time()
    detected_falling = False
    
    status_message = "Normal"

    if results.pose_landmarks:
        mp_drawing.draw_landmarks(
            img,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=mp_drawing.DrawingSpec(color=(245,117,66), thickness=2, circle_radius=2),
            connection_drawing_spec=mp_drawing.DrawingSpec(color=(245,66,230), thickness=2, circle_radius=2)
        )

        lst = []
        for i in results.pose_landmarks.landmark:
            lst.append((i.x, i.y, i.z, i.visibility))
        
        pose_history[str(frame_counter)] = lst
        frame_counter += 1
        
        current_orientation = determine_body_orientation(lst)
        if current_orientation == body_angle:
            pass
        else:
            body_angle = current_orientation
        
        # Fall detection
        is_fall, fall_status = detect_fall(lst)
        status_message = fall_status
        
        if is_fall:
            fall_counter += 1
            if fall_counter >= FALL_DETECTION_FRAMES and current_time - last_fall_time > fall_cooldown:
                detected_fall_this_frame = True
                last_fall_time = current_time
                print(f"!!! FALL DETECTED !!! - {fall_status}")
                
                # Save fall image
                _, jpeg_fall = cv2.imencode('.jpg', img)
                fall_frame = jpeg_fall.tobytes()
                log_fall_event_to_gcs(fall_frame, current_time)
                
                fall_counter = 0
        else:
            fall_counter = 0

        # Falling detection
        if frame_counter % FRAME_INTERVAL == 0:
            is_falling, falling_status = detect_falling(pose_history, frame_counter)
            if is_falling:
                detected_falling = True
                print(f"!!! FALLING DETECTED !!! - {falling_status}")
                status_message = falling_status
                
                _, jpeg_fall = cv2.imencode('.jpg', img)
                fall_frame = jpeg_fall.tobytes()
                
                if len(pose_history) > 80:  # Keep last ~4 seconds at 20fps
                    old_keys = sorted([int(k) for k in pose_history.keys()])[:-80]
                    for k in old_keys:
                        if str(k) in pose_history:
                            del pose_history[str(k)]

    # Add status text to image
    cv2.rectangle(img, (0, 0), (225, 130), (245, 117, 16), -1)
    cv2.putText(img, 'Fall Counter', (15, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, 'Body Angle', (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, str(fall_counter), (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, str(body_angle), (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    # Add status message
    cv2.putText(img, status_message, (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

    _, jpeg = cv2.imencode('.jpg', img)
    latest_frame = jpeg.tobytes()

    processing_time = time.time() - start_time

    return {
        "message": "Image processed", 
        "fall_detected": detected_fall_this_frame,
        "falling_detected": detected_falling,
        "body_angle": body_angle,
        "processing_time_ms": round(processing_time * 1000, 2)
    }

@app.get("/trigger_feed")
async def trigger_feed():
    global fall_frame
    if fall_frame:
        return StreamingResponse(BytesIO(fall_frame), media_type="image/jpeg")
    else:
        blank = np.zeros((200, 300, 3), dtype=np.uint8)
        cv2.putText(blank, "No Fall Detected Yet", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        _, jpeg = cv2.imencode('.jpg', blank)
        return StreamingResponse(BytesIO(jpeg.tobytes()), media_type="image/jpeg")

@app.post("/metrics")
async def receive_metrics(data: dict):
    metrics_data["cpu"] = data["cpu"]
    metrics_data["memory"] = data["memory"]
    return {"status": "received"}

@app.get("/get_metrics")
async def get_metrics():
    return metrics_data

@app.get("/fall_stats")
async def fall_stats():
    client = storage.Client()
    bucket = client.bucket("fall-log-data")

    blobs = bucket.list_blobs(prefix="fall_events/")
    
    hourly_stats = defaultdict(int)
    daily_stats = defaultdict(int)
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_month = datetime.now().strftime("%Y-%m")

    for blob in blobs:
        if blob.name.endswith(".json"):
            try:
                timestamp_str = blob.name.split("/")[-1].replace(".json", "")
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                
                if dt.strftime("%Y-%m-%d") == current_date:
                    hour_key = dt.strftime("%H:00")
                    hourly_stats[hour_key] += 1
                
                if dt.strftime("%Y-%m") == current_month:
                    day_key = dt.strftime("%Y-%m-%d")
                    daily_stats[day_key] += 1
                    
            except Exception as e:
                print("Error read timestamp:", blob.name, e)

    for hour in range(24):
        hour_key = f"{hour:02d}:00"
        if hour_key not in hourly_stats:
            hourly_stats[hour_key] = 0

    today = datetime.now()
    _, last_day = calendar.monthrange(today.year, today.month)
    for day in range(1, last_day + 1):
        day_key = f"{today.year}-{today.month:02d}-{day:02d}"
        if day_key not in daily_stats:
            daily_stats[day_key] = 0

    return {
        "hourly": dict(sorted(hourly_stats.items())),
        "daily": dict(sorted(daily_stats.items())),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)