#!/usr/bin/env python3
import argparse
import copy
import os
import shutil
import signal
import sys
import time

try:
    import plotext as plt
except ImportError:
    print("plotext is not installed. Run: pip install plotext")
    sys.exit(1)

CSV_FILE = "benchmark_data/continuous_monitor.csv"
MAX_POINTS = 120  # Show last 120 seconds of data by default (2x timeline capacity)
DEFAULT_MARKER = "braille"
DEFAULT_RESOLUTION_FACTOR = 2

# Subpixel matrix dimensions (cols_per_cell, rows_per_cell) per terminal character cell
SUBPIXEL_RESOLUTION = {
    "sd": (1, 1),
    "hd": (2, 2),
    "fhd": (2, 3),
    "braille": (2, 4),
}

CHART_KEYS = ("cpu", "gpu", "ram", "tps")

DEFAULT_CHART_CONFIGS = {
    "cpu": {
        "title": "CPU Usage (%)",
        "color": "blue",
        "ylim": (0, 100),
        "refresh_interval": 1.0,
        "window": MAX_POINTS,
        "subplot": (1, 1),
    },
    "gpu": {
        "title": "GPU Load (%)",
        "color": "red",
        "ylim": (0, 100),
        "refresh_interval": 1.0,
        "window": MAX_POINTS,
        "subplot": (1, 2),
    },
    "ram": {
        "title": "RAM Used (GB)",
        "color": "green",
        "ylim": None,
        "refresh_interval": 1.0,
        "window": MAX_POINTS,
        "subplot": (2, 1),
    },
    "tps": {
        "title": "Tokens Per Second (TPS)",
        "color": "magenta",
        "ylim": None,
        "refresh_interval": 1.0,
        "window": MAX_POINTS,
        "subplot": (2, 2),
    },
}

CHART_REFRESH_STATE = {}
RESIZE_PENDING = False


def get_subpixel_density(marker=DEFAULT_MARKER):
    """Return (subpixels_x, subpixels_y, subpixels_per_cell) for a plotext marker."""
    sub_x, sub_y = SUBPIXEL_RESOLUTION.get(marker, (1, 1))
    return sub_x, sub_y, sub_x * sub_y


def calculate_effective_resolution(cols, rows, marker=DEFAULT_MARKER):
    """Return effective (width_subpixels, height_subpixels, total_subpixels) for terminal cols x rows."""
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    sub_x, sub_y, _ = get_subpixel_density(marker)
    width_px = cols * sub_x
    height_px = rows * sub_y
    return width_px, height_px, width_px * height_px


def upsample_series(times, values=None, factor=DEFAULT_RESOLUTION_FACTOR):
    """Linearly upsample time series values by `factor` to leverage subpixel character density."""
    if values is None:
        values = list(times)
        times = [str(i) for i in range(len(values))]

    n = min(len(times), len(values))
    if n == 0:
        return [], []

    times_slice = list(times[:n])
    values_slice = [float(v) for v in values[:n]]

    factor = int(factor) if factor is not None else 1
    if n == 1 or factor <= 1:
        return times_slice, values_slice

    upsampled_times = []
    upsampled_values = []
    numeric_times = all(isinstance(t, (int, float)) for t in times_slice)

    for i in range(n - 1):
        v0 = values_slice[i]
        v1 = values_slice[i + 1]
        t0 = times_slice[i]
        t1 = times_slice[i + 1]
        for step in range(factor):
            frac = step / factor
            upsampled_values.append(v0 + (v1 - v0) * frac)
            if numeric_times:
                upsampled_times.append(t0 + (t1 - t0) * frac)
            else:
                upsampled_times.append(t0)

    upsampled_times.append(times_slice[-1])
    upsampled_values.append(values_slice[-1])
    return upsampled_times, upsampled_values


