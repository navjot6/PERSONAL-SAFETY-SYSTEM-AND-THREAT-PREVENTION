import random
import threading
import os
import time
import math
import sqlite3
from functools import wraps
from pathlib import Path

import cv2
import folium
import numpy as np
from dotenv import load_dotenv
from flask import (
    Flask, Response, jsonify, render_template,
    request, redirect, url_for, session,
)
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from werkzeug.security import check_password_hash, generate_password_hash

from alert import send_alert_email_detailed
from database import (
    add_alert, get_alerts_filtered, get_db_connection,
    init_db, set_email_status, get_or_create_google_user,
)
from detection import ThreatDetector

# ── Suppress TF / absl noise ──────────────────────────────────────────────────
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("ABSL_MIN_LOG_LEVEL", "2")
os.environ.setdefault("GLOG_minloglevel", "2")

# ── Load environment from project .env ────────────────────────────────────────
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path, override=False)

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "change-me-use-a-long-random-string"

# ── Google OAuth client ID ────────────────────────────────────────────────────
# Set GOOGLE_CLIENT_ID in your .env file (same file as ALERT_SENDER_EMAIL etc.)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# ── Detector & camera globals ─────────────────────────────────────────────────
detector        = ThreatDetector(threshold=0.5, cooldown_seconds=25)
camera_lock     = threading.Lock()
camera          = None
latest_jpeg     = None
latest_jpeg_lock = threading.Lock()
camera_open     = False
capture_thread  = None
location_lock   = threading.Lock()
latest_client_location = None
_runtime_started = False


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    """Redirect unauthenticated users to /login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def _parse_int_arg(name: str, default: int, min_value: int, max_value: int):
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"Invalid '{name}': expected integer"
    if value < min_value or value > max_value:
        return None, f"Invalid '{name}': must be between {min_value} and {max_value}"
    return value, None


def _parse_float_arg(name: str, default: float, min_value: float, max_value: float):
    raw = request.args.get(name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"Invalid '{name}': expected number"
    if value < min_value or value > max_value:
        return None, f"Invalid '{name}': must be between {min_value} and {max_value}"
    return value, None


def _safe_float(value, field_name: str):
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, f"Invalid '{field_name}': expected number"


def _ensure_auth_users_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            operator_id TEXT UNIQUE,
            password_hash TEXT,
            google_id   TEXT UNIQUE,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def _operator_id_from_email(email: str) -> str:
    return (email.split("@")[0] if "@" in email else email).strip().lower()

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


def _record_alert(message: str, latitude: float, longitude: float, snapshot: str = None):
    alert_id = add_alert(message=message, latitude=latitude, longitude=longitude, snapshot=snapshot)
    ok, err = send_alert_email_detailed(message=message, latitude=latitude, longitude=longitude)
    set_email_status(alert_id=alert_id, email_sent=ok, email_error=err)

def _generate_location():
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
    with location_lock:
        current = latest_client_location
    if current and (time.time() - current["updated_at"] <= 180):
        return float(current["latitude"]), float(current["longitude"]), True
    return 31.1471, 75.3412, False


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _filter_points_by_radius(points, center_lat, center_lon, radius_km):
    filtered = []
    for p in points:
        try:
            km = _haversine_km(center_lat, center_lon,
                               float(p["latitude"]), float(p["longitude"]))
        except (TypeError, ValueError):
            continue
        if km <= radius_km:
            filtered.append(p)
    return filtered


def _capture_loop():
    global latest_jpeg, camera_open

    placeholder = 255 * np.ones((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, "Starting camera...", (30, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".jpg", placeholder)
    if ok:
        with latest_jpeg_lock:
            latest_jpeg = buf.tobytes()

    while True:
        with camera_lock:
            ok_camera = _open_camera()
            camera_open = ok_camera
            detector.set_camera_open(camera_open)
            frame = None
            if ok_camera:
                ret, frame = camera.read()
                if not ret or frame is None or frame.size == 0:
                    frame = None

        if not camera_open:
            time.sleep(0.5)
            continue
        if frame is None:
            time.sleep(0.05)
            continue

        if not detector.monitoring:
            cv2.putText(frame, "Monitoring stopped. Click Start Monitoring.",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            processed, event = frame, None
        else:
            processed, event = detector.process_frame(frame)

       if event is not None:
        lat, lon = _generate_location()
        snapshot_dir = os.path.join("static", "snapshots")
        os.makedirs(snapshot_dir, exist_ok=True)
        snapshot_filename = f"alert_{int(time.time())}.jpg"
        snapshot_path = os.path.join(snapshot_dir, snapshot_filename)
        cv2.imwrite(snapshot_path, processed)
        threading.Thread(
            target=_record_alert,
            args=(event["message"], lat, lon, snapshot_filename),
            daemon=True,
            ).start()

        ok, buffer = cv2.imencode(".jpg", processed)
        if not ok:
            continue
        with latest_jpeg_lock:
            latest_jpeg = buffer.tobytes()


def _stream_frames():
    while True:
        with latest_jpeg_lock:
            jpeg = latest_jpeg
        if jpeg is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        time.sleep(0.05)


# ─────────────────────────────────────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/login")
def login_page():
    if "user" in session:
        return redirect(url_for("index"))
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/login", methods=["POST"])
def login_submit():
    identifier = (request.form.get("identifier") or "").strip().lower()
    password = request.form.get("password") or ""

    if not identifier or not password:
        return render_template(
            "login.html",
            google_client_id=GOOGLE_CLIENT_ID,
            error="Email/Operator ID and password are required.",
            identifier=identifier,
        ), 400

    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT id, name, email, operator_id, password_hash, google_id
        FROM auth_users
        WHERE lower(email) = ? OR lower(operator_id) = ?
        """,
        (identifier, identifier),
    ).fetchone()
    conn.close()

    if not row or not row["password_hash"] or not check_password_hash(row["password_hash"], password):
        return render_template(
            "login.html",
            google_client_id=GOOGLE_CLIENT_ID,
            error="Invalid email/operator ID or password.",
            identifier=identifier,
        ), 401

    session["user"] = {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "picture": "",
    }
    return redirect(url_for("index"))


