"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""
import os
import re
import json
import time
import html
import logging
import requests
import gradio as gr
import base64
import uuid
import imaplib
import email
import email.header
import email.utils
import asyncio
import threading
from datetime import datetime
from io import BytesIO
import copy
from email_validator import validate_email, EmailNotValidError
from dotenv import load_dotenv
load_dotenv()  # load env vars from .env
API_KEY = os.environ.get("API_KEY")

# Import the process_query_stream function
from src.compatible_chat_client_stream import CompatibleChatClientStream

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logs
)

mcp_base_url = os.environ.get('MCP_BASE_URL')
mcp_command_list = ["uvx", "npx", "node", "python", "docker", "uv"]
COOKIE_NAME = "mcp_chat_user_id"
EMAIL_ACCOUNTS_PATH = "conf/email_accounts.json"

# Email account management
def load_email_accounts():
    """Load email accounts from the configuration file"""
    try:
        with open(EMAIL_ACCOUNTS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Create default structure if file doesn't exist or is invalid
        default_accounts = {
            "accounts": [],
            "current_account": None
        }
        save_email_accounts(default_accounts)
        return default_accounts

def save_email_accounts(accounts_data):
    """Save email accounts to the configuration file"""
    with open(EMAIL_ACCOUNTS_PATH, "w") as f:
        json.dump(accounts_data, f, indent=2)

def add_email_account(username, password, imap_server, imap_port, use_ssl=True):
    """Add a new email account"""
    accounts_data = load_email_accounts()
    
    # Check if account already exists
    for account in accounts_data["accounts"]:
        if account["username"] == username:
            return False, f"Account {username} already exists"
    
    # Add the new account
    new_account = {
        "id": username,
        "username": username,
        "password": password,
        "imap_server": imap_server,
        "imap_port": int(imap_port),
        "use_ssl": use_ssl
    }
    
    accounts_data["accounts"].append(new_account)
    
    # If this is the first account, set it as the current account
    if accounts_data["current_account"] is None:
        accounts_data["current_account"] = username
    
    save_email_accounts(accounts_data)
    return True, f"Account {username} added successfully"

def delete_email_account(username):
    """Delete an email account"""
    accounts_data = load_email_accounts()
    
    # Find the account to delete
    account_found = False
    for i, account in enumerate(accounts_data["accounts"]):
        if account["username"] == username:
            accounts_data["accounts"].pop(i)
            account_found = True
            break
    
    if not account_found:
        return False, f"Account {username} not found"
    
    # Update current account if needed
    if accounts_data["current_account"] == username:
        if accounts_data["accounts"]:
            accounts_data["current_account"] = accounts_data["accounts"][0]["username"]
        else:
            accounts_data["current_account"] = None
    
    save_email_accounts(accounts_data)
    return True, f"Account {username} deleted successfully"

def set_current_account(username):
    """Set an account as the current account"""
    accounts_data = load_email_accounts()
    
    # Check if account exists
    account_found = False
    for account in accounts_data["accounts"]:
        if account["username"] == username:
            account_found = True
            break
    
    if not account_found:
        return False, f"Account {username} not found"
    
    accounts_data["current_account"] = username
    save_email_accounts(accounts_data)
    return True, f"Current account set to {username}"

def get_current_account():
    """Get the current account configuration"""
    accounts_data = load_email_accounts()
    current_account_id = accounts_data.get("current_account")
    
    if current_account_id is None:
        return None
    
    for account in accounts_data["accounts"]:
        if account["username"] == current_account_id:
            return account
    
    return None

def fetch_emails(account, max_emails=10):
    """Fetch emails from the specified account"""
    emails = []
    mail = None
    
    try:
        # Log account details (without password)
        logging.info(f"Attempting to fetch emails for: {account['username']}")
        logging.debug(f"IMAP server: {account['imap_server']}")
        logging.debug(f"IMAP port: {account['imap_port']}")
        logging.debug(f"Using SSL: {account['use_ssl']}")
        
        # Connect to the IMAP server
        try:
            logging.info(f"Connecting to IMAP server: {account['imap_server']}:{account['imap_port']}")
            if account["use_ssl"]:
                mail = imaplib.IMAP4_SSL(account["imap_server"], account["imap_port"])
                logging.info("Connected using SSL")
            else:
                mail = imaplib.IMAP4(account["imap_server"], account["imap_port"])
                logging.info("Connected without SSL")
        except Exception as e:
            logging.error(f"Error connecting to IMAP server: {str(e)}")
            return [], f"Connection error: {str(e)}"
        
        # Login to the server
        try:
            logging.info(f"Attempting to login as: {account['username']}")
            logging.info(f"Attempting to login as: {account['password']}")
            mail.login(account["username"], account["password"])
            logging.info("Login successful")
        except imaplib.IMAP4.error as e:
            logging.error(f"IMAP login error: {str(e)}")
            if mail:
                try:
                    mail.logout()
                except:
                    pass
            return [], f"Authentication error: {str(e)}"
        
        # Select the inbox
        logging.info("Selecting INBOX folder")
        status, messages = mail.select("INBOX")
        
        if status != "OK":
            logging.error(f"Failed to select INBOX: {messages}")
            return [], f"Failed to select INBOX: {messages}"
        
        logging.info("INBOX selected successfully")
        
        # Get the message IDs
        logging.info("Searching for messages")
        status, messages = mail.search(None, "ALL")
        
        if status != "OK":
            logging.error(f"Failed to search messages: {messages}")
            return [], f"Failed to search messages: {messages}"
        
        message_ids = messages[0].split()
        logging.info(f"Found {len(message_ids)} messages")
        
        # Get the most recent emails
        start_idx = max(0, len(message_ids) - max_emails)
        recent_ids = message_ids[start_idx:]
        recent_ids.reverse()  # Most recent first
        logging.info(f"Processing {len(recent_ids)} recent messages")
        
        for msg_id in recent_ids:
            logging.debug(f"Fetching message ID: {msg_id}")
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            
            if status != "OK":
                logging.warning(f"Failed to fetch message {msg_id}: {status}")
                continue
            
            # Parse the email
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # Decode the subject
            subject = ""
            subject_header = msg.get("Subject", "")
            if subject_header:
                decoded_header = email.header.decode_header(subject_header)
                subject = decoded_header[0][0]
                if isinstance(subject, bytes):
                    subject = subject.decode("utf-8", errors="replace")
            
            # Get the sender
            sender = ""
            from_header = msg.get("From", "")
            if from_header:
                sender_name, sender_addr = email.utils.parseaddr(from_header)
                if sender_name:
                    sender = sender_name
                else:
                    sender = sender_addr
            
            # Get the date
            date_header = msg.get("Date", "")
            date = email.utils.parsedate_to_datetime(date_header) if date_header else None
            date_str = date.strftime("%Y-%m-%d %H:%M:%S") if date else "Unknown"
            
            # Get the email body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                        except Exception as e:
                            logging.error(f"Error decoding email part: {str(e)}")
                            body = f"Error decoding email: {str(e)}"
            else:
                try:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception as e:
                    logging.error(f"Error decoding email body: {str(e)}")
                    body = f"Error decoding email: {str(e)}"
            
            # Add the email to the list
            emails.append({
                "id": msg_id.decode("utf-8"),
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "body": body
            })
            logging.debug(f"Added email: {subject}")
        
        # Close the connection
        logging.info("Closing IMAP connection")
        mail.close()
        mail.logout()
        
        logging.info(f"Successfully fetched {len(emails)} emails")
        return emails, "Emails fetched successfully"
    
    except Exception as e:
        logging.exception(f"Error in fetch_emails: {str(e)}")
        if mail:
            try:
                mail.logout()
            except:
                pass
        return [], f"Error fetching emails: {str(e)}"

# 用户会话管理
def get_user_id(request: gr.Request = None):
    """获取或生成用户ID"""
    user_id = None
    if request:
        cookies = request.cookies
        user_id = cookies.get(COOKIE_NAME)
    
    if not user_id:
        user_id = str(uuid.uuid4())[:8]
    
    return user_id

def get_auth_headers(user_id):
    """构建包含用户身份的认证头"""
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'X-User-ID': user_id
    }
    return headers

