import uuid
import base64
import json
import httpx
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from config import config
from filter_engine import EmailFilterEngine
from gemini_engine import gemini_engine
from gmail_manager import gmail_manager

app = FastAPI(title="Gemini Mail Bot")

# In-memory storage for pending Human-in-the-Loop confirmations
# Structure: { action_id: {"action": "trash", "ids": [...], "query": "..."} }
PENDING_ACTIONS = {}

async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None):
    """Utility to send messages back to Telegram asynchronously."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

@app.on_event("startup")
async def startup_event():
    """Run on startup: Set Telegram Webhook and renew Gmail Pub/Sub watch."""
    if config.RENDER_EXTERNAL_URL and config.TELEGRAM_BOT_TOKEN:
        webhook_url = f"{config.RENDER_EXTERNAL_URL}/webhook/telegram"
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setWebhook"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"url": webhook_url})
    
    # Refresh Gmail Watch
    gmail_manager.setup_pubsub_watch()

@app.get("/")
def health_check():
    return {"status": "ok", "bot": "Gemini Mail Bot Active"}

# -------------------------------------------------------------------
# TELEGRAM WEBHOOK HANDLER
# -------------------------------------------------------------------
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    # Handle Inline Button Clicks (Approvals / Cancellations)
    if "callback_query" in data:
        cb = data["callback_query"]
        cb_id = cb["id"]
        from_id = cb["from"]["id"]
        cb_data = cb.get("data", "")

        if from_id not in config.ALLOWED_USER_IDS:
            return {"status": "ignored_unauthorized"}

        if ":" in cb_data:
            action, action_id = cb_data.split(":", 1)
            pending_item = PENDING_ACTIONS.get(action_id)

            if not pending_item:
                background_tasks.add_task(
                    send_telegram_message, from_id, "❌ Action expired or not found."
                )
            elif action == "approve":
                act_type = pending_item["action"]
                ids = pending_item["ids"]
                
                if act_type == "trash":
                    gmail_manager.batch_trash_emails(ids)
                    msg = f"✅ Successfully moved {len(ids)} email(s) to Trash."
                elif act_type == "archive":
                    gmail_manager.batch_archive_emails(ids)
                    msg = f"✅ Successfully archived {len(ids)} email(s)."
                else:
                    msg = "✅ Action completed."
                
                del PENDING_ACTIONS[action_id]
                background_tasks.add_task(send_telegram_message, from_id, msg)
            
            elif action == "cancel":
                del PENDING_ACTIONS[action_id]
                background_tasks.add_task(send_telegram_message, from_id, "🚫 Action canceled safely.")

        return {"status": "ok"}

    # Handle Text Messages
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message.get("text", "").strip()

        # Security check
        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            background_tasks.add_task(send_telegram_message, chat_id, "⛔ Unauthorized user.")
            return {"status": "unauthorized"}

        # Command: /start or /help
        if text.startswith("/start") or text.startswith("/help"):
            reply = (
                "👋 **Welcome to Gemini Mail Bot!**\n\n"
                "Available Commands:\n"
                "• `/search <query>` - Find emails\n"
                "• `/delete <query>` - Safely trash emails (requires confirmation)\n"
                "• `/nlp <command>` - Natural language email control\n"
                "• Or simply chat with me!"
            )
            background_tasks.add_task(send_telegram_message, chat_id, reply)

        # Command: /search <query>
        elif text.startswith("/search"):
            query = text.replace("/search", "").strip()
            if not query:
                background_tasks.add_task(send_telegram_message, chat_id, "Usage: `/search is:unread`")
            else:
                emails = gmail_manager.search_emails(query, max_results=5)
                if not emails:
                    background_tasks.add_task(send_telegram_message, chat_id, "No emails found matching query.")
                else:
                    res_str = f"🔍 **Found {len(emails)} emails:**\n\n"
                    for e in emails:
                        res_str += f"• **{e['subject']}**\n  From: {e['sender']}\n\n"
                    background_tasks.add_task(send_telegram_message, chat_id, res_str)

        # Command: /delete <query> (Requires HITL Confirmation)
        elif text.startswith("/delete"):
            query = text.replace("/delete", "").strip()
            if not query:
                background_tasks.add_task(send_telegram_message, chat_id, "Usage: `/delete newsletters from last week`")
            else:
                emails = gmail_manager.search_emails(query, max_results=5)
                if not emails:
                    background_tasks.add_task(send_telegram_message, chat_id, "No matching emails found to delete.")
                else:
                    action_id = str(uuid.uuid4())[:8]
                    PENDING_ACTIONS[action_id] = {
                        "action": "trash",
                        "ids": [e["id"] for e in emails],
                        "query": query
                    }
                    
                    preview = f"⚠️ **CONFIRMATION REQUIRED**\nTarget Query: `{query}`\n\nFound Emails:\n"
                    for e in emails:
                        preview += f"• *{e['subject']}* ({e['sender']})\n"
                    
                    # Telegram Inline Buttons
                    buttons = {
                        "inline_keyboard": [[
                            {"text": "✅ Approve Delete", "callback_data": f"approve:{action_id}"},
                            {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}
                        ]]
                    }
                    background_tasks.add_task(send_telegram_message, chat_id, preview, buttons)

        # Command: /nlp <natural language command>
        elif text.startswith("/nlp"):
            prompt = text.replace("/nlp", "").strip()
            parsed = gemini_engine.parse_nlp_command(prompt)
            act = parsed.get("action")
            q = parsed.get("query", "")

            if act in ["archive", "trash"]:
                emails = gmail_manager.search_emails(q, max_results=5)
                if not emails:
                    background_tasks.add_task(send_telegram_message, chat_id, f"No emails found for query: `{q}`")
                else:
                    action_id = str(uuid.uuid4())[:8]
                    PENDING_ACTIONS[action_id] = {
                        "action": act,
                        "ids": [e["id"] for e in emails],
                        "query": q
                    }
                    preview = f"⚠️ **Confirm Action: {act.upper()}**\n\nExplanation: {parsed.get('explanation')}\n\nTarget Emails:\n"
                    for e in emails:
                        preview += f"• *{e['subject']}* ({e['sender']})\n"

                    buttons = {
                        "inline_keyboard": [[
                            {"text": f"✅ Approve {act.title()}", "callback_data": f"approve:{action_id}"},
                            {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}
                        ]]
                    }
                    background_tasks.add_task(send_telegram_message, chat_id, preview, buttons)
            else:
                background_tasks.add_task(
                    send_telegram_message, chat_id, f"Parsed Action: `{act}`\nQuery: `{q}`"
                )

        # General Conversation / Q&A
        else:
            response_text = gemini_engine.chat_response(text)
            background_tasks.add_task(send_telegram_message, chat_id, response_text)

    return {"status": "ok"}

# -------------------------------------------------------------------
# GMAIL PUSH NOTIFICATION WEBHOOK HANDLER
# -------------------------------------------------------------------
async def process_incoming_email_notification(history_id: str):
    """Fetches latest email triggered by GCP Pub/Sub and posts Gemini summary to Telegram."""
    # Retrieve the latest message using search or history endpoint
    emails = gmail_manager.search_emails("is:unread", max_results=1)
    if not emails:
        return

    email = emails[0]
    sender = email.get("sender", "")
    subject = email.get("subject", "")
    snippet = email.get("snippet", "")

    # Run through Filter Engine (Ignore OTPs, blacklisted senders, auto-responders)
    if not EmailFilterEngine.should_process_email(sender, subject, snippet):
        print(f"Skipping filtered email: {subject}")
        return

    # Generate Gemini Summary
    summary = gemini_engine.summarize_email(
        sender=sender,
        recipient=email.get("recipient", ""),
        subject=subject,
        date_str=email.get("date", ""),
        body=email.get("body", "")
    )

    # Post Summary to Whitelisted Telegram Chat
    target_chat = config.DEFAULT_CHAT_ID or (config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None)
    if target_chat:
        await send_telegram_message(target_chat, summary)

@app.post("/webhook/gmail")
async def gmail_pubsub_webhook(request: Request, background_tasks: BackgroundTasks):
    """Webhook triggered by GCP Pub/Sub when a new email arrives."""
    body = await request.json()
    message = body.get("message", {})
    data_b64 = message.get("data")

    if data_b64:
        decoded_data = json.loads(base64.b64decode(data_b64).decode("utf-8"))
        history_id = decoded_data.get("historyId")
        if history_id:
            background_tasks.add_task(process_incoming_email_notification, history_id)

    return {"status": "ok"}