import cv2
import requests
import time
import psutil
import threading
import os
import RPi.GPIO as GPIO

# Configuration
SERVER_URL = "http://34.9.237.44:8000"
TELEGRAM_TOKEN = '7285124282:AAEL3q-2G5KxTZ8hB7a6Hq62E5jR0aVZ1TM'
TELEGRAM_CHAT_ID = '6510802773'

# Buzzer setup
BUZZER_PIN = 17  # GPIO pin for buzzer
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.output(BUZZER_PIN, GPIO.HIGH)

# Camera settings
CAMERA_RESOLUTION = (640, 480)  # Lower resolution for better performance
CAMERA_FPS = 15  # Lower framerate to reduce CPU usage

# Alert settings
last_alert_time = 0
alert_cooldown = 5  # seconds

def sound_buzzer(duration=1):
    """Activate the buzzer for a specified duration"""
    try:
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        time.sleep(duration)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
    except Exception as e:
        print(f"Buzzer error: {e}")

# Send CPU and Memory usage
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
        time.sleep(2)  # Reduced frequency to lower resource usage

# Send webcam images
def send_camera():
    global last_alert_time
    
    # Initialize camera
    try:
        cap = cv2.VideoCapture(1)
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

            # Resize if necessary for performance
            # frame = cv2.resize(frame, (320, 240))  # Uncomment if needed
            
            # Compress image more aggressively for Pi
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
                        
                        # Sound the buzzer
                        threading.Thread(target=sound_buzzer, args=(2,), daemon=True).start()
                        
                        # Send Telegram alert
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
            time.sleep(5)  # Wait longer before retry if server is down
        except Exception as e:
            print(f"Camera error: {e}")
            
        time.sleep(1/CAMERA_FPS)  # Maintain consistent frame rate

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

def cleanup():
    """Clean up GPIO on program exit"""
    GPIO.cleanup()
    print("GPIO cleaned up")

if __name__ == "__main__":
    try:
        print("Fall detection system starting...")
        # Start metrics thread
        metrics_thread = threading.Thread(target=send_metrics, daemon=True)
        metrics_thread.start()
        print("Metrics monitoring started")
        
        # Start camera processing
        print("Starting camera monitoring...")
        send_camera()
    except KeyboardInterrupt:
        print("Program terminated by user")
    finally:
        cleanup()