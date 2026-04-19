# Edge AI Personal Safety System and Threat Prevention

A real-time personal safety monitoring system built with Python, Flask, OpenCV, and MediaPipe. The system uses Edge AI to detect distress gestures through a webcam, triggers alerts with email notifications, saves evidence snapshots, and displays alert locations on an interactive map — all running locally without any cloud dependency.

## Features

1. Real-time webcam streaming via Flask (/video_feed)
2. On-device threat detection using MediaPipe Pose landmarks (no cloud API required)
3. Distress gesture recognition — detects hands-up postures, panic motion, and sudden movements
4. Risk scoring system with EMA smoothing and multi-frame consensus for accurate detection
5. Cooldown logic to prevent alert spam (configurable)
6. Evidence snapshot capture — automatically saves a .jpg image of the frame when a threat is detected (static/snapshots/)
7. SMTP email alerting with Gmail App Password support
8. Alert storage in local SQLite database (alerts.db)
9. Interactive Folium map showing alert locations with timestamps
10. User authentication — register/login with email+password or Google OAuth
11. Single-page dashboard UI with live camera feed, evidence snapshots panel, and recent activity log


## Tech Stack

- Python + Flask
- OpenCV + MediaPipe
- SQLite
- Folium
- SMTP (Gmail)
- Flask Session, Google OAuth 2.0
- HTML, CSS, JavaScript

## Setup

1. Create virtual environment and activate it:

```bash
python -m venv edge_env
edge_env\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure SMTP in `.env` file:

```env
ALERT_SENDER_EMAIL=your_sender@gmail.com
ALERT_RECEIVER_EMAIL=receiver@gmail.com
ALERT_APP_PASSWORD=your_gmail_app_password
```

4. Run app:

```bash
python app.py
```

5. Open:

`http://127.0.0.1:5000`

## Project Files

- `app.py` - Flask routes, video streaming, APIs, and Folium map endpoint
- `detection.py` - Edge AI threat detection and cooldown
- `database.py` - SQL schema and alert CRUD helpers
- `alert.py` - SMTP email sending
- `templates/index.html` - single dashboard page
- 'static/style.css' and 'static/script.js'

## Requirements

- Python 3.8+
- Webcam / USB camera
- Gmail account with App Password enabled (for email alerts)

## Notes

- Camera access is required for real-time detection.
- Alerts are inserted into local `alerts.db`.
- Email alerts are skipped if SMTP environment variables are not set.
