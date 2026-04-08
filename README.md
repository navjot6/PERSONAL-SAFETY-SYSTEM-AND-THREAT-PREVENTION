# Edge AI Personal Safety System and Threat Prevention

Edge AI-based local safety monitoring system built with Python, Flask, OpenCV, and MediaPipe.

## Features

- Real-time webcam streaming via Flask (`/video_feed`)
- On-device threat detection using MediaPipe pose landmarks
- Start/Stop monitoring controls
- Cooldown logic to prevent alert spam
- SMTP email alerting (Gmail App Password)
- Alert storage in SQLite (`alerts.db`)
- Interactive Folium map showing alert locations
- Single-page dashboard UI (`templates/index.html`)

## Tech Stack

- Python + Flask
- OpenCV + MediaPipe
- SQL
- Folium
- SMTP (Gmail)

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

## Notes

- Camera access is required for real-time detection.
- Alerts are inserted into local `alerts.db`.
- Email alerts are skipped if SMTP environment variables are not set.