@app.route("/signup")
def signup_page():
    return redirect(url_for("register_page"))


@app.route("/register")
def register_page():
    if "user" in session:
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/register", methods=["POST"])
def register_submit():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not name or not email or not password:
        return render_template(
            "register.html",
            error="All fields are required.",
            name=name,
            email=email,
        ), 400

    if "@" not in email or "." not in email.split("@")[-1]:
        return render_template(
            "register.html",
            error="Please enter a valid email address.",
            name=name,
            email=email,
        ), 400

    operator_id = _operator_id_from_email(email)
    hashed_password = generate_password_hash(password)

    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO auth_users (name, email, operator_id, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, operator_id, hashed_password),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return render_template(
            "register.html",
            error="Account already exists. Please use a different email.",
            name=name,
            email=email,
        ), 409
    finally:
        if conn is not None:
            conn.close()

    return redirect(url_for("login_page"))


@app.route("/auth/google", methods=["POST"])
def google_auth():
    """
    Receives the Google credential token from the frontend,
    verifies it server-side, then creates/updates the user in SQLite
    and stores minimal info in the Flask session.
    """
    if not GOOGLE_CLIENT_ID:
        return jsonify({"ok": False,
                        "error": "GOOGLE_CLIENT_ID not configured in .env"}), 500

    payload = request.get_json(silent=True) or {}
    token   = payload.get("token", "")

    if not token:
        return jsonify({"ok": False, "error": "No credential token received"}), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            token, grequests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": f"Token verification failed: {exc}"}), 401

    google_id = idinfo["sub"]
    email     = idinfo.get("email", "")
    name      = idinfo.get("name", "")
    picture   = idinfo.get("picture", "")

    user = get_or_create_google_user(
        google_id=google_id,
        email=email,
        name=name,
        picture=picture,
    )

    conn = get_db_connection()
    existing = conn.execute(
        "SELECT id FROM auth_users WHERE lower(email) = ? OR google_id = ?",
        (email.lower(), google_id),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE auth_users
            SET name = ?, email = ?, operator_id = ?, google_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, email.lower(), _operator_id_from_email(email), google_id, existing["id"]),
        )
        auth_id = existing["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO auth_users (name, email, operator_id, google_id)
            VALUES (?, ?, ?, ?)
            """,
            (name, email.lower(), _operator_id_from_email(email), google_id),
        )
        auth_id = cur.lastrowid
    conn.commit()
    conn.close()

    session["user"] = {
        "id":      auth_id,
        "name":    name,
        "email":   email,
        "picture": picture,
    }

    return jsonify({"ok": True, "user": session["user"], "redirect": url_for("index")})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/api/me")
@login_required
def me():
    return jsonify(session.get("user", {}))

@app.route("/")
@login_required
def index():
    return render_template(
        "index.html",
        user=session["user"],
        google_client_id=GOOGLE_CLIENT_ID,
    )


@app.route("/video_feed")
@login_required
def video_feed():
    return Response(_stream_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/monitor/start", methods=["POST"])
@login_required
def start_monitoring():
    detector.set_monitoring(True)
    return jsonify({"ok": True, "monitoring": True})


@app.route("/api/monitor/stop", methods=["POST"])
@login_required
def stop_monitoring():
    detector.set_monitoring(False)
    return jsonify({"ok": True, "monitoring": False})


@app.route("/api/status")
@login_required
def status():
    db_connected = False
    try:
        conn = get_db_connection()
        conn.close()
        db_connected = True
    except Exception:
        pass

    data = detector.get_status()
    data["db_status"] = "connected" if db_connected else "disconnected"

    with location_lock:
        current = latest_client_location
    if current and (time.time() - current["updated_at"] <= 180):
        data["location_status"]    = "live"
        data["location_latitude"]  = current["latitude"]
        data["location_longitude"] = current["longitude"]
    else:
        data["location_status"] = "fallback"

    return jsonify(data)


@app.route("/api/alerts")
@login_required
def alerts():
    limit, err = _parse_int_arg("limit", default=20, min_value=1, max_value=200)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    hours, err = _parse_int_arg("hours", default=6, min_value=1, max_value=168)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    radius_km, err = _parse_float_arg("radius_km", default=300.0, min_value=0.1, max_value=5000.0)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    points = get_alerts_filtered(limit=limit, hours=hours)
    center_lat, center_lon, _ = _get_live_or_fallback_center()
    points = _filter_points_by_radius(points, center_lat, center_lon, radius_km)
    return jsonify(points)


@app.route("/api/location", methods=["POST"])
@login_required
def update_location():
    payload   = request.get_json(silent=True) or {}
    latitude  = payload.get("latitude")
    longitude = payload.get("longitude")

    try:
        latitude  = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid latitude/longitude"}), 400

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"ok": False, "error": "Out-of-range latitude/longitude"}), 400

    with location_lock:
        global latest_client_location
        latest_client_location = {
            "latitude":   round(latitude, 6),
            "longitude":  round(longitude, 6),
            "updated_at": time.time(),
        }
    return jsonify({"ok": True, "location_status": "live"})


@app.route("/api/map")
@login_required
def map_view():
    hours, err = _parse_int_arg("hours", default=6, min_value=1, max_value=168)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    radius_km, err = _parse_float_arg("radius_km", default=700.0, min_value=0.1, max_value=5000.0)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    points    = get_alerts_filtered(limit=200, hours=hours)

    center_lat, center_lon, _ = _get_live_or_fallback_center()
    points = _filter_points_by_radius(points, center_lat, center_lon, radius_km)

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=11)
    for point in points:
        folium.Marker(
            location=[point["latitude"], point["longitude"]],
            popup=f'{point["created_at"]}: {point["message"]}',
            icon=folium.Icon(color="red", icon="warning-sign"),
        ).add_to(fmap)
    return fmap.get_root().render()


@app.route("/api/test_email", methods=["POST"])
@login_required
def test_email():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "TEST ALERT - Edge AI Personal Safety")
    record  = bool(payload.get("record", True))
    lat     = payload.get("latitude")
    lon     = payload.get("longitude")

    if lat is None or lon is None:
        center_lat, center_lon, _ = _get_live_or_fallback_center()
        lat, lon = center_lat, center_lon

    lat_f, lat_err = _safe_float(lat, "latitude")
    if lat_err:
        return jsonify({"ok": False, "error": lat_err}), 400

    lon_f, lon_err = _safe_float(lon, "longitude")
    if lon_err:
        return jsonify({"ok": False, "error": lon_err}), 400

    ok, err = send_alert_email_detailed(
        message=message, latitude=lat_f, longitude=lon_f
    )
    alert_id = None
    if record:
        alert_id = add_alert(message=message, latitude=lat_f, longitude=lon_f)
        set_email_status(alert_id=alert_id, email_sent=ok, email_error=err)

    return jsonify({"ok": bool(ok), "message": message, "alert_id": alert_id})


def _start_runtime():
    global _runtime_started, capture_thread
    if _runtime_started:
        return
    init_db()
    _ensure_auth_users_table()
    capture_thread = threading.Thread(target=_capture_loop, daemon=True)
    capture_thread.start()
    _runtime_started = True

@app.before_request
def _ensure_runtime_started():
    _start_runtime()

if __name__ == "__main__":
    _start_runtime()
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=5000, debug=debug, threaded=True)
