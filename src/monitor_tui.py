#!/usr/bin/env python3
import argparse
import os
import signal
import sys
import time

try:
    import plotext as plt
except ImportError:
    print("plotext is not installed. Run: pip install plotext")
    sys.exit(1)

CSV_FILE = "benchmark_data/continuous_monitor.csv"
_DEFAULT_MAX_POINTS = int(os.environ.get("MONITOR_TUI_MAX_POINTS", "120"))
MAX_POINTS = _DEFAULT_MAX_POINTS  # Show last 120 seconds of data by default (2x density)
DEFAULT_MARKER = os.environ.get("MONITOR_TUI_MARKER", "braille")
_DEFAULT_REFRESH_INTERVAL = float(os.environ.get("MONITOR_TUI_REFRESH_INTERVAL", "1.0"))
REFRESH_INTERVAL = _DEFAULT_REFRESH_INTERVAL

CHART_NAMES = ("cpu", "gpu", "ram", "tps")

# Sub-character resolution factors (subcols, subrows) per 1 col x 1 char terminal cell:
# - sd:      1x1 = 1 pixel/cell
# - hd:      2x2 = 4 subpixels/cell (Unicode quadrant blocks U+2580..U+259F)
# - fhd:     2x3 = 6 subpixels/cell (Unicode sextant blocks U+1FB00..U+1FB3B)
# - braille: 2x4 = 8 subpixels/cell (Unicode Braille patterns U+2800..U+28FF; 2x over hd, 8x over sd)
MARKER_SUBPIXEL_FACTORS = {
    "sd": (1, 1),
    "dot": (1, 1),
    "hd": (2, 2),
    "fhd": (2, 3),
    "braille": (2, 4),
}

CHART_WINDOWS = {
    name: int(os.environ.get(f"MONITOR_TUI_{name.upper()}_WINDOW", str(MAX_POINTS)))
    for name in CHART_NAMES
}

CHART_REFRESH_INTERVALS = {
    name: float(os.environ.get(f"MONITOR_TUI_{name.upper()}_REFRESH", str(REFRESH_INTERVAL)))
    for name in CHART_NAMES
}

_chart_cache = {
    "csv_file": None,
    "charts": {},
}


def reset_chart_cache():
    """Clear cached per-chart timeline slices and refresh timestamps."""
    _chart_cache["csv_file"] = None
    _chart_cache["charts"] = {}


def get_marker_subpixels(marker=None):
    """Return (subcols, subrows) per character cell for the given plotext marker."""
    resolved = (marker or DEFAULT_MARKER).lower()
    return MARKER_SUBPIXEL_FACTORS.get(resolved, (1, 1))


def get_effective_resolution(cols, rows, marker=None):
    """Return effective (subpixel_cols, subpixel_rows) for a (cols, rows) character grid."""
    subcols, subrows = get_marker_subpixels(marker)
    return int(cols) * subcols, int(rows) * subrows


def compute_xticks(times, max_ticks=5):
    """Compute evenly spaced x-axis tick indices and timestamp labels."""
    n = len(times)
    if n <= max_ticks or max_ticks <= 1:
        return list(range(n)), list(times)
    indices = []
    for i in range(max_ticks):
        idx = round(i * (n - 1) / (max_ticks - 1))
        if not indices or idx != indices[-1]:
            indices.append(idx)
    return indices, [times[idx] for idx in indices]


def _resolve_chart_windows(chart_windows=None):
    resolved = {}
    for name in CHART_NAMES:
        if chart_windows and chart_windows.get(name) is not None:
            resolved[name] = max(1, int(chart_windows[name]))
        else:
            configured = CHART_WINDOWS.get(name, MAX_POINTS)
            if configured == _DEFAULT_MAX_POINTS and MAX_POINTS != _DEFAULT_MAX_POINTS:
                configured = MAX_POINTS
            resolved[name] = max(1, int(configured))
    return resolved


def _resolve_chart_refresh_intervals(chart_refresh_intervals=None):
    resolved = {}
    for name in CHART_NAMES:
        if chart_refresh_intervals and chart_refresh_intervals.get(name) is not None:
            resolved[name] = max(0.0, float(chart_refresh_intervals[name]))
        else:
            configured = CHART_REFRESH_INTERVALS.get(name, REFRESH_INTERVAL)
            if configured == _DEFAULT_REFRESH_INTERVAL and REFRESH_INTERVAL != _DEFAULT_REFRESH_INTERVAL:
                configured = REFRESH_INTERVAL
            resolved[name] = max(0.0, float(configured))
    return resolved


def read_data(max_points=None):
    if not os.path.exists(CSV_FILE):
        return [], [], [], [], [], "None", "None"

    try:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()[1:]  # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    limit = MAX_POINTS if max_points is None else int(max_points)
    if limit > 0:
        lines = lines[-limit:]
    else:
        lines = []

    times = []
    cpu = []
    gpu = []
    ram = []
    tps = []
    last_model_name = "None"
    last_model_meta = "None"

    for line in lines:
        parts = line.strip().split(',')
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


