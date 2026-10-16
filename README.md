# Ollama Benchmark Monitor

[![Python Tests](https://github.com/arsenyspb/ollama-monitor/actions/workflows/test.yml/badge.svg)](https://github.com/arsenyspb/ollama-monitor/actions/workflows/test.yml)
[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A set of handy shell scripts to benchmark and continuously monitor Ollama models performance and system resource utilization on macOS.

## Description

This repository provides tools to track hardware usage (CPU, GPU, RAM) and tokens-per-second (TPS) while running Ollama on macOS. It includes:
- **Benchmark Monitor:** Executes a single prompt and measures performance metrics.
- **Continuous Monitor:** Runs in the background as a daemon to continuously log system metrics and inference speeds.

### Interactive Dashboard

To view a real-time TUI (Text User Interface) plotting the continuous metrics in your terminal:
```shell
make dashboard
```
*Note: `make dashboard` starts the continuous monitor and the TPS proxy itself, so it prompts for `sudo` and reconfigures Ollama. See [Usage](#usage).*

![Ollama Monitor Dashboard](img/ollama-monitor-normalized.png)
*Example run of Mixtral 8x7B on an M4 Max with 64GB RAM during regular office load.*

#### High-Density Terminal Rendering & Shell Compatibility

The TUI renders charts using **Unicode Braille patterns (`U+2800`–`U+28FF`, `marker="braille"`)** by default, encoding a `2x4` dot matrix (`8` subpixels) inside every `1 col x 1 char` cell. Compared in the exact same `cols:chars` terminal dimensions:
- **`braille` (`2x4 = 8` subpixels/cell):** **2x** the subpixel resolution and **2x** the vertical resolution of `plotext`'s `hd` quadrant blocks (`2x2 = 4` subpixels/cell), and **8x** the resolution of standard full-block characters (`sd`, `1x1 = 1` cell), with a default `120`-point timeline window (`2x` temporal density over the legacy `60`-point window). Cleanly supported across `zsh`, `bash`, `fish`, `sh`, and `tmux` in any UTF-8 terminal emulator (macOS `Terminal.app`, `iTerm2`, `Ghostty`, `Kitty`, `WezTerm`, `Alacritty`, `xterm`).
- **`fhd` (`2x3 = 6` subpixels/cell):** Unicode 13.0 sextant blocks (`U+1FB00`–`U+1FB3B`); `1.5x` density over `hd`, selectable via `--marker fhd` on terminals with Legacy Computing font glyphs.
- **`hd` (`2x2 = 4` subpixels/cell) & `sd` (`1x1 = 1` cell):** Selectable via `--marker hd` or `--marker sd` for legacy font environments.
- **Dynamic resizing:** The dashboard listens for `SIGWINCH` and dynamically rescales subplots to the live terminal geometry without clamping to startup dimensions.



## Usage

### 1. Benchmark Testing

To run the benchmark, execute the script from your terminal with a run type argument.

```shell
./src/bench_monitor.sh [clean|dirty]
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

### 3. TPS Proxy (Zero-Configuration and safe rollback)

To capture Tokens-Per-Second (TPS) for background API inference, you can start the thin TPS proxy. This will automatically reconfigure your actual Ollama server to run on a background port (`11435`) and place the proxy on the default port (`11434`), allowing your existing client tools to work with zero configuration changes.

> **⚠️ Important Notice Regarding Live TPS Updates:**
> Ollama's API streams generated text continuously, but it **only emits performance statistics (`eval_count` and `eval_duration`) in the very last JSON chunk** when the generation is completely finished.
> Because of this architectural design, the proxy cannot calculate a "live" TPS. The TPS value in the monitor will remain `0` while the model is loading and generating text. You will only see the TPS spike logged at the exact moment the generation finishes.
>
> **Note on Large Models:** If you are running massive models (e.g., a 22B parameter model like Mixtral on a laptop) that spill into system RAM and generate text extremely slowly (e.g., 1 word per minute), you will not see *any* TPS reading until all requested words have finally finished generating, which could take a very long time.

To start the proxy:
```shell
make tps-proxy-start
```
*Note: On Linux, this will require `sudo` to configure systemd.*

To stop the proxy and restore Ollama to its default configuration:
```shell
make tps-proxy-stop
```


## 4. Configuration

### Benchmark Script Configuration

When ran in script mode, it is configured via variables at the top of the file.

-   `MODEL`: The Ollama model tag to benchmark (e.g., `qwen3-coder:30b`).
-   `PROMPT`: The input prompt for the model. As a shortcut, this is a hard-coded zero-shot prompt. For more advanced use cases, this can be externalized to be read from a file or command-line argument.
-   `OUTPUT_DIR`: The directory where benchmark reports and logs are stored.

### TUI Dashboard Configuration (`src/monitor_tui.py`)

Each chart (`cpu`, `gpu`, `ram`, `tps`) supports configurable timeline windows (data points) and refresh intervals (seconds) via CLI flags or environment variables:

```shell
python3 ./src/monitor_tui.py \
  --marker braille \
  --window 120 --tps-window 240 \
  --refresh 1.0 --cpu-refresh 0.5 --ram-refresh 5.0
```

-   `--marker` / `MONITOR_TUI_MARKER`: Sub-character resolution mode (`braille` [default, `2x4`], `fhd` [`2x3`], `hd` [`2x2`], `sd` [`1x1`]).
-   `--window` / `MONITOR_TUI_MAX_POINTS`: Default timeline window in data points across all charts (default: `120`).
-   `--cpu-window`, `--gpu-window`, `--ram-window`, `--tps-window` (or `MONITOR_TUI_<CHART>_WINDOW`): Per-chart timeline window override.
-   `--refresh` / `MONITOR_TUI_REFRESH_INTERVAL`: Default refresh interval in seconds (default: `1.0`).
-   `--cpu-refresh`, `--gpu-refresh`, `--ram-refresh`, `--tps-refresh` (or `MONITOR_TUI_<CHART>_REFRESH`): Per-chart refresh interval override in seconds.

## Output

The script generates the following files in the specified `OUTPUT_DIR`:

-   **Markdown Report** (`benchmark_report_[type]_[timestamp].md`): A detailed report containing performance metrics, system resource usage summaries, and the full model output.
-   **System Metrics CSV** (`system_metrics_[type]_[timestamp].csv`): Raw time-series data of CPU, GPU, and RAM usage during the run.
-   **Summary CSV** (`benchmark_summary.csv`): A log file that appends a summary of each benchmark run, including performance and configuration details.


## Contributing

Requirements: Python 3.10+. The shell scripts require macOS (`powermetrics`, `pmset`).

```shell
make setup   # create .venv and install development dependencies
make test    # run the test suite
```

Work is tracked through GitHub issues and pull requests. Pull requests are required for changes to `main`, and CI must pass.

AI coding agents (Claude, Gemini, Codex, Devin, and others) should read [AGENTS.md](AGENTS.md) before making changes. `CLAUDE.md` and `GEMINI.md` point to the same file.

