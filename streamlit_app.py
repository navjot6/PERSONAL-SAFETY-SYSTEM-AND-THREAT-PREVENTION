import streamlit as st
import cv2
import numpy as np
import pandas as pd
import time
import os
import re
from datetime import datetime
from ultralytics import YOLO
from PIL import Image
import smtplib
from email.message import EmailMessage
import plotly.express as px

# ==========================================
# PAGE CONFIG
# ==========================================

st.set_page_config(
    page_title="Edge AI Based Personal Safety System and Threat Prevention",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

# ==========================================
# LOGIN + SIGNUP SYSTEM
# ==========================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "registered_user" not in st.session_state:
    st.session_state.registered_user = "Admin@2025"

if "registered_pass" not in st.session_state:
    st.session_state.registered_pass = "Secure@123AI"

if not st.session_state.logged_in:

    auth_tab1, auth_tab2 = st.tabs(["🔐 Login", "📝 Signup"])

    # ==========================================
    # LOGIN PAGE
    # ==========================================

    with auth_tab1:

        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:

            st.title("🛡️ Edge AI Security Login")
            st.subheader("Edge AI Personal Safety & Threat Prevention")

            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")

            if st.button("Login", use_container_width=True):

                if (
                    username == st.session_state.registered_user
                    and password == st.session_state.registered_pass
                ):
                    st.session_state.logged_in = True
                    st.success("Login Successful")
                    st.rerun()

                else:
                    st.error("Invalid Username or Password")

    # ==========================================
    # SIGNUP PAGE
    # ==========================================

    with auth_tab2:

        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:

            st.title("📝 Create Account")
            st.subheader("Register for Edge AI Safety Dashboard")

            new_user     = st.text_input("Create Username",     key="signup_user")
            new_pass     = st.text_input("Create Strong Password", type="password", key="signup_pass")
            confirm_pass = st.text_input("Confirm Password",    type="password", key="signup_confirm")

            st.info("Password must contain uppercase, lowercase, numbers and special characters")

            if st.button("Signup", use_container_width=True):

                strong_password = re.match(
                    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$',
                    new_pass
                )

                if not strong_password:
                    st.error("Weak Password! Example: Secure@123")

                elif new_pass != confirm_pass:
                    st.error("Passwords do not match")

                else:
                    st.session_state.registered_user = new_user
                    st.session_state.registered_pass = new_pass
                    st.success("Signup Successful! Please Login")

    st.stop()

# ==========================================
# LOAD MODELS  (cached so they load only once)
# ==========================================

@st.cache_resource
def load_models():
    person_model = YOLO("../models/yolov8n.pt")
    weapon_model = YOLO("../models/weapon_model.pt")
    fall_model   = YOLO("../models/fall_model.pt")
    return person_model, weapon_model, fall_model

person_model, weapon_model, fall_model = load_models()

# ==========================================
# CREATE FOLDERS
# ==========================================

os.makedirs("screenshots", exist_ok=True)
os.makedirs("reports",     exist_ok=True)

# ==========================================
# TITLE
# ==========================================

st.title("🛡️ Edge AI Based Personal Safety System and Threat Prevention")
st.caption("Real-Time AI CCTV Monitoring Dashboard")

# ==========================================
# TOP DASHBOARD CARDS  (native Streamlit metrics)
# ==========================================

card1, card2, card3 = st.columns(3)

with card1:
    st.metric(label="📍 Active Location", value="Living Room Camera")

with card2:
    st.metric(label="🛡️ Security Status", value="Monitoring Active")

with card3:
    st.metric(label="🚨 Threat Engine", value="AI Enabled")

st.divider()

# ==========================================
# SIDEBAR
# ==========================================

st.sidebar.title("⚙️ Control Panel")

camera_source        = st.sidebar.selectbox("Select Camera", [0])
confidence_threshold = st.sidebar.slider("Confidence Threshold", 0.1, 1.0, 0.5)

start_button = st.sidebar.button("▶ Start Monitoring", use_container_width=True)
stop_button  = st.sidebar.button("⛔ Stop Monitoring",  use_container_width=True)

st.sidebar.divider()
st.sidebar.subheader("📍 Location Settings")

location_name = st.sidebar.text_input("Location", "Home Camera - Living Room")
city_name     = st.sidebar.text_input("City",     "Chandigarh")
country_name  = st.sidebar.text_input("Country",  "India")

st.sidebar.divider()
st.sidebar.success("✅ AI Monitoring Connected")

# ==========================================
# EMAIL ALERT FUNCTION
# ==========================================

ALERT_RECEIVER_EMAIL = "your_receiver@gmail.com"   # ← set your alert email here

def send_email_alert(subject, body):
    try:
        sender_email    = "your_email@gmail.com"
        sender_password = "your_app_password"

        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"]    = sender_email
        msg["To"]      = ALERT_RECEIVER_EMAIL

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()

    except Exception as e:
        print("Email Error:", e)

# ==========================================
# LIVE METRICS ROW  (placeholders updated in loop)
# ==========================================

col1, col2, col3, col4 = st.columns(4)

person_metric = col1.empty()
weapon_metric = col2.empty()
fall_metric   = col3.empty()
score_metric  = col4.empty()

# ==========================================
# VIDEO + LIVE ALERT COLUMNS
# ==========================================

video_col, alert_col = st.columns([3, 1])

frame_placeholder = video_col.empty()
alert_placeholder  = alert_col.empty()

# ==========================================
# ANALYTICS CHART PLACEHOLDER
# ==========================================

chart_placeholder = st.empty()

# ==========================================
# EVENT LOGS
# ==========================================

st.subheader("📄 Event Logs")

log_table = st.empty()

logs = []

# ==========================================
# CAMERA LOOP
# ==========================================

if start_button:

    cap = cv2.VideoCapture(camera_source)

    threat_history = []

    while cap.isOpened():

        ret, frame = cap.read()

        if not ret:
            st.error("Camera not working")
            break

        # ── Counters ───────────────────────────────────────

        person_count = 0
        weapon_count = 0
        fall_count   = 0
        threat_score = 0

        # ── Person Detection ───────────────────────────────

        person_results = person_model(frame)

        for r in person_results:
            for box in r.boxes:

                cls  = int(box.cls[0])
                conf = float(box.conf[0])

                if cls == 0 and conf > confidence_threshold:

                    person_count += 1
                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        frame, "PERSON", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
                    )

        # ── Weapon Detection ───────────────────────────────

        weapon_results = weapon_model(frame)

        for r in weapon_results:
            for box in r.boxes:

                conf = float(box.conf[0])

                if conf > confidence_threshold:

                    weapon_count += 1
                    threat_score += 40

                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                    cv2.putText(
                        frame, "WEAPON DETECTED", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2
                    )

                    cv2.imwrite(f"screenshots/weapon_{time.time()}.jpg", frame)

                    logs.append({
                        "Time":     datetime.now().strftime("%H:%M:%S"),
                        "Event":    "Weapon Detection",
                        "Status":   "Critical",
                        "Location": location_name
                    })

        # ── Fall Detection ─────────────────────────────────

        fall_results = fall_model(frame)

        for r in fall_results:
            for box in r.boxes:

                conf = float(box.conf[0])

                if conf > confidence_threshold:

                    fall_count   += 1
                    threat_score += 30

                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 3)
                    cv2.putText(
                        frame, "FALL DETECTED", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2
                    )

                    cv2.imwrite(f"screenshots/fall_{time.time()}.jpg", frame)

                    logs.append({
                        "Time":     datetime.now().strftime("%H:%M:%S"),
                        "Event":    "Fall Detection",
                        "Status":   "Warning",
                        "Location": location_name
                    })

        # ── Threat Score Cap ───────────────────────────────

        threat_score = min(threat_score, 100)

        # ── Update Metrics ─────────────────────────────────

        person_metric.metric("👤 Persons",      person_count)
        weapon_metric.metric("🔫 Weapons",      weapon_count)
        fall_metric.metric(  "🤕 Falls",        fall_count)
        score_metric.metric( "⚠️ Threat Score", f"{threat_score}%")

        # ── Live Alert ─────────────────────────────────────

        if weapon_count > 0:
            alert_placeholder.error(f"🚨 Weapon Detected at {location_name}")
            send_email_alert(
                "Weapon Threat Alert",
                f"Weapon detected at {location_name}. Please check immediately."
            )

        elif fall_count > 0:
            alert_placeholder.warning(f"⚠️ Fall Detected at {location_name}")
            send_email_alert(
                "Fall Detection Alert",
                f"A person fall was detected at {location_name}."
            )

        else:
            alert_placeholder.success("✅ System Safe")

        # ── Show Video Frame ───────────────────────────────

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_placeholder.image(frame_rgb, channels="RGB", use_container_width=True)

        # ── Analytics Chart ────────────────────────────────

        threat_history.append(threat_score)

        if len(threat_history) > 20:
            threat_history.pop(0)

        df = pd.DataFrame({
            "Frame":  list(range(len(threat_history))),
            "Threat": threat_history
        })

        fig = px.line(df, x="Frame", y="Threat", title="Live Threat Analytics")
        chart_placeholder.plotly_chart(fig, use_container_width=True)

        # ── Event Log Table ────────────────────────────────

        if len(logs) > 15:
            logs.pop(0)

        log_table.dataframe(pd.DataFrame(logs), use_container_width=True)

        # ── Stop Check ─────────────────────────────────────

        if stop_button:
            break

    cap.release()