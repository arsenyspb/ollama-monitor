## Purpose
A set of shell scripts and Python tools to benchmark and continuously monitor Ollama models' performance and system resource utilization (CPU, GPU, RAM, Tokens-Per-Second) on macOS.

## Key Technologies
- Python 3.10+
- Shell scripting
- Ollama API
- macOS powermetrics
- Make

## Top-Level Structure
- `src/`: Contains the core scripts, including the benchmark monitor, continuous monitor daemon, TUI dashboard, and TPS proxy.
- `tests/`: Python unit tests for the proxy and TUI dashboard.
- `Makefile`: Provides shortcuts for starting and stopping the monitors and proxy.
- `AI.md`: Guidelines for AI-assisted development workflows.

## Key Concepts
- Benchmark Monitor: Executes a single prompt to measure performance metrics, outputting markdown reports and CSV metrics.
- Continuous Monitor: A background daemon that logs system metrics (CPU, GPU, RAM) and inference speeds continuously.
- Interactive Dashboard: A real-time Text User Interface (TUI) that plots metrics in the terminal during model execution.
- TPS Proxy: A zero-configuration proxy that runs on Ollama's default port (11434) while moving the actual server to a background port (11435) in order to intercept and calculate Tokens-Per-Second (TPS).
- Live TPS Limitations: Because Ollama only emits performance statistics in the final JSON chunk of its streaming API, live TPS calculation remains zero until the text generation is completely finished.