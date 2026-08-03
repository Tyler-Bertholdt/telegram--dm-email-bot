import json
import httpx
from config import config

class GeminiEngine:
    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        # You can use gemini-2.5-flash, gemini-1.5-flash, or gemini-2.0-flash
        self.model_name = config.GEMINI_MODEL_NAME or "gemini-2.5-flash"

    @property
    def endpoint_url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

    async def summarize_email(self, sender: str, recipient: str, subject: str, date_str: str, body: str) -> str:
        """Summarizes an email using a direct REST POST request."""
        if not self.api_key:
            return "❌ **Gemini API Key missing.** Set `GEMINI_API_KEY` in environment variables."

        prompt = f"""
Summarize the following email clearly for a Telegram message:

From: {sender}
To: {recipient}
Date: {date_str}
Subject: {subject}

Body:
{body[:3000]}

Please format the response strictly as:
👤 **From:** {sender}
📌 **Subject:** {subject}
📅 **Date:** {date_str}
📝 **Summary:** [2-3 concise sentence summary]
🎯 **Action Items:** [None or specific action required]
"""

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ]
        }

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

                return "❌ No text returned from Gemini."
        except Exception as e:
            return f"❌ HTTP Error calling Gemini API: {str(e)}"

    async def parse_nlp_command(self, user_command: str) -> dict:
        """Parses natural language commands using JSON mode via REST API."""
        if not self.api_key:
            return {"action": "error", "message": "GEMINI_API_KEY is missing."}

        prompt = f"""
You are a Gmail Intent Parser. Convert the user's natural language command into a JSON response.

User Command: {user_command}

Supported actions:
- "summarize": user wants to read or summarize emails.
- "search": user wants to find or list emails.
- "trash": user wants to delete emails.
- "archive": user wants to archive emails.
- "unknown": command is unclear or unsupported.

Return ONLY a valid JSON object matching this schema:
{{
  "action": "summarize" | "search" | "trash" | "archive" | "unknown",
  "query": "<valid gmail search query string e.g. is:unread, label:newsletter, newer_than:2d>",
  "explanation": "<short natural language summary of what will happen>"
}}
"""

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(self.endpoint_url, json=payload, timeout=30.0)
                if res.status_code != 200:
                    return {"action": "error", "message": f"API Error ({res.status_code}): {res.text}"}

                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        json_text = parts[0].get("text", "")
                        return json.loads(json_text)

                return {"action": "error", "message": "No JSON returned from Gemini."}
        except Exception as e:
            return {"action": "error", "message": str(e)}

    async def chat_response(self, user_text: str) -> str:
        """Handles basic conversational queries."""
        if not self.api_key:
            return "❌ Gemini API Key is missing."

        payload = {
            "contents": [{"parts": [{"text": user_text}]}]
        }

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(self.endpoint_url, json=payload, timeout=30.0)
                if res.status_code != 200:
                    return f"❌ Error ({res.status_code}): {res.text}"

                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                return "No response generated."
        except Exception as e:
            return f"Error: {str(e)}"

gemini_engine = GeminiEngine()