def compute_xticks(times, term_width=80, max_ticks=None):
    """Compute adaptive x-axis tick indices and labels scaled to terminal width to prevent overlap."""
    n = len(times)
    if n == 0:
        return [], []
    if n == 1:
        return [0], [times[0]]

    if max_ticks is None:
        subplot_width = max(16, int(term_width) // 2)
        max_ticks = max(2, min(8, subplot_width // 12))
    else:
        max_ticks = max(2, int(max_ticks))

    if n <= max_ticks:
        return list(range(n)), list(times)

    indices = []
    for i in range(max_ticks):
        idx = round(i * (n - 1) / (max_ticks - 1))
        if not indices or idx != indices[-1]:
            indices.append(idx)

    labels = [times[idx] for idx in indices]
    return indices, labels


def handle_sigwinch(signum, frame):
    """Signal handler for terminal window resize (SIGWINCH)."""
    global RESIZE_PENDING
    RESIZE_PENDING = True


def consume_resize_event():
    """Return True and clear flag if a terminal resize signal was received."""
    global RESIZE_PENDING
    if RESIZE_PENDING:
        RESIZE_PENDING = False
        return True
    return False


def register_resize_handler(handler=None):
    """Register SIGWINCH handler if supported by the current platform and thread."""
    if not hasattr(signal, "SIGWINCH"):
        return False
    try:
        signal.signal(signal.SIGWINCH, handler or handle_sigwinch)
        return True
    except (ValueError, OSError):
        return False


def get_terminal_dimensions(default_width=120, default_height=36, min_width=40, min_height=12):
    """Safely query current terminal dimensions with fallback and minimum bounds."""
    w, h = None, None
    try:
        size = plt.terminal_size()
        if size and len(size) >= 2:
            w, h = size[0], size[1]
    except Exception:
        w, h = None, None

    if not w or not h:
        fallback = shutil.get_terminal_size((default_width, default_height))
        w = w or fallback.columns
        h = h or fallback.lines

    return max(min_width, int(w)), max(min_height, int(h))


def get_chart_configs(overrides=None, default_window=None, default_refresh=1.0):
    """Build normalized per-chart configuration dictionary."""
    base_window = MAX_POINTS if default_window is None else max(1, int(default_window))
    base_refresh = max(0.05, float(default_refresh))
    configs = copy.deepcopy(DEFAULT_CHART_CONFIGS)
    for key in CHART_KEYS:
        configs[key]["window"] = base_window
        configs[key]["refresh_interval"] = base_refresh
        if overrides and key in overrides and isinstance(overrides[key], dict):
            configs[key].update(overrides[key])
            configs[key]["window"] = max(1, int(configs[key].get("window", base_window)))
            configs[key]["refresh_interval"] = max(
                0.0, float(configs[key].get("refresh_interval", base_refresh))
            )
    return configs


def should_refresh_chart(chart_key, chart_config, refresh_state, now, force=False):
    """Determine whether `chart_key` is due for a timeline data refresh at timestamp `now`."""
    if force:
        return True
    entry = refresh_state.get(chart_key)
    if not entry or entry.get("last_refresh") is None:
        return True
    interval = max(0.0, float(chart_config.get("refresh_interval", 1.0)))
    return (now - entry["last_refresh"]) >= interval


def update_chart_timelines(
    times,
    series_by_chart,
    chart_configs=None,
    refresh_state=None,
    now=None,
    force=False,
):
    """Update per-chart cached timeline series for due charts while preserving non-due charts."""
    configs = get_chart_configs(chart_configs)
    state = CHART_REFRESH_STATE if refresh_state is None else refresh_state
    current_time = time.monotonic() if now is None else float(now)

    for key in CHART_KEYS:
        cfg = configs[key]
        window = max(1, int(cfg.get("window", MAX_POINTS)))
        entry = state.setdefault(key, {"last_refresh": None, "times": [], "values": []})

        if should_refresh_chart(key, cfg, state, current_time, force=force):
            raw_values = list(series_by_chart.get(key, []))
            entry["times"] = list(times[-window:])
            entry["values"] = list(raw_values[-window:])
            entry["last_refresh"] = current_time

    return state


def read_data(max_points=None):
    if not os.path.exists(CSV_FILE):
        return [], [], [], [], [], "None", "None"

    try:
        with open(CSV_FILE, "r") as f:
            lines = f.readlines()[1:]  # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    limit = MAX_POINTS if max_points is None else max(1, int(max_points))
    lines = lines[-limit:]

    times = []
    cpu = []
    gpu = []
    ram = []
    tps = []
    last_model_name = "None"
    last_model_meta = "None"

    for line in lines:
        parts = line.strip().split(",")
        if len(parts) >= 5:
            t, c, g, r, p = parts[:5]
            try:
                times.append(t)
                cpu.append(float(c))
                gpu.append(float(g))
                ram.append(float(r))
                tps.append(float(p))
            except ValueError:
                continue

            if len(parts) >= 7:
                last_model_name = parts[5]
                last_model_meta = parts[6]

    return times, cpu, gpu, ram, tps, last_model_name, last_model_meta


def draw_dashboard(
    chart_configs=None,
    refresh_state=None,
    now=None,
    marker=DEFAULT_MARKER,
    resolution_factor=DEFAULT_RESOLUTION_FACTOR,
    force_refresh=False,
):
    plt.clear_terminal()
    plt.theme("clear")

    configs = get_chart_configs(chart_configs)
    max_window = max(MAX_POINTS, max(cfg["window"] for cfg in configs.values()))

    if max_window == MAX_POINTS:
        times, cpu, gpu, ram, tps, model_name, model_meta = read_data()
    else:
        times, cpu, gpu, ram, tps, model_name, model_meta = read_data(max_points=max_window)

    if not times:
        print(f"Waiting for data in {CSV_FILE}...")
        return

    # Render Top Row Outlook
    if model_name != "None":
        print(f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n")
    else:
        print("\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n")

    consume_resize_event()

    series_by_chart = {"cpu": cpu, "gpu": gpu, "ram": ram, "tps": tps}
    effective_force = force_refresh or (refresh_state is None and now is None)
    state = update_chart_timelines(
        times,
        series_by_chart,
        chart_configs=configs,
        refresh_state=refresh_state,
        now=now,
        force=effective_force,
    )

    # Adjust plot size to prevent terminal from scrolling and overwriting the top text
    w, h = 120, 36
    try:
        w, h = get_terminal_dimensions()
        plt.plotsize(w, max(8, h - 3))
    except Exception:
        pass

    plt.subplots(2, 2)

    for key in CHART_KEYS:
        cfg = configs[key]
        row, col = cfg["subplot"]
        chart_times = state[key]["times"]
        chart_values = state[key]["values"]

        dense_times, dense_values = upsample_series(
            chart_times, chart_values, factor=resolution_factor
        )
        x = list(range(len(dense_values)))
        tick_indices, tick_labels = compute_xticks(dense_times, term_width=w)

        plt.subplot(row, col)
        plt.title(cfg["title"])
        plt.plot(x, dense_values, color=cfg["color"], marker=marker)
        if cfg.get("ylim") is not None:
            plt.ylim(*cfg["ylim"])
        plt.xticks(tick_indices, tick_labels)

    plt.show()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="High-density terminal dashboard for Ollama continuous monitoring"
    )
    parser.add_argument(
        "--csv-file",
        default=CSV_FILE,
        help=f"Path to continuous monitor CSV (default: {CSV_FILE})",
    )
    parser.add_argument(
        "--marker",
        choices=list(SUBPIXEL_RESOLUTION.keys()),
        default=DEFAULT_MARKER,
        help=f"Plotext subpixel marker mode (default: {DEFAULT_MARKER})",
    )
    parser.add_argument(
        "--resolution-factor",
        type=int,
        default=DEFAULT_RESOLUTION_FACTOR,
        help=f"Series upsampling factor for subpixel rendering (default: {DEFAULT_RESOLUTION_FACTOR})",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=MAX_POINTS,
        help=f"Default timeline window in data points (default: {MAX_POINTS})",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=1.0,
        help="Default timeline refresh interval in seconds across charts (default: 1.0)",
    )
    for key in CHART_KEYS:
        parser.add_argument(
            f"--{key}-refresh",
            type=float,
            default=None,
            help=f"Refresh interval in seconds for {key.upper()} chart",
        )
        parser.add_argument(
            f"--{key}-window",
            type=int,
            default=None,
            help=f"Timeline window size (points) for {key.upper()} chart",
        )
    return parser.parse_args(argv)


def build_chart_configs_from_args(args):
    overrides = {}
    for key in CHART_KEYS:
        chart_override = {}
        refresh_val = getattr(args, f"{key}_refresh", None)
        window_val = getattr(args, f"{key}_window", None)
        if refresh_val is not None:
            chart_override["refresh_interval"] = refresh_val
        if window_val is not None:
            chart_override["window"] = window_val
        if chart_override:
            overrides[key] = chart_override

    return get_chart_configs(
        overrides=overrides,
        default_window=getattr(args, "max_points", MAX_POINTS),
        default_refresh=getattr(args, "refresh_interval", 1.0),
    )


def main(argv=None):
    global CSV_FILE, MAX_POINTS
    args = parse_args(argv)
    CSV_FILE = args.csv_file
    MAX_POINTS = max(1, int(args.max_points))
    chart_configs = build_chart_configs_from_args(args)
    refresh_state = {}

    register_resize_handler()
    min_interval = min(cfg["refresh_interval"] for cfg in chart_configs.values())
    poll_step = max(0.1, min(0.5, min_interval))

    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            draw_dashboard(
                chart_configs=chart_configs,
                refresh_state=refresh_state,
                now=time.monotonic(),
                marker=args.marker,
                resolution_factor=args.resolution_factor,
            )
            elapsed = 0.0
            while elapsed < min_interval:
                if RESIZE_PENDING:
                    break
                time.sleep(poll_step)
                elapsed += poll_step
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()
