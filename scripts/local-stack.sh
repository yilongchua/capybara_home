#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPYBARA_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DESKTOP_ROOT="${DESKTOP_ROOT:-$HOME/Desktop}"

MARINETIME_MCP_DIR="${MARINETIME_MCP_DIR:-$DESKTOP_ROOT/marinetime_mcp}"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$DESKTOP_ROOT/llama.cpp}"
COMFYUI_DIR="${COMFYUI_DIR:-$DESKTOP_ROOT/comfyUI}"
LIGHTRAG_DIR="${LIGHTRAG_DIR:-$DESKTOP_ROOT/LightRAG}"
WEBSEARCH_DIR="${WEBSEARCH_DIR:-$DESKTOP_ROOT/websearch}"
LOCAL_STACK_STATE_DIR="${LOCAL_STACK_STATE_DIR:-$CAPYBARA_ROOT/.local-stack}"

MARINETIME_MCP_PORT="${LOCAL_PORT_MARINETIME_MCP:-8091}"
LLAMA_CPP_PORT="${LOCAL_PORT_LLAMA_CPP:-1234}"
LLAMA_CPP_BASE_URL="${LLAMA_CPP_BASE_URL:-http://localhost:${LLAMA_CPP_PORT}/v1}"
COMFYUI_PORT="${LOCAL_PORT_COMFYUI:-8188}"
COMFYUI_BASE_URL="${COMFYUI_BASE_URL:-http://localhost:${COMFYUI_PORT}}"
BROWSER_AUTOMATION_PORT="${LOCAL_PORT_BROWSER_AUTOMATION:-9333}"
BROWSER_AUTOMATION_BASE_URL="${BROWSER_AUTOMATION_BASE_URL:-http://localhost:${BROWSER_AUTOMATION_PORT}}"
CAPYBARA_UI_PORT="${LOCAL_PORT_CAPYBARA_UI:-2026}"
LIGHTRAG_PORT="${LOCAL_PORT_LIGHTRAG:-9621}"
WEBSEARCH_PORT="${LOCAL_PORT_WEBSEARCH:-9000}"
INFINITY_RERANK_PORT="${LOCAL_PORT_INFINITY_RERANK:-7997}"
LIGHTRAG_BASE_URL="${LIGHTRAG_BASE_URL:-http://localhost:${LIGHTRAG_PORT}}"
WEBSEARCH_BASE_URL="${WEBSEARCH_BASE_URL:-http://localhost:${WEBSEARCH_PORT}}"
INFINITY_RERANK_BASE_URL="${INFINITY_RERANK_BASE_URL:-http://localhost:${INFINITY_RERANK_PORT}}"
LIGHTRAG_COMPOSE_PROJECT="${LIGHTRAG_COMPOSE_PROJECT:-lightrag}"
WEBSEARCH_COMPOSE_PROJECT="${WEBSEARCH_COMPOSE_PROJECT:-websearch}"
LIGHTRAG_COMPOSE_FILE="${LIGHTRAG_COMPOSE_FILE:-$LIGHTRAG_DIR/docker-compose.yml}"
LIGHTRAG_INFINITY_COMPOSE_FILE="${LIGHTRAG_INFINITY_COMPOSE_FILE:-$LIGHTRAG_DIR/docker-compose.infinity-standalone.yaml}"
WEBSEARCH_COMPOSE_FILE="${WEBSEARCH_COMPOSE_FILE:-$WEBSEARCH_DIR/docker-compose.yml}"
LLAMA_CPP_WORKDIR="${LLAMA_CPP_WORKDIR:-$LLAMA_CPP_DIR}"
COMFYUI_WORKDIR="${COMFYUI_WORKDIR:-$COMFYUI_DIR}"
BROWSER_AUTOMATION_WORKDIR="${BROWSER_AUTOMATION_WORKDIR:-$CAPYBARA_ROOT/backend}"
LLAMA_CPP_START_CMD="${LLAMA_CPP_START_CMD:-}"
LLAMA_CPP_START_SCRIPT="${LLAMA_CPP_START_SCRIPT:-$DESKTOP_ROOT/thesystem/start_llama_server.sh}"
LLAMA_CPP_USE_DOCKER="${LLAMA_CPP_USE_DOCKER:-1}"
LLAMA_CPP_DOCKER_IMAGE="${LLAMA_CPP_DOCKER_IMAGE:-ghcr.io/ggml-org/llama.cpp:server}"
LLAMA_CPP_CONTAINER_NAME="${LLAMA_CPP_CONTAINER_NAME:-llama-cpp-server}"
LLAMA_CPP_CTX_SIZE="${LLAMA_CPP_CTX_SIZE:-32000}"
LLAMA_CPP_MODEL_PATH="${LLAMA_CPP_MODEL_PATH:-$HOME/.lmstudio/models/lmstudio-community/gpt-oss-120b-GGUF/gpt-oss-120b-MXFP4-00001-of-00002.gguf}"
LLAMA_CPP_DOCKER_MODEL_PATH="${LLAMA_CPP_DOCKER_MODEL_PATH:-$HOME/.lmstudio/models/lmstudio-community/starcoder2-15b-instruct-v0.1-GGUF/starcoder2-15b-instruct-v0.1-Q4_K_M.gguf}"
COMFYUI_START_CMD="${COMFYUI_START_CMD:-}"
BROWSER_AUTOMATION_START_CMD="${BROWSER_AUTOMATION_START_CMD:-}"
BROWSER_AUTOMATION_ENABLE="${BROWSER_AUTOMATION_ENABLE:-1}"
LLAMA_CPP_PID_FILE="$LOCAL_STACK_STATE_DIR/llama-cpp.pid"
LLAMA_CPP_LOG_FILE="$LOCAL_STACK_STATE_DIR/llama-cpp.log"
COMFYUI_PID_FILE="$LOCAL_STACK_STATE_DIR/comfyui.pid"
COMFYUI_LOG_FILE="$LOCAL_STACK_STATE_DIR/comfyui.log"
BROWSER_AUTOMATION_PID_FILE="$LOCAL_STACK_STATE_DIR/browser-automation.pid"
BROWSER_AUTOMATION_LOG_FILE="$LOCAL_STACK_STATE_DIR/browser-automation.log"