def request_list_models(user_id):
    url = mcp_base_url.rstrip('/') + '/v1/list/models'
    models = []
    try:
        logging.info(f'Requesting models list for user: {user_id}')
        headers = get_auth_headers(user_id)
        logging.info(f'Request headers: {headers}')
        logging.info(f'Request URL: {url}')
        
        # Add timeout to prevent hanging
        response = requests.get(url, headers=headers, timeout=10)
        logging.info(f'Response status code: {response.status_code}')
        
        if response.status_code != 200:
            logging.error(f'Error response: {response.text}')
            # If we can't get models from the API, use fallback models
            return [
                {"model_id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "model_name": "Claude 3.5 Sonnet v2"},
                {"model_id": "us.amazon.nova-pro-v1:0", "model_name": "Amazon Nova Pro v1"}
            ]
            
        data = response.json()
        models = data.get('models', [])
        logging.info(f'Retrieved models: {models}')
        
        # If no models returned, use fallback models
        if not models:
            logging.warning("No models returned from API, using fallback models")
            return [
                {"model_id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "model_name": "Claude 3.5 Sonnet v2"},
                {"model_id": "us.amazon.nova-pro-v1:0", "model_name": "Amazon Nova Pro v1"}
            ]
            
    except Exception as e:
        logging.error(f'Request list models error: {str(e)}')
        import traceback
        logging.error(traceback.format_exc())
        
        # Return fallback models in case of any exception
        logging.warning("Using fallback models due to exception")
        return [
            {"model_id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "model_name": "Claude 3.5 Sonnet v2"},
            {"model_id": "us.amazon.nova-pro-v1:0", "model_name": "Amazon Nova Pro v1"}
        ]
        
    return models

def request_list_mcp_servers(user_id):
    url = mcp_base_url.rstrip('/') + '/v1/list/mcp_server'
    mcp_servers = []
    try:
        response = requests.get(url, headers=get_auth_headers(user_id))
        data = response.json()
        mcp_servers = data.get('servers', [])
    except Exception as e:
        logging.error('request list mcp servers error: %s' % e)
    return mcp_servers

def request_add_mcp_server(user_id, server_id, server_name, command, args=[], env=None, config_json={}):
    url = mcp_base_url.rstrip('/') + '/v1/add/mcp_server'
    status = False
    try:
        payload = {
            "server_id": server_id,
            "server_desc": server_name,
            "command": command,
            "args": args,
            "config_json": config_json
        }
        if env:
            payload["env"] = env
        response = requests.post(url, json=payload, headers=get_auth_headers(user_id))
        data = response.json()
        status = data['errno'] == 0
        msg = data['msg']
    except Exception as e:
        msg = "Add MCP server occurred errors!"
        logging.error('request add mcp servers error: %s' % e)
    return status, msg

def process_stream_response(response):
    """Process streaming response and yield content chunks"""
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data = line[6:]  # Remove 'data: ' prefix
                if data == '[DONE]':
                    break
                try:
                    json_data = json.loads(data)
                    delta = json_data['choices'][0].get('delta', {})
                    if 'role' in delta:
                        continue
                    if 'content' in delta:
                        yield delta['content']
                    
                    message_extras = json_data['choices'][0].get('message_extras', {})
                    if "tool_use" in message_extras:
                        yield f"<tool_use>{message_extras['tool_use']}</tool_use>"

                except json.JSONDecodeError:
                    logging.error(f"Failed to parse JSON: {data}")
                except Exception as e:
                    logging.error(f"Error processing stream: {e}")

def request_chat(user_id, messages, model_id, mcp_server_ids, stream=True, max_tokens=1024, temperature=0.6, extra_params={}):
    url = mcp_base_url.rstrip('/') + '/v1/chat/completions'
    msg, msg_extras = 'something is wrong!', {}
    try:
        payload = {
            'messages': messages,
            'model': model_id,
            'mcp_server_ids': mcp_server_ids,
            'extra_params': extra_params,
            'stream': stream,
            'temperature': temperature,
            'max_tokens': max_tokens
        }
        logging.info(f'用户 {user_id} 请求payload: %s' % payload)
        
        if stream:
            # 流式请求
            headers = get_auth_headers(user_id)
            headers['Accept'] = 'text/event-stream'  
            response = requests.post(url, json=payload, stream=True, headers=headers)
            
            if response.status_code == 200:
                return response, {}
            else:
                msg = 'An error occurred when calling the Converse operation: The system encountered an unexpected error during processing. Try your request again.'
                logging.error(f'用户 {user_id} 请求聊天错误: %d' % response.status_code)
        else:
            # 常规请求
            response = requests.post(url, json=payload, headers=get_auth_headers(user_id))
            data = response.json()
            msg = data['choices'][0]['message']['content']
            msg_extras = data['choices'][0]['message_extras']

    except Exception as e:
        msg = 'An error occurred when calling the Converse operation: The system encountered an unexpected error during processing. Try your request again.'
        logging.error(f'用户 {user_id} 请求聊天错误: %s' % e)
    
    logging.info(f'用户 {user_id} 响应消息: %s' % msg)
    return msg, msg_extras

def add_new_mcp_server(user_id, server_name, server_id, server_cmd, server_args, server_env, server_config_json):
    status, msg = True, "The server already been added!"
    config_json = {}
    
    if not server_name:
        status, msg = False, "The server name is empty!"
    
    # 如果server_config_json配置，则已server_config_json为准
    if server_config_json:
        try:
            config_json = json.loads(server_config_json)
            if not all([isinstance(k, str) for k in config_json.keys()]):
                raise ValueError("env key must be str.")
            if "mcpServers" in config_json:
                config_json = config_json["mcpServers"]
            # 直接使用json配置里的id
            logging.info(f'用户 {user_id} 添加新MCP服务器: {config_json}')
            server_id = list(config_json.keys())[0]
            server_cmd = config_json[server_id]["command"]
            server_args = config_json[server_id]["args"]
            server_env = config_json[server_id].get('env')
        except Exception as e:
            status, msg = False, "The config must be a valid JSON."

    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', server_id):
        status, msg = False, "The server id must be a valid variable name!"
    elif not server_cmd or server_cmd not in mcp_command_list:
        status, msg = False, "The server command is invalid!"
    
    if server_env:
        try:
            server_env = json.loads(server_env) if not isinstance(server_env, dict) else server_env
            if not all([isinstance(k, str) for k in server_env.keys()]):
                raise ValueError("env key must be str.")
            if not all([isinstance(v, str) for v in server_env.values()]):
                raise ValueError("env value must be str.")
        except Exception as e:
            server_env = {}
            status, msg = False, "The server env must be a JSON dict[str, str]."
    
    if isinstance(server_args, str):
        server_args = [x.strip() for x in server_args.split(' ') if x.strip()]

    logging.info(f'用户 {user_id} 添加新MCP服务器: {server_id}:{server_name}')
    
    if status:
        status, msg = request_add_mcp_server(user_id, server_id, server_name, server_cmd, 
                                         args=server_args, env=server_env, config_json=config_json)
    
    return status, msg

def chat_function(user_id, message, history, model_name, model_id_map, mcp_servers, selected_servers, 
                  system_prompt, max_tokens, budget_tokens, temperature, n_recent_images, enable_thinking, enable_stream):
    """处理聊天功能"""
    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]
    
    # 添加历史消息
    for user_msg, bot_msg in history:
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": bot_msg})
    
    # 添加当前用户消息
    messages.append({"role": "user", "content": message})
    
    # 获取选中的MCP服务器ID
    mcp_server_ids = [mcp_servers[server]["server_id"] for server in selected_servers]
    
    # 获取模型ID
    model_id = model_id_map[model_name]
    
    # 构建额外参数
    extra_params = {
        "only_n_most_recent_images": n_recent_images,
        "budget_tokens": budget_tokens,
        "enable_thinking": enable_thinking
    }
    
    # 请求聊天
    response, msg_extras = request_chat(
        user_id, messages, model_id, mcp_server_ids, 
        stream=enable_stream, max_tokens=max_tokens,
        temperature=temperature, extra_params=extra_params
    )
    
    full_response = ""
    thinking_content = ""
    tool_use_content = []
    
    # 处理流式响应
    if enable_stream and isinstance(response, requests.Response):
        for content in process_stream_response(response):
            full_response += content
            
            # 处理thinking内容
            thk_regex = r"<thinking>(.*?)</thinking>"
            thk_m = re.search(thk_regex, full_response, re.DOTALL)
            if thk_m:
                thinking_content = thk_m.group(1)
                full_response = re.sub(thk_regex, "", full_response, flags=re.DOTALL)
            
            # 处理tool_use内容
            tooluse_regex = r"<tool_use>(.*?)</tool_use>"
            tool_m = re.search(tooluse_regex, full_response, re.DOTALL)
            if tool_m:
                tool_msg = tool_m.group(1)
                full_response = re.sub(tooluse_regex, "", full_response)
                tool_use_content.append(tool_msg)
            
            # 更新UI
            yield full_response, thinking_content, json.dumps(tool_use_content, ensure_ascii=False, indent=2)
    else:
        # 处理非流式响应
        full_response = response if not isinstance(response, requests.Response) else "Error in response"
        
        # 处理thinking内容
        thk_regex = r"<thinking>(.*?)</thinking>"
        thk_m = re.search(thk_regex, full_response, re.DOTALL)
        if thk_m:
            thinking_content = thk_m.group(1)
            full_response = re.sub(thk_regex, "", full_response, flags=re.DOTALL)
        
        # 处理tool_use内容
        if msg_extras.get('tool_use'):
            tool_use_content.append(json.dumps(msg_extras.get('tool_use')))
        
        yield full_response, thinking_content, json.dumps(tool_use_content, ensure_ascii=False, indent=2)

def refresh_mcp_servers(user_id):
    """刷新MCP服务器列表"""
    mcp_servers = {}
    for server in request_list_mcp_servers(user_id):
        mcp_servers[server['server_name']] = {
            "server_id": server['server_id'],
            "server_desc": server.get('server_desc', server['server_name'])
        }
    return mcp_servers, list(mcp_servers.keys())

def refresh_models(user_id):
    """刷新模型列表"""
    model_names = []
    model_id_map = {}
    models = request_list_models(user_id)
    logging.info(f"Retrieved models for refresh: {models}")
    
    # 确保models是列表类型
    if not isinstance(models, list):
        logging.warning(f"Models is not a list: {type(models)}")
        models = []
    
    for model in models:
        if isinstance(model, dict) and 'model_name' in model and 'model_id' in model:
            model_names.append(model['model_name'])
            model_id_map[model['model_name']] = model['model_id']
    
    # 如果没有获取到模型，使用默认模型
    if not model_names:
        logging.warning("No models retrieved, using fallback models")
        # 添加一些默认模型作为备用
        fallback_models = [
            {"model_id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "model_name": "Claude 3.5 Sonnet v2"},
            {"model_id": "us.amazon.nova-pro-v1:0", "model_name": "Amazon Nova Pro v1"}
        ]
        for model in fallback_models:
            model_names.append(model['model_name'])
            model_id_map[model['model_name']] = model['model_id']
    
    return model_names, model_id_map

def add_mcp_server_ui(user_id, server_name, server_id, server_cmd, server_args, server_env, server_config_json):
    """添加MCP服务器UI处理"""
    status, msg = add_new_mcp_server(
        user_id, server_name, server_id, server_cmd, 
        server_args, server_env, server_config_json
    )
    
    if status:
        # 刷新服务器列表
        mcp_servers, server_names = refresh_mcp_servers(user_id)
        return gr.update(value=""), gr.update(value=""), gr.update(value=""), gr.update(value=""), gr.update(value=""), gr.update(value=""), f"✅ {msg}", mcp_servers, server_names
    else:
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), f"❌ {msg}", gr.update(), gr.update()

def clear_conversation():
    """清空对话历史"""
    return [], "", "", ""

def generate_random_user_id():
    """生成随机用户ID"""
    return str(uuid.uuid4())[:8]

def save_user_id(user_id):
    """保存用户ID到cookie"""
    return user_id

# Email account management UI functions
def add_email_account_ui(username, password, imap_server, imap_port, use_ssl, current_accounts):
    """UI function for adding an email account"""
    try:
        logging.info(f"Adding email account: {username}")
        # Validate email address
        try:
            validate_email(username, check_deliverability=False)
        except EmailNotValidError:
            logging.error(f"Invalid email address: {username}")
            return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), f"❌ Invalid email address", current_accounts
        
        # Add account
        status, message = add_email_account(
            username, password, imap_server, imap_port, use_ssl
        )
        
        if status:
            # Refresh account list
            accounts_data = load_email_accounts()
            account_names = [account["username"] for account in accounts_data["accounts"]]
            current_account = accounts_data["current_account"]
            logging.info(f"Account added successfully: {username}")
            
            # Clear the form
            return (
                gr.update(value=""), 
                gr.update(value=""), 
                gr.update(value=""), 
                gr.update(value=993),
                gr.update(value=True),
                gr.update(value=current_account, choices=account_names), 
                f"✅ {message}", 
                account_names
            )
        else:
            logging.warning(f"Failed to add account: {message}")
            return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), f"❌ {message}", current_accounts
    except Exception as e:
        logging.exception(f"Error in add_email_account_ui: {str(e)}")
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), f"❌ Error: {str(e)}", current_accounts

