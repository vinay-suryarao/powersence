# ⚡ PowerSense – AI + IoT Smart Energy Saver

Camera (YOLO11) **+ PIR sensor** se insaan detect karta hai, **DHT temperature sensor** se fan control karta hai,
aur har appliance ka energy/bill **Firebase Firestore** me save karta hai. Monthly report PDF me download hoti hai.

```
Webcam ──► YOLO11 ─┐
                   ├─► main.py (Flask: logic + API + DB) ◄──► Firebase Firestore
ESP32 PIR + DHT ───┘          │  ▲                ▲
        ▲                     ▼  │                │ /api/status, /api/report (har second)
        └──── Node-RED (127.0.0.1:1880) ──────────┘
              ├─ /ai-control, /sensor-status  (Python <-> ESP32 bridge)
              └─ Dashboard: http://127.0.0.1:1880/ui
ESP32 ──► Relay 1 Light | Relay 2 Lamp | Relay 3 Fan
```

**Dashboard Node-RED (node-red-dashboard) me hai.** Python sirf brain hai: YOLO, decision logic, Firestore, PDF.
Dashboard ke dropdown/numeric se command Node-RED → Python API → Node-RED → ESP32 jaati hai.

## Logic
| Device | AUTO mode me kab ON hoga |
|---|---|
| Light, Lamp | Room occupied (camera me human **ya** PIR motion) |
| Fan | Temperature ≥ threshold (default 20 °C), threshold − 0.5 °C se neeche OFF. Room khaali ho tab bhi (`FAN_NEEDS_OCCUPANCY` se badal sakte ho) |

* Camera aur PIR dono me `TIMEOUT_SECONDS` (5s) tak kuch nahi → sab OFF.
* Camera fail / andhera ho → PIR se kaam chalta rahega. Insaan still baitha ho (PIR miss kare) → camera pakad lega.
* Node-RED dashboard se har device ka **AUTO / ON / OFF** mode alag set kar sakte ho; fan threshold bhi wahi se change hota hai.
* Bill poore din ka banta hai: system start pe aaj ka data DB se load hota hai aur wahin se count continue hota hai
  (har 30s save + band hote waqt save).

## Wiring (ESP32)
| Part | ESP32 pin |
|---|---|
| Relay IN1 – Light | GPIO 26 |
| Relay IN2 – Lamp | GPIO 27 |
| Relay IN3 – Fan | GPIO 14 |
| PIR (HC-SR501) OUT | GPIO 13 (VCC → 5V/VIN, GND → GND) |
| DHT11/DHT22 DATA | GPIO 4 (VCC → 3.3V, GND → GND, 10k pull-up agar bare sensor hai) |

## Setup
1. **ESP32**: Arduino IDE → Library Manager se *DHT sensor library* (Adafruit) install karo →
   `powersense/powersense.ino` me Wi-Fi name/password daalo (DHT22 hai toh `DHTTYPE` badlo) → upload.
   Serial Monitor me ESP32 ka IP note karo.
2. **Node-RED**: `node-red-dashboard` palette me installed hona chahiye. Purana flow (jisme `/ai-control` hai) **delete** karo,
   phir Menu → Import → `node-red/flows.json` → **"Settings"** node me ESP32 ka IP check karo → Deploy.
3. **Firebase**:
   1. [console.firebase.google.com](https://console.firebase.google.com) → project banao → *Firestore Database* → Create.
   2. Project Settings → Service accounts → *Generate new private key*.
   3. Downloaded file ko project folder me `serviceAccountKey.json` naam se rakho.

   Key nahi hogi toh data `data/local_db.json` me save hoga (dashboard pe "DB: Local" dikhega).
4. **Python**:
   ```
   venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```
   Dashboard: <http://127.0.0.1:1880/ui> — tabs (left menu): **Dashboard**, **Charts**, **Monthly Report**, **Settings**

Wattage, unit rate (₹/kWh), timeout — sab `config.py` me hai.

## Firestore data
| Collection | Kya hai |
|---|---|
| `daily_usage/{YYYY-MM-DD}` | Har device ka ON time, kWh, bill, occupied time, temp min/max/avg |
| `events` | Device ON/OFF, occupancy, mode change log |
| `sensor_logs` | Har minute temperature, humidity, occupancy, relay states |
| `settings/app` | Fan threshold, device modes |

## API
| Endpoint | Kaam |
|---|---|
| `GET /` | Node-RED dashboard pe redirect |
| `GET /video_feed` | Live camera stream |
| `GET /api/status` | Sensors, devices, aaj ka bill |
| `POST /api/device/<light\|lamp\|fan>` `{"mode":"auto\|on\|off"}` | Device control |
| `POST /api/settings` `{"fan_threshold":20}` | Fan threshold |
| `GET /api/history?hours=6` | Sensor history (charts) |
| `GET /api/days?n=7` | Pichle N din ka energy |
| `GET /api/report?month=YYYY-MM` | Monthly summary JSON |
| `GET /report/pdf?month=YYYY-MM` | Monthly report PDF download |