require_file() {
    local file="$1"
    local label="$2"
    if [ ! -f "$file" ]; then
        echo -e "${YELLOW}Missing ${label}: ${file}${NC}"
        return 1
    fi
    return 0
}

lightrag_compose() {
    require_file "$LIGHTRAG_COMPOSE_FILE" "LightRAG compose file" || return 1
    require_file "$LIGHTRAG_INFINITY_COMPOSE_FILE" "Infinity compose file" || return 1
    docker compose \
        --project-name "$LIGHTRAG_COMPOSE_PROJECT" \
        --project-directory "$LIGHTRAG_DIR" \
        -f "$LIGHTRAG_COMPOSE_FILE" \
        -f "$LIGHTRAG_INFINITY_COMPOSE_FILE" \
        "$@"
}

websearch_compose() {
    require_file "$WEBSEARCH_COMPOSE_FILE" "WebSearch compose file" || return 1
    docker compose \
        --project-name "$WEBSEARCH_COMPOSE_PROJECT" \
        --project-directory "$WEBSEARCH_DIR" \
        -f "$WEBSEARCH_COMPOSE_FILE" \
        "$@"
}

print_header() {
    echo "=========================================="
    echo "  Capybara Home Local Research Stack"
    echo "=========================================="
}

ensure_state_dir() {
    mkdir -p "$LOCAL_STACK_STATE_DIR"
}

is_pid_running() {
    local pid_file="$1"
    if [ ! -f "$pid_file" ]; then
        return 1
    fi
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -z "$pid" ]; then
        return 1
    fi
    kill -0 "$pid" >/dev/null 2>&1
}

