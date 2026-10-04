#!/bin/bash

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Setup Output
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_ROOT/benchmark_data}"
mkdir -p "$OUTPUT_DIR"
METRICS_FILE="${OUTPUT_DIR}/continuous_monitor.csv"

# Runtime directory for temporary files (per-user)
USER_ID=$(id -u 2>/dev/null || echo "0")
RUNTIME_DIR="${OLLAMA_MONITOR_DIR:-/tmp/ollama-monitor-${USER_ID}}"
mkdir -p "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR" 2>/dev/null || true
TPS_FILE="${OLLAMA_TPS_FILE:-$RUNTIME_DIR/ollama_current_tps}"
PID_FILE="${RUNTIME_DIR}/ollama_monitor.pid"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
    echo "Continuous monitor is already running (PID $(cat "$PID_FILE"))."
    exit 1
fi
echo $$ > "$PID_FILE"

# Initialize CSV Headers
if [ ! -f "$METRICS_FILE" ]; then
    echo "Timestamp,CPU_Usage_%,GPU_Load_%,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata" > "$METRICS_FILE"
fi

echo "--- Starting Continuous Monitor ---"
echo "Monitoring system metrics and Ollama tokens-per-second..."
echo "Press Ctrl+C or run 'make monitor-stop' to stop."

# Verify sudo status
if ! sudo -n true 2>/dev/null; then
    echo "Warning: sudo credentials expired or missing; GPU metrics require sudo." >&2
fi

# --- CLEANUP TRAP ---
cleanup() {
    trap - EXIT INT TERM
    echo "Stopping continuous monitor..."
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true
    fi
    if [[ -n "${AWK_PID:-}" ]]; then
        kill "$AWK_PID" 2>/dev/null || true
    fi
    if [[ -n "${POWER_PID:-}" ]]; then
        kill "$POWER_PID" 2>/dev/null || true
    fi
    if [[ -n "${MONITOR_PID:-}" ]]; then
        kill "$MONITOR_PID" 2>/dev/null || true
    fi
    rm -f "${FIFO:-}" "${GPU_FILE:-}" "$TPS_FILE" "$PID_FILE" "/tmp/ollama_monitor.pid"
    exit 0
}
trap cleanup EXIT INT TERM

# --- MODEL METADATA EXTRACTOR ---
get_model_info() {
    python3 - 2>/dev/null << 'EOF' || echo "None,None"
import urllib.request
import json

try:
    port = 11434
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ps")
    with urllib.request.urlopen(req, timeout=0.5) as response:
        data = json.loads(response.read())
        models = data.get("models", [])
        if models:
            m = models[0]
            name = m.get("name", "Unknown")
            details = m.get("details", {})
            param_size = details.get("parameter_size", "?")
            quant = details.get("quantization_level", "?")
            size_bytes = m.get("size", 0)
            size_gb = size_bytes / (1024**3)
            size_str = f"{size_gb:.1f}GB"
            print(f"{name},{param_size}|{quant}|{size_str}")
        else:
            print("None,None")
except Exception:
    print("None,None")
EOF
}

# --- OLLAMA LOG TAILER (TPS) ---
echo "0" > "$TPS_FILE"
FIFO="${RUNTIME_DIR}/ollama_log_fifo.$$"
rm -f "$FIFO"
mkfifo "$FIFO"

tail -F ~/.ollama/logs/server.log > "$FIFO" 2>/dev/null &
TAIL_PID=$!

awk -v tps_file="$TPS_FILE" '
/eval_count=/ && /eval_duration=/ {
    match($0, /eval_count=[0-9]+/)
    c = substr($0, RSTART+11, RLENGTH-11)
    match($0, /eval_duration=[0-9]+/)
    d = substr($0, RSTART+14, RLENGTH-14)
    if (c != "" && d != "" && d > 0) {
        tps = c / (d / 1000000000)
        printf "%.2f\n", tps > tps_file
        close(tps_file)
    }
}' < "$FIFO" &
AWK_PID=$!

# --- LONG-LIVED POWERMETRICS STREAM ---
GPU_FILE="${RUNTIME_DIR}/gpu_residency.$$"
echo "0" > "$GPU_FILE"
POWER_PID=""
if sudo -n true 2>/dev/null; then
    (
        sudo powermetrics --samplers gpu_power -i 1000 2>/dev/null | awk -v out="$GPU_FILE" '
        /GPU HW active residency:/ {
            val = $5
            gsub(/%/, "", val)
            print val > out
            fflush(out)
            close(out)
        }'
    ) &
    POWER_PID=$!
fi

# --- SYSTEM MONITORING LOOP ---
monitor_system() {
    set +e
    while true; do
        TS=$(date +"%H:%M:%S")

        # 1. CPU Load: top -l 2 -s 1 takes 1 second interval sample without requiring sleep
        CPU_STATS=$(top -l 2 -s 1 -n 0 2>/dev/null | grep "CPU usage" | tail -n 1 || true)
        if [ -z "$CPU_STATS" ]; then
            CPU_STATS=$(top -l 1 2>/dev/null | grep "CPU usage" || true)
            sleep 1
        fi
        USER_CPU=$(echo "$CPU_STATS" | awk '{print $3}' | sed 's/%//')
        SYS_CPU=$(echo "$CPU_STATS" | awk '{print $5}' | sed 's/%//')
        CPU_LOAD=$(echo "${USER_CPU:-0} + ${SYS_CPU:-0}" | bc 2>/dev/null || echo "0")

        # 2. GPU Load (% active residency)
        GPU_LOAD=$(cat "$GPU_FILE" 2>/dev/null || echo "0")
        GPU_LOAD=$(echo "$GPU_LOAD" | tr -cd '0-9.' || echo "0")
        if [ -z "$GPU_LOAD" ]; then
            GPU_LOAD="0"
        fi

        # 3. RAM Usage
        PAGES_ACTIVE=$(vm_stat 2>/dev/null | grep "Pages active" | awk '{print $3}' | sed 's/\.//' || echo "0")
        PAGES_WIRED=$(vm_stat 2>/dev/null | grep "Pages wired" | awk '{print $4}' | sed 's/\.//')
        RAM_GB=$(echo "scale=2; (${PAGES_ACTIVE:-0} + ${PAGES_WIRED:-0}) * 16384 / 1024 / 1024 / 1024" | bc 2>/dev/null || echo "0")

        # 4. Read latest TPS (validated)
        LATEST_TPS=$(head -n 1 "$TPS_FILE" 2>/dev/null | tr -cd '0-9.' || echo "0")
        if [ -z "$LATEST_TPS" ]; then
            LATEST_TPS="0"
        fi

        # 5. Get Model Info
        MODEL_INFO=$(get_model_info)

        echo "$TS,$CPU_LOAD,$GPU_LOAD,$RAM_GB,$LATEST_TPS,$MODEL_INFO" >> "$METRICS_FILE"

        # Reset TPS file after reporting so it goes back to 0 when idle
        echo "0" > "$TPS_FILE"
    done
}

monitor_system &
MONITOR_PID=$!

# Keep main script alive
wait $MONITOR_PID
