# Research: High-Density Terminal Charting Solutions (SOTA 2026)

## 1. Executive Summary

Terminal User Interfaces (TUIs) in 2026 operate across diverse terminal emulators, shells, and remote multiplexers. Traditional terminal charting relied on single character cells (1x1) or half-block characters (1x2 / 2x2), yielding low visual density and jagged lines on modern high-resolution displays.

This research documents terminal graphing approaches across modern shells (`bash`, `zsh`, `fish`) and terminal emulators, analyzing compatibility, resolution gains, and performance to select the canonical State-of-the-Art (SOTA) 2026 solution for `ollama-monitor`.

**Conclusion:** Unicode Braille Patterns (U+2800..U+28FF) provide the canonical host-local solution, delivering a **2x horizontal × 4x vertical (8 subpixels per character cell)** rendering matrix. This **doubles** the effective vertical and overall resolution over half-block baselines in the exact same `cols:chars` footprint with zero external dependencies and universal compatibility.

---

## 2. Shell and Terminal Compatibility Analysis

Terminal rendering occurs over standard stdout streams via UTF-8 encoding and ANSI/VT escape sequences. The shell (`bash`, `zsh`, `fish`) acts as an interactive command processor and environment manager; the terminal emulator and underlying monospaced font govern graphical display and character rendering.

| Terminal Emulator | Platform | Braille (U+2800) | Sextant (U+1FB00) | Half-Blocks (HD) | Kitty Graphics | Sixel Graphics |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Apple Terminal.app** | macOS | ✅ Full | ⚠️ Font-dependent | ✅ Full | ❌ Unsupported | ❌ Unsupported |
| **iTerm2** | macOS | ✅ Full | ✅ Full | ✅ Full | ⚠️ Third-party | ✅ Full |
| **Ghostty** | macOS / Linux | ✅ Full | ✅ Full | ✅ Full | ✅ Native | ⚠️ Partial |
| **Kitty** | macOS / Linux | ✅ Full | ✅ Full | ✅ Full | ✅ Native | ❌ Unsupported |
| **WezTerm** | macOS / Linux / Win | ✅ Full | ✅ Full | ✅ Full | ✅ Native | ✅ Full |
| **Alacritty** | macOS / Linux / Win | ✅ Full | ✅ Full | ✅ Full | ❌ Unsupported | ❌ Unsupported |
| **tmux / screen** | All (Multiplexer) | ✅ Passthrough | ✅ Passthrough | ✅ Passthrough | ⚠️ Needs passthru | ⚠️ Needs passthru |

### Shell Compatibility (`bash`, `zsh`, `fish`)
- All modern POSIX and non-POSIX shells transparently pass UTF-8 byte sequences for Unicode Braille patterns.
- Signals (`SIGWINCH` for terminal resize, `SIGINT` for clean termination) are handled consistently across shells.
- Resizing events dynamically trigger `plotext.terminal_size()` recalculations, adapting plot bounds without restarting the process.

---

## 3. Comparison of Rendering Techniques

### A. Unicode Braille Patterns (`braille`) — Canonical SOTA Choice
- **Mechanism:** Unicode characters U+2800 through U+28FF encode an 8-dot matrix (2 columns × 4 rows) within a single character cell.
- **Resolution Gain:** 
  - Subpixels per cell: **8** (2 × 4)
  - Baseline half-block (`hd`): **4** (2 × 2)
  - Standard character (`sd`): **1** (1 × 1)
  - **Resolution Multiplier:** **2.0x vs HD (doubling resolution)**, **8.0x vs SD**.
- **Pros:**
  - Universal font support (SF Mono, Menlo, JetBrains Mono, Fira Code, DejaVu Sans Mono).
  - Zero external GUI or IPC dependencies; host-local terminal execution.
  - Native SSH and tmux compatibility.
  - Negligible CPU and memory overhead during streaming redraws.
- **Cons:** Dot patterns rather than solid continuous area fills (ideal for line plots).

### B. Unicode 13 Legacy Computing Sextants (`fhd`)
- **Mechanism:** Unicode block characters (U+1FB00–U+1FB3B) representing a 2×3 grid.
- **Resolution:** 6 subpixels per cell (1.5x vs HD).
- **Cons:** Inconsistent font fallback on older macOS / Linux distributions, resulting in missing glyph boxes.

### C. Half-Blocks (`hd` — Original Baseline)
- **Mechanism:** Top half `▀` (U+2580), bottom half `▄` (U+2584), full block `█` (U+2588).
- **Resolution:** 4 subpixels per cell (2×2).
- **Cons:** Coarse stair-stepping on fast transitions (e.g. sharp TPS spikes).

### D. Pixel Graphics Protocols (Kitty / Sixel / iTerm2 OSC 1337)
- **Mechanism:** Transferring raster bitmaps over escape codes.
- **Why Rejected:** 
  - Violates portability: Apple Terminal.app (the macOS default) does not support Kitty or Sixel graphics.
  - Significant overhead when serializing frames at 1Hz in remote sessions.
  - Explicitly out of scope per issue criteria (must remain host-local, shell-agnostic TUI).

---

## 4. Implementation Details

In `src/monitor_tui.py`:

1. **High-Density Braille Marker:**
   - Default plot marker set to `braille`, doubling vertical resolution from 2 to 4 dots per row and doubling total subpixel density from 4 to 8 dots per cell.
   - Selectable fallback density modes via `--density` (`braille`, `fhd`, `hd`, `sd`).

2. **Per-Chart Configurable Density:**
   - Override density individually: `--cpu-density`, `--gpu-density`, `--ram-density`, `--tps-density`.

3. **Per-Chart Configurable Timeline History:**
   - Configure timeline points per chart: `--cpu-timeline`, `--gpu-timeline`, `--ram-timeline`, `--tps-timeline` (e.g., long window for RAM, short high-frequency window for TPS).

4. **Per-Chart Configurable Refresh Rate:**
   - Decoupled refresh intervals per chart: `--cpu-refresh`, `--gpu-refresh`, `--ram-refresh`, `--tps-refresh` (e.g., fast 1s refresh for TPS/CPU, slower 5s or 10s refresh for RAM).
   - Retains cached rendered data when a chart's refresh interval has not elapsed, minimizing redundant calculations and flickering.

5. **Terminal Resizing:**
   - `plt.plotsize(w, h - 3)` dynamically samples `plt.terminal_size()` on every draw call to adapt to window resize events in real time.
