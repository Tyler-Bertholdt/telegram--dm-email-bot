import json
from google import genai
from google.genai import types
from config import config

class GeminiEngine:
    def __init__(self):
        if config.GEMINI_API_KEY:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        else:
            self.client = None

    def summarize_email(self, sender: str, recipient: str, subject: str, date_str: str, body: str) -> str:
        """Generates a structured summary for new incoming emails using Gemini 2.5 Flash."""
        if not self.client:
            return "Gemini API Key is missing."

        prompt = f"""
You are an AI email assistant. Summarize the following email clearly and concisely.

From: {sender}
To: {recipient}
Date: {date_str}
Subject: {subject}

Body:
{body[:3000]}  # Truncate very long bodies

Format your response as a Telegram message with bold headers:
👤 **From:** [Sender Name / Email]
📌 **Subject:** [Subject]
📅 **Date:** [Date/Time]
📝 **Summary:** [2-3 sentence summary]
🎯 **Action Needed:** [Yes/No - if Yes, what action]
"""
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Error generating summary: {str(e)}"

    def parse_nlp_command(self, user_command: str) -> dict:
        """Uses Gemini Function Calling / Structured Output to convert user commands into structured actions."""
        if not self.client:
            return {"action": "error", "message": "Gemini API Key missing"}

        system_instruction = """
You are a Gmail Intent Parser. Convert the user's natural language command into structured JSON parameters for Gmail API.
Return ONLY a valid JSON object matching this schema:
{
  "action": "search" | "archive" | "trash" | "mark_spam" | "mark_read" | "unknown",
  "query": "<gmail search query e.g. is:unread label:newsletter from:substack>",
  "explanation": "<short natural language summary of what will happen>"
}
Do not include code markdown ticks (```json).
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
        """Generates conversational responses for non-command chat messages."""
        if not self.client:
            return "Gemini API Key is missing."
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_text
            )
            return response.text
        except Exception as e:
            return f"Error processing message: {str(e)}"

gemini_engine = GeminiEngine()