start_marinetime_mcp() {
    echo -e "${BLUE}Starting Marinetime MCP on localhost:${MARINETIME_MCP_PORT}...${NC}"
    local marinetime_dir="${MARINETIME_MCP_DIR}"
    if [ ! -d "$marinetime_dir" ]; then
        echo -e "${YELLOW}Missing Marinetime MCP directory: ${marinetime_dir}${NC}"
        exit 1
    fi
    (
        cd "$marinetime_dir"
        docker build -t marinetime-mcp:local .
        docker rm -f marinetime-mcp >/dev/null 2>&1 || true
        docker run -d \
            --name marinetime-mcp \
            -e MCP_HOST=0.0.0.0 \
            -e MCP_PORT="${MARINETIME_MCP_PORT}" \
            -e MCP_TRANSPORT=streamable-http \
            -p "${MARINETIME_MCP_PORT}:${MARINETIME_MCP_PORT}" \
            marinetime-mcp:local >/dev/null
    )
}

start_optional_process() {
    local label="$1"
    local cmd="$2"
    local workdir="$3"
    local pid_file="$4"
    local log_file="$5"

    if [ -z "$cmd" ]; then
        echo -e "${YELLOW}Skipping ${label} (set ${label}_START_CMD or the matching env var to enable it).${NC}"
        return
    fi

    if [ ! -d "$workdir" ]; then
        echo -e "${YELLOW}Skipping ${label} (missing workdir: ${workdir}).${NC}"
        return
    fi

    ensure_state_dir
    if is_pid_running "$pid_file"; then
        echo -e "${BLUE}${label} already running (pid $(cat "$pid_file")).${NC}"
        return
    fi

    echo -e "${BLUE}Starting ${label}...${NC}"
    (
        cd "$workdir"
        nohup bash -lc "$cmd" >"$log_file" 2>&1 &
        echo $! > "$pid_file"
    )
}

stop_optional_process() {
    local label="$1"
    local pid_file="$2"

    if ! is_pid_running "$pid_file"; then
        rm -f "$pid_file"
        return
    fi

    local pid
    pid="$(cat "$pid_file")"
    echo -e "${BLUE}Stopping ${label} (pid ${pid})...${NC}"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    kill -9 "$pid" >/dev/null 2>&1 || true
    rm -f "$pid_file"
}

start_llama_cpp() {
    if [ "$LLAMA_CPP_USE_DOCKER" = "1" ]; then
        start_llama_cpp_docker
        return
    fi

    local cmd="$LLAMA_CPP_START_CMD"
    local workdir="$LLAMA_CPP_WORKDIR"

    # Default to the shared llama.cpp launcher when no explicit command is provided.
    if [ -z "$cmd" ] && [ -f "$LLAMA_CPP_START_SCRIPT" ]; then
        cmd="exec bash \"$LLAMA_CPP_START_SCRIPT\""
        workdir="$(dirname "$LLAMA_CPP_START_SCRIPT")"
    fi

    start_optional_process "LLAMA_CPP" "$cmd" "$workdir" "$LLAMA_CPP_PID_FILE" "$LLAMA_CPP_LOG_FILE"
}

