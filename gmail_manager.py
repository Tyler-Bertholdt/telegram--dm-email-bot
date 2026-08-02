import base64
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import config

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

class GmailManager:
    def __init__(self):
        self.service = self._get_gmail_service()

    def _get_gmail_service(self):
        """Authenticates and returns the Gmail API service instance."""
        creds = None
        token_path = 'tokens/token.json'

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Note: In production on Render, credentials should be pre-authenticated or passed via ENV.
                if os.path.exists('credentials.json'):
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    creds = flow.run_local_server(port=0)
                    os.makedirs('tokens', exist_ok=True)
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
        
        if creds:
            return build('gmail', 'v1', credentials=creds)
        return None

    def setup_pubsub_watch(self):
        """Sets up Gmail Push Notifications (Pub/Sub watch). Must be renewed every 7 days."""
        if not self.service or not config.GCP_PUBSUB_TOPIC:
            return False
        request_body = {
            'topicName': config.GCP_PUBSUB_TOPIC,
            'labelIds': ['INBOX']
        }
        try:
            res = self.service.users().watch(userId='me', body=request_body).execute()
            print(f"Gmail Pub/Sub watch established: {res}")
            return True
        except Exception as e:
            print(f"Failed to setup Gmail watch: {e}")
            return False

    def search_emails(self, query: str, max_results: int = 5) -> list:
        """Searches emails matching a Gmail query string."""
        if not self.service:
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
            print(f"Error searching emails: {e}")
            return []

    def get_email_details(self, msg_id: str) -> dict:
        """Fetches headers and body of a specific email by ID."""
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

            # Extract body
            body = snippet
            payload = msg.get('payload', {})
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break

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
            print(f"Error getting message details: {e}")
            return {}

    def batch_trash_emails(self, msg_ids: list) -> bool:
        """Trashes a list of message IDs (safe delete)."""
        if not self.service or not msg_ids:
            return False
        try:
            self.service.users().messages().batchDelete(userId='me', body={'ids': msg_ids}).execute()
            return True
        except Exception as e:
            print(f"Error trashing emails: {e}")
            return False

    def batch_archive_emails(self, msg_ids: list) -> bool:
        """Archives a list of message IDs by removing INBOX label."""
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