import json
import httpx
from config import config

class GeminiEngine:
    def __init__(self):
        self.api_key = config.GEMINI_API_KEY

    @property
    def model_name(self) -> str:
        return config.GEMINI_MODEL_NAME or "gemini-flash-latest"

    @property
    def endpoint_url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

    async def _post(self, prompt: str, json_mode: bool = False) -> str:
        """Helper to post prompts to Gemini REST API."""
        if not self.api_key:
            return "❌ **Gemini API Key missing.** Set `GEMINI_API_KEY` in environment variables."

        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        if json_mode:
            payload["generationConfig"] = {"responseMimeType": "application/json"}

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(self.endpoint_url, json=payload, timeout=30.0)
                if res.status_code != 200:
                    return f"❌ Gemini API Error ({res.status_code}): {res.text}"

                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                return "❌ No response from Gemini."
        except Exception as e:
            return f"❌ HTTP Error: {str(e)}"

    async def summarize_email(self, sender: str, recipient: str, subject: str, date_str: str, body: str, msg_id: str = "") -> str:
        prompt = f"""
Summarize the following email clearly for a Telegram message:

From: {sender}
To: {recipient}
Date: {date_str}
Subject: {subject}

Body:
{body[:3000]}

Format output strictly:
👤 **From:** {sender}
📌 **Subject:** {subject}
📅 **Date:** {date_str}
📝 **Summary:** [2-3 concise sentence summary]
🎯 **Action Items:** [None or specific action required]
"""
        res = await self._post(prompt)
        if msg_id and "❌ Error" not in res:
            res += f"\n\n🔗 [Open Email in Gmail App](https://mail.google.com/mail/u/0/#all/{msg_id})"
        return res

    async def parse_nlp_command(self, user_command: str) -> dict:
        prompt = f"""
You are a Gmail Intent Parser. Convert the user command into JSON.

User Command: {user_command}

Supported actions: "summarize", "search", "trash", "archive", "spam", "read", "unread", "star", "otp", "expenses", "tracking", "action", "brief", "phishing", "unknown".

Return ONLY a JSON object:
{{
  "action": "summarize" | "search" | "trash" | "archive" | "spam" | "read" | "unread" | "star" | "otp" | "expenses" | "tracking" | "action" | "brief" | "phishing" | "unknown",
  "query": "<gmail search query e.g. is:unread, label:newsletter, category:updates>",
  "explanation": "<short explanation>"
}}
"""
        res_text = await self._post(prompt, json_mode=True)
        try:
            return json.loads(res_text)
        except Exception:
            return {"action": "unknown", "query": user_command, "explanation": "Direct search"}

    async def generate_briefing(self, emails: list) -> str:
        email_text = "\n---\n".join([f"From: {e['sender']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}" for e in emails])
        prompt = f"Provide a executive morning digest of these inbox emails in bullet points:\n{email_text[:4000]}"
        return await self._post(prompt)

    async def extract_action_items(self, emails: list) -> str:
        email_text = "\n---\n".join([f"From: {e['sender']}\nSubject: {e['subject']}\nBody: {e['body'][:500]}" for e in emails])
        prompt = f"Extract all action items, tasks, and deadlines from these emails:\n{email_text[:4000]}"
        return await self._post(prompt)

    async def analyze_phishing(self, email_detail: dict) -> str:
        prompt = f"""
Analyze this email for security risk and phishing likelihood (Rate 0-10):

From: {email_detail.get('sender')}
Subject: {email_detail.get('subject')}
Body:
{email_detail.get('body')[:2000]}

Provide:
1. 🛡️ Risk Score (0-10)
2. ⚠️ Suspicious Indicators
3. 💡 Recommendation
"""
        return await self._post(prompt)

    async def summarize_newsletter_group(self, emails: list) -> str:
        email_text = "\n---\n".join([f"Subject: {e['subject']}\nSnippet: {e['snippet']}" for e in emails])
        prompt = f"Group and summarize these newsletter emails into key topics:\n{email_text[:3000]}"
        return await self._post(prompt)

    async def chat_with_inbox(self, query: str, context_emails: list) -> str:
        context = "\n---\n".join([f"From: {e['sender']}\nDate: {e['date']}\nSubject: {e['subject']}\nBody: {e['body'][:600]}" for e in context_emails])
        prompt = f"Answer the user's question based strictly on their emails:\n\nUser Question: {query}\n\nEmail Context:\n{context[:4000]}"
        return await self._post(prompt)

    async def chat_response(self, user_text: str) -> str:
        return await self._post(user_text)

gemini_engine = GeminiEngine()