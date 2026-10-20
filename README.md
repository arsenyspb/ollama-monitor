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

### High-Density TUI & Per-Chart Timeline Configuration

`src/monitor_tui.py` renders a 2x2 grid (`CPU`, `GPU`, `RAM`, `TPS`) using Unicode Braille (`2x4` subpixels per character cell) with linear series upsampling (`--resolution-factor 2` by default) and a default 120-point timeline window (`MAX_POINTS = 120`), doubling effective subpixel density and vertical resolution within the exact same terminal `cols:chars` as standard quadrant (`hd`) rendering.

You can customize the subpixel marker, upsampling factor, and per-chart timeline refresh intervals and window sizes via CLI flags:

```shell
./src/monitor_tui.py \
  --marker braille \
  --resolution-factor 2 \
  --max-points 120 \
  --refresh-interval 1.0 \
  --cpu-refresh 0.5 --cpu-window 120 \
  --gpu-refresh 1.0 --gpu-window 120 \
  --ram-refresh 5.0 --ram-window 240 \
  --tps-refresh 1.0 --tps-window 120
```

-   `--marker {sd,hd,fhd,braille}`: Subpixel character cell matrix mode (default: `braille` for `2x4` = 8 subpixels/cell).
-   `--resolution-factor N`: Subpixel curve upsampling factor between consecutive samples (default: `2`).
-   `--max-points N`: Default timeline capacity in points across charts (default: `120`).
-   `--refresh-interval SEC`: Default timeline refresh period in seconds (default: `1.0`).
-   `--<chart>-refresh SEC` (`--cpu-refresh`, `--gpu-refresh`, `--ram-refresh`, `--tps-refresh`): Independently control how often each chart refreshes its timeline series; non-due charts retain their cached series between refreshes.
-   `--<chart>-window N` (`--cpu-window`, `--gpu-window`, `--ram-window`, `--tps-window`): Independently configure how many historical data points are plotted in each chart's timeline window.
-   **Dynamic Terminal Resizing:** The TUI listens for `SIGWINCH` events to trigger immediate redraws on terminal resize and adaptively decimates x-axis timestamp ticks (`compute_xticks`) based on current terminal width so labels never collide.

### Terminal Charting & Subpixel Density Research

To at least double chart resolution in the same terminal `cols:chars` without introducing external GUI or web dependencies, we evaluated terminal charting approaches across common shells (`zsh`, `bash`, `fish`) and terminal emulators (macOS Terminal.app, iTerm2, Ghostty, Kitty, WezTerm, Alacritty, xterm, and `tmux`/`screen` multiplexers):

| Rendering Mode | Unicode Block / Protocol | Subpixel Matrix (Cols × Rows) | Subpixels / Cell | Density vs `hd` (`2×2`) | Shell & Emulator Portability |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Standard (`sd`)** | ASCII / full block (`U+2588`) | `1 × 1` | 1 | `0.25×` | Universal |
| **Quadrant (`hd`)** | Block Elements (`U+2596`–`U+259F`) | `2 × 2` | 4 | `1.0×` (baseline) | Universal UTF-8 terminals |
| **Sextant (`fhd`)** | Symbols for Legacy Computing (`U+1FB00`–`U+1FB3B`) | `2 × 3` | 6 | `1.5×` | Missing glyphs in several default system fonts; does not reach `2×` density |
| **Braille (`braille`)** | Unicode Braille Patterns (`U+2800`–`U+28FF`) | `2 × 4` | **8** | **`2.0×`** (`8.0×` vs `sd`) | Universal across macOS/Linux UTF-8 terminals, SSH, and `tmux` |
| **Pixel Protocols** | Sixel / Kitty Graphics / iTerm2 `osc 1337` | Arbitrary | Pixel-level | N/A | Emulator-specific; breaks or requires passthrough in `tmux`, SSH, and macOS Terminal.app |

**Selected Solution (`braille` + series upsampling):**
- Switching the default `plotext` marker from `hd` (`2×2` = 4 subpixels/cell) to `braille` (`2×4` = 8 subpixels/cell) doubles the vertical subpixel resolution and doubles total subpixel density in identical `cols:chars` (e.g., an `80×24` terminal canvas expands from `160×48` = 7,680 subpixels to `160×96` = 15,360 subpixels).
- Combining `braille` rendering with linear series upsampling (`upsample_series`) and doubling `MAX_POINTS` from `60` to `120` produces smooth, continuous high-density curves across all standard UTF-8 shells and multiplexers.


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

