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
MAX_POINTS = 60  # Default history points (last 60 seconds)
DEFAULT_TIMELINE_POINTS = 60
DEFAULT_REFRESH_INTERVAL = 1.0
DEFAULT_MARKER = "braille"
CHART_NAMES = ["cpu", "gpu", "ram", "tps"]


def get_marker_resolution(marker):
    """Return the (horizontal, vertical) subpixel resolution for a marker code.

    SOTA 2026 canonical TUI:
      - 'braille': (2, 4) -> 8 subpixels per character cell (doubled vs 'hd')
      - 'fhd':     (2, 3) -> 6 subpixels per character cell
      - 'hd':      (2, 2) -> 4 subpixels per character cell (classic half-block)
      - 'sd':      (1, 1) -> 1 subpixel per character cell (standard block)
    """
    m = str(marker).lower()
    if m == "braille":
        return (2, 4)
    elif m == "fhd":
        return (2, 3)
    elif m == "hd":
        return (2, 2)
    elif m == "sd":
        return (1, 1)
    else:
        return (1, 1)


class DashboardConfig:
    def __init__(self, timeline, refresh, marker):
        self.timeline = timeline
        self.points = timeline
        self.refresh = refresh
        self.marker = marker
        self.density = marker


def parse_config(args=None):
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Ollama TUI Monitor with High-Density Braille Charting and Configurable Timelines"
    )

    # Global controls
    parser.add_argument(
        "--density", "--marker",
        dest="density",
        default=None,
        help="Global plot marker density ('braille', 'fhd', 'hd', 'sd'). Default: braille"
    )
    parser.add_argument(
        "--timeline",
        dest="timeline",
        type=int,
        default=None,
        help="Global timeline window in points/seconds. Default: 60"
    )
    parser.add_argument(
        "--refresh",
        dest="refresh",
        type=float,
        default=None,
        help="Global dashboard refresh interval in seconds. Default: 1.0"
    )

    # Per-chart controls
    for c in CHART_NAMES:
        c_upper = c.upper()
        parser.add_argument(
            f"--density-{c}", f"--marker-{c}",
            dest=f"density_{c}",
            default=None,
            help=f"Marker density for {c_upper} chart"
        )
        parser.add_argument(
            f"--timeline-{c}",
            dest=f"timeline_{c}",
            type=int,
            default=None,
            help=f"Timeline window for {c_upper} chart in points"
        )
        parser.add_argument(
            f"--refresh-{c}",
            dest=f"refresh_{c}",
            type=float,
            default=None,
            help=f"Refresh interval for {c_upper} chart in seconds"
        )

    parsed = parser.parse_args(args)

    # Precedence:
    # 1. Per-chart CLI flag
    # 2. Per-chart env var
    # 3. Global CLI flag
    # 4. Global env var
    # 5. Global default constant

    global_marker_env = os.environ.get("TUI_DENSITY") or os.environ.get("TUI_MARKER")
    global_marker = parsed.density or global_marker_env or DEFAULT_MARKER

    global_timeline_env = os.environ.get("TIMELINE_POINTS")
    global_timeline = parsed.timeline or (int(global_timeline_env) if global_timeline_env else DEFAULT_TIMELINE_POINTS)

    global_refresh_env = os.environ.get("REFRESH_INTERVAL")
    global_refresh = parsed.refresh or (float(global_refresh_env) if global_refresh_env else DEFAULT_REFRESH_INTERVAL)

    resolved_markers = {}
    resolved_timelines = {}
    resolved_refreshes = {}

    for c in CHART_NAMES:
        c_upper = c.upper()
        # Marker
        m_cli = getattr(parsed, f"density_{c}")
        m_env = os.environ.get(f"TUI_DENSITY_{c_upper}") or os.environ.get(f"MARKER_{c_upper}")
        resolved_markers[c] = m_cli or m_env or global_marker

        # Timeline
        t_cli = getattr(parsed, f"timeline_{c}")
        t_env = os.environ.get(f"TIMELINE_{c_upper}")
        resolved_timelines[c] = t_cli or (int(t_env) if t_env else global_timeline)

        # Refresh
        r_cli = getattr(parsed, f"refresh_{c}")
        r_env = os.environ.get(f"REFRESH_{c_upper}")
        resolved_refreshes[c] = r_cli or (float(r_env) if r_env else global_refresh)

    return DashboardConfig(
        timeline=resolved_timelines,
        refresh=resolved_refreshes,
        marker=resolved_markers
    )


