import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from typing import List, Union
from dotenv import load_dotenv

load_dotenv()


class EmailNotifier:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.username = os.getenv('SMTP_USER')
        self.password = os.getenv('SMTP_PASSWORD')
    
    def send_report(self, to_emails: Union[str, List[str]], subject: str, body: str):
        if not self.username or not self.password:
            print("SMTP credentials not configured")
            return False
        
        if isinstance(to_emails, str):
            to_emails = [e.strip() for e in to_emails.split(',') if e.strip()]
        
        to_email_str = ', '.join(to_emails)
        
        msg = MIMEMultipart('alternative')
        msg['From'] = self.username
        msg['To'] = to_email_str
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'html'))
        
        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            print(f"Email sent to {to_email_str}")
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False