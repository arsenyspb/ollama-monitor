## Purpose
A set of tools to benchmark and continuously monitor Ollama model performance, inference speeds (Tokens-Per-Second), and system resource utilization (CPU, GPU, RAM) on macOS.

## Key Technologies
- Python
- Shell scripting (Bash)
- Ollama
- macOS powermetrics
- Make

## Top-Level Structure
The repository root contains the Makefile, documentation (README.md, AI.md), and dependency configurations. The `src/` directory includes the core logic: shell scripts for monitoring (`bench_monitor.sh`, `continuous_monitor.sh`) and Python scripts for the TUI dashboard and TPS proxy. The `tests/` directory contains automated test suites for the Python components.

## Key Concepts
- Benchmark Monitor: A tool that executes a single prompt and measures performance metrics, generating Markdown and CSV reports.
- Continuous Monitor: A background daemon that continuously logs system resource utilization and model inference speeds.
- Interactive Dashboard: A real-time Text User Interface (TUI) that visually plots continuous metrics in the terminal.
- TPS Proxy: A zero-configuration proxy that intercepts Ollama API calls to capture and log Tokens-Per-Second metrics transparently.