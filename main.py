import uuid
import json
import asyncio
import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse
from config import config
from gemini_engine import gemini_engine
from gmail_manager import gmail_manager
from gmail_notifier import (
    start_notifier_polling_loop,
    handle_gmail_pubsub_push,
    send_email_summary_card,
    send_telegram_msg,
    MESSAGE_TO_EMAIL_MAP,
    LAST_VIEWED_EMAILS
)

app = FastAPI(title="Gemini Mail Bot")

PENDING_ACTIONS = {}
LAST_ACTION_STATE = {}

async def answer_telegram_callback(callback_query_id: str, text: str = "Action processed"):
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"callback_query_id": callback_query_id, "text": text})
        except Exception as e:
            print(f"Error answering callback query: {e}")

async def delete_telegram_message(chat_id: int, message_id: int):
    if not message_id or not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/deleteMessage"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"chat_id": chat_id, "message_id": message_id})
        except Exception:
            pass

def get_universal_email_link(msg_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{msg_id}"

@app.on_event("startup")
async def startup_event():
    if config.RENDER_EXTERNAL_URL and config.TELEGRAM_BOT_TOKEN:
        webhook_url = f"{config.RENDER_EXTERNAL_URL}/webhook/telegram"
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setWebhook"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"url": webhook_url})
    
    gmail_manager.setup_pubsub_watch()
    asyncio.create_task(start_notifier_polling_loop(PENDING_ACTIONS))

@app.get("/")
def health_check():
    return {"status": "ok", "bot": "Gemini Mail Bot is running!"}

# OAUTH ROUTING
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

# TELEGRAM WEBHOOK HANDLER
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    # 1. Inline Buttons Execution
    if "callback_query" in data:
        cb = data["callback_query"]
        cb_id = cb["id"]
        from_id = cb["from"]["id"]
        cb_data = cb.get("data", "")

        if config.ALLOWED_USER_IDS and from_id not in config.ALLOWED_USER_IDS:
            await answer_telegram_callback(cb_id, "Unauthorized user")
            return {"status": "ignored"}

        if ":" in cb_data:
            action, action_id = cb_data.split(":", 1)
            pending_item = PENDING_ACTIONS.get(action_id)

            if not pending_item:
                await answer_telegram_callback(cb_id, "Action expired")
                background_tasks.add_task(send_telegram_msg, from_id, "❌ Action expired or not found.")
            elif action == "approve":
                act_type = pending_item["action"]
                ids = pending_item["ids"]

                LAST_ACTION_STATE["action"] = act_type
                LAST_ACTION_STATE["ids"] = ids

                if act_type == "trash":
                    gmail_manager.batch_trash_emails(ids)
                    msg = f"✅ Moved {len(ids)} email(s) to Trash. Type `/undo` to restore."
                elif act_type == "archive":
                    gmail_manager.batch_archive_emails(ids)
                    msg = f"✅ Archived {len(ids)} email(s). Type `/undo` to restore."
                elif act_type == "spam":
                    gmail_manager.batch_mark_spam(ids)
                    msg = f"✅ Marked {len(ids)} email(s) as Spam."
                elif act_type == "read":
                    gmail_manager.batch_mark_read(ids)
                    msg = f"✅ Marked {len(ids)} email(s) as Read."
                elif act_type == "unread":
                    gmail_manager.batch_mark_unread(ids)
                    msg = f"✅ Marked {len(ids)} email(s) as Unread."
                elif act_type == "star":
                    gmail_manager.batch_star(ids)
                    msg = f"✅ Starred {len(ids)} email(s)."
                else:
                    msg = "✅ Action completed."

                del PENDING_ACTIONS[action_id]
                await answer_telegram_callback(cb_id, "Action completed!")
                background_tasks.add_task(send_telegram_msg, from_id, msg)

            elif action == "cancel":
                del PENDING_ACTIONS[action_id]
                await answer_telegram_callback(cb_id, "Action canceled")
                background_tasks.add_task(send_telegram_msg, from_id, "🚫 Action canceled safely.")

        return {"status": "ok"}

    # 2. Text Commands & Processing
    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message.get("text", "").strip()

        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            background_tasks.add_task(send_telegram_msg, chat_id, "⛔ Unauthorized user.")
            return {"status": "unauthorized"}

        loading_id = await send_telegram_msg(chat_id, "⏳ *Processing request...*")

        try:
            # SMART DELETE COMMAND
            if text.lower() in ["delete", "/delete", "trash", "/trash"] or text.startswith("/delete") or text.startswith("delete "):
                raw_arg = text.replace("/delete", "").replace("/trash", "").replace("delete", "").replace("trash", "").strip()
                target_email = None

                # 1. Swipe-to-reply
                if "reply_to_message" in message:
                    replied_msg_id = message["reply_to_message"]["message_id"]
                    target_email = MESSAGE_TO_EMAIL_MAP.get(replied_msg_id)

                # 2. Numerical index (e.g., delete 1, /delete 2)
                elif raw_arg.isdigit() and chat_id in LAST_VIEWED_EMAILS:
                    idx = int(raw_arg) - 1
                    viewed_list = LAST_VIEWED_EMAILS[chat_id]
                    if 0 <= idx < len(viewed_list):
                        e_item = viewed_list[idx]
                        target_email = {"gmail_id": e_item["id"], "subject": e_item["subject"], "sender": e_item["sender"]}

                # 3. Direct standalone 'delete' -> Target the most recent viewed email
                elif not raw_arg and chat_id in LAST_VIEWED_EMAILS and LAST_VIEWED_EMAILS[chat_id]:
                    e_item = LAST_VIEWED_EMAILS[chat_id][0]
                    target_email = {"gmail_id": e_item["id"], "subject": e_item["subject"], "sender": e_item["sender"]}

                if target_email:
                    action_id = str(uuid.uuid4())[:8]
                    PENDING_ACTIONS[action_id] = {
                        "action": "trash",
                        "ids": [target_email["gmail_id"]],
                        "query": f"subject:{target_email['subject']}"
                    }
                    preview = (
                        f"⚠️ **CONFIRM DELETE**\n\n"
                        f"• *Subject:* {target_email['subject']}\n"
                        f"• *From:* `{target_email['sender']}`\n\n"
                        f"Move this email to Trash?"
                    )
                    buttons = {
                        "inline_keyboard": [[
                            {"text": "✅ Confirm Delete", "callback_data": f"approve:{action_id}"},
                            {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}
                        ]]
                    }
                    background_tasks.add_task(send_telegram_msg, chat_id, preview, buttons)

                elif raw_arg:
                    emails = gmail_manager.search_emails(raw_arg, max_results=5)
                    if emails:
                        action_id = str(uuid.uuid4())[:8]
                        PENDING_ACTIONS[action_id] = {"action": "trash", "ids": [e["id"] for e in emails], "query": raw_arg}
                        preview = f"⚠️ **CONFIRM DELETE**\nQuery: `{raw_arg}`\n\nTarget Emails:\n" + "\n".join([f"• *{e['subject']}* ({e['sender']})" for e in emails])
                        buttons = {"inline_keyboard": [[{"text": "✅ Confirm Delete", "callback_data": f"approve:{action_id}"}, {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}]]}
                        background_tasks.add_task(send_telegram_msg, chat_id, preview, buttons)
                    else:
                        background_tasks.add_task(send_telegram_msg, chat_id, f"No emails found to delete for query: `{raw_arg}`.")
                else:
                    background_tasks.add_task(send_telegram_msg, chat_id, "❌ No recent email found to delete. Search for emails first or swipe-reply!")

            # NATURAL LANGUAGE CHAT & INBOX INQUIRIES
            elif text.startswith("/chat") or "recent mail" in text.lower() or "list of mail" in text.lower() or "my emails" in text.lower():
                q = text.replace("/chat", "").strip()
                if not q: q = "newer_than:7d"
                
                parsed = await gemini_engine.parse_nlp_command(q)
                search_q = parsed.get("query", "newer_than:7d")
                
                emails = gmail_manager.search_emails(search_q, max_results=5) or gmail_manager.search_emails("newer_than:7d", max_results=5) or []
                if emails:
                    LAST_VIEWED_EMAILS[chat_id] = emails
                    res = await gemini_engine.chat_with_inbox(text, emails)
                    background_tasks.add_task(send_telegram_msg, chat_id, res)
                else:
                    background_tasks.add_task(send_telegram_msg, chat_id, "No recent emails found in your inbox.")

            # QUICK ACTIONS: READ, UNREAD, ARCHIVE, STAR, SPAM
            elif any(text.startswith(cmd) for cmd in ["/read", "/unread", "/archive", "/star", "/spam"]):
                cmd = text.split()[0][1:]
                arg = text.replace(f"/{cmd}", "").strip()
                target_ids = []

                if arg.isdigit() and chat_id in LAST_VIEWED_EMAILS:
                    idx = int(arg) - 1
                    if 0 <= idx < len(LAST_VIEWED_EMAILS[chat_id]):
                        target_ids = [LAST_VIEWED_EMAILS[chat_id][idx]["id"]]
                elif not arg and chat_id in LAST_VIEWED_EMAILS and LAST_VIEWED_EMAILS[chat_id]:
                    target_ids = [LAST_VIEWED_EMAILS[chat_id][0]["id"]]

                if target_ids:
                    action_id = str(uuid.uuid4())[:8]
                    PENDING_ACTIONS[action_id] = {"action": cmd, "ids": target_ids, "query": "last viewed"}
                    preview = f"⚠️ **Confirm {cmd.upper()}** for recent email?\n"
                    buttons = {"inline_keyboard": [[{"text": f"✅ Approve {cmd.title()}", "callback_data": f"approve:{action_id}"}, {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}]]}
                    background_tasks.add_task(send_telegram_msg, chat_id, preview, buttons)
                else:
                    emails = gmail_manager.search_emails(arg if arg else "is:unread", max_results=5) or []
                    if emails:
                        action_id = str(uuid.uuid4())[:8]
                        PENDING_ACTIONS[action_id] = {"action": cmd, "ids": [e["id"] for e in emails], "query": arg}
                        preview = f"⚠️ **Confirm {cmd.upper()}**\nQuery: `{arg}`\n\nTarget Emails:\n" + "\n".join([f"• *{e['subject']}* ({e['sender']})" for e in emails])
                        buttons = {"inline_keyboard": [[{"text": f"✅ Approve {cmd.title()}", "callback_data": f"approve:{action_id}"}, {"text": "❌ Cancel", "callback_data": f"cancel:{action_id}"}]]}
                        background_tasks.add_task(send_telegram_msg, chat_id, preview, buttons)

            # SEARCH
            elif text.startswith("/search") or text.startswith("/from") or text.startswith("/subject"):
                q = text
                if text.startswith("/search"): q = text.replace("/search", "").strip() or "is:unread"
                elif text.startswith("/from"): q = f"from:{text.replace('/from', '').strip()}"
                elif text.startswith("/subject"): q = f"subject:{text.replace('/subject', '').strip()}"

                emails = gmail_manager.search_emails(q, max_results=5)
                if emails is None:
                    background_tasks.add_task(send_telegram_msg, chat_id, "❌ **Gmail API Error:** Unauthenticated. Visit `/auth/login`.")
                elif len(emails) == 0:
                    background_tasks.add_task(send_telegram_msg, chat_id, f"No emails found for query: `{q}`")
                else:
                    LAST_VIEWED_EMAILS[chat_id] = emails
                    res_str = f"🔍 **Found {len(emails)} emails:**\n\n"
                    for idx, e in enumerate(emails, start=1):
                        mail_link = get_universal_email_link(e['id'])
                        res_str += f"{idx}. **[{e['subject']}]({mail_link})**\n   From: `{e['sender']}`\n\n"
                    res_str += "💡 *Tip: Type `delete 1` or `/read 1` to manage any email above!*"
                    sent_id = await send_telegram_msg(chat_id, res_str)
                    if sent_id:
                        for e in emails:
                            MESSAGE_TO_EMAIL_MAP[sent_id] = {"gmail_id": e["id"], "subject": e["subject"], "sender": e["sender"]}

            # BRIEF & HELP
            elif text.startswith("/brief"):
                emails = gmail_manager.search_emails("newer_than:2d", max_results=5) or []
                brief = await gemini_engine.generate_briefing(emails) if emails else "No recent emails to brief."
                background_tasks.add_task(send_telegram_msg, chat_id, f"⚡ **Inbox Digest:**\n\n{brief}")

            elif text.startswith("/start") or text.startswith("/help"):
                help_menu = (
                    "🤖 **Gemini AI Mail Assistant Guide**\n\n"
                    "📥 **Inbox Management**\n"
                    "• `/search <query>` – Search emails\n"
                    "• `delete` or `delete 1` – Trash last viewed or 1st email\n"
                    "• `/read 1`, `/unread 1`, `/archive 1`, `/star 1` – Quick actions\n"
                    "• `/undo` – Restore last trashed email\n"
                    "• `/chat <question>` – Natural language inbox questions\n"
                    "• `/brief` – Today's 30s inbox digest\n\n"
                    "💡 *Pro Tip: Send `/chat give list of recent mail` or send `delete 1` after searching!*"
                )
                background_tasks.add_task(send_telegram_msg, chat_id, help_menu)

            else:
                res = await gemini_engine.chat_response(text)
                background_tasks.add_task(send_telegram_msg, chat_id, res)

        finally:
            await delete_telegram_message(chat_id, loading_id)

    return {"status": "ok"}

@app.post("/webhook/gmail")
async def gmail_pubsub_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    background_tasks.add_task(handle_gmail_pubsub_push, body, PENDING_ACTIONS)
    return {"status": "ok"}