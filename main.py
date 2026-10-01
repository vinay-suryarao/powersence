import threading
import time
from collections import deque
from datetime import datetime, timedelta

import cv2
import requests
from flask import Flask, Response, jsonify, redirect, request
from ultralytics import YOLO

import config
from report import DEVICES, build_pdf, day_energy, day_row, summarize_month
from storage import Storage

app = Flask(__name__)
lock = threading.Lock()
storage = Storage(config.FIREBASE_KEY_PATH, config.LOCAL_DB_PATH)

# --- SHARED STATE (teeno threads + Flask isko padhte/likhte hain, lock ke saath) ---
vision = {"person": False, "camera_ok": False, "jpeg": None}
sensors = {"pir": False, "temp": None, "humidity": None, "esp_online": False, "last_seen": 0.0, "ever_seen": False}
occupancy = {"occupied": False, "last_presence": 0.0}
devices = {name: {"mode": "auto", "state": False, "reason": "", "next_retry": 0.0} for name in DEVICES}
settings = {"fan_threshold": config.FAN_TEMP_THRESHOLD}
recent_events = deque(maxlen=40)


def new_day(date_str):
    return {"date": date_str, "light_on_s": 0.0, "lamp_on_s": 0.0, "fan_on_s": 0.0, "occupied_s": 0.0,
            "temp_sum": 0.0, "temp_count": 0, "temp_min": None, "temp_max": None}


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


# System start: aaj ka data DB se wapas lo, taaki bill poore din ka bane (restart ke baad bhi)
day = storage.get_day(today_str()) or new_day(today_str())
if day.get("light_on_s") or day.get("lamp_on_s") or day.get("fan_on_s"):
    print(f"Aaj ka purana data restore hua: {day_energy(day)[1]:.3f} kWh")

saved = storage.get_settings()
settings["fan_threshold"] = float(saved.get("fan_threshold", config.FAN_TEMP_THRESHOLD))
for name, mode in (saved.get("modes") or {}).items():
    if name in devices and mode in ("auto", "on", "off"):
        devices[name]["mode"] = mode


def add_event(kind, detail):
    recent_events.appendleft({"time": datetime.now().strftime("%H:%M:%S"), "kind": kind, "detail": detail})
    print(f"[{kind}] {detail}")
    threading.Thread(target=storage.log_event, args=(kind, detail), daemon=True).start()


def persist_settings():
    storage.save_settings({"fan_threshold": settings["fan_threshold"],
                           "modes": {n: d["mode"] for n, d in devices.items()}})


def save_day_record(record):
    kwh, total, cost = day_energy(record)
    data = dict(record, **{f"{d}_kwh": round(kwh[d], 4) for d in DEVICES},
                energy_kwh=round(total, 4), cost=round(cost, 2),
                updated_at=datetime.now().isoformat(timespec="seconds"))
    storage.save_day(record["date"], data)