start_llama_cpp_docker() {
    local model_path="$LLAMA_CPP_DOCKER_MODEL_PATH"
    if [ ! -f "$model_path" ]; then
        model_path="$LLAMA_CPP_MODEL_PATH"
    fi
    if [ ! -f "$model_path" ]; then
        echo -e "${YELLOW}Missing llama.cpp model file: $model_path${NC}"
        echo -e "${YELLOW}Set LLAMA_CPP_MODEL_PATH to a valid GGUF file and retry.${NC}"
        exit 1
    fi

    local model_dir
    local model_file
    model_dir="$(dirname "$model_path")"
    model_file="$(basename "$model_path")"

    # Ensure the target port is free before binding the Docker container.
    local port_pids
    port_pids="$(lsof -ti tcp:${LLAMA_CPP_PORT} -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$port_pids" ]; then
        echo -e "${BLUE}Releasing port ${LLAMA_CPP_PORT} from process(es): ${port_pids}${NC}"
        kill ${port_pids} 2>/dev/null || true
        sleep 2
    fi
    if lsof -ti tcp:${LLAMA_CPP_PORT} -sTCP:LISTEN >/dev/null 2>&1; then
        echo -e "${YELLOW}Port ${LLAMA_CPP_PORT} is still in use. Cannot start llama.cpp container.${NC}"
        exit 1
    fi

    if docker ps -a --format '{{.Names}}' | rg -x "$LLAMA_CPP_CONTAINER_NAME" >/dev/null 2>&1; then
        docker rm -f "$LLAMA_CPP_CONTAINER_NAME" >/dev/null 2>&1 || true
    fi

    echo -e "${BLUE}Starting llama.cpp Docker container (${LLAMA_CPP_CONTAINER_NAME})...${NC}"
    docker run -d \
        --name "$LLAMA_CPP_CONTAINER_NAME" \
        -p "${LLAMA_CPP_PORT}:1234" \
        -v "${model_dir}:/models:ro" \
        "$LLAMA_CPP_DOCKER_IMAGE" \
        -m "/models/${model_file}" \
        --host 0.0.0.0 \
        --port 1234 \
        --ctx-size "${LLAMA_CPP_CTX_SIZE}" \
        --parallel 1 \
        --cont-batching \
        --flash-attn on >/dev/null
}

start_comfyui() {
    start_optional_process "COMFYUI" "$COMFYUI_START_CMD" "$COMFYUI_WORKDIR" "$COMFYUI_PID_FILE" "$COMFYUI_LOG_FILE"
}

start_browser_automation() {
    if [ "$BROWSER_AUTOMATION_ENABLE" != "1" ]; then
        echo -e "${YELLOW}Skipping browser automation stub (BROWSER_AUTOMATION_ENABLE=${BROWSER_AUTOMATION_ENABLE}).${NC}"
        return
    fi
    if [ -z "${BROWSER_AUTOMATION_START_CMD}" ]; then
        if [ -x "$CAPYBARA_ROOT/backend/.venv/bin/uvicorn" ]; then
            BROWSER_AUTOMATION_START_CMD="$CAPYBARA_ROOT/backend/.venv/bin/uvicorn src.community.browser_automation.app:app --host 0.0.0.0 --port ${BROWSER_AUTOMATION_PORT}"
        else
            BROWSER_AUTOMATION_START_CMD="uvicorn src.community.browser_automation.app:app --host 0.0.0.0 --port ${BROWSER_AUTOMATION_PORT}"
        fi
    fi
    start_optional_process "BROWSER_AUTOMATION" "$BROWSER_AUTOMATION_START_CMD" "$BROWSER_AUTOMATION_WORKDIR" "$BROWSER_AUTOMATION_PID_FILE" "$BROWSER_AUTOMATION_LOG_FILE"
}

start_stack() {
    print_header
    start_comfyui
    start_lightrag_compose
    start_websearch_compose
    start_browser_automation

    echo ""
    echo -e "${GREEN}Local stack is up.${NC}"
    echo "llama.cpp: ${LLAMA_CPP_BASE_URL}"
    echo "ComfyUI : ${COMFYUI_BASE_URL}"
    echo "LightRAG: ${LIGHTRAG_BASE_URL}"
    echo "Infinity Rerank: ${INFINITY_RERANK_BASE_URL}"
    echo "WebSearch: ${WEBSEARCH_BASE_URL}"
    echo "Browser : ${BROWSER_AUTOMATION_BASE_URL}"
    echo "Capybara Home is excluded from integration startup."
}

start_lightrag_compose() {
    echo -e "${BLUE}Starting LightRAG compose stack...${NC}"
    lightrag_compose up -d --remove-orphans
}

