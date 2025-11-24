#!/bin/bash

set -e
set -o pipefail

# --- CONFIGURATION ---
MODEL="qwen3-coder:30b"  # Change this to your exact model tag
PROMPT="[ROLE] You are a Solutions Architect at HashiCorp. You're closely familiar with HashiCorp Validated Designs (HVDs) and principles of Cloud Foundations. Write a set of HCL scripts to provision a highly available AWS VPC Foundations using Terraform, including subnets, NAT gateways, and route tables. Explain every step in detail."
OUTPUT_DIR="benchmark_data"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
CSV_TIMESTAMP=$(date +"%Y-%m-%dT%H:%M:%S")
RUN_TYPE="$1" # Pass "clean" or "dirty" as the first argument

# Validate Input
if [[ -z "$RUN_TYPE" ]]; then
    echo "Usage: ./bench_monitor.sh [clean|dirty]"
    exit 1
fi

# Setup Directories
mkdir -p $OUTPUT_DIR
METRICS_FILE="${OUTPUT_DIR}/system_metrics_${RUN_TYPE}_${TIMESTAMP}.csv"
LLM_LOG_FILE="${OUTPUT_DIR}/llm_log_${RUN_TYPE}_${TIMESTAMP}.txt"
SUMMARY_FILE="${OUTPUT_DIR}/benchmark_summary.csv"

# Initialize CSV Headers
if [ ! -f "$SUMMARY_FILE" ]; then
    echo "Timestamp,Run_Type,Model,Prompt,Eval_TPS,Prompt_Eval_TPS" > "$SUMMARY_FILE"
fi
echo "Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB" > "$METRICS_FILE"

echo "--- Starting Benchmark: $RUN_TYPE ---"
echo "--- Model: $MODEL ---"
echo "--- You may be asked for sudo password to read GPU stats via powermetrics ---"

# --- BACKGROUND MONITORING FUNCTION ---
monitor_system() {
    while true; do
        TS=$(date +"%H:%M:%S")
        
        # 1. CPU Load (User + Sys %) via top
        CPU_STATS=$(top -l 1 | grep "CPU usage")
        USER_CPU=$(echo "$CPU_STATS" | awk '{print $3}' | sed 's/%//')
        SYS_CPU=$(echo "$CPU_STATS" | awk '{print $5}' | sed 's/%//')
        CPU_LOAD=$(echo "$USER_CPU + $SYS_CPU" | bc)
        
        # 2. GPU Power (best proxy for Load on Mac CLI) via powermetrics
        # This pulls the immediate power draw of the GPU in milliwatts
        GPU_POWER=$(sudo powermetrics --samplers gpu_power -n 1 | grep "GPU Power" | awk '{print $3}')
        
        # 3. RAM Usage (System wide used) via vm_stat
        # Calculating used pages * 16384 (page size on M-series) / 1024 / 1024 / 1024 for GB
        PAGES_ACTIVE=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
        PAGES_WIRED=$(vm_stat | grep "Pages wired" | awk '{print $4}' | sed 's/\.//')
        RAM_GB=$(echo "scale=2; ($PAGES_ACTIVE + $PAGES_WIRED) * 16384 / 1024 / 1024 / 1024" | bc)

        echo "$TS,$CPU_LOAD,$GPU_POWER,$RAM_GB" >> "$METRICS_FILE"
        sleep 1
    done
}

# Start Monitoring in Background
monitor_system &
MONITOR_PID=$!

# --- RUN OLLAMA INFERENCE ---
echo ">>> Running Inference..."
# We use --verbose to get the timing stats sent to stderr
ollama run $MODEL "$PROMPT" --verbose > "$LLM_LOG_FILE" 2>&1

# --- CLEANUP ---
kill $MONITOR_PID
echo ">>> Inference Complete."

# --- PARSE RESULTS ---
# Extract Eval Rate (Generation speed) and Prompt Eval Rate (Processing speed)
EVAL_TPS=$(grep "eval rate:" "$LLM_LOG_FILE" | awk '{print $3}' || true)
PROMPT_TPS=$(grep "prompt eval rate:" "$LLM_LOG_FILE" | awk '{print $4}' || true)

# Handle cases where grep finds nothing
if [ -z "$EVAL_TPS" ]; then
    EVAL_TPS="N/A"
fi
if [ -z "$PROMPT_TPS" ]; then
    PROMPT_TPS="N/A"
fi

# Log Summary
# Truncate prompt for summary file
TRUNCATED_PROMPT=$(echo "$PROMPT" | tr -d '\n' | cut -c 1-50)
echo "$CSV_TIMESTAMP,$RUN_TYPE,$MODEL,\"$TRUNCATED_PROMPT...\",$EVAL_TPS,$PROMPT_TPS" >> "$SUMMARY_FILE"

echo "------------------------------------------------"
echo "RESULTS FOR $RUN_TYPE:"
echo "Generation Speed: $EVAL_TPS tokens/s"
echo "Processing Speed: $PROMPT_TPS tokens/s"
echo "System telemetry saved to: $METRICS_FILE"
echo "------------------------------------------------"