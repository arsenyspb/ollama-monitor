#!/usr/bin/env python3
import argparse
import os
import shutil
import signal
import sys
import time

try:
    import plotext as plt
except ImportError:
    plt = None

__version__ = "0.2.0"

CSV_FILE = "benchmark_data/continuous_monitor.csv"
BASELINE_MAX_POINTS = 60
MAX_POINTS = 120  # Doubled default point window (2x over legacy 60-point chart)
DEFAULT_REFRESH = 1.0
DEFAULT_MARKER = "braille"  # Unicode Braille 2x4 subpixels/cell (2x over hd 2x2)
DEFAULT_UPSAMPLE_FACTOR = 2
CHART_NAMES = ("cpu", "gpu", "ram", "tps")

SUBPIXEL_CELL_GRID = {
    "sd": (1, 1),
    "hd": (2, 2),
    "fhd": (2, 3),
    "braille": (2, 4),
}

_RESIZE_PENDING = False


def handle_sigwinch(signum, frame):
    global _RESIZE_PENDING
    _RESIZE_PENDING = True


def consume_resize_event():
    global _RESIZE_PENDING
    pending = _RESIZE_PENDING
    _RESIZE_PENDING = False
    return pending


def install_resize_handler():
    sigwinch = getattr(signal, "SIGWINCH", None)
    if sigwinch is not None:
        try:
            signal.signal(sigwinch, handle_sigwinch)
        except (ValueError, OSError):
            pass


def chart_density_ratio(
    marker=DEFAULT_MARKER,
    upsample_factor=DEFAULT_UPSAMPLE_FACTOR,
    baseline_marker="hd",
):
    """Return effective chart resolution multiplier in the same cols:chars footprint."""
    cols, rows = SUBPIXEL_CELL_GRID.get(marker, (2, 4))
    base_cols, base_rows = SUBPIXEL_CELL_GRID.get(baseline_marker, (2, 2))
    subpixel_ratio = (cols * rows) / max(1, base_cols * base_rows)
    sample_ratio = max(1, int(upsample_factor))
    return max(subpixel_ratio, subpixel_ratio * (sample_ratio / 2.0))


def upsample_series(x, y, factor=DEFAULT_UPSAMPLE_FACTOR):
    """Linearly upsample (x, y) by `factor` so Braille subpixel cells render continuous curves."""
    x_list = [float(v) for v in x]
    y_list = [float(v) for v in y]
    n = len(y_list)
    factor = int(factor)
    if factor <= 1 or n == 0:
        return x_list, y_list
    if n == 1:
        return [x_list[0]] * factor, [y_list[0]] * factor

    total = n * factor
    x_up = []
    y_up = []
    span = n - 1
    denom = total - 1
    for k in range(total):
        pos = (k * span) / denom
        idx = min(int(pos), span - 1)
        frac = pos - idx
        x_val = x_list[idx] + frac * (x_list[idx + 1] - x_list[idx])
        y_val = y_list[idx] + frac * (y_list[idx + 1] - y_list[idx])
        x_up.append(x_val)
        y_up.append(y_val)
    return x_up, y_up


