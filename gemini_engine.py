import json
from google import genai
from google.genai import types
from config import config

class GeminiEngine:
    def __init__(self):
        self._init_client()

    def _init_client(self):
        """Initializes or re-initializes the Google GenAI Client."""
        if config.GEMINI_API_KEY:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        else:
            self.client = None

    def summarize_email(self, sender: str, recipient: str, subject: str, date_str: str, body: str) -> str:
        """Generates a clean Telegram summary of an email using Gemini 2.5 Flash."""
        if not self.client:
            self._init_client()
            if not self.client:
                return "❌ **Gemini API Key missing.** Set `GEMINI_API_KEY` in Render environment variables."

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
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"❌ Error generating summary: {str(e)}"

    def parse_nlp_command(self, user_command: str) -> dict:
        """Parses natural language commands into Gmail parameters via Gemini JSON Output."""
        if not self.client:
            self._init_client()
            if not self.client:
                return {"action": "error", "message": "GEMINI_API_KEY is missing in Render variables."}

        system_instruction = """
You are a Gmail Intent Parser. Convert the user's natural language command into a structured JSON payload for Gmail API actions.

Supported actions:
- "summarize": user wants to read or summarize emails.
- "search": user wants to find or list emails.
- "trash": user wants to delete emails.
- "archive": user wants to archive emails.
- "unknown": command is unclear or unsupported.

Return ONLY a valid JSON object matching this schema:
{
  "action": "summarize" | "search" | "trash" | "archive" | "unknown",
  "query": "<valid gmail search query string e.g. is:unread, label:newsletter, newer_than:2d>",
  "explanation": "<short natural language summary of what will happen>"
}
Do not wrap response in markdown code ticks.
"""
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"User Command: {user_command}",
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            return {"action": "error", "message": str(e)}

    def chat_response(self, user_text: str) -> str:
        """Handles regular conversational messages."""
        if not self.client:
            self._init_client()
            if not self.client:
                return "❌ Gemini API Key is missing."
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_text
            )
            return response.text
        except Exception as e:
            return f"Error processing message: {str(e)}"

gemini_engine = GeminiEngine()