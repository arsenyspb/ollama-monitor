#!/usr/bin/env python3
import argparse
import os
import sys
import time

try:
    import plotext as plt
except ImportError:
    print("plotext is not installed. Run: pip install plotext")
    sys.exit(1)

CSV_FILE = "benchmark_data/continuous_monitor.csv"
MAX_POINTS = int(os.environ.get("OLLAMA_TUI_MAX_POINTS", "120"))  # Doubled default timeline capacity
DEFAULT_MARKER = os.environ.get("OLLAMA_TUI_MARKER", "braille")  # 2x4 sub-pixel braille matrix (8 subpixels/cell)
RESOLUTION_FACTOR = int(os.environ.get("OLLAMA_TUI_DENSITY_FACTOR", "2"))  # Sub-step series interpolation factor
DEFAULT_REFRESH_INTERVAL = float(os.environ.get("OLLAMA_TUI_REFRESH", "1.0"))

MARKER_SUBPIXELS = {
    "sd": (1, 1),
    "dot": (1, 1),
    "hd": (2, 2),
    "fhd": (2, 3),
    "braille": (2, 4),
}

CHART_KEYS = ("cpu", "gpu", "ram", "tps")

CHART_REFRESH_INTERVALS = {
    "cpu": DEFAULT_REFRESH_INTERVAL,
    "gpu": DEFAULT_REFRESH_INTERVAL,
    "ram": DEFAULT_REFRESH_INTERVAL,
    "tps": DEFAULT_REFRESH_INTERVAL,
}

CHART_TIMELINE_POINTS = {
    "cpu": MAX_POINTS,
    "gpu": MAX_POINTS,
    "ram": MAX_POINTS,
    "tps": MAX_POINTS,
}

_REFRESH_STATE = {
    "csv_file": CSV_FILE,
    "last_refresh": {k: None for k in CHART_KEYS},
    "series": {k: ([], []) for k in CHART_KEYS},
}


def reset_refresh_state():
    _REFRESH_STATE["csv_file"] = CSV_FILE
    _REFRESH_STATE["last_refresh"] = {k: None for k in CHART_KEYS}
    _REFRESH_STATE["series"] = {k: ([], []) for k in CHART_KEYS}


def get_marker_subpixels(marker=DEFAULT_MARKER):
    return MARKER_SUBPIXELS.get(marker, (1, 1))


def get_chart_resolution(cols, rows, marker=DEFAULT_MARKER, density_factor=RESOLUTION_FACTOR):
    xf, yf = get_marker_subpixels(marker)
    safe_cols = max(0, int(cols))
    safe_rows = max(0, int(rows))
    x_subpixels = safe_cols * xf
    y_subpixels = safe_rows * yf
    return {
        "cols": safe_cols,
        "rows": safe_rows,
        "marker": marker,
        "x_factor": xf,
        "y_factor": yf,
        "subpixels_per_cell": xf * yf,
        "x_subpixels": x_subpixels,
        "y_subpixels": y_subpixels,
        "total_subpixels": x_subpixels * y_subpixels,
        "density_factor": max(1, int(density_factor)),
    }


def upsample_series(x, y, factor=RESOLUTION_FACTOR):
    if len(x) != len(y):
        raise ValueError("x and y series must have the same length")
    if len(x) < 2 or factor is None or int(factor) <= 1:
        return [float(v) for v in x], [float(v) for v in y]

    step_factor = int(factor)
    ux = []
    uy = []
    for i in range(len(x) - 1):
        x0, x1 = float(x[i]), float(x[i + 1])
        y0, y1 = float(y[i]), float(y[i + 1])
        for step in range(step_factor):
            ratio = step / step_factor
            ux.append(x0 + (x1 - x0) * ratio)
            uy.append(y0 + (y1 - y0) * ratio)
    ux.append(float(x[-1]))
    uy.append(float(y[-1]))
    return ux, uy


def build_timeline_ticks(x, times, max_ticks=5):
    n = min(len(x), len(times))
    if n == 0:
        return [], []
    max_ticks = max(1, int(max_ticks))
    if n <= max_ticks or max_ticks == 1:
        indices = list(range(n)) if n <= max_ticks else [n - 1]
    else:
        indices = []
        for i in range(max_ticks):
            idx = round(i * (n - 1) / (max_ticks - 1))
            if idx not in indices:
                indices.append(idx)
    return [x[idx] for idx in indices], [times[idx] for idx in indices]


def should_refresh_chart(chart_key, now, interval):
    last = _REFRESH_STATE["last_refresh"].get(chart_key)
    cached_times, _ = _REFRESH_STATE["series"].get(chart_key, ([], []))
    if last is None or not cached_times:
        return True
    if interval is None or float(interval) <= 0:
        return True
    return (float(now) - float(last)) >= (float(interval) - 1e-9)


def get_loop_sleep_interval(refresh_intervals=None):
    intervals = CHART_REFRESH_INTERVALS.copy()
    if refresh_intervals:
        intervals.update(refresh_intervals)
    positive = [float(v) for v in intervals.values() if v is not None and float(v) > 0]
    return min(positive) if positive else DEFAULT_REFRESH_INTERVAL


