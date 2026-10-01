import cv2
from ultralytics import YOLO
import requests
import time
from flask import Flask, Response

app = Flask(__name__)

# --- CONFIGURATION (NODE-RED KO BHEJO, ESP KO NAHI) ---
# Ab yaha ESP32 ka dynamic IP dalne ki zaroorat nahi!
url_all_on = "http://127.0.0.1:1880/ai-control?state=/ALL=ON"
url_all_off = "http://127.0.0.1:1880/ai-control?state=/ALL=OFF"
TIMEOUT_SECONDS = 5 

print("Loading AI Model...")
model = YOLO('yolo11n.pt') 
cap = cv2.VideoCapture(0) 

system_state = False # False = Sab Band, True = Sab Chalu
last_person_time = time.time()

def generate_frames():
    global system_state, last_person_time
    
    while True:
        ret, frame = cap.read()
        if not ret: break

        results = model(frame, stream=True, verbose=False)
        person_detected = False
        
        for r in results:
            for box in r.boxes:
                if int(box.cls[0]) == 0: # Class 0 = Person
                    person_detected = True
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, "Human", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                    break

        current_time = time.time()

        if person_detected:
            last_person_time = current_time 
            if not system_state:
                print("Human Detected -> Telling Node-RED to turn ALL ON")
                try:
                    # Request Node-RED ko ja rahi hai
                    requests.get(url_all_on, timeout=1)
                    system_state = True
                except:
                    print("Error: Node-RED server nahi chal raha ya flow band hai.")

        else:
            if (current_time - last_person_time > TIMEOUT_SECONDS) and system_state:
                print(f"Room Empty for {TIMEOUT_SECONDS}s -> Telling Node-RED to turn ALL OFF")
                try:
                    requests.get(url_all_off, timeout=1)
                    system_state = False
                except:
                    print("Error: Node-RED server nahi chal raha.")
            
            if system_state:
                remaining = int(TIMEOUT_SECONDS - (current_time - last_person_time))
                if remaining > 0:
                    cv2.putText(frame, f"OFF in: {remaining}s", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)

        # Dashboard ke liye image encode karo aur Flask stream me bhejo
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# UI ko video bhejne wala API endpoint
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("⚡ PowerSense AI Vision Server Started on http://127.0.0.1:5000")
    # Ye server dashboard me camera dikhayega
    app.run(host='0.0.0.0', port=5000, debug=False)