def delete_email_account_ui(username, current_accounts):
    """UI function for deleting an email account"""
    try:
        logging.info(f"Deleting email account: {username}")
        status, message = delete_email_account(username)
        
        if status:
            # Refresh account list
            accounts_data = load_email_accounts()
            account_names = [account["username"] for account in accounts_data["accounts"]]
            current_account = accounts_data["current_account"]
            logging.info(f"Account deleted successfully: {username}")
            
            return gr.update(value=current_account, choices=account_names), f"✅ {message}", account_names
        else:
            logging.warning(f"Failed to delete account: {message}")
            return gr.update(), f"❌ {message}", current_accounts
    except Exception as e:
        logging.exception(f"Error in delete_email_account_ui: {str(e)}")
        return gr.update(), f"❌ Error: {str(e)}", current_accounts

def set_current_account_ui(username):
    """UI function for setting the current account"""
    try:
        logging.info(f"Setting current account to: {username}")
        status, message = set_current_account(username)
        if status:
            logging.info(f"Current account set successfully: {username}")
            return f"✅ {message}"
        else:
            logging.warning(f"Failed to set current account: {message}")
            return f"❌ {message}"
    except Exception as e:
        logging.exception(f"Error in set_current_account_ui: {str(e)}")
        return f"❌ Error: {str(e)}"

