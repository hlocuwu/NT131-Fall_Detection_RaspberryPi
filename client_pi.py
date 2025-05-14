import cv2
import requests
import time
import psutil
import threading
import os
from dotenv import load_dotenv
import RPi.GPIO as GPIO

load_dotenv()
SERVER_URL = "http://34.9.237.44:8000"
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Buzzer setup
BUZZER_PIN = 17  # GPIO pin for buzzer
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.output(BUZZER_PIN, GPIO.HIGH)

# Camera settings
CAMERA_RESOLUTION = (640, 480)
CAMERA_FPS = 18

# Alert settings
last_alert_time = 0
alert_cooldown = 5

def sound_buzzer(duration=1):
    try:
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        time.sleep(duration)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
    except Exception as e:
        print(f"Buzzer error: {e}")

def send_metrics():
    while True:
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            payload = {"cpu": cpu, "memory": mem}
            response = requests.post(f"{SERVER_URL}/metrics", json=payload, timeout=5)
            if response.status_code != 200:
                print(f"Metrics send failed with status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Metric request error: {e}")
        except Exception as e:
            print(f"Metric error: {e}")
        time.sleep(2)

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message
        }
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("Telegram alert sent successfully")
        else:
            print(f"Telegram alert failed with status code: {response.status_code}")
    except Exception as e:
        print(f"Telegram error: {e}")

def send_camera():
    global last_alert_time
    
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    except Exception as e:
        print(f"Failed to initialize camera: {e}")
        return
    
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return
    
    print("Camera initialized successfully")
    
    while True:
        try:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame")
                time.sleep(1)
                continue
            
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
            _, img_encoded = cv2.imencode('.jpg', frame, encode_param)
            
            files = {
                'file': ('frame.jpg', img_encoded.tobytes(), 'image/jpeg')
            }
            
            response = requests.post(
                f"{SERVER_URL}/upload", 
                files=files,
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("fall_detected"):
                    current_time = time.time()
                    if current_time - last_alert_time > alert_cooldown:
                        last_alert_time = current_time
                        print("FALL DETECTED! Activating warning system.")
                        
                        threading.Thread(target=sound_buzzer, args=(2,), daemon=True).start()
                        
                        threading.Thread(
                            target=send_telegram_message, 
                            args=("⚠️ ALERT: Fall detected!",), 
                            daemon=True
                        ).start()
            else:
                print(f"Failed to send frame. Code: {response.status_code}")
                
        except requests.exceptions.Timeout:
            print("Request timed out")
        except requests.exceptions.ConnectionError:
            print("Connection error - server may be down")
            time.sleep(5)
        except Exception as e:
            print(f"Camera error: {e}")
            
        time.sleep(1/CAMERA_FPS)

def cleanup():
    GPIO.cleanup()
    print("GPIO cleaned up")

if __name__ == "__main__":
    try:
        print("Fall detection system starting...")
        metrics_thread = threading.Thread(target=send_metrics, daemon=True)
        metrics_thread.start()
        print("Metrics monitoring started")
        
        print("Starting camera monitoring...")
        send_camera()
    except KeyboardInterrupt:
        print("Program terminated by user")
    finally:
        cleanup()