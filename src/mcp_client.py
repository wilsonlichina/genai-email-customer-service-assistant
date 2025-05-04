"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""
"""
MCP Client maintains Multi-MCP-Servers
"""
import os
import logging
import asyncio
from typing import Optional, Dict
from contextlib import AsyncExitStack
from pydantic import ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client, get_default_environment
from mcp.types import Resource, Tool, TextContent, ImageContent, EmbeddedResource,CallToolResult,NotificationParams
from mcp.shared.exceptions import McpError
from dotenv import load_dotenv
from mcp.client.sse import sse_client

load_dotenv()  # load environment variables from .env

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
)
logger = logging.getLogger(__name__)
delimiter = "___"
tool_name_mapping = {}
tool_name_mapping_r = {}
class MCPClient:
    """Manage MCP sessions.

    Support features:
    - MCP multi-server
    - get tool config from server
    - call tool and get result from server
    """

    def __init__(self, name, access_key_id='', secret_access_key='', region='us-east-1'):
        self.env = {
            'AWS_ACCESS_KEY_ID': access_key_id or os.environ.get('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': secret_access_key or os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'AWS_REGION': region or os.environ.get('AWS_REGION'),
        }
        self.name = name
        # self.sessions: Dict[str, Optional[ClientSession]] = {}
        self.session = None
        self.exit_stack = AsyncExitStack()

    @staticmethod
    def normalize_tool_name(tool_name):
        normalized = tool_name.replace('-', '_').replace('/', '_').replace(':', '_')
        logger.info(f"Normalized tool name: {tool_name} -> {normalized}")
        return normalized
    
    @staticmethod
    def get_tool_name4llm(server_id, tool_name, norm=True, ns_delimiter=delimiter):
        """Convert MCP server tool name to llm tool call"""
        global tool_name_mapping, tool_name_mapping_r
        # prepend server prefix namespace to support multi-mcp-server
        tool_key = server_id + ns_delimiter + tool_name
        tool_name4llm = tool_key if not norm else MCPClient.normalize_tool_name(tool_key)
        tool_name_mapping[tool_key] = tool_name4llm
        tool_name_mapping_r[tool_name4llm] = tool_key
        logger.info(f"Mapped MCP tool to LLM tool: {tool_key} -> {tool_name4llm}")
        return tool_name4llm
    
    @staticmethod
    def get_tool_name4mcp(tool_name4llm, ns_delimiter=delimiter):
        """Convert llm tool call name to MCP server original name"""
        global tool_name_mapping_r
        server_id, tool_name = "", ""
        tool_name4mcp = tool_name_mapping_r.get(tool_name4llm, "")
        if len(tool_name4mcp.split(ns_delimiter)) == 2:
            server_id, tool_name = tool_name4mcp.split(ns_delimiter)
            logger.info(f"Converted LLM tool to MCP tool: {tool_name4llm} -> server: {server_id}, tool: {tool_name}")
        else:
            logger.warning(f"Could not parse tool name: {tool_name4llm}, mapping: {tool_name4mcp}")
        return server_id, tool_name

    async def disconnect_to_server(self):
        logger.info(f"Disconnecting to server [{self.name}]")
        await self.cleanup()

    async def handle_resource_change(params: NotificationParams):
        logger.info(f"Resource change type: {params['changeType']}")
        logger.info(f"Affected URIs: {params['resourceURIs']}")
    
    
    async def connect_to_server(self, server_script_path: str = "", server_script_args: list = [], 
            server_script_envs: Dict = {}, command: str = "", server_url: str = ""):
        """Connect to an MCP server"""
        # if not ((command and server_script_args) or server_script_path):
        #     raise ValueError("Run server via script or command.")
        logger.info(f"Connecting to server [{self.name}]")
        if  server_script_path:
            # run via script
            is_python = server_script_path.endswith('.py')
            is_js = server_script_path.endswith('.js')
            is_uvx = server_script_path.startswith('uvx:')
            is_np = server_script_path.startswith('npx:')
            is_docker = server_script_path.startswith('docker:')
            is_uv = server_script_path.startswith('uv:')

            if not (is_python or is_js or is_uv or is_np or is_docker or is_uvx):
                logger.error(f"Server script must be a .py or .js file or package: {server_script_path}")
                raise ValueError("Server script must be a .py or .js file or package")
            if is_uv or is_np or is_uvx:
                server_script_path = server_script_path[server_script_path.index(':')+1:]

            server_script_args = [server_script_path] + server_script_args
    
            if is_python:
                command = "python"
            elif is_uv:
                command = "uv"
            elif is_uvx:
                command = "uvx"
            elif is_np:
                command = "npx"
                server_script_args = ["-y"] + server_script_args
            elif is_js:
                command = "node"
            elif is_docker:
                command = "docker"
            
            logger.info(f"Using command: {command} with args: {server_script_args}")

        env = get_default_environment()
        if self.env['AWS_ACCESS_KEY_ID'] and self.env['AWS_ACCESS_KEY_ID']:
            env['AWS_ACCESS_KEY_ID'] =  self.env['AWS_ACCESS_KEY_ID']
            env['AWS_SECRET_ACCESS_KEY'] = self.env['AWS_SECRET_ACCESS_KEY']
            env['AWS_REGION'] = self.env['AWS_REGION']
            logger.info(f"Using AWS credentials for region: {self.env['AWS_REGION']}")
        env.update(server_script_envs)
        try: 
            if server_url:
                logger.info(f"Connecting to server URL: {server_url}")
                transport = sse_client(server_url)
            else:
                logger.info(f"Starting server process: {command} {' '.join(server_script_args)}")
                transport = stdio_client(StdioServerParameters(
                    command=command, args=server_script_args, env=env
                ))
        except Exception as e:
            logger.error(f"Failed to create transport: {e}")
            raise ValueError(f"Invalid server script or command. {e}")
        logger.info(f"Adding server {command} {server_script_args}")
        try:
            _stdio, _write = await self.exit_stack.enter_async_context(transport)
            self.session = await self.exit_stack.enter_async_context(ClientSession(_stdio, _write))
            await self.session.initialize()
            logger.info(f"{self.name} session initialized successfully")
        except Exception as e:
            logger.error(f"{self.name} session initialization failed: {e}")
            raise ValueError(f"Invalid server script or command. {e}")   
        await self.list_mcp_server()
        
    async def list_mcp_server(self):
        try:
            resource = await self.session.list_resources()
            logger.info(f"Server [{self.name}] resources: {resource}")
        except McpError as e:
            logger.info(f"Server [{self.name}] list_resources error: {str(e)}")
        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        tool_names = [tool.name for tool in tools]
        logger.info(f"Connected to server [{self.name}] with tools: {tool_names}")
        
        
    async def get_tool_config(self, model_provider='bedrock', server_id : str = ''):
        """Get llm's tool usage config via MCP server"""
        # list tools via mcp server
        logger.info(f"Getting tool config for server [{self.name}] with ID [{server_id}]")
        try:
            response = await self.session.list_tools()
            if not response:
                logger.error('list_tools returns empty')
                raise ValueError('list_tools returns empty')
        except Exception as e:
            logger.error(f'Failed to list tools: {e}')
            return None

        # for bedrock tool config
        tool_config = {"tools": []}
        for tool in response.tools:
            tool_name_for_llm = MCPClient.get_tool_name4llm(server_id, tool.name, norm=True)
            logger.info(f"Mapping tool: {tool.name} -> {tool_name_for_llm}")
            tool_config["tools"].append({
                "toolSpec":{
                    "name": tool_name_for_llm,
                    "description": tool.description, 
                    "inputSchema": {"json": tool.inputSchema}
                }
            })

        logger.info(f"Generated tool config with {len(tool_config['tools'])} tools")
        return tool_config

    async def call_tool(self, tool_name, tool_args):
        """Call tool via MCP server"""
        logger.info(f"Calling tool [{tool_name}] with args: {tool_args}")
        try:
            result = await self.session.call_tool(tool_name, tool_args)
            logger.info(f"Tool [{tool_name}] call successful")
            return result
        except ValidationError as e:
            # Extract the actual tool result from the validation error
            raw_data = e.errors() if hasattr(e, 'errors') else None
            logger.info(f"Validation error in tool call, raw_data: {raw_data}")
            if raw_data and len(raw_data) > 0:
                tool_result = raw_data[0]['input']
                logger.info(f"Extracted tool result from validation error")
                return CallToolResult.model_validate(tool_result)
            # Re-raise the exception if the result cannot be extracted
            logger.error(f"Failed to extract tool result from validation error: {e}")
            raise

    async def cleanup(self):
        """Clean up resources"""
        logger.info(f"Cleaning up resources for server [{self.name}]")
        try:
            await self.exit_stack.aclose()
            logger.info(f"Successfully closed exit stack for [{self.name}]")
        except RuntimeError as e:
            # Handle the case where exit_stack is being closed in a different task
            if "Attempted to exit cancel scope in a different task" in str(e):
                # Create a new exit stack for future use
                self.exit_stack = AsyncExitStack()
                logger.warning(f"Handled cross-task exit_stack closure for [{self.name}]")
            else:
                # Re-raise if it's a different error
                logger.error(f"Error during cleanup for [{self.name}]: {e}")
                raise
