#!/bin/bash

set -e
set -o pipefail

RUN_TYPE="$1" # Pass "clean" or "dirty" as the first argument

# Validate Input first before executing external commands
if [[ -z "$RUN_TYPE" ]]; then
    echo "Usage: ./bench_monitor.sh [clean|dirty]"
    exit 1
fi

# --- CONFIGURATION ---
MODEL="qwen3-coder:30b"  # Change this to your exact model tag
PROMPT="[ROLE] You are a Solutions Architect at HashiCorp. You're closely familiar with HashiCorp Validated Designs (HVDs), HashiCorp Validated Patterns (HVP), principles of writing clean HCL, and building Cloud Foundations. [TASK] Reason on your approach to write best-practice aligned Terraform to provision a highly available AWS VPC Foundations, including subnets, NAT gateways, and route tables. After you've reasoned, execute code writing. [FORMAT] Explain sections of code. Do not add in-line comments."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_ROOT/benchmark_data}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
CSV_TIMESTAMP=$(date +"%Y-%m-%dT%H:%M:%S")
POWER_SOURCE=$(pmset -g batt 2>/dev/null | grep "Now drawing from" | sed "s/Now drawing from '//" | sed "s/'//" || echo "Unknown")

# Setup Directories
mkdir -p "$OUTPUT_DIR"
METRICS_FILE="${OUTPUT_DIR}/system_metrics_${RUN_TYPE}_${TIMESTAMP}.csv"
LLM_LOG_FILE="${OUTPUT_DIR}/llm_log_${RUN_TYPE}_${TIMESTAMP}.txt"
RAW_OUTPUT_FILE="${OUTPUT_DIR}/raw_output_${RUN_TYPE}_${TIMESTAMP}.txt"
MARKDOWN_REPORT_FILE="${OUTPUT_DIR}/benchmark_report_${RUN_TYPE}_${TIMESTAMP}.md"
SUMMARY_FILE="${OUTPUT_DIR}/benchmark_summary.csv"

# Initialize CSV Headers
if [ ! -f "$SUMMARY_FILE" ]; then
    echo "Timestamp,Run_Type,Model,Prompt,Power_Source,Eval_TPS,Prompt_Eval_TPS" > "$SUMMARY_FILE"
fi
echo "Timestamp,CPU_Usage_%,GPU_Load_%,RAM_Used_GB" > "$METRICS_FILE"

echo "--- Starting Benchmark: $RUN_TYPE ---"
echo "--- Model: $MODEL ---"
echo "--- Power Source: $POWER_SOURCE ---"
echo "--- You may be asked for sudo password to read GPU stats via powermetrics ---"

