import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Configuration
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ALLOWED_USER_IDS = [
        int(uid.strip()) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()
    ]
    DEFAULT_CHAT_ID = int(os.getenv("DEFAULT_CHAT_ID", "0"))

    # Gemini Configuration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Google Cloud & Gmail Configuration
    GCP_PUBSUB_TOPIC = os.getenv("GCP_PUBSUB_TOPIC", "") # e.g. "projects/YOUR_PROJECT/topics/gmail-notifications"
    GMAIL_CREDENTIALS_JSON = os.getenv("GMAIL_CREDENTIALS_JSON", "") # Service Account / OAuth JSON content

    # Server Configuration
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super-secret-webhook-key")
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "") # e.g. "https://your-app.onrender.com"

config = Config()