import base64
import json
import uuid
import asyncio
import httpx
from config import config
from filter_engine import EmailFilterEngine
from gemini_engine import gemini_engine
from gmail_manager import gmail_manager

PROCESSED_EMAIL_IDS = set()
MESSAGE_TO_EMAIL_MAP = {}
LAST_VIEWED_EMAILS = {}

async def send_telegram_msg(chat_id: int, text: str, reply_markup: dict = None) -> int:
    if not config.TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": False}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, json=payload)
            data = res.json()
            if data.get("ok"):
                return data["result"]["message_id"]
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")
    return None

async def send_email_summary_card(chat_id: int, e: dict, pending_actions_dict: dict):
    summary_text = await gemini_engine.summarize_email(
        sender=e["sender"],
        recipient=e["recipient"],
        subject=e["subject"],
        date_str=e["date"],
        body=e["body"],
        msg_id=e["id"]
    )

    action_id = str(uuid.uuid4())[:8]
    pending_actions_dict[action_id] = {
        "action": "trash",
        "ids": [e["id"]],
        "query": f"subject:{e['subject']}"
    }

    mail_link = f"https://mail.google.com/mail/u/0/#all/{e['id']}"

    buttons = {
        "inline_keyboard": [[
            {"text": "📬 Open Email", "url": mail_link},
            {"text": "🗑️ Delete Email", "callback_data": f"approve:{action_id}"}
        ]]
    }

    sent_msg_id = await send_telegram_msg(chat_id, summary_text, buttons)
    if sent_msg_id:
        MESSAGE_TO_EMAIL_MAP[sent_msg_id] = {
            "gmail_id": e["id"],
            "subject": e["subject"],
            "sender": e["sender"]
        }
        
        # Track email as viewed for chat_id
        if chat_id not in LAST_VIEWED_EMAILS:
            LAST_VIEWED_EMAILS[chat_id] = []
        LAST_VIEWED_EMAILS[chat_id].insert(0, e)

async def seed_initial_unread_emails():
    try:
        if gmail_manager.service:
            unread = gmail_manager.search_emails("is:unread", max_results=15) or []
            for e in unread:
                PROCESSED_EMAIL_IDS.add(e["id"])
            print(f"✅ Notifier initialized: Seeded {len(PROCESSED_EMAIL_IDS)} existing unread emails.")
    except Exception as e:
        print(f"Error seeding unread emails: {e}")

async def start_notifier_polling_loop(pending_actions_dict: dict):
    await seed_initial_unread_emails()

    while True:
        try:
            target_chat = config.DEFAULT_CHAT_ID or (config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None)
            if target_chat and gmail_manager.service:
                unread_emails = gmail_manager.search_emails("is:unread newer_than:2d", max_results=10) or []
                for email in unread_emails:
                    msg_id = email["id"]
                    if msg_id not in PROCESSED_EMAIL_IDS:
                        PROCESSED_EMAIL_IDS.add(msg_id)
                        if EmailFilterEngine.should_process_email(email["sender"], email["subject"], email["snippet"]):
                            print(f"🔔 New incoming email detected: {email['subject']}")
                            await send_email_summary_card(target_chat, email, pending_actions_dict)
        except Exception as e:
            print(f"Notifier polling error: {e}")

        await asyncio.sleep(30)

async def handle_gmail_pubsub_push(body: dict, pending_actions_dict: dict):
    message = body.get("message", {})
    data_b64 = message.get("data")

    if data_b64:
        decoded_data = json.loads(base64.b64decode(data_b64).decode("utf-8"))
        history_id = decoded_data.get("historyId")
        if history_id:
            unread_emails = gmail_manager.search_emails("is:unread newer_than:1d", max_results=5) or []
            target_chat = config.DEFAULT_CHAT_ID or (config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None)
            
            for email in unread_emails:
                if email["id"] not in PROCESSED_EMAIL_IDS:
                    PROCESSED_EMAIL_IDS.add(email["id"])
                    if EmailFilterEngine.should_process_email(email["sender"], email["subject"], email["snippet"]):
                        if target_chat:
                            await send_email_summary_card(target_chat, email, pending_actions_dict)