# --- CLEANUP TRAP ---
cleanup() {
    if [[ -n "${MONITOR_PID:-}" ]]; then
        kill "$MONITOR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# --- BACKGROUND MONITORING FUNCTION ---
monitor_system() {
    set +e
    while true; do
        TS=$(date +"%H:%M:%S")
        
        # 1. CPU Load (User + Sys %) via top
        CPU_STATS=$(top -l 1 2>/dev/null | grep "CPU usage" || true)
        USER_CPU=$(echo "$CPU_STATS" | awk '{print $3}' | sed 's/%//')
        SYS_CPU=$(echo "$CPU_STATS" | awk '{print $5}' | sed 's/%//')
        CPU_LOAD=$(echo "${USER_CPU:-0} + ${SYS_CPU:-0}" | bc 2>/dev/null || echo "0")
        
        # 2. GPU Load (% active residency) via powermetrics
        GPU_LOAD=$(sudo powermetrics --samplers gpu_power -n 1 -i 100 2>/dev/null | grep "GPU HW active residency:" | awk '{print $5}' | sed 's/%//' || echo "0")
        if [ -z "$GPU_LOAD" ]; then
            GPU_LOAD="0"
        fi
        
        # 3. RAM Usage (System wide used) via vm_stat
        # Calculating used pages * 16384 (page size on M-series) / 1024 / 1024 / 1024 for GB
        PAGES_ACTIVE=$(vm_stat 2>/dev/null | grep "Pages active" | awk '{print $3}' | sed 's/\.//' || echo "0")
        PAGES_WIRED=$(vm_stat 2>/dev/null | grep "Pages wired" | awk '{print $4}' | sed 's/\.//' || echo "0")
        RAM_GB=$(echo "scale=2; (${PAGES_ACTIVE:-0} + ${PAGES_WIRED:-0}) * 16384 / 1024 / 1024 / 1024" | bc 2>/dev/null || echo "0")

        echo "$TS,$CPU_LOAD,$GPU_LOAD,$RAM_GB" >> "$METRICS_FILE"
        sleep 1
    done
}

# Start Monitoring in Background
monitor_system &
MONITOR_PID=$!

# --- RUN OLLAMA INFERENCE ---
echo ">>> Running Inference..."
RC=0
ollama run "$MODEL" "$PROMPT" --verbose > "$RAW_OUTPUT_FILE" 2> "$LLM_LOG_FILE" || RC=$?
if [ $RC -ne 0 ]; then
    echo "ollama run failed with exit code $RC"
    exit $RC
fi

# Stop monitor
kill "$MONITOR_PID" 2>/dev/null || true
echo ">>> Inference Complete."

# --- PARSE RESULTS ---
# Read the log file and clean ANSI codes from it before parsing
CLEAN_LOG=$(sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g' "$LLM_LOG_FILE")

# Extract Eval Rate (Generation speed) and Prompt Eval Rate (Processing speed) from the clean log
# Anchored to start of line to avoid 'eval rate:' matching inside 'prompt eval rate:'
EVAL_TPS=$(echo "$CLEAN_LOG" | grep -E "^[[:space:]]*eval rate:" | awk '{print $3}' || true)
PROMPT_TPS=$(echo "$CLEAN_LOG" | grep -E "^[[:space:]]*prompt eval rate:" | awk '{print $4}' || true)

# Handle cases where grep finds nothing
if [ -z "$EVAL_TPS" ]; then
    EVAL_TPS="N/A"
fi
if [ -z "$PROMPT_TPS" ]; then
    PROMPT_TPS="N/A"
fi

# --- CALCULATE SUMMARY METRICS ---
calc_summary() {
    local col="$1"
    local fmt="$2"
    tail -n +2 "$METRICS_FILE" | awk -F, -v c="$col" -v f="$fmt" '
    BEGIN {min=999999999; max=0; sum=0; count=0}
    {
        val = $c + 0;
        if (val == 0) next; # Ignore 0 values which can happen at the start/end
        if (val < min) min = val;
        if (val > max) max = val;
        sum += val;
        count++;
    }
    END {
        if (count > 0) {
            printf f "\t" f "\t" f, min, max, sum/count;
        } else {
            printf "N/A\tN/A\tN/A";
        }
    }'
}

# Summary stats for GPU load from metrics file (col 3)
GPU_STATS=$(calc_summary 3 "%.0f")
GPU_MIN=$(echo "$GPU_STATS" | cut -f1)
GPU_MAX=$(echo "$GPU_STATS" | cut -f2)
GPU_AVG=$(echo "$GPU_STATS" | cut -f3)

# Summary stats for RAM usage from metrics file (col 4)
RAM_STATS=$(calc_summary 4 "%.2f")
RAM_MIN=$(echo "$RAM_STATS" | cut -f1)
RAM_MAX=$(echo "$RAM_STATS" | cut -f2)
RAM_AVG=$(echo "$RAM_STATS" | cut -f3)

# --- GENERATE MARKDOWN REPORT ---
{
    echo "# Benchmark Run Details"
    echo ""
    echo "**Timestamp:** \`$CSV_TIMESTAMP\`"
    echo "**Model:** \`$MODEL\`"
    echo "**Run Type:** \`$RUN_TYPE\`"
    echo "**Power Source:** \`$POWER_SOURCE\`"
    echo ""
    echo "## Performance"
    echo "- **Generation Speed:** \`$EVAL_TPS tokens/s\`"
    echo "- **Processing Speed:** \`$PROMPT_TPS tokens/s\`"
    echo "- **Min GPU Load:** \`$GPU_MIN %\`"
    echo "- **Peak GPU Load:** \`$GPU_MAX %\`"
    echo "- **Average GPU Load:** \`$GPU_AVG %\`"
    echo "- **Min RAM Used:** \`$RAM_MIN GB\`"
    echo "- **Peak RAM Used:** \`$RAM_MAX GB\`"
    echo "- **Average RAM Used:** \`$RAM_AVG GB\`"
    echo ""
    echo "## Prompt"
    echo '```'
    echo "$PROMPT"
    echo '```'
    echo ""
    echo "---"
    echo ""
    echo "## Model Output"
    echo ""
} > "$MARKDOWN_REPORT_FILE"

# Append the model's output to the markdown file
cat "$RAW_OUTPUT_FILE" >> "$MARKDOWN_REPORT_FILE"

# Clean up temporary raw files
rm "$RAW_OUTPUT_FILE"
rm "$LLM_LOG_FILE"

# Log Summary
# Truncate prompt for summary file
TRUNCATED_PROMPT=$(echo "$PROMPT" | tr -d '\n' | cut -c 1-50)
echo "$CSV_TIMESTAMP,$RUN_TYPE,$MODEL,\"$TRUNCATED_PROMPT...\",$POWER_SOURCE,$EVAL_TPS,$PROMPT_TPS" >> "$SUMMARY_FILE"

echo "------------------------------------------------"
echo "RESULTS FOR $RUN_TYPE:"
echo "Generation Speed: $EVAL_TPS tokens/s"
echo "Processing Speed: $PROMPT_TPS tokens/s"
echo "Peak GPU Load: $GPU_MAX % (Avg: $GPU_AVG %, Min: $GPU_MIN %)"
echo "Peak RAM Used: $RAM_MAX GB (Avg: $RAM_AVG GB, Min: $RAM_MIN GB)"
echo "Markdown report saved to: $MARKDOWN_REPORT_FILE"
echo "System telemetry saved to: $METRICS_FILE"
echo "------------------------------------------------"
