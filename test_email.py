python
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EMAIL_SENDER    = os.environ.get("GMAIL_SENDER")
EMAIL_PASSWORD  = os.environ.get("GMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")

print(f"Sending from: {EMAIL_SENDER}")
print(f"Sending to: {EMAIL_RECIPIENT}")

msg = MIMEMultipart("alternative")
msg["Subject"] = "✅ YouTube Digest — Test Email"
msg["From"] = EMAIL_SENDER
msg["To"] = EMAIL_RECIPIENT
msg.attach(MIMEText("<h1>It works!</h1><p>Your YouTube Digest email is set up correctly.</p>", "html"))

try:
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    print("✅ Email sent successfully!")
except Exception as e:
    print(f"❌ Email failed: {e}")