def fetch_emails_ui(account_list):
    """UI function for fetching emails from the current account"""
    try:
        logging.info("Fetching emails from current account")
        current_account = get_current_account()
        if not current_account:
            logging.warning("No account selected")
            return None, None, None, "No account selected", [], []
        
        logging.info(f"Current account: {current_account['username']}")
        emails, message = fetch_emails(current_account)
        
        if not emails:
            logging.warning(f"No emails found or error occurred: {message}")
            return None, None, None, message, [], []
        
        # Format emails for UI display
        email_display_list = [f"[{email['date']}] {email['subject']} (From: {email['sender']})" for email in emails]
        logging.info(f"Successfully fetched {len(emails)} emails")
        
        return current_account["username"], None, None, f"✅ {message}", email_display_list, emails
    except Exception as e:
        logging.exception("Exception in fetch_emails_ui")
        return None, None, None, f"❌ Error: {str(e)}", []

def load_email_content(emails, selected_index):
    """Load the content of a selected email"""
    if not emails or selected_index < 0 or selected_index >= len(emails):
        return "", "", "", False
    
    selected_email = emails[selected_index]
    logging.info(f"Loading email content: {selected_email['subject']}")
    return (
        selected_email["subject"],
        selected_email["sender"],
        selected_email["body"],
        True  # Enable the AI response button
    )

