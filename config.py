# --- POWERSENSE CONFIGURATION ---
# Saari settings yaha ek jagah. Code me kahin aur hard-code mat karna.

# Node-RED bridge (Python -> Node-RED -> ESP32)
# ESP32 ka IP sirf Node-RED flow me set karna hai, yaha nahi.
NODE_RED_CONTROL_URL = "http://127.0.0.1:1880/ai-control"   # ?state=/LIGHT=ON
NODE_RED_STATUS_URL = "http://127.0.0.1:1880/sensor-status"  # ESP32 ka /STATUS JSON

# Camera
CAMERA_INDEX = 0
YOLO_MODEL = "yolo11n.pt"

# Occupancy: camera ya PIR me se koi bhi insaan dikhaye -> room occupied.
# Itne seconds tak dono me kuch nahi mila -> room empty -> appliances OFF.
TIMEOUT_SECONDS = 5

# Fan: temperature >= threshold -> fan apne aap ON
FAN_TEMP_THRESHOLD = 20.0   # degree Celsius
FAN_HYSTERESIS = 0.5        # threshold - 0.5 se neeche jaaye tab hi OFF (bar bar on/off na ho)
FAN_NEEDS_OCCUPANCY = False # True = fan sirf tab chale jab room me koi ho

# Appliance ratings (Watt) -> energy aur bill calculate karne ke liye
DEVICE_WATTS = {
    "light": 40,
    "lamp": 60,
    "fan": 75,
}

# Electricity rate (Rupees per kWh / unit)
RATE_PER_KWH = 8.0

# Firebase service account key (Firebase Console -> Project Settings ->
# Service accounts -> Generate new private key). File na mile toh data
# local JSON file me save hoga (data/local_db.json).
FIREBASE_KEY_PATH = "serviceAccountKey.json"
LOCAL_DB_PATH = "data/local_db.json"

# Kitni der me data database me save ho (seconds)
SAVE_INTERVAL_SECONDS = 30
SENSOR_LOG_INTERVAL_SECONDS = 60
SENSOR_POLL_SECONDS = 1.0
