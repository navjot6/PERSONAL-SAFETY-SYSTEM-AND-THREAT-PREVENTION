import random
import threading
import os
import time
import math

import cv2
import folium
import numpy as np
from flask import Flask, Response, jsonify, render_template, request

from alert import send_alert_email_detailed
from database import add_alert, get_alerts_filtered, get_db_connection, init_db, set_email_status
from detection import ThreatDetector

# Reduce noisy logs from TensorFlow/absl during local runs.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("ABSL_MIN_LOG_LEVEL", "2")
os.environ.setdefault("GLOG_minloglevel", "2")

app = Flask(__name__)

# Threshold tuned for the more sensitive, motion-aware detector.
detector = ThreatDetector(threshold=0.5, cooldown_seconds=25)
camera_lock = threading.Lock()
camera = None
latest_jpeg = None
latest_jpeg_lock = threading.Lock()
camera_open = False
capture_thread = None
location_lock = threading.Lock()
latest_client_location = None


def _open_camera():
    global camera
    if camera is None:
        camera = cv2.VideoCapture(0)
    return camera is not None and camera.isOpened()


def _close_camera():
    global camera
    if camera is not None:
        camera.release()
        camera = None


def _record_alert(message: str, latitude: float, longitude: float):
    alert_id = add_alert(message=message, latitude=latitude, longitude=longitude)
    ok, err = send_alert_email_detailed(message=message, latitude=latitude, longitude=longitude)
    set_email_status(alert_id=alert_id, email_sent=ok, email_error=err)


def _generate_location():
    # Prefer live browser geolocation when available (recent update),
    # otherwise fall back to a Punjab-centered demo location.
    with location_lock:
        current = latest_client_location

    if current and (time.time() - current["updated_at"] <= 180):
        base_lat, base_lon = current["latitude"], current["longitude"]
        jitter = 0.0008
    else:
        base_lat, base_lon = 31.1471, 75.3412
        jitter = 0.01

    return (
        round(base_lat + random.uniform(-jitter, jitter), 6),
        round(base_lon + random.uniform(-jitter, jitter), 6),
    )


def _get_live_or_fallback_center():
    # Returns (lat, lon, is_live)
    with location_lock:
        current = latest_client_location
    if current and (time.time() - current["updated_at"] <= 180):
        return float(current["latitude"]), float(current["longitude"]), True
    return 31.1471, 75.3412, False


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    # Great-circle distance in kilometers.
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _filter_points_by_radius(points, center_lat, center_lon, radius_km):
    filtered = []
    for p in points:
        try:
            km = _haversine_km(center_lat, center_lon, float(p["latitude"]), float(p["longitude"]))
        except (TypeError, ValueError):
            continue
        if km <= radius_km:
            filtered.append(p)
    return filtered

def _capture_loop():
    global latest_jpeg, camera_open

    # Basic placeholder shown until the first camera frame arrives.
    placeholder = 255 * np.ones((480, 640, 3), dtype=np.uint8)
    cv2.putText(
        placeholder,
        "Starting camera...",
        (30, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 0, 0),
        2,
    )
    ok, buf = cv2.imencode(".jpg", placeholder)
    if ok:
        with latest_jpeg_lock:
            latest_jpeg = buf.tobytes()

    while True:
        with camera_lock:
            ok_camera = _open_camera()
            camera_open = ok_camera
            detector.set_camera_open(camera_open)
            if not ok_camera:
                frame = None
            else:
                ret, frame = camera.read()
                if not ret or frame is None or frame.size == 0:
                    frame = None

        if not camera_open:
            import time

            time.sleep(0.5)
            continue

        if frame is None:
            import time

            time.sleep(0.05)
            continue

        if not detector.monitoring:
            cv2.putText(
                frame,
                "Monitoring stopped. Click Start Monitoring.",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )
            processed = frame
            event = None
        else:
            processed, event = detector.process_frame(frame)

        if event is not None:
            lat, lon = _generate_location()
            threading.Thread(
                target=_record_alert,
                args=(event["message"], lat, lon),
                daemon=True,
            ).start()

        ok, buffer = cv2.imencode(".jpg", processed)
        if not ok:
            continue

        with latest_jpeg_lock:
            latest_jpeg = buffer.tobytes()