async def generate_ai_response(subject, sender, body, model_name, model_id_map):
    """Generate an AI response for an email"""
    try:
        logging.info(f"Generating AI response for email: {subject}")
        client = CompatibleChatClientStream()
        
        model_id = model_id_map[model_name]
        logging.info(f"Using model: {model_name} ({model_id})")
        
        system_prompt = """You are an advanced email customer service expert for LSCS, specializing in processing product inquiries and generating price quotes. Your primary functions include:

1. Extracting product codes and quantities from customer emails
2. Responding professionally to customer inquiries about product availability and pricing

Respond to customers in a helpful, professional manner while ensuring all pricing information is accurate and clearly presented."""
        
        message = f"Subject: {subject}\nFrom: {sender}\n\n{body}\n\nPlease generate a professional response to this email."
        
        response_text = ""
        
        messages = [{"role": "user", "content": message}]
        system = [{"text": system_prompt}]
        
        logging.info("Starting AI response generation")
        # Generate response using process_query_stream
        async for event in client.process_query_stream(
            model_id=model_id,
            max_tokens=2048,
            temperature=0.7,
            messages=messages,
            system=system
        ):
            if event["type"] == "block_delta" and "text" in event["data"]["delta"]:
                response_text += event["data"]["delta"]["text"]
        
        logging.info(f"AI response generation complete ({len(response_text)} chars)")
        return response_text
    except Exception as e:
        logging.exception(f"Error generating AI response: {str(e)}")
        return f"Error generating response: {str(e)}"

