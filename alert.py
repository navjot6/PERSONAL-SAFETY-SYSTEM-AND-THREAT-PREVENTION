import os
import smtplib
from pathlib import Path
from email.mime.text import MIMEText

from dotenv import load_dotenv

dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path, override=False)

def send_alert_email_detailed(message: str, latitude: float, longitude: float) -> tuple[bool, str | None]:
    sender_email = os.getenv("ALERT_SENDER_EMAIL", "")
    receiver_email = os.getenv("ALERT_RECEIVER_EMAIL", "")
    app_password = os.getenv("ALERT_APP_PASSWORD", "")

    if not sender_email or not receiver_email or not app_password:
        print("Email alert skipped: missing SMTP env vars.", flush=True)
        return False, "Missing SMTP env vars"

    location_link = f"https://maps.google.com/?q={latitude},{longitude}"
    body = (
        f"ALERT: {message}\n\n"
        f"Location:\nLatitude: {latitude}\nLongitude: {longitude}\n\n"
        f"Map: {location_link}"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Threat Detected - Edge AI Safety System"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)
        print(f"Email alert sent: to={receiver_email} lat={latitude} lon={longitude}", flush=True)
        return True, None
    except Exception as exc:
        print(f"Email alert failed: {exc}", flush=True)
        return False, str(exc)
        
def send_alert_email(message: str, latitude: float, longitude: float) -> bool:
    ok, _err = send_alert_email_detailed(message=message, latitude=latitude, longitude=longitude)
    return ok
