#!/bin/bash
export $(grep -v '^#' .env | xargs)
export PYTHONPATH=./src:$PYTHONPATH
source .venv/bin/activate

# Create necessary directories
mkdir -p ./tmp 
mkdir -p ${LOG_DIR}

LOG_FILE1="${LOG_DIR}/start_mcp_$(date +%Y%m%d_%H%M%S).log"
LOG_FILE2="${LOG_DIR}/start_chatbot_$(date +%Y%m%d_%H%M%S).log"
MAX_LOG_SIZE=10M  # 设置日志文件大小上限为10MB
# Set environment variables
export MCP_BASE_URL=http://${MCP_SERVICE_HOST}:${MCP_SERVICE_PORT}
echo "MCP_BASE_URL: ${MCP_BASE_URL}"
# Start MCP service
echo "Starting MCP service..."
nohup python src/main.py --mcp-conf conf/config.json --user-conf conf/user_mcp_config.json \
    --host ${MCP_SERVICE_HOST} --port ${MCP_SERVICE_PORT} > ${LOG_FILE1} 2>&1 &

# Choose which UI to start
if [ "$1" == "gradio" ]; then
    echo "Starting Gradio Chatbot UI..."
    ./start_chatbotui.sh
elif [ "$1" == "streamlit" ]; then
    echo "Starting Streamlit mailagent UI..."
    nohup streamlit run mailagent.py \
        --server.port ${CHATBOT_SERVICE_PORT} > ${LOG_FILE2} 2>&1 &
fi

echo "Services started. Check logs in ${LOG_DIR}"
