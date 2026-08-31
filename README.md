# Ollama Benchmark Monitor

A set of shell scripts to benchmark and continuously monitor Ollama model performance and system resource utilization on macOS.

## Description

This repository provides tools to track hardware usage (CPU, GPU, RAM) and tokens-per-second (TPS) while running Ollama on macOS. It includes:
- **Benchmark Monitor:** Executes a single prompt and measures performance metrics.
- **Continuous Monitor:** Runs in the background as a daemon to continuously log system metrics and inference speeds.

## AI Co-Development Guidelines
This project supports AI-assisted development. Please refer to [AI.md](AI.md) for guidelines on how AI agents should interact with this repository (Issue-driven development, PR workflows, and CI/CD).

## Prerequisites

Ensure the Ollama service is running before executing the script. You can start it with the following command:
```shell
ollama serve
```

## Usage

### 1. Benchmark Testing

To run the benchmark, execute the script from your terminal with a run type argument.

```shell
./bench_monitor.sh [clean|dirty]
```
-   `clean`: Intended for a run on a system with minimal background processes.
-   `dirty`: Intended for a run under normal system load.

The script requires `sudo` privileges to access `powermetrics` for GPU statistics.

### 2. Continuous Monitoring

To start the continuous monitoring daemon in the background:
```shell
make monitor-start
```
*Note: This will prompt for your `sudo` password to access GPU metrics.*

To stop the continuous monitor:
```shell
make monitor-stop
```

> **Current Limitation (TPS Tracking):** The continuous monitor currently tracks CPU, GPU, and RAM. It cannot capture Tokens-Per-Second (TPS) for API-based background inference (e.g. from external clients) because Ollama does not log generation stats to its server log. We are planning to introduce a thin proxy to intercept and log these metrics globally.

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