def read_data(max_points=None):
    if not os.path.exists(CSV_FILE):
        return [], [], [], [], [], "None", "None"

    try:
        with open(CSV_FILE, "r") as f:
            lines = f.readlines()[1:]  # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    limit = MAX_POINTS if max_points is None else int(max_points)
    lines = lines[-limit:] if limit > 0 else []

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
    now=None,
    refresh_intervals=None,
    timeline_points=None,
    marker=None,
    density_factor=None,
):
    if _REFRESH_STATE.get("csv_file") != CSV_FILE:
        reset_refresh_state()

    plt.clear_terminal()
    plt.theme("clear")

    intervals = CHART_REFRESH_INTERVALS.copy()
    if refresh_intervals:
        intervals.update(refresh_intervals)

    windows = {k: CHART_TIMELINE_POINTS.get(k, MAX_POINTS) for k in CHART_KEYS}
    if timeline_points:
        windows.update(timeline_points)

    max_window = max([MAX_POINTS] + [int(v) for v in windows.values() if v is not None])
    times, cpu, gpu, ram, tps, model_name, model_meta = read_data(max_points=max_window)

    if not times:
        print(f"Waiting for data in {CSV_FILE}...")
        return

    # Render Top Row Outlook
    if model_name != "None":
        print(f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n")
    else:
        print("\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n")

    current_time = time.monotonic() if now is None else float(now)
    active_marker = DEFAULT_MARKER if marker is None else marker
    active_density = RESOLUTION_FACTOR if density_factor is None else int(density_factor)

    raw_by_chart = {
        "cpu": cpu,
        "gpu": gpu,
        "ram": ram,
        "tps": tps,
    }

    for key in CHART_KEYS:
        if should_refresh_chart(key, current_time, intervals.get(key)):
            win = max(1, int(windows.get(key, MAX_POINTS)))
            _REFRESH_STATE["series"][key] = (
                list(times[-win:]),
                list(raw_by_chart[key][-win:]),
            )
            _REFRESH_STATE["last_refresh"][key] = current_time

    # Adjust plot size dynamically to terminal dimensions and compute tick density
    max_ticks = 5
    try:
        w, h = plt.terminal_size()
        plt.plotsize(w, h - 3)
        if w and w > 0:
            max_ticks = max(2, min(6, (w // 2) // 12))
    except Exception:
        pass

    plt.subplots(2, 2)

    chart_specs = [
        (1, 1, "cpu", "CPU Usage (%)", "blue", (0, 100)),
        (1, 2, "gpu", "GPU Load (%)", "red", (0, 100)),
        (2, 1, "ram", "RAM Used (GB)", "green", None),
        (2, 2, "tps", "Tokens Per Second (TPS)", "magenta", None),
    ]

    for row, col, key, title, color, ylim in chart_specs:
        chart_times, chart_values = _REFRESH_STATE["series"][key]
        x_raw = list(range(len(chart_times)))
        ux, uy = upsample_series(x_raw, chart_values, factor=active_density)
        tick_pos, tick_labels = build_timeline_ticks(x_raw, chart_times, max_ticks=max_ticks)

        plt.subplot(row, col)
        plt.title(title)
        plt.plot(ux, uy, color=color, marker=active_marker)
        if ylim is not None:
            plt.ylim(*ylim)
        plt.xticks(tick_pos, tick_labels)

    plt.show()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="High-density terminal dashboard for Ollama monitoring metrics."
    )
    parser.add_argument(
        "--marker",
        choices=list(MARKER_SUBPIXELS.keys()),
        default=DEFAULT_MARKER,
        help="Sub-character marker resolution (default: braille, 2x4 sub-pixels/cell).",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=MAX_POINTS,
        help="Default timeline window in data points across charts (default: 120).",
    )
    parser.add_argument(
        "--density-factor",
        type=int,
        default=RESOLUTION_FACTOR,
        help="Sub-step interpolation factor per chart segment (default: 2).",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=DEFAULT_REFRESH_INTERVAL,
        help="Default timeline refresh interval in seconds (default: 1.0).",
    )
    for key in CHART_KEYS:
        parser.add_argument(
            f"--{key}-refresh",
            type=float,
            default=None,
            help=f"Timeline refresh interval in seconds for the {key.upper()} chart.",
        )
        parser.add_argument(
            f"--{key}-window",
            type=int,
            default=None,
            help=f"Timeline window size (points) for the {key.upper()} chart.",
        )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render a single dashboard frame and exit.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    refresh_intervals = {}
    timeline_points = {}
    for key in CHART_KEYS:
        custom_refresh = getattr(args, f"{key}_refresh", None)
        refresh_intervals[key] = args.refresh if custom_refresh is None else custom_refresh
        custom_window = getattr(args, f"{key}_window", None)
        timeline_points[key] = args.max_points if custom_window is None else custom_window

    sleep_interval = get_loop_sleep_interval(refresh_intervals)
    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            draw_dashboard(
                now=time.monotonic(),
                refresh_intervals=refresh_intervals,
                timeline_points=timeline_points,
                marker=args.marker,
                density_factor=args.density_factor,
            )
            if args.once:
                break
            time.sleep(sleep_interval)
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()