#!/bin/bash

set -e
set -o pipefail

# Setup Output
OUTPUT_DIR="benchmark_data"
mkdir -p "$OUTPUT_DIR"
METRICS_FILE="${OUTPUT_DIR}/continuous_monitor.csv"
TPS_FILE="/tmp/ollama_current_tps"

# Initialize CSV Headers
if [ ! -f "$METRICS_FILE" ]; then
    echo "Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS" > "$METRICS_FILE"
fi

echo "--- Starting Continuous Monitor ---"
echo "Monitoring system metrics and Ollama tokens-per-second..."
echo "Press Ctrl+C or run 'make monitor-stop' to stop."

# --- OLLAMA LOG TAILER (TPS) ---
# Tails the Ollama server log to capture eval_count and eval_duration
tail -F ~/.ollama/logs/server.log 2>/dev/null | awk '
/eval_count=/ && /eval_duration=/ {
    match($0, /eval_count=[0-9]+/)
    c = substr($0, RSTART+11, RLENGTH-11)
    match($0, /eval_duration=[0-9]+/)
    d = substr($0, RSTART+14, RLENGTH-14)
    if (c != "" && d != "" && d > 0) {
        # eval_duration is in nanoseconds
        tps = c / (d / 1000000000)
        printf "%.2f\n", tps > "'"$TPS_FILE"'"
    }
}' &
TAIL_PID=$!

echo "0" > "$TPS_FILE"

# --- SYSTEM MONITORING LOOP ---
monitor_system() {
    while true; do
        TS=$(date +"%H:%M:%S")
        
        # 1. CPU Load
        CPU_STATS=$(top -l 1 | grep "CPU usage")
        USER_CPU=$(echo "$CPU_STATS" | awk '{print $3}' | sed 's/%//')
        SYS_CPU=$(echo "$CPU_STATS" | awk '{print $5}' | sed 's/%//')
        CPU_LOAD=$(echo "$USER_CPU + $SYS_CPU" | bc 2>/dev/null || echo "0")
        
        # 2. GPU Load
        GPU_POWER=$(sudo powermetrics --samplers gpu_power -n 1 -i 100 2>/dev/null | grep "GPU HW active residency:" | awk '{print $5}' | sed 's/%//' || echo "0")
        
        # 3. RAM Usage
        PAGES_ACTIVE=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
        PAGES_WIRED=$(vm_stat | grep "Pages wired" | awk '{print $4}' | sed 's/\.//')
        RAM_GB=$(echo "scale=2; ($PAGES_ACTIVE + $PAGES_WIRED) * 16384 / 1024 / 1024 / 1024" | bc 2>/dev/null || echo "0")

        # 4. Read latest TPS
        LATEST_TPS=$(cat "$TPS_FILE" 2>/dev/null || echo "0")

        echo "$TS,$CPU_LOAD,$GPU_POWER,$RAM_GB,$LATEST_TPS" >> "$METRICS_FILE"
        
        # Reset TPS file after reporting so it goes back to 0 when idle
        echo "0" > "$TPS_FILE"
        
        sleep 1
    done
}

monitor_system &
MONITOR_PID=$!

# Trap signals for graceful shutdown
cleanup() {
    echo "Stopping continuous monitor..."
    kill $TAIL_PID 2>/dev/null || true
    kill $MONITOR_PID 2>/dev/null || true
    rm -f "$TPS_FILE"
    rm -f "/tmp/ollama_monitor.pid"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Save PID so external tools can stop it
echo $$ > "/tmp/ollama_monitor.pid"

# Keep main script alive
wait $MONITOR_PID