stop_lightrag_compose() {
    echo -e "${BLUE}Stopping LightRAG compose stack...${NC}"
    lightrag_compose down --remove-orphans
}

start_websearch_compose() {
    echo -e "${BLUE}Starting WebSearch compose stack...${NC}"
    websearch_compose up -d --remove-orphans
}

stop_websearch_compose() {
    echo -e "${BLUE}Stopping WebSearch compose stack...${NC}"
    websearch_compose down --remove-orphans
}

start_llm_service() {
    print_header
    echo -e "${BLUE}LLM startup integration is disabled.${NC}"
    echo -e "${BLUE}Running health check only for ${LLAMA_CPP_BASE_URL%/}/models ...${NC}"
    local code
    code="$(curl -s -o /dev/null -w "%{http_code}" "${LLAMA_CPP_BASE_URL%/}/models" || true)"
    echo "llama.cpp health HTTP status: ${code}"
    if [ "$code" = "200" ]; then
        echo -e "${GREEN}LLM health check passed.${NC}"
    else
        echo -e "${YELLOW}LLM health check failed (expected 200).${NC}"
    fi
}

start_lightrag_service() {
    print_header
    start_lightrag_compose
    echo -e "${GREEN}LightRAG startup command completed.${NC}"
}

start_websearch_service() {
    print_header
    start_websearch_compose
    echo -e "${GREEN}WebSearch startup command completed.${NC}"
}

start_comfyui_service() {
    print_header
    start_comfyui
    echo -e "${GREEN}ComfyUI startup command completed.${NC}"
}

stop_lightrag_service() {
    print_header
    stop_lightrag_compose
    echo -e "${GREEN}LightRAG stop command completed.${NC}"
}

stop_websearch_service() {
    print_header
    stop_websearch_compose
    echo -e "${GREEN}WebSearch stop command completed.${NC}"
}

stop_comfyui_service() {
    print_header
    # Stop optional process (if managed by pid file)
    stop_optional_process "COMFYUI" "$COMFYUI_PID_FILE"
    # Stop container if one exists
    docker rm -f comfyui >/dev/null 2>&1 || true
    echo -e "${GREEN}ComfyUI stop command completed.${NC}"
}

stop_stack() {
    print_header
    stop_optional_process "BROWSER_AUTOMATION" "$BROWSER_AUTOMATION_PID_FILE"
    stop_optional_process "COMFYUI" "$COMFYUI_PID_FILE"
    docker rm -f "$LLAMA_CPP_CONTAINER_NAME" >/dev/null 2>&1 || true
    stop_optional_process "LLAMA_CPP" "$LLAMA_CPP_PID_FILE"
    stop_lightrag_compose || true
    stop_websearch_compose || true

    echo -e "${BLUE}Stopping Capybara Home...${NC}"
    (cd "$CAPYBARA_ROOT" && ./scripts/docker.sh stop) || true

    echo -e "${GREEN}Local stack is stopped.${NC}"
}