def create_ui():
    """Create Gradio UI"""
    with gr.Blocks(title="💬 Customer Support Agent", css="""
        .container { max-width: 1200px; margin: auto; }
        .sidebar { min-width: 300px; }
        .chat-container { flex-grow: 1; }
        .tool-output { margin-top: 10px; }
        .email-display { margin-top: 15px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
        .email-header { font-weight: bold; margin-bottom: 10px; }
        .email-response { margin-top: 15px; padding: 10px; background-color: #f8f9fa; border-radius: 5px; }
    """) as demo:
        # 初始化用户ID
        user_id = gr.State(value=str(uuid.uuid4())[:8])
        
        # 初始化模型和服务器列表
        mcp_servers = gr.State({})
        model_id_map = gr.State({})
        
        # 初始化邮箱和邮件列表
        email_accounts = gr.State([])
        email_list = gr.State([])
        
        gr.Markdown("# 💬 Email Customer Service Agent")
        
        with gr.Row():
            # 左侧面板 - 邮箱管理和邮件显示
            with gr.Column(scale=3):
                # 邮箱账户管理部分
                with gr.Group():
                    gr.Markdown("## Email Account Management")
                    
                    # 添加邮箱表单
                    with gr.Row():
                        email_username = gr.Textbox(label="Email", placeholder="example@gmail.com")
                        email_password = gr.Textbox(label="Password", placeholder="your-app-password", type="password")
                    
                    with gr.Row():
                        imap_server = gr.Textbox(label="IMAP Server", placeholder="imap.gmail.com", value="imap.gmail.com")
                        imap_port = gr.Number(label="IMAP Port", value=993, precision=0)
                    
                    with gr.Row():
                        use_ssl = gr.Checkbox(label="Use SSL", value=True)
                    
                    with gr.Row():
                        add_account_btn = gr.Button("Add Account", variant="primary")
                        delete_account_btn = gr.Button("Delete Account", variant="stop")
                    
                    account_status = gr.Textbox(label="Status", interactive=False)
                
                # 邮箱切换
                with gr.Group():
                    with gr.Row():
                        account_dropdown = gr.Dropdown(label="Email Accounts", choices=[], interactive=True)
                        set_current_btn = gr.Button("Set Current", variant="secondary")
                    
                    account_change_status = gr.Textbox(label="Status", interactive=False)
                
                # 邮件接收部分
                with gr.Group():
                    with gr.Row():
                        fetch_emails_btn = gr.Button("Fetch Emails", variant="primary")
                        refresh_btn = gr.Button("🔄", scale=1)
                    
                    fetch_status = gr.Textbox(label="Status", interactive=False)
                    
                    email_select = gr.Radio(label="Received Emails", choices=[], interactive=True)
                
                # 邮件显示和AI回复部分
                with gr.Group():
                    gr.Markdown("## Email Content")
                    
                    email_subject = gr.Textbox(label="Subject", interactive=False)
                    email_sender = gr.Textbox(label="From", interactive=False)
                    email_body = gr.Textbox(label="Body", lines=10, interactive=False)
                    
                    ai_response_btn = gr.Button("Generate AI Response", variant="primary", interactive=False)
                    
                    ai_response = gr.Textbox(label="AI Response", lines=10, interactive=False)
            
            # 右侧面板 - 原有的MCP服务器管理
            with gr.Column(scale=1, elem_classes="sidebar"):
                with gr.Group():
                    with gr.Row():
                        user_id_input = gr.Textbox(label="User ID", value=lambda: user_id.value)
                        refresh_id_btn = gr.Button("🔄", scale=1)
                
                model_dropdown = gr.Dropdown(label="模型", interactive=True)
                
                max_tokens = gr.Slider(
                    minimum=1, maximum=64000, value=8000, step=1000,
                    label="最大输出token"
                )
                
                budget_tokens = gr.Slider(
                    minimum=1024, maximum=128000, value=8192, step=1024,
                    label="最大思考token"
                )
                
                temperature = gr.Slider(
                    minimum=0.0, maximum=1.0, value=0.6, step=0.1,
                    label="Temperature"
                )
                
                n_recent_images = gr.Slider(
                    minimum=0, maximum=10, value=1, step=1,
                    label="最近图片数量"
                )
                
                system_prompt = gr.Textbox(
                    label="System Prompt",
                    value="""You are an advanced email customer service expert for LSCS, specializing in processing product inquiries and generating price quotes. Your primary functions include:

1. Extracting product codes and quantities from customer emails
2. Responding professionally to customer inquiries about product availability and pricing

Respond to customers in a helpful, professional manner while ensuring all pricing information is accurate and clearly presented.""",
                    lines=3
                )
                
                with gr.Row():
                    enable_thinking = gr.Checkbox(label="启用思考", value=False)
                    enable_stream = gr.Checkbox(label="启用流式输出", value=True)
                
                with gr.Accordion("MCP 服务器", open=True):
                    server_checkboxes = gr.CheckboxGroup(label="选择服务器")
                    
                    with gr.Accordion("添加新服务器", open=False):
                        with gr.Group():
                            new_server_name = gr.Textbox(label="服务器名称", placeholder="Name description of server")
                            new_server_id = gr.Textbox(label="服务器ID", placeholder="server id")
                            new_server_cmd = gr.Dropdown(label="运行命令", choices=mcp_command_list)
                            new_server_args = gr.Textbox(label="运行参数", placeholder="mcp-server-git --repository path/to/git/repo")
                            new_server_env = gr.Textbox(label="环境变量", placeholder="需要提供一个有效的JSON字典")
                            new_server_config = gr.Textbox(label="JSON配置", placeholder="需要提供一个有效的JSON字典", lines=5)
                            add_server_status = gr.Textbox(label="状态", interactive=False)
                            add_server_btn = gr.Button("添加服务器")
        
        # 页面加载时初始化数据
        def init_data(request: gr.Request):
            current_user_id = get_user_id(request)
            mcp_servers_data, server_names = refresh_mcp_servers(current_user_id)
            model_names, model_id_map_data = refresh_models(current_user_id)
            
            # 加载已有的邮箱账户
            accounts_data = load_email_accounts()
            account_names = [account["username"] for account in accounts_data["accounts"]]
            current_account = accounts_data["current_account"]
            
            return (
                current_user_id,
                mcp_servers_data,
                model_id_map_data,
                gr.update(choices=model_names, value=model_names[0] if model_names else None),
                gr.update(choices=server_names),
                gr.update(choices=account_names, value=current_account),
                account_names
            )
        
        demo.load(
            init_data,
            inputs=[],
            outputs=[user_id, mcp_servers, model_id_map, model_dropdown, server_checkboxes, account_dropdown, email_accounts]
        )
        
        # 邮箱账户管理事件
        add_account_btn.click(
            add_email_account_ui,
            inputs=[email_username, email_password, imap_server, imap_port, use_ssl, email_accounts],
            outputs=[email_username, email_password, imap_server, imap_port, use_ssl, account_dropdown, account_status, email_accounts]
        )
        
        delete_account_btn.click(
            delete_email_account_ui,
            inputs=[account_dropdown, email_accounts],
            outputs=[account_dropdown, account_status, email_accounts]
        )
        
        set_current_btn.click(
            set_current_account_ui,
            inputs=[account_dropdown],
            outputs=[account_change_status]
        )
        
        # 邮件获取事件
        fetch_emails_btn.click(
            fetch_emails_ui,
            inputs=[email_accounts],
            outputs=[email_username, email_subject, email_body, fetch_status, email_select, email_list]
        )
        
        refresh_btn.click(
            fetch_emails_ui,
            inputs=[email_accounts],
            outputs=[email_username, email_subject, email_body, fetch_status, email_select, email_list]
        )
        
        # 选择邮件事件
        email_select.change(
            load_email_content,
            inputs=[email_list, email_select],
            outputs=[email_subject, email_sender, email_body, ai_response_btn]
        )
        
        # AI生成回复事件
        ai_response_btn.click(
            lambda subject, sender, body, model, model_id_map: asyncio.run(generate_ai_response(subject, sender, body, model, model_id_map)),
            inputs=[email_subject, email_sender, email_body, model_dropdown, model_id_map],
            outputs=[ai_response]
        )
        
        # 刷新用户ID
        refresh_id_btn.click(
            generate_random_user_id,
            outputs=[user_id_input]
        )
        
        # 保存用户ID
        user_id_input.change(
            save_user_id,
            inputs=[user_id_input],
            outputs=[user_id]
        )
        
        # 添加MCP服务器
        add_server_btn.click(
            add_mcp_server_ui,
            inputs=[
                user_id, new_server_name, new_server_id, new_server_cmd,
                new_server_args, new_server_env, new_server_config
            ],
            outputs=[
                new_server_name, new_server_id, new_server_cmd,
                new_server_args, new_server_env, new_server_config,
                add_server_status, mcp_servers, server_checkboxes
            ]
        )
        
    return demo

if __name__ == "__main__":
    port = int(os.environ.get("CHATBOT_SERVICE_PORT", 8502))
    demo = create_ui()
    demo.queue()
    demo.launch(server_name="0.0.0.0", server_port=port, share=False)
