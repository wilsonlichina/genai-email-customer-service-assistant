# Gmail API Email Retrieval Tool

This tool allows you to interact with your Gmail inbox using the Gmail API, retrieve emails from different labels, and display their content.

## Features

- List all Gmail labels
- Retrieve emails from any label (default: INBOX)
- Filter emails using Gmail search queries
- View email previews or full message bodies
- Retrieve a specific email by its ID
- Customize the number of emails to retrieve

## Prerequisites

1. Google API credentials (`credentials.json` file)
2. Required Python packages:
   - google-auth
   - google-auth-oauthlib
   - google-auth-httplib2
   - google-api-python-client

## Usage

### Basic usage (default: retrieves 5 emails from INBOX)

```bash
python gmailfetch.py
```

### List all available Gmail labels

```bash
python gmailfetch.py --list-labels
```

### Retrieve emails from a specific label

```bash
python gmailfetch.py --label "INBOX"
python gmailfetch.py --label "IMPORTANT"
python gmailfetch.py --label "UNREAD"
```

### Customize the number of emails to retrieve

```bash
python gmailfetch.py --max 10
```

### Display full email bodies (instead of just previews)

```bash
python gmailfetch.py --full
```

### Use search queries to filter emails

```bash
python gmailfetch.py --query "from:example@gmail.com"
python gmailfetch.py --query "subject:meeting"
python gmailfetch.py --query "is:unread"
python gmailfetch.py --query "after:2023/01/01 before:2023/02/01"
```

### Retrieve a specific email by ID

```bash
python gmailfetch.py --id "YOUR_EMAIL_ID"
```

### Combine options

```bash
python gmailfetch.py --label "SENT" --max 20 --full --query "to:example@gmail.com"
```

## Authentication

The first time you run the script, it will open a browser window asking you to authorize the application. After authorization, a `token.json` file will be created for future use.

## Common Gmail Search Operators

- `from:` - Specify the sender
- `to:` - Specify the recipient
- `subject:` - Search for words in the subject line
- `is:unread` - Find unread messages
- `is:read` - Find read messages
- `has:attachment` - Find messages with attachments
- `after:YYYY/MM/DD` - Find messages sent after a certain date
- `before:YYYY/MM/DD` - Find messages sent before a certain date
- `is:starred` - Find starred messages
- `is:important` - Find important messages
- `in:anywhere` - Search all emails
- `in:inbox` - Search inbox
- `in:trash` - Search trash
