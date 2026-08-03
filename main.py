import uuid
import base64
import json
import asyncio
import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse
from config import config
from filter_engine import EmailFilterEngine
from gemini_engine import gemini_engine
from gmail_manager import gmail_manager

app = FastAPI(title="Gemini Mail Bot")

# Action states & Undo tracking
PENDING_ACTIONS = {}
LAST_ACTION_STATE = {}
MESSAGE_TO_EMAIL_MAP = {}
PROCESSED_NOTIFICATIONS = set()

async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None) -> int:
    """Sends a Telegram message and returns the message_id."""
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

async def delete_telegram_message(chat_id: int, message_id: int):
    """Deletes a Telegram message (e.g. loading indicator)."""
    if not message_id or not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/deleteMessage"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"chat_id": chat_id, "message_id": message_id})
        except Exception as e:
            print(f"Failed to delete loading message: {e}")

async def send_email_summary_card(chat_id: int, e: dict):
    summary_text = await gemini_engine.summarize_email(
        sender=e["sender"],
        recipient=e["recipient"],
        subject=e["subject"],
        date_str=e["date"],
        body=e["body"],
        msg_id=e["id"]
    )

    action_id = str(uuid.uuid4())[:8]
    PENDING_ACTIONS[action_id] = {
        "action": "trash",
        "ids": [e["id"]],
        "query": f"subject:{e['subject']}"
    }

    gmail_link = f"https://mail.google.com/mail/u/0/#all/{e['id']}"

    buttons = {
        "inline_keyboard": [[
            {"text": "🔗 Open in Gmail", "url": gmail_link},
            {"text": "🗑️ Delete Email", "callback_data": f"approve:{action_id}"}
        ]]
    }

    sent_msg_id = await send_telegram_message(chat_id, summary_text, buttons)
    if sent_msg_id:
        MESSAGE_TO_EMAIL_MAP[sent_msg_id] = {
            "gmail_id": e["id"],
            "subject": e["subject"],
            "sender": e["sender"]
        }

async def poll_gmail_for_new_emails():
    """Background polling fallback to guarantee 100% notification delivery."""
    while True:
        try:
            target_chat = config.DEFAULT_CHAT_ID or (config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None)
            if target_chat and gmail_manager.service:
                unread_emails = gmail_manager.search_emails("is:unread", max_results=3)
                if unread_emails:
                    for email in unread_emails:
                        if email["id"] not in PROCESSED_NOTIFICATIONS:
                            PROCESSED_NOTIFICATIONS.add(email["id"])
                            if EmailFilterEngine.should_process_email(email["sender"], email["subject"], email["snippet"]):
                                await send_email_summary_card(target_chat, email)
        except Exception as e:
            print(f"Polling loop error: {e}")
        await asyncio.sleep(60) # Polls every 60 seconds

@app.on_event("startup")
async def startup_event():
    if config.RENDER_EXTERNAL_URL and config.TELEGRAM_BOT_TOKEN:
        webhook_url = f"{config.RENDER_EXTERNAL_URL}/webhook/telegram"
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setWebhook"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"url": webhook_url})
    
    gmail_manager.setup_pubsub_watch()
    asyncio.create_task(poll_gmail_for_new_emails())

@app.get("/")
def health_check():
    return {"status": "ok", "bot": "Gemini Mail Bot is active!"}

