import base64
import os
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import config

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

class GmailManager:
    def __init__(self):
        self.service = self._get_gmail_service()

    def _get_gmail_service(self):
        """Authenticates using environment JSON variable or local token file."""
        creds = None
        env_token = config.GMAIL_TOKEN_JSON or os.getenv("GMAIL_TOKEN_JSON")

        # 1. Load from Environment Variable (Render Cloud Production)
        if env_token:
            try:
                token_info = json.loads(env_token)
                creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            except Exception as e:
                print(f"Error parsing GMAIL_TOKEN_JSON: {e}")

        # 2. Fallback to local token file if present
        token_path = 'tokens/token.json'
        if not creds and os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception as e:
                print(f"Error reading local token file: {e}")

        # Refresh token if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token credentials: {e}")

        if creds and creds.valid:
            return build('gmail', 'v1', credentials=creds)

        print("⚠️ Warning: Gmail service could not be authenticated. Ensure GMAIL_TOKEN_JSON is configured.")
        return None

    def setup_pubsub_watch(self):
        """Establishes Gmail Push Watch notification with GCP Pub/Sub."""
        if not self.service:
            print("Cannot setup watch: Gmail service not authenticated.")
            return False
        if not config.GCP_PUBSUB_TOPIC:
            print("Cannot setup watch: GCP_PUBSUB_TOPIC not configured.")
            return False

        request_body = {
            'topicName': config.GCP_PUBSUB_TOPIC,
            'labelIds': ['INBOX']
        }
        try:
            res = self.service.users().watch(userId='me', body=request_body).execute()
            print(f"Gmail Pub/Sub watch established successfully: {res}")
            return True
        except Exception as e:
            print(f"Failed to setup Gmail watch: {e}")
            return False

    def search_emails(self, query: str, max_results: int = 5) -> list:
        """Searches emails matching a query string."""
        if not self.service:
            print("Search failed: Gmail service unauthenticated.")
            return []
        try:
            results = self.service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
            messages = results.get('messages', [])
            detailed_list = []
            for msg in messages:
                detail = self.get_email_details(msg['id'])
                if detail:
                    detailed_list.append(detail)
            return detailed_list
        except Exception as e:
            print(f"Error searching emails ({query}): {e}")
            return []

    def get_email_details(self, msg_id: str) -> dict:
        """Fetches full details and body of an email by message ID."""
        if not self.service:
            return {}
        try:
            msg = self.service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            headers = msg.get('payload', {}).get('headers', [])

            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            recipient = next((h['value'] for h in headers if h['name'].lower() == 'to'), 'Unknown Recipient')
            date_str = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')
            snippet = msg.get('snippet', '')

            # Extract email body
            body = snippet
            payload = msg.get('payload', {})
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break
            elif 'body' in payload and 'data' in payload['body']:
                body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')

            return {
                "id": msg_id,
                "sender": sender,
                "recipient": recipient,
                "subject": subject,
                "date": date_str,
                "snippet": snippet,
                "body": body
            }
        except Exception as e:
            print(f"Error getting message details for ID {msg_id}: {e}")
            return {}

    def batch_trash_emails(self, msg_ids: list) -> bool:
        """Moves a list of email IDs to trash."""
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchDelete(userId='me', body={'ids': msg_ids}).execute()
            return True
        except Exception as e:
            print(f"Error trashing emails: {e}")
            return False

    def batch_archive_emails(self, msg_ids: list) -> bool:
        """Archives a list of email IDs."""
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'removeLabelIds': ['INBOX']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error archiving emails: {e}")
            return False

gmail_manager = GmailManager()