class DashboardState:
    def __init__(self, timeline=None, refresh=None, marker=None):
        # Normalize timeline
        if timeline is None:
            self.timeline = {c: DEFAULT_TIMELINE_POINTS for c in CHART_NAMES}
        elif isinstance(timeline, int):
            self.timeline = {c: timeline for c in CHART_NAMES}
        elif isinstance(timeline, dict):
            self.timeline = {c: timeline.get(c, DEFAULT_TIMELINE_POINTS) for c in CHART_NAMES}
        else:
            self.timeline = {c: DEFAULT_TIMELINE_POINTS for c in CHART_NAMES}

        # Normalize refresh
        if refresh is None:
            self.refresh = {c: DEFAULT_REFRESH_INTERVAL for c in CHART_NAMES}
        elif isinstance(refresh, (int, float)):
            self.refresh = {c: float(refresh) for c in CHART_NAMES}
        elif isinstance(refresh, dict):
            self.refresh = {c: float(refresh.get(c, DEFAULT_REFRESH_INTERVAL)) for c in CHART_NAMES}
        else:
            self.refresh = {c: DEFAULT_REFRESH_INTERVAL for c in CHART_NAMES}

        # Normalize marker
        if marker is None:
            self.marker = {c: DEFAULT_MARKER for c in CHART_NAMES}
        elif isinstance(marker, str):
            self.marker = {c: marker for c in CHART_NAMES}
        elif isinstance(marker, dict):
            self.marker = {c: marker.get(c, DEFAULT_MARKER) for c in CHART_NAMES}
        else:
            self.marker = {c: DEFAULT_MARKER for c in CHART_NAMES}

        self.last_refresh_time = {c: -1e9 for c in CHART_NAMES}
        self.cached_slices = {c: {"x": [], "y": [], "times": []} for c in CHART_NAMES}
        self.last_model_name = "None"
        self.last_model_meta = "None"

    def get_chart_slices(self, current_time=None):
        now = time.time() if current_time is None else float(current_time)
        max_needed = max(self.timeline.values()) if self.timeline else DEFAULT_TIMELINE_POINTS
        times, cpu, gpu, ram, tps, model_name, model_meta = read_data(max_points=max_needed)
        self.last_model_name = model_name
        self.last_model_meta = model_meta

        metric_series = {
            "cpu": cpu,
            "gpu": gpu,
            "ram": ram,
            "tps": tps
        }

        for c in CHART_NAMES:
            elapsed = now - self.last_refresh_time[c]
            # Update cache if interval elapsed or never refreshed
            if elapsed >= self.refresh[c] or self.last_refresh_time[c] < -1e8:
                raw_y = metric_series.get(c, [])
                win = self.timeline[c]
                y_slice = raw_y[-win:]
                times_slice = times[-win:]
                x_slice = list(range(len(y_slice)))
                self.cached_slices[c] = {
                    "x": x_slice,
                    "y": y_slice,
                    "times": times_slice
                }
                self.last_refresh_time[c] = now

        return self.cached_slices


def read_data(max_points=None):
    pts = MAX_POINTS if max_points is None else max_points
    if not os.path.exists(CSV_FILE):
        return [], [], [], [], [], "None", "None"

    try:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()[1:]  # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    # Get last pts lines
    lines = lines[-pts:]

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


def draw_dashboard(timeline=None, refresh=None, marker=None, build_only=False, state=None):
    if state is None:
        state = DashboardState(timeline=timeline, refresh=refresh, marker=marker)
    else:
        if timeline is not None:
            if isinstance(timeline, int):
                state.timeline = {c: timeline for c in CHART_NAMES}
            elif isinstance(timeline, dict):
                state.timeline.update(timeline)
        if refresh is not None:
            if isinstance(refresh, (int, float)):
                state.refresh = {c: float(refresh) for c in CHART_NAMES}
            elif isinstance(refresh, dict):
                state.refresh.update({k: float(v) for k, v in refresh.items()})
        if marker is not None:
            if isinstance(marker, str):
                state.marker = {c: marker for c in CHART_NAMES}
            elif isinstance(marker, dict):
                state.marker.update(marker)

    if not build_only:
        plt.clear_terminal()
    plt.main()
    plt.clf()
    plt.theme("clear")

    slices = state.get_chart_slices()
    model_name = state.last_model_name
    model_meta = state.last_model_meta

    has_data = any(len(s["y"]) > 0 for s in slices.values())
    if not has_data:
        msg = f"Waiting for data in {CSV_FILE}...\n"
        if not build_only:
            print(msg, end="")
        return msg

    # Top Row Outlook
    if model_name != "None":
        header = f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n\n"
    else:
        header = "\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n\n"

    if not build_only:
        print(header, end="")

    # Adjust plot size to prevent terminal scrolling while adapting to resizing
    try:
        w, h = plt.terminal_size()
        plt.plotsize(max(w, 20), max(h - 3, 10))
    except Exception:
        pass

    plt.subplots(2, 2)

    # 1, 1: CPU Usage
    cpu_s = slices["cpu"]
    plt.subplot(1, 1)
    plt.title("CPU Usage (%)")
    if cpu_s["y"]:
        plt.plot(cpu_s["x"], cpu_s["y"], color="blue", marker=state.marker["cpu"])
        plt.ylim(0, 100)
        plt.xticks(cpu_s["x"], cpu_s["times"])

    # 1, 2: GPU Load
    gpu_s = slices["gpu"]
    plt.subplot(1, 2)
    plt.title("GPU Load (%)")
    if gpu_s["y"]:
        plt.plot(gpu_s["x"], gpu_s["y"], color="red", marker=state.marker["gpu"])
        plt.ylim(0, 100)
        plt.xticks(gpu_s["x"], gpu_s["times"])

    # 2, 1: RAM Usage
    ram_s = slices["ram"]
    plt.subplot(2, 1)
    plt.title("RAM Used (GB)")
    if ram_s["y"]:
        plt.plot(ram_s["x"], ram_s["y"], color="green", marker=state.marker["ram"])
        plt.xticks(ram_s["x"], ram_s["times"])

    # 2, 2: TPS
    tps_s = slices["tps"]
    plt.subplot(2, 2)
    plt.title("Tokens Per Second (TPS)")
    if tps_s["y"]:
        plt.plot(tps_s["x"], tps_s["y"], color="magenta", marker=state.marker["tps"])
        plt.xticks(tps_s["x"], tps_s["times"])

    rendered = plt.build()
    if not build_only:
        plt.show()

    return header + rendered


def main():
    config = parse_config()
    state = DashboardState(
        timeline=config.timeline,
        refresh=config.refresh,
        marker=config.marker
    )
    min_tick = max(0.1, min(config.refresh.values()))
    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            draw_dashboard(state=state)
            time.sleep(min_tick)
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()
