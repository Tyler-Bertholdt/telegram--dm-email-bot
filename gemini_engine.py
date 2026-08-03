import json
from google import genai
from google.genai import types
from config import config

class GeminiEngine:
    def __init__(self):
        self._init_client()

    def _init_client(self):
        """Initializes the GenAI Client with the API Key."""
        if config.GEMINI_API_KEY:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        else:
            self.client = None

    @property
    def model_name(self) -> str:
        return config.GEMINI_MODEL_NAME or "gemini-2.5-flash"

    def summarize_email(self, sender: str, recipient: str, subject: str, date_str: str, body: str) -> str:
        """Generates a structured email summary for Telegram."""
        if not self.client:
            self._init_client()
            if not self.client:
                return "❌ **Gemini API Key missing.** Please set GEMINI_API_KEY in environment variables."

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
                model=self.model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"❌ Error generating summary ({self.model_name}): {str(e)}"

    def parse_nlp_command(self, user_command: str) -> dict:
        """Parses user natural language into structured JSON for Gmail actions."""
        if not self.client:
            self._init_client()
            if not self.client:
                return {"action": "error", "message": "GEMINI_API_KEY is missing in environment variables."}

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
"""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
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
        """Handles standard chatbot conversations."""
        if not self.client:
            self._init_client()
            if not self.client:
                return "❌ Gemini API Key is missing."
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_text
            )
            return response.text
        except Exception as e:
            return f"Error processing message ({self.model_name}): {str(e)}"

gemini_engine = GeminiEngine()