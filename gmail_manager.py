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
        creds = None
        env_token = config.GMAIL_TOKEN_JSON or os.getenv("GMAIL_TOKEN_JSON")

        if env_token:
            try:
                token_info = json.loads(env_token)
                creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            except Exception as e:
                print(f"Error parsing GMAIL_TOKEN_JSON: {e}")

        token_path = 'tokens/token.json'
        if not creds and os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception as e:
                print(f"Error reading token file: {e}")

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing credentials: {e}")

        if creds and creds.valid:
            return build('gmail', 'v1', credentials=creds)

        print("⚠️ Gmail service unauthenticated.")
        return None

    def setup_pubsub_watch(self):
        if not self.service:
            self.service = self._get_gmail_service()
        if not self.service or not config.GCP_PUBSUB_TOPIC:
            return False

        try:
            res = self.service.users().watch(userId='me', body={'topicName': config.GCP_PUBSUB_TOPIC, 'labelIds': ['INBOX']}).execute()
            print(f"Gmail Pub/Sub watch established: {res}")
            return True
        except Exception as e:
            print(f"Failed to setup Gmail watch: {e}")
            return False

    def search_emails(self, query: str, max_results: int = 5):
        if not self.service:
            self.service = self._get_gmail_service()
            if not self.service:
                return None

        try:
            results = self.service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
            messages = results.get('messages', [])
            return [self.get_email_details(msg['id']) for msg in messages if self.get_email_details(msg['id'])]
        except Exception as e:
            print(f"Error searching emails ({query}): {e}")
            return None

    def get_email_details(self, msg_id: str) -> dict:
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
            print(f"Error getting message {msg_id}: {e}")
            return {}

    def batch_trash_emails(self, msg_ids: list) -> bool:
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'addLabelIds': ['TRASH'], 'removeLabelIds': ['INBOX']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error trashing emails: {e}")
            return False

    def batch_untrash_emails(self, msg_ids: list) -> bool:
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'addLabelIds': ['INBOX'], 'removeLabelIds': ['TRASH']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error restoring emails: {e}")
            return False

    def batch_archive_emails(self, msg_ids: list) -> bool:
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

    def batch_mark_spam(self, msg_ids: list) -> bool:
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'addLabelIds': ['SPAM'], 'removeLabelIds': ['INBOX']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error marking spam: {e}")
            return False

    def batch_mark_read(self, msg_ids: list) -> bool:
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'removeLabelIds': ['UNREAD']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error marking read: {e}")
            return False

    def batch_mark_unread(self, msg_ids: list) -> bool:
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'addLabelIds': ['UNREAD']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error marking unread: {e}")
            return False

    def batch_star(self, msg_ids: list) -> bool:
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchModify(
                userId='me',
                body={'ids': msg_ids, 'addLabelIds': ['STARRED']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error starring emails: {e}")
            return False

    def get_inbox_stats(self) -> dict:
        if not self.service:
            return {}
        try:
            profile = self.service.users().getProfile(userId='me').execute()
            unread = self.service.users().labels().get(userId='me', id='UNREAD').execute()
            return {
                "email": profile.get("emailAddress"),
                "total_messages": profile.get("messagesTotal"),
                "unread_messages": unread.get("messagesUnread"),
                "threads_total": profile.get("threadsTotal")
            }
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}

gmail_manager = GmailManager()