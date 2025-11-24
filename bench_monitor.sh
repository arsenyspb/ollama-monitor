#!/bin/bash

set -e
set -o pipefail

# --- CONFIGURATION ---
MODEL="qwen3-coder:480b"  # Change this to your exact model tag
PROMPT="[ROLE] You are a Solutions Architect at HashiCorp. You're closely familiar with HashiCorp Validated Designs (HVDs), HashiCorp Validated Patterns (HVP), principles of writing clean HCL, and building Cloud Foundations. [TASK] Reason on your approach to write best-practice aligned Terraform to provision a highly available AWS VPC Foundations, including subnets, NAT gateways, and route tables. After you've reasoned, execute code writing. [FORMAT] Explain sections of code. Do not add in-line comments."
OUTPUT_DIR="benchmark_data"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
CSV_TIMESTAMP=$(date +"%Y-%m-%dT%H:%M:%S")
POWER_SOURCE=$(pmset -g batt | grep "Now drawing from" | sed "s/Now drawing from '//" | sed "s/'//")
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
RAW_OUTPUT_FILE="${OUTPUT_DIR}/raw_output_${RUN_TYPE}_${TIMESTAMP}.txt"
MARKDOWN_REPORT_FILE="${OUTPUT_DIR}/benchmark_report_${RUN_TYPE}_${TIMESTAMP}.md"
SUMMARY_FILE="${OUTPUT_DIR}/benchmark_summary.csv"

# Initialize CSV Headers
if [ ! -f "$SUMMARY_FILE" ]; then
    echo "Timestamp,Run_Type,Model,Prompt,Power_Source,Eval_TPS,Prompt_Eval_TPS" > "$SUMMARY_FILE"
fi
echo "Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB" > "$METRICS_FILE"

echo "--- Starting Benchmark: $RUN_TYPE ---"
echo "--- Model: $MODEL ---"
echo "--- Power Source: $POWER_SOURCE ---"
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
# stdout (model output) goes to RAW_OUTPUT_FILE
# stderr (verbose stats) goes to LLM_LOG_FILE
ollama run $MODEL "$PROMPT" --verbose > "$RAW_OUTPUT_FILE" 2> "$LLM_LOG_FILE"

# --- CLEANUP ---
kill $MONITOR_PID
echo ">>> Inference Complete."

# --- PARSE RESULTS ---
# Read the log file and clean ANSI codes from it before parsing
CLEAN_LOG=$(sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g' "$LLM_LOG_FILE")

# Extract Eval Rate (Generation speed) and Prompt Eval Rate (Processing speed) from the clean log
EVAL_TPS=$(echo "$CLEAN_LOG" | grep "eval rate:" | awk '{print $3}' || true)
PROMPT_TPS=$(echo "$CLEAN_LOG" | grep "prompt eval rate:" | awk '{print $4}' || true)

# Handle cases where grep finds nothing
if [ -z "$EVAL_TPS" ]; then
    EVAL_TPS="N/A"
fi
if [ -z "$PROMPT_TPS" ]; then
    PROMPT_TPS="N/A"
fi

# --- CALCULATE SUMMARY METRICS ---
# Calculate summary stats for GPU power from the metrics file
GPU_STATS=$(tail -n +2 "$METRICS_FILE" | awk -F, '{print $3}' | awk '
    BEGIN {min=999999999; max=0; sum=0; count=0}
    {
        val = $1 + 0;
        if (val == 0) next; # Ignore 0 values which can happen at the start/end
        if (val < min) min = val;
        if (val > max) max = val;
        sum += val;
        count++;
    }
    END {
        if (count > 0) {
            printf "%.0f\t%.0f\t%.0f", min, max, sum/count;
        } else {
            printf "N/A\tN/A\tN/A";
        }
    }')
GPU_MIN=$(echo "$GPU_STATS" | cut -f1)
GPU_MAX=$(echo "$GPU_STATS" | cut -f2)
GPU_AVG=$(echo "$GPU_STATS" | cut -f3)

# Calculate summary stats for RAM usage from the metrics file
RAM_STATS=$(tail -n +2 "$METRICS_FILE" | awk -F, '{print $4}' | awk '
    BEGIN {min=99999; max=0; sum=0; count=0}
    {
        val = $1 + 0;
        if (val < min) min = val;
        if (val > max) max = val;
        sum += val;
        count++;
    }
    END {
        if (count > 0) {
            printf "%.2f\t%.2f\t%.2f", min, max, sum/count;
        } else {
            printf "N/A\tN/A\tN/A";
        }
    }')
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
    echo "- **Peak GPU Power:** \`$GPU_MAX mW\`"
    echo "- **Average GPU Power:** \`$GPU_AVG mW\`"
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
echo "Markdown report saved to: $MARKDOWN_REPORT_FILE"
echo "System telemetry saved to: $METRICS_FILE"
echo "------------------------------------------------"