# ---------------- THREAD 1: CAMERA + YOLO ----------------
def vision_loop():
    print("Loading AI Model...")
    model = YOLO(config.YOLO_MODEL)
    cap = cv2.VideoCapture(config.CAMERA_INDEX)

    while True:
        ret, frame = cap.read()
        if not ret:
            # Camera nahi mila -> PIR se kaam chalega, camera dobara try karo
            with lock:
                vision["camera_ok"] = False
                vision["person"] = False
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(config.CAMERA_INDEX)
            continue

        person_detected = False
        for r in model(frame, stream=True, verbose=False):
            for box in r.boxes:
                if int(box.cls[0]) == 0:  # Class 0 = Person
                    person_detected = True
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, "Human", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        with lock:
            pir = sensors["pir"]
            occupied = occupancy["occupied"]
            last_presence = occupancy["last_presence"]

        if pir:
            cv2.putText(frame, "PIR: Motion", (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
        if occupied and not (person_detected or pir):
            remaining = int(config.TIMEOUT_SECONDS - (time.time() - last_presence)) + 1
            if remaining > 0:
                cv2.putText(frame, f"OFF in: {remaining}s", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        ok, buffer = cv2.imencode(".jpg", frame)
        with lock:
            vision["person"] = person_detected
            vision["camera_ok"] = True
            if ok:
                vision["jpeg"] = buffer.tobytes()


# ---------------- THREAD 2: ESP32 SENSORS (Node-RED ke through) ----------------
def sensor_loop():
    while True:
        try:
            data = requests.get(config.NODE_RED_STATUS_URL, timeout=1.5).json()
            with lock:
                sensors["pir"] = bool(data.get("pir"))
                temp = data.get("temp")
                sensors["temp"] = round(float(temp), 1) if temp is not None else None
                hum = data.get("humidity")
                sensors["humidity"] = round(float(hum), 1) if hum is not None else None
                sensors["last_seen"] = time.time()
                sensors["ever_seen"] = True
                # ESP32 ka actual relay state hi sach hai
                for name in DEVICES:
                    if name in data:
                        devices[name]["state"] = bool(data[name])
        except (requests.RequestException, ValueError):
            pass
        with lock:
            online = time.time() - sensors["last_seen"] < 5
            if sensors["esp_online"] != online:
                sensors["esp_online"] = online
                if not online:
                    sensors["pir"] = False
                changed = True
            else:
                changed = False
        if changed:
            add_event("esp", "ESP32 online" if online else "ESP32 offline / Node-RED not reachable")
        time.sleep(config.SENSOR_POLL_SECONDS)


# ---------------- THREAD 3: DECISION + ENERGY ----------------
def send_command(name, on):
    state = f"/{name.upper()}={'ON' if on else 'OFF'}"
    try:
        r = requests.get(config.NODE_RED_CONTROL_URL, params={"state": state}, timeout=1.5)
        return r.ok
    except requests.RequestException:
        return False


def decide(name, occupied, temp, currently_on, threshold):
    """Auto mode me device ON hona chahiye ya nahi, aur kyun."""
    if name in ("light", "lamp"):
        return occupied, "Room occupied" if occupied else "Room empty"
    if config.FAN_NEEDS_OCCUPANCY and not occupied:
        return False, "Room empty"
    if temp is None:
        return False, "No temperature reading"
    off_below = threshold - config.FAN_HYSTERESIS if currently_on else threshold
    if temp >= threshold:
        return True, f"{temp}°C ≥ {threshold}°C"
    if temp >= off_below:
        return True, f"{temp}°C, OFF below {off_below}°C"
    return False, f"{temp}°C < {off_below}°C"


def control_loop():
    global day
    last_tick = time.time()
    last_save = time.time()
    # Pehla sensor log start ke 5s baad (tab tak ESP32 se temperature aa chuka hoga)
    last_sensor_log = time.time() - config.SENSOR_LOG_INTERVAL_SECONDS + 5

    while True:
        now = time.time()
        dt = min(now - last_tick, 5.0)  # bada gap (sleep/hang) ko energy me mat jodo
        last_tick = now

        with lock:
            present_now = vision["person"] or sensors["pir"]
            if present_now:
                occupancy["last_presence"] = now
            occupied = present_now or (now - occupancy["last_presence"] <= config.TIMEOUT_SECONDS
                                       and occupancy["occupied"])
            occ_changed = occupied != occupancy["occupied"]
            occupancy["occupied"] = occupied
            temp = sensors["temp"]
            threshold = settings["fan_threshold"]
            plan = {}
            for name, d in devices.items():
                if d["mode"] == "auto":
                    want, reason = decide(name, occupied, temp, d["state"], threshold)
                    d["reason"] = f"Auto: {reason}"
                else:
                    want = d["mode"] == "on"
                    d["reason"] = f"Manual {d['mode'].upper()}"
                if want != d["state"] and now >= d["next_retry"]:
                    plan[name] = want

        if occ_changed:
            add_event("occupancy", "Human detected - room occupied" if occupied
                      else f"Room empty for {config.TIMEOUT_SECONDS}s")

        for name, want in plan.items():
            ok = send_command(name, want)
            with lock:
                if ok:
                    devices[name]["state"] = want
                else:
                    devices[name]["next_retry"] = time.time() + 3
            if ok:
                add_event("device", f"{name.title()} turned {'ON' if want else 'OFF'}")
            else:
                print(f"Error: {name} command fail - Node-RED/ESP32 check karo")

        # --- Energy accounting ---
        date = today_str()
        with lock:
            if date != day["date"]:  # midnight: purana din save, naya shuru
                save_day_record(day)
                day = storage.get_day(date) or new_day(date)
            # ESP pehle mila tha par ab offline -> relay state pata nahi, count mat karo
            countable = sensors["esp_online"] or not sensors["ever_seen"]
            if countable:
                for name in DEVICES:
                    if devices[name]["state"]:
                        day[f"{name}_on_s"] += dt
            if occupied:
                day["occupied_s"] += dt
            log_sensor = now - last_sensor_log >= config.SENSOR_LOG_INTERVAL_SECONDS
            if log_sensor:
                last_sensor_log = now
                if temp is not None:
                    day["temp_sum"] += temp
                    day["temp_count"] += 1
                    day["temp_min"] = temp if day["temp_min"] is None else min(day["temp_min"], temp)
                    day["temp_max"] = temp if day["temp_max"] is None else max(day["temp_max"], temp)
                sensor_snapshot = {"temp": temp, "humidity": sensors["humidity"], "occupied": occupied,
                                   **{n: devices[n]["state"] for n in DEVICES}}
            snapshot = dict(day) if now - last_save >= config.SAVE_INTERVAL_SECONDS else None

        if log_sensor:
            storage.log_sensor(sensor_snapshot)
        if snapshot:
            save_day_record(snapshot)
            last_save = now

        time.sleep(0.5)


# ---------------- FLASK ROUTES ----------------
# Dashboard Node-RED me hai (node-red/flows.json); Python sirf API + camera stream deta hai
@app.route("/")
def dashboard():
    return redirect(f"http://{request.host.split(':')[0]}:1880/ui")


@app.route("/video_feed")
def video_feed():
    def stream():
        while True:
            with lock:
                jpeg = vision["jpeg"]
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            time.sleep(0.05)
    return Response(stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def api_status():
    now = time.time()
    with lock:
        kwh, total, cost = day_energy(day)
        present_now = vision["person"] or sensors["pir"]
        countdown = 0
        if occupancy["occupied"] and not present_now:
            countdown = max(0, int(config.TIMEOUT_SECONDS - (now - occupancy["last_presence"])) + 1)
        return jsonify({
            "time": datetime.now().strftime("%d %b %Y, %I:%M:%S %p"),
            "occupancy": {"occupied": occupancy["occupied"], "camera": vision["person"],
                          "pir": sensors["pir"], "countdown": countdown},
            "sensors": {"temp": sensors["temp"], "humidity": sensors["humidity"],
                        "esp_online": sensors["esp_online"], "camera_ok": vision["camera_ok"]},
            "devices": {n: {"mode": d["mode"], "state": d["state"], "reason": d["reason"],
                            "watts": config.DEVICE_WATTS[n], "on_hours": round(day[f"{n}_on_s"] / 3600, 2),
                            "kwh": round(kwh[n], 3)}
                        for n, d in devices.items()},
            "settings": {"fan_threshold": settings["fan_threshold"], "fan_hysteresis": config.FAN_HYSTERESIS,
                         "fan_needs_occupancy": config.FAN_NEEDS_OCCUPANCY, "rate": config.RATE_PER_KWH,
                         "timeout": config.TIMEOUT_SECONDS},
            "today": {"date": day["date"], "kwh": round(total, 3), "cost": round(cost, 2),
                      "occupied_h": round(day["occupied_s"] / 3600, 2)},
            "db_backend": storage.backend,
            "events": list(recent_events),
        })


@app.route("/api/device/<name>", methods=["POST"])
def api_device(name):
    mode = (request.get_json(silent=True) or {}).get("mode")
    if name not in devices or mode not in ("auto", "on", "off"):
        return jsonify({"error": "invalid device or mode"}), 400
    with lock:
        devices[name]["mode"] = mode
        devices[name]["next_retry"] = 0.0
    # Firestore slow ho toh dashboard ka request atke nahi
    threading.Thread(target=persist_settings, daemon=True).start()
    add_event("mode", f"{name.title()} set to {mode.upper()}")
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    try:
        threshold = float((request.get_json(silent=True) or {})["fan_threshold"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "fan_threshold required"}), 400
    if not 0 <= threshold <= 50:
        return jsonify({"error": "threshold 0-50 ke beech hona chahiye"}), 400
    with lock:
        settings["fan_threshold"] = threshold
    threading.Thread(target=persist_settings, daemon=True).start()
    add_event("settings", f"Fan threshold set to {threshold}°C")
    return jsonify({"ok": True})


@app.route("/api/history")
def api_history():
    """Charts ke liye pichle N ghante ke sensor logs (temperature, humidity, occupancy)."""
    try:
        hours = min(max(float(request.args.get("hours", 6)), 0.5), 72)
    except ValueError:
        hours = 6
    since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    points = [{"t": p["time"], "temp": p.get("temp"), "humidity": p.get("humidity"),
               "occupied": bool(p.get("occupied"))} for p in storage.get_sensor_logs(since)]
    with lock:
        threshold = settings["fan_threshold"]
    return jsonify({"hours": hours, "fan_threshold": threshold, "points": points})


@app.route("/api/days")
def api_days():
    """Pichle N din ka energy (har din ek row, jis din data nahi wo 0)."""
    try:
        n = min(max(int(request.args.get("n", 7)), 1), 31)
    except ValueError:
        n = 7
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]
    found = {d["date"]: d for d in storage.get_days(dates[0], dates[-1])}
    with lock:
        found[day["date"]] = dict(day)  # aaj ka live data
    return jsonify({"days": [day_row(found.get(d) or new_day(d)) for d in dates]})


def month_summary(month_param):
    try:
        target = datetime.strptime(month_param, "%Y-%m") if month_param else datetime.now()
    except ValueError:
        target = datetime.now()
    days = storage.get_month(target.year, target.month)
    # Aaj ka live data (DB me 30s purana ho sakta hai) use karo
    with lock:
        live = dict(day)
    if live["date"].startswith(target.strftime("%Y-%m")):
        days = [d for d in days if d["date"] != live["date"]] + [live]
        days.sort(key=lambda d: d["date"])
    return summarize_month(target.year, target.month, days)


@app.route("/api/report")
def api_report():
    return jsonify(month_summary(request.args.get("month")))


@app.route("/report/pdf")
def report_pdf():
    summary = month_summary(request.args.get("month"))
    pdf = build_pdf(summary)
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=PowerSense_Report_{summary['month']}.pdf"})


if __name__ == "__main__":
    add_event("system", f"PowerSense started (DB: {storage.backend})")
    for target in (vision_loop, sensor_loop, control_loop):
        threading.Thread(target=target, daemon=True).start()
    print("⚡ PowerSense API: http://127.0.0.1:5000  |  Dashboard (Node-RED): http://127.0.0.1:1880/ui")
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    finally:
        # Band hote waqt aaj ka data save karo
        with lock:
            final = dict(day)
        save_day_record(final)
        print("Aaj ka data save ho gaya. Bye!")
