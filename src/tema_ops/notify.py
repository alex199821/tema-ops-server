import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def send_email(to, subject, body, attachment=None):
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment:
        path = Path(attachment)
        msg.add_attachment(path.read_bytes(), maintype="application",
                           subtype="octet-stream", filename=path.name)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def alert(subject, body):
    send_email(os.environ["ALERT_TO"], f"[tema-ops] {subject}", body)


if __name__ == "__main__":
    alert("test", "If you see this, alerts work.")
    print("sent")