stack_status() {
    print_header
    echo "Port checks:"
    for port in "$CAPYBARA_UI_PORT" "$LLAMA_CPP_PORT" "$COMFYUI_PORT" "$LIGHTRAG_PORT" "$INFINITY_RERANK_PORT" "$WEBSEARCH_PORT" "$BROWSER_AUTOMATION_PORT"; do
        if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "  [up]   :${port}"
        else
            echo "  [down] :${port}"
        fi
    done

    echo ""
    echo "HTTP checks:"
    curl -s -o /dev/null -w "  capybara-home  %{http_code}\n" "http://localhost:${CAPYBARA_UI_PORT}/" || true
    curl -s -o /dev/null -w "  llama.cpp %{http_code}\n" "${LLAMA_CPP_BASE_URL%/}/models" || true
    curl -s -o /dev/null -w "  comfyui   %{http_code}\n" "${COMFYUI_BASE_URL}/system_stats" || true
    curl -s -o /dev/null -w "  lightrag  %{http_code}\n" "${LIGHTRAG_BASE_URL}/health" || true
    curl -s -o /dev/null -w "  infinity  %{http_code}\n" "${INFINITY_RERANK_BASE_URL}/health" || true
    curl -s -o /dev/null -w "  websearch %{http_code}\n" "${WEBSEARCH_BASE_URL}/health" || true
    curl -s -o /dev/null -w "  browser   %{http_code}\n" "${BROWSER_AUTOMATION_BASE_URL}/health" || true

    echo ""
    echo "Managed optional processes:"
    if [ "$LLAMA_CPP_USE_DOCKER" = "1" ]; then
        if docker ps --format '{{.Names}}' | rg -x "$LLAMA_CPP_CONTAINER_NAME" >/dev/null 2>&1; then
            echo "  [up]   llama.cpp  container $LLAMA_CPP_CONTAINER_NAME"
        else
            echo "  [down] llama.cpp  container $LLAMA_CPP_CONTAINER_NAME"
        fi
    elif is_pid_running "$LLAMA_CPP_PID_FILE"; then
        echo "  [up]   llama.cpp  pid $(cat "$LLAMA_CPP_PID_FILE")"
    else
        echo "  [down] llama.cpp  (set LLAMA_CPP_START_CMD to manage it here)"
    fi
    if is_pid_running "$COMFYUI_PID_FILE"; then
        echo "  [up]   ComfyUI    pid $(cat "$COMFYUI_PID_FILE")"
    else
        echo "  [down] ComfyUI    (set COMFYUI_START_CMD to manage it here)"
    fi
    if is_pid_running "$BROWSER_AUTOMATION_PID_FILE"; then
        echo "  [up]   Browser automation pid $(cat "$BROWSER_AUTOMATION_PID_FILE")"
    else
        echo "  [down] Browser automation (set BROWSER_AUTOMATION_ENABLE=0 to disable)"
    fi

    echo ""
    echo "Containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | \
        rg "capybara-home|lightrag|infinity|websearch|NAMES" || true
}

stack_logs() {
    print_header
    echo "Use these focused log commands:"
    echo "  Capybara Home:  cd \"$CAPYBARA_ROOT\" && ./scripts/docker.sh logs"
    echo "  lightrag: docker logs -f lightrag-lightrag-1"
    echo "  infinity: docker logs -f infinity-rerank"
    echo "  websearch: docker logs -f websearch"
    echo "  llama.cpp: tail -f \"$LLAMA_CPP_LOG_FILE\""
    echo "  ComfyUI:   tail -f \"$COMFYUI_LOG_FILE\""
    echo "  Browser:   tail -f \"$BROWSER_AUTOMATION_LOG_FILE\""
}

usage() {
    cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  start              Start local integrations stack (ComfyUI, LightRAG, WebSearch)
  start-llm          LLM health check only (:1234/v1/models)
  start-lightrag     Start LightRAG + Infinity compose stack
  start-websearch    Start WebSearch compose stack
  start-comfyui       Start ComfyUI only
  stop-lightrag      Stop LightRAG + Infinity compose stack
  stop-websearch     Stop WebSearch compose stack
  stop-comfyui        Stop ComfyUI only
  stop               Stop local stack
  restart            Restart local stack
  status             Show local stack status
  logs               Print log commands for each service
EOF
}

main() {
    case "${1:-}" in
        start)
            start_stack
            ;;
        start-llm)
            start_llm_service
            ;;
        start-lightrag)
            start_lightrag_service
            ;;
        start-websearch)
            start_websearch_service
            ;;
        start-comfyui)
            start_comfyui_service
            ;;
        stop-lightrag)
            stop_lightrag_service
            ;;
        stop-websearch)
            stop_websearch_service
            ;;
        stop-comfyui)
            stop_comfyui_service
            ;;
        stop)
            stop_stack
            ;;
        restart)
            stop_stack
            start_stack
            ;;
        status)
            stack_status
            ;;
        logs)
            stack_logs
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