def _stream_frames():
    import time

    # Stream at a modest rate to reduce CPU load.
    while True:
        with latest_jpeg_lock:
            jpeg = latest_jpeg
        if jpeg is None:
            time.sleep(0.05)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg
            + b"\r\n"
        )
        time.sleep(0.05)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(
        _stream_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/monitor/start", methods=["POST"])
def start_monitoring():
    detector.set_monitoring(True)
    return jsonify({"ok": True, "monitoring": True})


@app.route("/api/monitor/stop", methods=["POST"])
def stop_monitoring():
    detector.set_monitoring(False)
    return jsonify({"ok": True, "monitoring": False})


@app.route("/api/status")
def status():
    db_connected = False
    try:
        conn = get_db_connection()
        conn.close()
        db_connected = True
    except Exception:
        db_connected = False

    data = detector.get_status()
    data["db_status"] = "connected" if db_connected else "disconnected"
    with location_lock:
        current = latest_client_location
    if current and (time.time() - current["updated_at"] <= 180):
        data["location_status"] = "live"
        data["location_latitude"] = current["latitude"]
        data["location_longitude"] = current["longitude"]
    else:
        data["location_status"] = "fallback"
    return jsonify(data)


@app.route("/api/alerts")
def alerts():
    limit = int(request.args.get("limit", 20))
    hours = int(request.args.get("hours", 6))
    radius_km = float(request.args.get("radius_km", 300))

    points = get_alerts_filtered(limit=limit, hours=hours)
    center_lat, center_lon, _ = _get_live_or_fallback_center()
    points = _filter_points_by_radius(points, center_lat, center_lon, radius_km)
    return jsonify(points)


@app.route("/api/location", methods=["POST"])
def update_location():
    payload = request.get_json(silent=True) or {}
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid latitude/longitude"}), 400

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"ok": False, "error": "Out-of-range latitude/longitude"}), 400

    with location_lock:
        global latest_client_location
        latest_client_location = {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "updated_at": time.time(),
        }

    return jsonify({"ok": True, "location_status": "live"})


@app.route("/api/map")
def map_view():
    hours = int(request.args.get("hours", 6))
    radius_km = float(request.args.get("radius_km", 700))
    points = get_alerts_filtered(limit=200, hours=hours)

    center_lat, center_lon, is_live = _get_live_or_fallback_center()
    points = _filter_points_by_radius(points, center_lat, center_lon, radius_km)
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=11)
    for point in points:
        folium.Marker(
            location=[point["latitude"], point["longitude"]],
            popup=f'{point["created_at"]}: {point["message"]}',
            icon=folium.Icon(color="red", icon="warning-sign"),
        ).add_to(fmap)
    # Use the raw Folium render so the iframe works outside Jupyter notebooks.
    return fmap.get_root().render()


@app.route("/api/test_email", methods=["POST"])
def test_email():
    # Local debug endpoint to verify SMTP works.
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "TEST ALERT - Edge AI Personal Safety")
    record = bool(payload.get("record", True))
    lat = payload.get("latitude")
    lon = payload.get("longitude")

    if lat is None or lon is None:
        center_lat, center_lon, _ = _get_live_or_fallback_center()
        lat, lon = center_lat, center_lon

    ok, err = send_alert_email_detailed(
        message=message,
        latitude=float(lat),
        longitude=float(lon),
    )

    alert_id = None
    if record:
        alert_id = add_alert(message=message, latitude=float(lat), longitude=float(lon))
        set_email_status(alert_id=alert_id, email_sent=ok, email_error=err)

    return jsonify({"ok": bool(ok), "message": message, "alert_id": alert_id})


if __name__ == "__main__":
    init_db()
    # Start capture thread once.
    capture_thread = threading.Thread(target=_capture_loop, daemon=True)
    capture_thread.start()
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=5000, debug=debug, threaded=True)
