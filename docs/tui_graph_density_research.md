# Research: Terminal Graph Density & SOTA 2026 TUI Solutions

## 1. Executive Summary

This research evaluates approaches to significantly increase the resolution and data density of terminal charts in `ollama-monitor`'s TUI without migrating to heavy GUI frameworks, external web UIs, or breaking compatibility with host-local terminal environments.

The current implementation utilizes `plotext` with default half-block rendering (`hd`), providing a 2×2 subpixel grid (4 subpixels per character cell). By transitioning to **Unicode Braille Patterns (U+2800..U+28FF)** as the default plotting marker, the vertical resolution is **doubled** (4 vertical subpixels vs 2), and the total subpixel density per character cell is **doubled** (8 subpixels vs 4). When compared to standard single-character block plotting (`sd`), Braille achieves an **8× density increase** in the exact same column and row footprint.

Furthermore, decoupling timeline windows and refresh rates across individual charts enables tailored temporal resolution for high-frequency metrics (e.g., Tokens Per Second spikes, GPU activity) versus slow-moving metrics (e.g., RAM footprint).

---

## 2. Terminal Charting Paradigms (SOTA 2026)

### 2.1 Standard Block Characters (1×1 Density)
- **Codepoints:** U+2588 (Full Block `█`), standard ASCII (`*`, `+`, `#`).
- **Effective Resolution:** 1 horizontal point × 1 vertical point per terminal cell.
- **Pros:** 100% universal compatibility across ancient teletypes, dumb terminals, and non-UTF-8 legacy environments.
- **Cons:** Stepped, coarse, low-information graphs that waste display area on modern retina/4K displays.

### 2.2 Half-Block and Quadrant Elements (2×2 Density)
- **Codepoints:** U+2580 (`▀`), U+2584 (`▄`), quadrants U+2596..U+259F (`▖▗▘▙▚▛▜▝▞▟`).
- **Effective Resolution:** 2 horizontal × 2 vertical subpixels = 4 subpixels per character cell.
- **Pros:** Native Unicode 1.0 support across virtually all modern terminals.
- **Cons:** Curve lines still exhibit 2-step stepping; fine inflections in TPS or power measurements are lost in low terminal heights.

### 2.3 Unicode 13.0 Sextants (2×3 Density)
- **Codepoints:** Symbols for Legacy Computing (U+1FB00..U+1FB3B, e.g., `🬀🬁🬂...🬭🬮🬯`).
- **Effective Resolution:** 2 horizontal × 3 vertical subpixels = 6 subpixels per character cell (1.5× density over half-blocks).
- **Pros:** Finer vertical slicing than half-blocks while retaining solid fill aesthetics.
- **Cons:** Incomplete font coverage. Default system fonts on older macOS (Terminal.app with Menlo/Monaco) and many enterprise Linux distributions lack Unicode 13.0 glyphs, rendering empty boxes or question marks.

### 2.4 Unicode Braille Patterns (2×4 Density — Selected Solution)
- **Codepoints:** Unicode Braille Patterns block (U+2800..U+28FF, 256 code points).
- **Dot Matrix:** Each cell is arranged in a 2-column by 4-row matrix:
  ```
  Dot 1 (left top)     ●  ● Dot 4 (right top)
  Dot 2                ●  ● Dot 5
  Dot 3                ●  ● Dot 6
  Dot 7 (left bottom)  ●  ● Dot 8 (right bottom)
  ```
- **Effective Resolution:** 2 horizontal × 4 vertical dots = **8 subpixels per character cell**.
- **Density Comparison:**
  - **vs Standard (1×1):** 8× resolution.
  - **vs Half-block `hd` (2×2):** Exactly **2× resolution** (4 vertical subpixels vs 2, 8 total vs 4).
- **Adoption:** Canonical standard for modern CLI/TUI observability tools including `bottom` (btm), `glances`, `drawille`, and `viddy`.
- **Pros:** Supported across all major fonts (Monaco, Menlo, SF Mono, DejaVu, JetBrains Mono, Cascadia Code) and terminal emulators without font patching or protocol dependencies.

