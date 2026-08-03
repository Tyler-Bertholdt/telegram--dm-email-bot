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
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-latest")

    # Google Cloud & Gmail Configuration
    GCP_PUBSUB_TOPIC = os.getenv("GCP_PUBSUB_TOPIC", "")
    GMAIL_TOKEN_JSON = os.getenv("GMAIL_TOKEN_JSON", "")
    GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
    GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")

    # Server Configuration
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super-secret-webhook-key")
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

config = Config()