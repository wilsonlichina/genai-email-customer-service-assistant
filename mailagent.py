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
from io import BytesIO
import copy
from dotenv import load_dotenv
load_dotenv()  # load env vars from .env
API_KEY = os.environ.get("API_KEY")

logging.basicConfig(level=logging.INFO)
mcp_base_url = os.environ.get('MCP_BASE_URL')
mcp_command_list = ["uvx", "npx", "node", "python", "docker", "uv"]
COOKIE_NAME = "mcp_chat_user_id"

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

def create_ui():
    """创建Gradio UI"""
    with gr.Blocks(title="💬 Customer Support Agent", css="""
        .container { max-width: 1200px; margin: auto; }
        .sidebar { min-width: 300px; }
        .chat-container { flex-grow: 1; }
        .tool-output { margin-top: 10px; }
    """) as demo:
        # 初始化用户ID
        user_id = gr.State(value=str(uuid.uuid4())[:8])
        
        # 初始化模型和服务器列表
        mcp_servers = gr.State({})
        model_id_map = gr.State({})
        
        gr.Markdown("# 💬 Customer Support Agent")
        
        with gr.Row():
            with gr.Column(scale=3, elem_classes="chat-container"):
                chatbot = gr.Chatbot(height=600)
                
                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="输入您的消息...",
                        show_label=False,
                        container=False,
                        scale=9
                    )
                    submit_btn = gr.Button("发送", scale=1)
                
                with gr.Accordion("思考过程", open=False):
                    thinking_output = gr.Textbox(label="Thinking", lines=10, interactive=False)
                
                with gr.Accordion("工具使用", open=False):
                    tool_output = gr.Code(language="json", label="Tool Use", interactive=False)
                
                clear_btn = gr.Button("🗑️ 清空对话")
            
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
            logging.info(f"Initializing data for user: {current_user_id}")
            mcp_servers_data, server_names = refresh_mcp_servers(current_user_id)
            model_names, model_id_map_data = refresh_models(current_user_id)
            logging.info(f"Initialized with models: {model_names}")
            logging.info(f"Initialized with servers: {server_names}")
            
            return (
                current_user_id,
                mcp_servers_data,
                model_id_map_data,
                gr.update(choices=model_names, value=model_names[0] if model_names else None),
                gr.update(choices=server_names)
            )
        
        demo.load(
            init_data,
            inputs=[],
            outputs=[user_id, mcp_servers, model_id_map, model_dropdown, server_checkboxes]
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
        
        # 清空对话
        clear_btn.click(
            clear_conversation,
            outputs=[chatbot, msg, thinking_output, tool_output]
        )
        
        # 处理聊天
        chat_event = msg.submit(
            chat_function,
            inputs=[
                user_id, msg, chatbot, model_dropdown, model_id_map, 
                mcp_servers, server_checkboxes, system_prompt, max_tokens,
                budget_tokens, temperature, n_recent_images, 
                enable_thinking, enable_stream
            ],
            outputs=[thinking_output, tool_output],
            queue=True
        ).then(
            lambda x, y, z: ((y, x), ""),
            inputs=[msg, chatbot, thinking_output],
            outputs=[chatbot, msg]
        )
        
        submit_btn.click(
            chat_function,
            inputs=[
                user_id, msg, chatbot, model_dropdown, model_id_map, 
                mcp_servers, server_checkboxes, system_prompt, max_tokens,
                budget_tokens, temperature, n_recent_images, 
                enable_thinking, enable_stream
            ],
            outputs=[thinking_output, tool_output],
            queue=True
        ).then(
            lambda x, y, z: ((y, x), ""),
            inputs=[msg, chatbot, thinking_output],
            outputs=[chatbot, msg]
        )
        
    return demo

if __name__ == "__main__":
    port = int(os.environ.get("CHATBOT_SERVICE_PORT", 8502))
    demo = create_ui()
    demo.queue()
    demo.launch(server_name="0.0.0.0", server_port=port, share=False)
