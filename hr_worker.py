import imaplib
import email
import smtplib
import gspread
import schedule
import time
import io
import datetime
import os
import json
from email.message import EmailMessage
from email.header import decode_header
from oauth2client.service_account import ServiceAccountCredentials
from PyPDF2 import PdfReader
from openai import OpenAI

# ================= CONFIGURATION (From Environment Variables) =================
ZOHO_IMAP_SERVER = os.getenv("ZOHO_IMAP_SERVER", "imap.zoho.com")
ZOHO_SMTP_SERVER = os.getenv("ZOHO_SMTP_SERVER", "smtp.zoho.com")
ZOHO_EMAIL = os.getenv("ZOHO_EMAIL")
ZOHO_APP_PASSWORD = os.getenv("ZOHO_APP_PASSWORD")

GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_SHEET_LINK = os.getenv("GOOGLE_SHEET_LINK")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Replace Gemini key with Grok key
GROK_API_KEY = os.getenv("GROK_API_KEY")
TARGET_KEYWORDS = ["jai gurudev", "bhaiya", "didi", "art of living"]
# ==============================================================================

# Initialize Grok (xAI) Client using the OpenAI SDK
llm_client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1",
)

# Initialize Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1

def extract_text_from_pdf(pdf_bytes):
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Could not parse PDF: {e}"

def summarize_resume(resume_text):
    prompt = f"Provide a brief, 3-sentence professional summary of this candidate's resume, highlighting their key skills and experience:\n\n{resume_text}"
    
    try:
        response = llm_client.chat.completions.create(
            model="grok-2-latest",
            messages=[
                {"role": "system", "content": "You are a professional HR assistant. Your job is to read resumes and provide concise, 3-sentence summaries focusing on skills and experience."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating summary: {e}"

def process_unread_emails():
    try:
        print("Checking emails...")
        mail = imaplib.IMAP4_SSL(ZOHO_IMAP_SERVER)
        mail.login(ZOHO_EMAIL, ZOHO_APP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        email_ids = messages[0].split()

        for e_id in email_ids:
            res, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")
                    
                    sender = msg.get("From")
                    body = ""
                    resume_text = ""

                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))

                            if content_type == "text/plain" and "attachment" not in content_disposition:
                                body = part.get_payload(decode=True).decode()
                            
                            elif "attachment" in content_disposition and part.get_filename() and part.get_filename().endswith(".pdf"):
                                pdf_bytes = part.get_payload(decode=True)
                                resume_text = extract_text_from_pdf(pdf_bytes)
                    else:
                        body = msg.get_payload(decode=True).decode()

                    body_lower = body.lower()
                    if any(keyword in body_lower for keyword in TARGET_KEYWORDS):
                        print(f"Match found for: {sender}")
                        
                        summary = summarize_resume(resume_text) if resume_text else "No parseable PDF attached."
                        
                        sheet.append_row([
                            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            sender,
                            subject,
                            summary
                        ])

        mail.logout()
    except Exception as e:
        print(f"Error checking emails: {e}")

def send_daily_summary():
    print("Sending daily summary...")
    msg = EmailMessage()
    msg.set_content(f"Hello,\n\nThe automated candidate filtering has run for today.\n\nYou can view the updated list of identified devotees and their resume summaries here:\n{GOOGLE_SHEET_LINK}\n\nBest,\nHR Bot")
    
    msg['Subject'] = f"Daily Candidate Summary - {datetime.datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = ZOHO_EMAIL
    msg['To'] = ZOHO_EMAIL

    try:
        server = smtplib.SMTP_SSL(ZOHO_SMTP_SERVER, 465)
        server.login(ZOHO_EMAIL, ZOHO_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Daily summary email sent successfully.")
    except Exception as e:
        print(f"Failed to send daily summary: {e}")

# ================= SCHEDULING =================
schedule.every(5).minutes.do(process_unread_emails)
schedule.every().day.at("18:00").do(send_daily_summary)

if __name__ == "__main__":
    print("Worker script started. Listening for emails...")
    while True:
        schedule.run_pending()
        time.sleep(1)
