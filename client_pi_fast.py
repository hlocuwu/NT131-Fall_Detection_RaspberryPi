import cv2, requests, time, psutil, threading, os, json
import websocket
from dotenv import load_dotenv

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("RPi.GPIO not found. Running in Local mode.")
    GPIO_AVAILABLE = False

load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:8000")
WS_URL = SERVER_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/pi"
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BUZZER_PIN = 17 
if GPIO_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUZZER_PIN, GPIO.OUT)
    GPIO.output(BUZZER_PIN, GPIO.HIGH)

CAMERA_RESOLUTION = (640, 480)
CAMERA_FPS = 15

# Global frame buffer
latest_frame = None
frame_lock = threading.Lock()

def sound_buzzer(duration=1):
    try:
        if GPIO_AVAILABLE:
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(duration)
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
        else:
            print(f"[LOCAL] *BUZZER SOUNDING* for {duration}s!")
            time.sleep(duration)
    except Exception as e:
        print(f"Buzzer error: {e}")

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=10)
    except Exception as e: print(e)

def capture_frames():
    global latest_frame
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
    
    if not cap.isOpened():
        print("Camera Error")
        return
        
    print("Camera Started")
    while True:
        ret, frame = cap.read()
        if ret:
            with frame_lock:
                latest_frame = frame
        time.sleep(1/CAMERA_FPS)

def on_message(ws, message):
    data = json.loads(message)
    if data.get("event") == "FALL":
        print("FALL DETECTED! Activating warning system.")
        threading.Thread(target=sound_buzzer, args=(2,), daemon=True).start()
        threading.Thread(target=send_telegram_message, args=("⚠️ ALERT: Fall detected!",), daemon=True).start()

def on_error(ws, error):
    print("WebSocket Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket Closed. Reconnecting in 3s...")
    time.sleep(3)
    stream_to_server()

def stream_to_server():
    def push_frames(ws):
        while True:
            frame = None
            with frame_lock:
                if latest_frame is not None:
                    frame = latest_frame.copy()
            if frame is not None:
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                try:
                    ws.send(buffer.tobytes(), opcode=websocket.ABNF.OPCODE_BINARY)
                except websocket.WebSocketConnectionClosedException:
                    break
            time.sleep(1/CAMERA_FPS)

    ws = websocket.WebSocketApp(WS_URL, on_message=on_message, on_error=on_error, on_close=on_close)
    ws.on_open = lambda w: threading.Thread(target=push_frames, args=(w,), daemon=True).start()
    ws.run_forever()

if __name__ == "__main__":
    threading.Thread(target=capture_frames, daemon=True).start()
    stream_to_server()