# -------------------------------------------------------------------
# OAUTH ROUTING
# -------------------------------------------------------------------
@app.get("/auth/login")
def auth_login():
    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET:
        return HTMLResponse("❌ Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in Render Environment Variables first.")

    redirect_uri = f"{config.RENDER_EXTERNAL_URL}/auth/callback"
    scope = "https://www.googleapis.com/auth/gmail.modify"
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={config.GMAIL_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def auth_callback(code: str = None, error: str = None):
    if error:
        return HTMLResponse(f"❌ Google OAuth Error: {error}")
    if not code:
        return HTMLResponse("❌ Missing code. Visit <a href='/auth/login'>/auth/login</a>.")

    redirect_uri = f"{config.RENDER_EXTERNAL_URL}/auth/callback"
    token_url = "https://oauth2.googleapis.com/token"

    payload = {
        "code": code,
        "client_id": config.GMAIL_CLIENT_ID,
        "client_secret": config.GMAIL_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(token_url, data=payload, timeout=20.0)
            token_data = res.json()

        if "error" in token_data:
            err_desc = token_data.get("error_description", token_data.get("error"))
            return HTMLResponse(f"❌ **OAuth Error:** {err_desc}<br><br><a href='/auth/login'>Try again</a>")

        token_json = {
            "token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"]
        }

        token_json_str = json.dumps(token_json, indent=2)

        return HTMLResponse(content=f"""
        <html>
          <body style="font-family:sans-serif; padding:20px;">
            <h2>✅ Authorization Successful!</h2>
            <p>Copy the JSON text below and paste it as <b>GMAIL_TOKEN_JSON</b> in Render Environment Variables:</p>
            <textarea style="width:100%; height:250px; font-size:12px;">{token_json_str}</textarea>
          </body>
        </html>
        """)
    except Exception as e:
        return HTMLResponse(f"❌ Error exchanging token: {str(e)}")

# -------------------------------------------------------------------
# TELEGRAM WEBHOOK HANDLER
# -------------------------------------------------------------------
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    # 1. Inline Buttons (HITL Confirmation)
    if "callback_query" in data:
        cb = data["callback_query"]
        from_id = cb["from"]["id"]
        cb_data = cb.get("data", "")

        if config.ALLOWED_USER_IDS and from_id not in config.ALLOWED_USER_IDS:
            return {"status": "ignored"}

        if ":" in cb_data:
            action, action_id = cb_data.split(":", 1)
            pending_item = PENDING_ACTIONS.get(action_id)

            if not pending_item:
                background_tasks.add_task(send_telegram_message, from_id, "❌ Action expired or not found.")
            elif action == "approve":
                act_type = pending_item["action"]
                ids = pending_item["ids"]

                # Store for Undo
                LAST_ACTION_STATE["action"] = act_type
                LAST_ACTION_STATE["ids"] = ids

                if act_type == "trash":
                    gmail_manager.batch_trash_emails(ids)
                    msg = f"✅ Moved {len(ids)} email(s) to Trash. Type `/undo` to restore."
                elif act_type == "archive":
                    gmail_manager.batch_archive_emails(ids)
                    msg = f"✅ Archived {len(ids)} email(s). Type `/undo` to restore."
                else:
                    msg = "✅ Action completed."

                del PENDING_ACTIONS[action_id]
                background_tasks.add_task(send_telegram_message, from_id, msg)

            elif action == "cancel":
                del PENDING_ACTIONS[action_id]
                background_tasks.add_task(send_telegram_message, from_id, "🚫 Action canceled safely.")

        return {"status": "ok"}

    # 2. Text Commands & Processing
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message.get("text", "").strip()

        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            background_tasks.add_task(send_telegram_message, chat_id, "⛔ Unauthorized user.")
            return {"status": "unauthorized"}

        # Telegram Swipe-to-Reply Delete Handler
        if "reply_to_message" in message and text.lower() in ["delete", "/delete", "trash", "/trash"]:
            loading_id = await send_telegram_message(chat_id, "⏳ *Locating replied email...*")
            replied_msg_id = message["reply_to_message"]["message_id"]
            matched_email = MESSAGE_TO_EMAIL_MAP.get(replied_msg_id)

            await delete_telegram_message(chat_id, loading_id)

            if matched_email:
                action_id = str(uuid.uuid4())[:8]
                PENDING_ACTIONS[action_id] = {
                    "action": "trash",
                    "ids": [matched_email["gmail_id"]],
                    "query": f"subject:{matched_email['subject']}"
                }

                preview = (
                    f"⚠️ **CONFIRM DELETE**\n\n"
                    f"• *Subject:* {matched_email['subject']}\n"
                    f"• *From:* `{matched_email['sender']}`\n\n"
                    f"Move this email to Trash?"
                )
                buttons = {
                    "inline_keyboard": [[
                        {"text": "✅ Confirm Delete", "callback_data": f"approve:{action_id}"},
                        {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}
                    ]]
                }
                background_tasks.add_task(send_telegram_message, chat_id, preview, buttons)
            else:
                background_tasks.add_task(send_telegram_message, chat_id, "❌ Could not match replied message to an email ID.")
            return {"status": "ok"}

        # Standard Commands with Loading Auto-Delete Indicators
        loading_id = await send_telegram_message(chat_id, "⏳ *Processing request...*")

        try:
            # /undo Command
            if text.startswith("/undo"):
                if not LAST_ACTION_STATE or "ids" not in LAST_ACTION_STATE:
                    background_tasks.add_task(send_telegram_message, chat_id, "❌ No recent action to undo.")
                else:
                    gmail_manager.batch_untrash_emails(LAST_ACTION_STATE["ids"])
                    background_tasks.add_task(send_telegram_message, chat_id, f"↺ Successfully restored {len(LAST_ACTION_STATE['ids'])} email(s) to Inbox!")
                    LAST_ACTION_STATE.clear()

            # /help
            elif text.startswith("/start") or text.startswith("/help"):
                help_menu = (
                    "🤖 **Gemini AI Mail Assistant Guide**\n\n"
                    "📥 **Management**\n"
                    "• `/search <query>` – Search emails\n"
                    "• `/delete <query>` – Trash emails safely\n"
                    "• `/archive <query>` – Archive emails\n"
                    "• `/unread <query>` / `/read <query>` – Mark unread/read\n"
                    "• `/star <query>` – Star emails\n"
                    "• `/undo` – Undo last trash/archive action\n\n"
                    "🧠 **AI Features**\n"
                    "• `/brief` – Today's inbox in 30 seconds\n"
                    "• `/action` – Extract tasks & deadlines\n"
                    "• `/otp` – Find latest OTP codes\n"
                    "• `/expenses` – Find receipts & bills\n"
                    "• `/tracking` – Shipment & delivery updates\n"
                    "• `/phishing` – Scan unread emails for security risks\n"
                    "• `/chat <question>` – Ask questions about your emails\n"
                    "• `/nlp <command>` – Natural language command parser\n\n"
                    "💡 *Pro Tip: Swipe-reply to any summary with 'delete' to trash it instantly!*"
                )
                background_tasks.add_task(send_telegram_message, chat_id, help_menu)

            # AI Briefing
            elif text.startswith("/brief"):
                emails = gmail_manager.search_emails("is:unread", max_results=5) or []
                brief = await gemini_engine.generate_briefing(emails) if emails else "No unread emails to brief."
                background_tasks.add_task(send_telegram_message, chat_id, f"⚡ **Inbox 30s Briefing:**\n\n{brief}")

            # AI Action Extraction
            elif text.startswith("/action"):
                emails = gmail_manager.search_emails("is:unread", max_results=5) or []
                actions = await gemini_engine.extract_action_items(emails) if emails else "No action items found."
                background_tasks.add_task(send_telegram_message, chat_id, f"🎯 **Extracted Action Items:**\n\n{actions}")

            # OTP Finder
            elif text.startswith("/otp"):
                emails = gmail_manager.search_emails("OTP OR code OR verification", max_results=2) or []
                if emails:
                    otp_res = "\n\n".join([f"🔑 **{e['subject']}**\nFrom: `{e['sender']}`\nSnippet: `{e['snippet']}`" for e in emails])
                    background_tasks.add_task(send_telegram_message, chat_id, otp_res)
                else:
                    background_tasks.add_task(send_telegram_message, chat_id, "No recent OTP codes found.")

            # Expenses & Bills
            elif text.startswith("/expenses"):
                emails = gmail_manager.search_emails("bill OR receipt OR invoice OR payment", max_results=3) or []
                if emails:
                    exp_res = "🧾 **Recent Expenses & Receipts:**\n\n" + "\n\n".join([f"• **{e['subject']}** ({e['sender']})\n  Date: {e['date']}" for e in emails])
                    background_tasks.add_task(send_telegram_message, chat_id, exp_res)
                else:
                    background_tasks.add_task(send_telegram_message, chat_id, "No recent expenses found.")

            # Shipment Tracking
            elif text.startswith("/tracking"):
                emails = gmail_manager.search_emails("shipped OR tracking OR delivery OR courier", max_results=3) or []
                if emails:
                    track_res = "📦 **Shipment & Delivery Updates:**\n\n" + "\n\n".join([f"• **{e['subject']}**\n  Snippet: {e['snippet']}" for e in emails])
                    background_tasks.add_task(send_telegram_message, chat_id, track_res)
                else:
                    background_tasks.add_task(send_telegram_message, chat_id, "No tracking updates found.")

            # AI Security Phishing Scan
            elif text.startswith("/phishing"):
                emails = gmail_manager.search_emails("is:unread", max_results=1) or []
                if emails:
                    res = await gemini_engine.analyze_phishing(emails[0])
                    background_tasks.add_task(send_telegram_message, chat_id, res)
                else:
                    background_tasks.add_task(send_telegram_message, chat_id, "No unread emails to scan.")

            # Natural Language Chat with Inbox
            elif text.startswith("/chat"):
                q = text.replace("/chat", "").strip()
                emails = gmail_manager.search_emails(q if q else "is:unread", max_results=5) or []
                chat_res = await gemini_engine.chat_with_inbox(q, emails) if emails else "No matching emails found to answer your query."
                background_tasks.add_task(send_telegram_message, chat_id, chat_res)

            # /search
            elif text.startswith("/search"):
                query = text.replace("/search", "").strip() or "is:unread"
                emails = gmail_manager.search_emails(query, max_results=5)
                if emails is None:
                    background_tasks.add_task(send_telegram_message, chat_id, "❌ **Gmail API Error:** Unauthenticated. Visit `/auth/login`.")
                elif len(emails) == 0:
                    background_tasks.add_task(send_telegram_message, chat_id, f"No emails found for query: `{query}`")
                else:
                    res_str = f"🔍 **Found {len(emails)} emails:**\n\n"
                    for e in emails:
                        gmail_link = f"https://mail.google.com/mail/u/0/#all/{e['id']}"
                        res_str += f"• **[{e['subject']}]({gmail_link})**\n  From: `{e['sender']}`\n\n"
                    background_tasks.add_task(send_telegram_message, chat_id, res_str)

            # /delete
            elif text.startswith("/delete"):
                query = text.replace("/delete", "").strip()
                if not query:
                    background_tasks.add_task(send_telegram_message, chat_id, "Usage: `/delete newsletters` or **swipe-reply** to an email summary and type `delete`.")
                else:
                    emails = gmail_manager.search_emails(query, max_results=5)
                    if emails:
                        action_id = str(uuid.uuid4())[:8]
                        PENDING_ACTIONS[action_id] = {"action": "trash", "ids": [e["id"] for e in emails], "query": query}
                        preview = f"⚠️ **CONFIRM DELETE**\nQuery: `{query}`\n\nTarget Emails:\n" + "\n".join([f"• *{e['subject']}* ({e['sender']})" for e in emails])
                        buttons = {"inline_keyboard": [[{"text": "✅ Confirm Delete", "callback_data": f"approve:{action_id}"}, {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}]]}
                        background_tasks.add_task(send_telegram_message, chat_id, preview, buttons)
                    else:
                        background_tasks.add_task(send_telegram_message, chat_id, "No matching emails found to delete.")

            # /nlp
            elif text.startswith("/nlp"):
                prompt = text.replace("/nlp", "").strip()
                parsed = await gemini_engine.parse_nlp_command(prompt)
                act = parsed.get("action")
                q = parsed.get("query", "is:unread")

                if act == "summarize":
                    emails = gmail_manager.search_emails(q, max_results=3) or []
                    for e in emails:
                        background_tasks.add_task(send_email_summary_card, chat_id, e)
                elif act in ["trash", "archive"]:
                    emails = gmail_manager.search_emails(q, max_results=5) or []
                    if emails:
                        action_id = str(uuid.uuid4())[:8]
                        PENDING_ACTIONS[action_id] = {"action": act, "ids": [e["id"] for e in emails], "query": q}
                        preview = f"⚠️ **Confirm {act.upper()}**\nQuery: `{q}`\n\nTarget Emails:\n" + "\n".join([f"• *{e['subject']}* ({e['sender']})" for e in emails])
                        buttons = {"inline_keyboard": [[{"text": f"✅ Approve {act.title()}", "callback_data": f"approve:{action_id}"}, {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}]]}
                        background_tasks.add_task(send_telegram_message, chat_id, preview, buttons)

            # Direct Chat
            else:
                res = await gemini_engine.chat_response(text)
                background_tasks.add_task(send_telegram_message, chat_id, res)

        finally:
            # Always delete loading indicator when processing completes
            await delete_telegram_message(chat_id, loading_id)

    return {"status": "ok"}

# -------------------------------------------------------------------
# GMAIL PUSH NOTIFICATION WEBHOOK HANDLER
# -------------------------------------------------------------------
@app.post("/webhook/gmail")
async def gmail_pubsub_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    message = body.get("message", {})
    data_b64 = message.get("data")

    if data_b64:
        decoded_data = json.loads(base64.b64decode(data_b64).decode("utf-8"))
        history_id = decoded_data.get("historyId")
        if history_id:
            unread_emails = gmail_manager.search_emails("is:unread", max_results=1) or []
            if unread_emails:
                email = unread_emails[0]
                if email["id"] not in PROCESSED_NOTIFICATIONS:
                    PROCESSED_NOTIFICATIONS.add(email["id"])
                    if EmailFilterEngine.should_process_email(email["sender"], email["subject"], email["snippet"]):
                        target_chat = config.DEFAULT_CHAT_ID or (config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None)
                        if target_chat:
                            background_tasks.add_task(send_email_summary_card, target_chat, email)

    return {"status": "ok"}