def compute_xticks(times, width=80, max_ticks=None):
    """Decimate x-axis timestamp ticks adaptively for the given terminal width."""
    n = len(times)
    if n == 0:
        return [], []
    if max_ticks is None:
        subplot_width = max(20, int(width) // 2)
        max_ticks = max(2, min(8, subplot_width // 12))
    if n <= max_ticks:
        return list(range(n)), list(times)

    indices = []
    steps = max(1, max_ticks - 1)
    for i in range(max_ticks):
        idx = round(i * (n - 1) / steps)
        if not indices or idx != indices[-1]:
            indices.append(idx)
    labels = [times[idx] for idx in indices]
    return indices, labels


def get_terminal_dimensions(fallback=(120, 40)):
    """Query terminal size safely across interactive TTYs, tmux, and headless tests."""
    try:
        size = shutil.get_terminal_size(fallback=fallback)
        w, h = int(size.columns), int(size.lines)
        if w > 0 and h > 0:
            return max(40, w), max(12, h)
    except Exception:
        pass
    if plt is not None:
        try:
            w, h = plt.terminal_size()
            if w and h:
                return max(40, int(w)), max(12, int(h))
        except Exception:
            pass
    return fallback


def read_data(max_points=None, csv_file=None):
    target_csv = csv_file if csv_file is not None else CSV_FILE
    limit = MAX_POINTS if max_points is None else int(max_points)
    if limit <= 0 or not os.path.exists(target_csv):
        return [], [], [], [], [], "None", "None"

    try:
        with open(target_csv, "r") as f:
            lines = f.readlines()[1:]  # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    # Get last `limit` lines
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


class ChartRefreshScheduler:
    """Manages independent refresh intervals and window sizes per chart (cpu, gpu, ram, tps)."""

    def __init__(self, refresh_intervals=None, window_sizes=None, csv_file=None):
        self.refresh_intervals = {name: DEFAULT_REFRESH for name in CHART_NAMES}
        if refresh_intervals:
            for name, val in refresh_intervals.items():
                if name in self.refresh_intervals and val is not None:
                    self.refresh_intervals[name] = max(0.05, float(val))

        self.window_sizes = {name: MAX_POINTS for name in CHART_NAMES}
        if window_sizes:
            for name, val in window_sizes.items():
                if name in self.window_sizes and val is not None:
                    self.window_sizes[name] = max(1, int(val))

        self.csv_file = csv_file
        self.last_updated = {name: None for name in CHART_NAMES}
        self._series_cache = {name: ([], []) for name in CHART_NAMES}
        self.model_name = "None"
        self.model_meta = "None"

    def due_charts(self, now):
        due = []
        for name in CHART_NAMES:
            last = self.last_updated[name]
            if last is None or (now - last) >= (self.refresh_intervals[name] - 1e-9):
                due.append(name)
        return due

    def update(self, now=None, raw_data=None, force=False):
        if now is None:
            now = time.monotonic()
        due = list(CHART_NAMES) if force else self.due_charts(now)
        if not due:
            return set()

        if raw_data is None:
            max_window = max(self.window_sizes.values())
            raw_data = read_data(max_points=max_window, csv_file=self.csv_file)

        times, cpu, gpu, ram, tps, model_name, model_meta = raw_data
        self.model_name = model_name
        self.model_meta = model_meta
        raw_map = {
            "cpu": cpu,
            "gpu": gpu,
            "ram": ram,
            "tps": tps,
        }

        updated = set()
        for name in due:
            win = self.window_sizes[name]
            series = raw_map[name]
            self._series_cache[name] = (list(times[-win:]), list(series[-win:]))
            self.last_updated[name] = now
            updated.add(name)
        return updated

    def get_series(self, chart_name):
        return self._series_cache.get(chart_name, ([], []))

    def has_data(self):
        return any(len(times) > 0 for times, _ in self._series_cache.values())

    def next_sleep_interval(self, now=None):
        if now is None:
            now = time.monotonic()
        remaining = []
        for name in CHART_NAMES:
            last = self.last_updated[name]
            interval = self.refresh_intervals[name]
            if last is None:
                remaining.append(interval)
            else:
                rem = interval - (now - last)
                remaining.append(max(0.05, rem))
        return min(remaining) if remaining else DEFAULT_REFRESH


def _positive_float(value):
    val = float(value)
    if val <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return val


def _positive_int(value):
    val = int(value)
    if val < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return val


def build_parser():
    parser = argparse.ArgumentParser(
        description="Ollama Monitor Terminal Dashboard (High-Density Braille TUI)"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help=f"Path to continuous monitor CSV (default: {CSV_FILE})",
    )
    parser.add_argument(
        "--refresh",
        type=_positive_float,
        default=DEFAULT_REFRESH,
        help=f"Default timeline refresh interval in seconds (default: {DEFAULT_REFRESH})",
    )
    parser.add_argument(
        "--cpu-refresh",
        type=_positive_float,
        default=None,
        help="CPU chart refresh interval in seconds (overrides --refresh)",
    )
    parser.add_argument(
        "--gpu-refresh",
        type=_positive_float,
        default=None,
        help="GPU chart refresh interval in seconds (overrides --refresh)",
    )
    parser.add_argument(
        "--ram-refresh",
        type=_positive_float,
        default=None,
        help="RAM chart refresh interval in seconds (overrides --refresh)",
    )
    parser.add_argument(
        "--tps-refresh",
        type=_positive_float,
        default=None,
        help="TPS chart refresh interval in seconds (overrides --refresh)",
    )
    parser.add_argument(
        "--window",
        type=_positive_int,
        default=MAX_POINTS,
        help=f"Default timeline window size in points (default: {MAX_POINTS})",
    )
    parser.add_argument(
        "--cpu-window",
        type=_positive_int,
        default=None,
        help="CPU chart window size in points (overrides --window)",
    )
    parser.add_argument(
        "--gpu-window",
        type=_positive_int,
        default=None,
        help="GPU chart window size in points (overrides --window)",
    )
    parser.add_argument(
        "--ram-window",
        type=_positive_int,
        default=None,
        help="RAM chart window size in points (overrides --window)",
    )
    parser.add_argument(
        "--tps-window",
        type=_positive_int,
        default=None,
        help="TPS chart window size in points (overrides --window)",
    )
    parser.add_argument(
        "--marker",
        choices=list(SUBPIXEL_CELL_GRID.keys()),
        default=DEFAULT_MARKER,
        help=f"Subpixel chart marker (default: {DEFAULT_MARKER})",
    )
    parser.add_argument(
        "--upsample",
        type=_positive_int,
        default=DEFAULT_UPSAMPLE_FACTOR,
        help=f"Series interpolation factor for subpixel density (default: {DEFAULT_UPSAMPLE_FACTOR})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render a single dashboard frame and exit",
    )
    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)


def scheduler_from_args(args):
    refresh_intervals = {
        "cpu": args.cpu_refresh if args.cpu_refresh is not None else args.refresh,
        "gpu": args.gpu_refresh if args.gpu_refresh is not None else args.refresh,
        "ram": args.ram_refresh if args.ram_refresh is not None else args.refresh,
        "tps": args.tps_refresh if args.tps_refresh is not None else args.refresh,
    }
    window_sizes = {
        "cpu": args.cpu_window if args.cpu_window is not None else args.window,
        "gpu": args.gpu_window if args.gpu_window is not None else args.window,
        "ram": args.ram_window if args.ram_window is not None else args.window,
        "tps": args.tps_window if args.tps_window is not None else args.window,
    }
    return ChartRefreshScheduler(
        refresh_intervals=refresh_intervals,
        window_sizes=window_sizes,
        csv_file=args.csv,
    )


def _require_plotext():
    if plt is None:
        print("plotext is not installed. Run: pip install plotext")
        sys.exit(1)


def draw_dashboard(
    scheduler=None,
    now=None,
    marker=DEFAULT_MARKER,
    upsample_factor=DEFAULT_UPSAMPLE_FACTOR,
):
    _require_plotext()
    consume_resize_event()

    plt.clear_terminal()
    if hasattr(plt, "clf"):
        plt.clf()
    plt.theme("clear")

    if scheduler is None:
        scheduler = ChartRefreshScheduler(csv_file=CSV_FILE)
        scheduler.update(now=0.0 if now is None else now, force=True)
    else:
        scheduler.update(now=now)

    target_csv = scheduler.csv_file if scheduler.csv_file is not None else CSV_FILE
    if not scheduler.has_data():
        print(f"Waiting for data in {target_csv}...")
        return

    model_name = scheduler.model_name
    model_meta = scheduler.model_meta

    # Render Top Row Outlook
    if model_name != "None":
        print(
            f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n"
        )
    else:
        print("\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n")

    # Adjust plot size to prevent terminal from scrolling and overwriting the top text
    w, h = 120, 40
    try:
        w, h = get_terminal_dimensions()
        plt.plotsize(w, max(8, h - 3))
    except Exception:
        pass

    plt.subplots(2, 2)

    chart_specs = [
        (1, 1, "cpu", "CPU Usage (%)", "blue", (0, 100)),
        (1, 2, "gpu", "GPU Load (%)", "red", (0, 100)),
        (2, 1, "ram", "RAM Used (GB)", "green", None),
        (2, 2, "tps", "Tokens Per Second (TPS)", "magenta", None),
    ]

    for row, col, name, title, color, y_bounds in chart_specs:
        c_times, c_vals = scheduler.get_series(name)
        x = list(range(len(c_times)))
        x_up, y_up = upsample_series(x, c_vals, factor=upsample_factor)
        tick_pos, tick_labels = compute_xticks(c_times, width=w)

        plt.subplot(row, col)
        cadence = scheduler.refresh_intervals[name]
        win = scheduler.window_sizes[name]
        plt.title(f"{title} [{win}pts @ {cadence:g}s]")
        plt.plot(x_up, y_up, color=color, marker=marker)
        if y_bounds is not None:
            plt.ylim(y_bounds[0], y_bounds[1])
        plt.xticks(tick_pos, tick_labels)

    plt.show()


def main(argv=None):
    args = parse_args(argv)
    _require_plotext()
    install_resize_handler()
    scheduler = scheduler_from_args(args)

    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            now = time.monotonic()
            draw_dashboard(
                scheduler=scheduler,
                now=now,
                marker=args.marker,
                upsample_factor=args.upsample,
            )
            if args.once:
                break
            sleep_for = scheduler.next_sleep_interval(now=time.monotonic())
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()