### 2.5 Terminal Graphics Protocols (Kitty, Sixel, iTerm2)
- **Protocols:** Kitty Graphics Protocol, DEC Sixel graphics, iTerm2 inline image protocol.
- **Effective Resolution:** Pixel-perfect framebuffer rendering within terminal panes.
- **Evaluation:**
  - Incompatible with standard macOS Terminal.app (no Sixel or Kitty support out-of-the-box).
  - Fragile over nested SSH, `tmux`, and CI runners.
  - Excluded by the issue specification's constraint against non-standard or heavyweight solutions.

---

## 3. Shell and Terminal Compatibility Matrix

| Terminal / Shell | UTF-8 Braille (2×4) | Half-Block (2×2) | Sextants (2×3) | Sixel / Protocol |
|---|---|---|---|---|
| **macOS Terminal.app** (zsh/bash) | **Full Support** | Full Support | Font dependent (often missing) | Unsupported |
| **iTerm2** (macOS) | **Full Support** | Full Support | Full Support (modern fonts) | Proprietary protocol / Sixel |
| **Kitty / WezTerm / Ghostty** | **Full Support** | Full Support | Full Support | Protocol support |
| **Alacritty** (macOS / Linux) | **Full Support** | Full Support | Font dependent | Unsupported |
| **GNOME Terminal / Ptyxis** (Linux) | **Full Support** | Full Support | Font dependent | Limited |
| **tmux / screen** | **Full Support** | Full Support | Full Support | Requires passthrough config |
| **Ubuntu CI (headless Linux)** | **Full Support** | Full Support | Fallback required | Headless framebuffer needed |

*Conclusion:* Unicode Braille is the highest-density graphing representation with universal out-of-the-box compatibility across all shells and terminal emulators on macOS and Linux.

---

## 4. Architecture & Implementation Design

### 4.1 Resolution Doubling via Braille Marker
In `plotext`, each signal plotted on a canvas computes its subpixel factors via `marker_factor`:
- `marker="hd"`: `xf = 2`, `yf = 2` -> canvas height = `2 * H`
- `marker="braille"`: `xf = 2`, `yf = 4` -> canvas height = `4 * H`

By setting `DEFAULT_MARKER = "braille"` across all charts:
- Vertical plotting resolution doubles from 2 to 4 levels per row.
- Total subpixel addressability doubles from 4 to 8 dots per cell.
- Smooth gradients, fine inflection points, and sudden spikes in TPS are visibly distinct.

### 4.2 Decoupled Per-Chart Timeline Windows
Hardware metrics differ fundamentally in temporal velocity:
- **Tokens Per Second (TPS):** Burst-heavy during inference, requires fine-grained recent observation (e.g., 30–60s).
- **GPU Load:** Rapid active residency transitions (e.g., 60s).
- **RAM Usage:** Memory allocations (model weight loading and KV-cache allocation) are persistent and slow-moving, benefiting from wider observation windows (e.g., 120–300s).

The implementation introduces:
- Independent timeline lengths per chart (`cpu`, `gpu`, `ram`, `tps`).
- Flexible CLI (`--timeline`, `--timeline-cpu`, `--timeline-gpu`, `--timeline-ram`, `--timeline-tps`) and environment variable configuration (`TIMELINE_POINTS`, `TIMELINE_CPU`, etc.).
- Efficient CSV ingestion fetching `max(timeline.values())` rows to satisfy all chart windows simultaneously.

### 4.3 Decoupled Per-Chart Refresh Intervals
Different metrics do not need to poll or redraw at identical frequencies:
- Rapid metrics (`cpu`, `gpu`, `tps`) refresh on 1.0s ticks.
- Stable metrics (`ram`) can update on slower intervals (e.g., 2.0s or 5.0s) to minimize unnecessary redraws.
- Each chart maintains its own cache and update timestamp; charts whose interval has not yet elapsed retain their current display slice, preventing visual churn.

### 4.4 Dynamic Terminal Resizing & Layout Protection
- Queries terminal dimensions dynamically via `plt.terminal_size()`.
- Constrains layout to `plt.plotsize(w, h - 3)` with safe lower bounds to prevent terminal scrolling or model header truncation on narrow/short viewports.
