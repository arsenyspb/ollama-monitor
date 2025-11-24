# Ollama Benchmark Monitor

A shell script to benchmark Ollama model performance while monitoring system resource utilization on macOS.

## Description

This script executes a benchmark test for a specified Ollama model. While the model is running an inference task, the script monitors system metrics including:
- CPU Usage (%)
- GPU Power (mW)
- RAM Usage (GB)

Upon completion, it measures the model's performance (tokens/second) and generates a detailed Markdown report and logs data to a summary CSV file.

## Prerequisites

Ensure the Ollama service is running before executing the script. You can start it with the following command:
```shell
ollama serve
```

## Usage

To run the benchmark, execute the script from your terminal with a run type argument.

```shell
./bench_monitor.sh [clean|dirty]
```
-   `clean`: Intended for a run on a system with minimal background processes.
-   `dirty`: Intended for a run under normal system load.

The script requires `sudo` privileges to access `powermetrics` for GPU statistics.

## Configuration

The script is configured via variables at the top of the file.

-   `MODEL`: The Ollama model tag to benchmark (e.g., `qwen3-coder:30b`).
-   `PROMPT`: The input prompt for the model. As a shortcut, this is a hard-coded zero-shot prompt. For more advanced use cases, this can be externalized to be read from a file or command-line argument.
-   `OUTPUT_DIR`: The directory where benchmark reports and logs are stored.

## Output

The script generates the following files in the specified `OUTPUT_DIR`:

-   **Markdown Report** (`benchmark_report_[type]_[timestamp].md`): A detailed report containing performance metrics, system resource usage summaries, and the full model output.
-   **System Metrics CSV** (`system_metrics_[type]_[timestamp].csv`): Raw time-series data of CPU, GPU, and RAM usage during the run.
-   **Summary CSV** (`benchmark_summary.csv`): A log file that appends a summary of each benchmark run, including performance and configuration details.