def draw_dashboard(marker=None, chart_windows=None, chart_refresh_intervals=None, now=None):
    plt.clear_terminal()
    plt.clear_figure()
    plt.theme("clear")

    active_marker = marker or DEFAULT_MARKER
    resolved_windows = _resolve_chart_windows(chart_windows)
    resolved_intervals = _resolve_chart_refresh_intervals(chart_refresh_intervals)
    max_window = max(resolved_windows.values())

    try:
        times, cpu, gpu, ram, tps, model_name, model_meta = read_data(max_points=max_window)
    except TypeError:
        times, cpu, gpu, ram, tps, model_name, model_meta = read_data()

    if not times:
        print(f"Waiting for data in {CSV_FILE}...")
        return

    # Render Top Row Outlook
    if model_name != "None":
        print(f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n")
    else:
        print("\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n")

    if _chart_cache["csv_file"] != CSV_FILE:
        _chart_cache["csv_file"] = CSV_FILE
        _chart_cache["charts"] = {}

    current_time = time.time() if now is None else float(now)
    use_refresh_throttling = (
        now is not None
        or chart_refresh_intervals is not None
        or any(v != _DEFAULT_REFRESH_INTERVAL for v in CHART_REFRESH_INTERVALS.values())
    )

    raw_series = {
        "cpu": cpu,
        "gpu": gpu,
        "ram": ram,
        "tps": tps,
    }
    chart_data = {}

    for name in CHART_NAMES:
        win = resolved_windows[name]
        latest_times = times[-win:]
        latest_values = raw_series[name][-win:]
        cached = _chart_cache["charts"].get(name)

        should_refresh = (
            cached is None
            or not use_refresh_throttling
            or (current_time - cached["last_updated"]) >= (resolved_intervals[name] - 1e-9)
        )
        if should_refresh:
            cached = {
                "last_updated": current_time,
                "times": list(latest_times),
                "values": list(latest_values),
            }
            _chart_cache["charts"][name] = cached

        chart_data[name] = (cached["times"], cached["values"])

    # Adjust plot size dynamically to fit modern terminal resizing without clamping to initial size
    try:
        w, h = plt.terminal_size()
        if w is not None and h is not None and w > 0 and h > 3:
            plt.limitsize(False, False)
            plt.plotsize(w, h - 3)
    except Exception:
        pass

    plt.subplots(2, 2)

    subplot_specs = [
        (1, 1, "cpu", "CPU Usage (%)", "blue", (0, 100)),
        (1, 2, "gpu", "GPU Load (%)", "red", (0, 100)),
        (2, 1, "ram", "RAM Used (GB)", "green", None),
        (2, 2, "tps", "Tokens Per Second (TPS)", "magenta", None),
    ]

    for row, col, name, title, color, ylim_bounds in subplot_specs:
        c_times, c_values = chart_data[name]
        x = list(range(len(c_times)))
        plt.subplot(row, col)
        plt.title(title)
        plt.plot(x, c_values, color=color, marker=active_marker)
        if ylim_bounds is not None:
            plt.ylim(*ylim_bounds)
        tick_x, tick_labels = compute_xticks(c_times)
        plt.xticks(tick_x, tick_labels)

    plt.show()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="High-density terminal dashboard for Ollama monitoring metrics."
    )
    parser.add_argument(
        "--window",
        "--max-points",
        dest="window",
        type=int,
        default=MAX_POINTS,
        help="Default timeline window (number of data points) for all charts (default: %(default)s).",
    )
    for name in CHART_NAMES:
        parser.add_argument(
            f"--{name}-window",
            dest=f"{name}_window",
            type=int,
            default=None,
            help=f"Timeline window override (data points) for the {name.upper()} chart.",
        )
    parser.add_argument(
        "--refresh",
        dest="refresh",
        type=float,
        default=REFRESH_INTERVAL,
        help="Default refresh interval in seconds for all charts (default: %(default)s).",
    )
    for name in CHART_NAMES:
        parser.add_argument(
            f"--{name}-refresh",
            dest=f"{name}_refresh",
            type=float,
            default=None,
            help=f"Refresh interval override in seconds for the {name.upper()} chart.",
        )
    parser.add_argument(
        "--marker",
        choices=tuple(MARKER_SUBPIXEL_FACTORS.keys()),
        default=DEFAULT_MARKER,
        help="Sub-character plot marker resolution mode (default: %(default)s, 2x4 subpixels/cell).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    chart_windows = {
        name: getattr(args, f"{name}_window") or args.window
        for name in CHART_NAMES
    }
    chart_refresh_intervals = {
        name: (
            getattr(args, f"{name}_refresh")
            if getattr(args, f"{name}_refresh") is not None
            else args.refresh
        )
        for name in CHART_NAMES
    }
    loop_sleep = max(0.1, min(chart_refresh_intervals.values()))

    resize_pending = False

    def _on_sigwinch(signum, frame):
        nonlocal resize_pending
        resize_pending = True

    if hasattr(signal, "SIGWINCH"):
        try:
            signal.signal(signal.SIGWINCH, _on_sigwinch)
        except Exception:
            pass

    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            resize_pending = False
            draw_dashboard(
                marker=args.marker,
                chart_windows=chart_windows,
                chart_refresh_intervals=chart_refresh_intervals,
                now=time.time(),
            )
            if not resize_pending:
                time.sleep(loop_sleep)
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()
