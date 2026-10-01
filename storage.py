"""Database layer: Firebase Firestore, aur agar key na ho toh local JSON fallback.

Firestore collections:
  daily_usage/{YYYY-MM-DD}  -> din bhar ka usage (on-time, kWh, bill, temperature)
  events/{auto}             -> device ON/OFF aur occupancy change log
  sensor_logs/{auto}        -> har minute temperature/humidity/occupancy
  settings/app              -> fan threshold, device modes
"""
import json
import os
import threading
from datetime import datetime


class Storage:
    def __init__(self, firebase_key_path, local_db_path):
        self.db = None
        self.backend = "local"
        self.local_db_path = local_db_path
        self._lock = threading.Lock()

        if os.path.exists(firebase_key_path):
            try:
                import firebase_admin
                from firebase_admin import credentials, firestore

                if not firebase_admin._apps:
                    firebase_admin.initialize_app(credentials.Certificate(firebase_key_path))
                db = firestore.client()
                db.collection("settings").document("app").get(timeout=10)  # connection test
                self.db = db
                self.backend = "firestore"
                print("Database: Firebase Firestore connected")
            except Exception as e:
                print(f"Firestore connect nahi hua ({str(e).splitlines()[0][:200]}) -> local JSON use karenge")

        if self.db is None:
            print(f"Database: Local JSON ({local_db_path}) - Firebase key nahi mili")
            os.makedirs(os.path.dirname(local_db_path) or ".", exist_ok=True)
            self._local = self._load_local()

    # ---------- local JSON helpers ----------
    def _load_local(self):
        if os.path.exists(self.local_db_path):
            try:
                with open(self.local_db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {"daily_usage": {}, "events": [], "sensor_logs": [], "settings": {}}

    def _flush_local(self):
        tmp = self.local_db_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._local, f, indent=1)
        os.replace(tmp, self.local_db_path)

    # ---------- daily usage ----------
    def get_day(self, date_str):
        try:
            if self.db:
                snap = self.db.collection("daily_usage").document(date_str).get()
                return snap.to_dict() if snap.exists else None
            with self._lock:
                return dict(self._local["daily_usage"].get(date_str) or {}) or None
        except Exception as e:
            print(f"DB read error (get_day): {e}")
            return None

    def save_day(self, date_str, data):
        try:
            if self.db:
                self.db.collection("daily_usage").document(date_str).set(data)
                return True
            with self._lock:
                self._local["daily_usage"][date_str] = data
                self._flush_local()
            return True
        except Exception as e:
            print(f"DB write error (save_day): {e}")
            return False

    def get_month(self, year, month):
        return self.get_days(f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-31")

    def get_days(self, start, end):
        """start se end (YYYY-MM-DD, dono shamil) tak ke daily_usage records."""
        try:
            if self.db:
                docs = (self.db.collection("daily_usage")
                        .where("date", ">=", start)
                        .where("date", "<=", end)
                        .stream())
                days = [d.to_dict() for d in docs]
            else:
                with self._lock:
                    days = [dict(v) for k, v in self._local["daily_usage"].items() if start <= k <= end]
            return sorted(days, key=lambda d: d["date"])
        except Exception as e:
            print(f"DB read error (get_days): {e}")
            return []

    def get_sensor_logs(self, since_iso):
        """since_iso ke baad ke sensor logs (charts ke liye), purane se naye."""
        try:
            if self.db:
                docs = (self.db.collection("sensor_logs")
                        .where("time", ">=", since_iso)
                        .order_by("time")
                        .limit(3000)
                        .stream())
                return [d.to_dict() for d in docs]
            with self._lock:
                return [dict(e) for e in self._local["sensor_logs"] if e["time"] >= since_iso]
        except Exception as e:
            print(f"DB read error (get_sensor_logs): {e}")
            return []

    # ---------- logs ----------
    def log_event(self, kind, detail):
        entry = {"time": datetime.now().isoformat(timespec="seconds"), "kind": kind, "detail": detail}
        try:
            if self.db:
                self.db.collection("events").add(entry)
            else:
                with self._lock:
                    self._local["events"].append(entry)
                    self._local["events"] = self._local["events"][-2000:]
                    self._flush_local()
        except Exception as e:
            print(f"DB write error (log_event): {e}")

    def log_sensor(self, data):
        entry = {"time": datetime.now().isoformat(timespec="seconds"), **data}
        try:
            if self.db:
                self.db.collection("sensor_logs").add(entry)
            else:
                with self._lock:
                    self._local["sensor_logs"].append(entry)
                    self._local["sensor_logs"] = self._local["sensor_logs"][-5000:]
                    self._flush_local()
        except Exception as e:
            print(f"DB write error (log_sensor): {e}")

    # ---------- settings ----------
    def get_settings(self):
        try:
            if self.db:
                snap = self.db.collection("settings").document("app").get()
                return snap.to_dict() if snap.exists else {}
            with self._lock:
                return dict(self._local.get("settings", {}))
        except Exception as e:
            print(f"DB read error (get_settings): {e}")
            return {}

    def save_settings(self, data):
        try:
            if self.db:
                self.db.collection("settings").document("app").set(data)
            else:
                with self._lock:
                    self._local["settings"] = data
                    self._flush_local()
        except Exception as e:
            print(f"DB write error (save_settings): {e}")
