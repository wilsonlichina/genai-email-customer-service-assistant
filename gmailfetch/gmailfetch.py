import os.path
import base64
import email
import datetime
import argparse
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gmailfetch")

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

TOKEN_FILE_PATH = "gmailfetch/token.json"
CREDENTIALS_FILE_PATH = "gmailfetch/credentials.json"

def get_gmail_service():
    """Authenticate and return the Gmail service."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(TOKEN_FILE_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE_PATH, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_FILE_PATH, "w") as token:
            token.write(creds.to_json())
    
    # Build and return the Gmail service
    service = build("gmail", "v1", credentials=creds)
    return service

def get_email_content(service, msg_id):
    """Get the full content of an email message."""
    try:
        # Get the full message
        message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        # Get message payload and headers
        payload = message.get('payload', {})
        headers = payload.get('headers', [])
        
        # Extract header information
        email_data = {
            'id': msg_id,
            'subject': next((header['value'] for header in headers if header['name'].lower() == 'subject'), 'No Subject'),
            'from': next((header['value'] for header in headers if header['name'].lower() == 'from'), 'Unknown Sender'),
            'to': next((header['value'] for header in headers if header['name'].lower() == 'to'), 'Unknown Recipient'),
            'date': next((header['value'] for header in headers if header['name'].lower() == 'date'), 'Unknown Date'),
        }
        
        # Get the message body
        body = ""
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    body = get_message_text(part)
                    break
                elif 'parts' in part:  # Handle nested parts
                    for subpart in part['parts']:
                        if subpart['mimeType'] == 'text/plain':
                            body = get_message_text(subpart)
                            break
        elif 'body' in payload and 'data' in payload['body']:
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')
        
        email_data['body'] = body
        email_data['snippet'] = message.get('snippet', 'No preview available')
        
        return email_data
    except Exception as e:
        logger.info(f"Error retrieving email content: {e}")
        return None

def get_message_text(message_part):
    """Decode and return the message text from a message part."""
    if 'body' in message_part and 'data' in message_part['body']:
        text = base64.urlsafe_b64decode(message_part['body']['data']).decode('utf-8', errors='replace')
        return text
    return ""

def list_labels(service):
    """List all available Gmail labels."""
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    
    if not labels:
        logger.info("No labels found.")
        return []
    
    logger.info("Available labels:")
    for label in labels:
        logger.info(f"- {label['name']}")
    
    return labels

def fetch_emails(service, label_ids=['INBOX'], max_results=10, query=None):
    """Fetch emails from specified labels with optional query."""
    try:
        # Build the list request
        request = {
            'userId': 'me',
            'labelIds': label_ids,
            'maxResults': max_results
        }
        if query:
            request['q'] = query
            
        # Execute the request
        results = service.users().messages().list(**request).execute()
        messages = results.get('messages', [])
        
        if not messages:
            logger.info(f"No messages found with the specified criteria.")
            return []
        
        logger.info(f"\nFound {len(messages)} messages.")
        email_list = []
        
        for i, message in enumerate(messages, 1):
            email_data = get_email_content(service, message['id'])
            if email_data:
                email_list.append(email_data)
            
            # Print progress for larger fetches
            if i % 5 == 0 and max_results > 5:
                logger.info(f"Processed {i}/{min(len(messages), max_results)} emails...")
        
        return email_list
        
    except HttpError as error:
        logger.info(f"An error occurred: {error}")
        return []

def display_email(email_data, show_body=True):
    """Display email information in a readable format."""
    logger.info("\n" + "=" * 80)
    logger.info(f"ID: {email_data['id']}")
    logger.info(f"From: {email_data['from']}")
    logger.info(f"To: {email_data['to']}")
    logger.info(f"Date: {email_data['date']}")
    logger.info(f"Subject: {email_data['subject']}")
    logger.info("-" * 80)
    
    if show_body:
        logger.info("Body:")
        logger.info(email_data['body'] if email_data['body'] else email_data['snippet'])
    else:
        logger.info("Preview:")
        logger.info(email_data['snippet'])
    
    logger.info("=" * 80)

def get_complete_emails(count=5, display=False):
    """
    Fetch complete emails from INBOX.
    
    Args:
        count: Number of emails to fetch (default: 5)
        display: Whether to display the emails after fetching (default: False)
        
    Returns:
        List of email objects with complete content
    """
    try:
        # Get authenticated Gmail service
        service = get_gmail_service()
        
        logger.info(f"Fetching {count} complete emails from INBOX...")
        
        # Fetch emails from INBOX
        emails = fetch_emails(
            service,
            label_ids=['INBOX'],
            max_results=count,
            query=None
        )
        
        # Display emails if requested
        if display and emails:
            for email_data in emails:
                display_email(email_data, show_body=True)
        
        return emails
    
    except HttpError as error:
        logger.info(f"An error occurred: {error}")
        return []
    except Exception as e:
        logger.info(f"An unexpected error occurred: {e}")
        return []


def main():
    """Enhanced Gmail API tool to interact with your email inbox."""
    parser = argparse.ArgumentParser(description='Gmail API Email Retrieval Tool')
    parser.add_argument('--list-labels', action='store_true', help='List all available Gmail labels')
    parser.add_argument('--label', default='INBOX', help='Label to fetch emails from (default: INBOX)')
    parser.add_argument('--max', type=int, default=5, help='Maximum number of emails to retrieve (default: 5)')
    parser.add_argument('--query', help='Search query to filter emails')
    parser.add_argument('--full', action='store_true', help='Show full email body (default: preview only)')
    parser.add_argument('--id', help='Fetch and display a specific email by ID')
    parser.add_argument('--complete', action='store_true', help='Fetch complete emails from INBOX (default: 5 emails)')
    parser.add_argument('--count', type=int, default=5, help='Number of complete emails to fetch (works with --complete)')
    
    args = parser.parse_args()
    
    try:
        # Get authenticated Gmail service
        service = get_gmail_service()
        
        # List labels if requested
        if args.list_labels:
            list_labels(service)
            return
        
        # If specific email ID provided, fetch and display just that email
        if args.id:
            logger.info(f"Fetching email with ID: {args.id}")
            email_data = get_email_content(service, args.id)
            if email_data:
                display_email(email_data, show_body=True)
            else:
                logger.info(f"Email with ID {args.id} not found or inaccessible.")
            return
        
        # Handle the complete emails request
        if args.complete:
            emails = get_complete_emails(count=args.count, display=True)
            return
        
        # Otherwise fetch emails based on criteria
        label_ids = [args.label]
        logger.info(f"Fetching up to {args.max} emails from {args.label}" + 
              (f" matching query: '{args.query}'" if args.query else ""))
        
        emails = fetch_emails(
            service,
            label_ids=label_ids,
            max_results=args.max,
            query=args.query
        )
        
        # Display the retrieved emails
        for email_data in emails:
            display_email(email_data, show_body=args.full)
            
    except HttpError as error:
        logger.info(f"An error occurred: {error}")
    except Exception as e:
        logger.info(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
  main()
