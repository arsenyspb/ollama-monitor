#!/usr/bin/env python3
import time
import os
import sys
import argparse

try:
    import plotext as plt
except ImportError:
    print("plotext is not installed. Run: pip install plotext")
    sys.exit(1)

CSV_FILE = "benchmark_data/continuous_monitor.csv"
MAX_POINTS = 60 # Show last 60 seconds of data

DEFAULT_DENSITY = "braille"
DEFAULT_MAX_POINTS = 60
DEFAULT_REFRESH_INTERVAL = 1.0

# Resolution factors for terminal plotting markers
# braille: 2x horizontal * 4x vertical = 8 subpixels per character cell
# fhd: 2x horizontal * 3x vertical = 6 subpixels per character cell
# hd: 2x horizontal * 2x vertical = 4 subpixels per character cell
# sd: 1x horizontal * 1x vertical = 1 subpixel per character cell
MARKER_RESOLUTIONS = {
    "braille": {
        "horizontal_factor": 2,
        "vertical_factor": 4,
        "subpixels": 8,
        "description": "Unicode Braille Patterns (2x4 dot matrix, 8 subpixels/cell, SOTA high density)",
    },
    "fhd": {
        "horizontal_factor": 2,
        "vertical_factor": 3,
        "subpixels": 6,
        "description": "Unicode Sextant Blocks (2x3 legacy computing matrix, 6 subpixels/cell)",
    },
    "hd": {
        "horizontal_factor": 2,
        "vertical_factor": 2,
        "subpixels": 4,
        "description": "Half-blocks (1x2 / 2x2 half block matrix, 4 subpixels/cell, original baseline)",
    },
    "sd": {
        "horizontal_factor": 1,
        "vertical_factor": 1,
        "subpixels": 1,
        "description": "Standard character cell (1x1 block matrix, 1 subpixel/cell)",
    },
}


def get_marker_resolution(marker: str) -> dict:
    marker_key = marker.lower()
    if marker_key in MARKER_RESOLUTIONS:
        return MARKER_RESOLUTIONS[marker_key]
    return {
        "horizontal_factor": 1,
        "vertical_factor": 1,
        "subpixels": 1,
        "description": f"Custom marker '{marker}'",
    }


class ChartConfig:
    def __init__(
        self,
        name: str,
        density: str = DEFAULT_DENSITY,
        timeline: int = DEFAULT_MAX_POINTS,
        refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
        color: str = "blue",
        title: str = "",
        ylim: tuple = None,
    ):
        self.name = name
        self.density = density
        self.timeline = timeline
        self.refresh_interval = refresh_interval
        self.color = color
        self.title = title
        self.ylim = ylim


class DashboardConfig:
    def __init__(
        self,
        default_density: str = DEFAULT_DENSITY,
        default_timeline: int = DEFAULT_MAX_POINTS,
        default_refresh: float = DEFAULT_REFRESH_INTERVAL,
        csv_file: str = None,
        charts: dict = None,
    ):
        self.default_density = default_density
        self.default_timeline = default_timeline
        self.default_refresh = default_refresh
        self.csv_file = csv_file
        
        default_specs = {
            "cpu": {"color": "blue", "title": "CPU Usage (%)", "ylim": (0, 100)},
            "gpu": {"color": "red", "title": "GPU Load (%)", "ylim": (0, 100)},
            "ram": {"color": "green", "title": "RAM Used (GB)", "ylim": None},
            "tps": {"color": "magenta", "title": "Tokens Per Second (TPS)", "ylim": None},
        }
        
        if charts is None:
            self.charts = {}
            for name, spec in default_specs.items():
                self.charts[name] = ChartConfig(
                    name=name,
                    density=default_density,
                    timeline=default_timeline,
                    refresh_interval=default_refresh,
                    color=spec["color"],
                    title=spec["title"],
                    ylim=spec["ylim"],
                )
        else:
            self.charts = charts


class DashboardState:
    def __init__(self):
        self.last_refresh_time: dict[str, float] = {}
        self.cached_data: dict[str, dict] = {}


def read_data(csv_file: str = None, max_points: int = None):
    target_csv = csv_file if csv_file is not None else CSV_FILE
    points_limit = max_points if max_points is not None else MAX_POINTS
    
    if not os.path.exists(target_csv):
        return [], [], [], [], [], "None", "None"
    
    try:
        with open(target_csv, 'r') as f:
            lines = f.readlines()[1:] # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    # Get last points_limit lines if specified and positive
    if points_limit and points_limit > 0:
        lines = lines[-points_limit:]
    
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


def get_dashboard_data(config: DashboardConfig, state: DashboardState = None, current_time: float = None) -> dict:
    if current_time is None:
        current_time = time.time()
        
    target_csv = config.csv_file if config.csv_file is not None else CSV_FILE
    
    # Check if any chart needs refreshing
    needs_refresh = False
    max_timeline = 0
    for name, chart_cfg in config.charts.items():
        if chart_cfg.timeline > max_timeline:
            max_timeline = chart_cfg.timeline
        if state is None:
            needs_refresh = True
        else:
            last_t = state.last_refresh_time.get(name)
            if last_t is None or (current_time - last_t >= chart_cfg.refresh_interval):
                needs_refresh = True

    # Read data from CSV if needed
    times, cpu, gpu, ram, tps, model_name, model_meta = [], [], [], [], [], "None", "None"
    if needs_refresh:
        times, cpu, gpu, ram, tps, model_name, model_meta = read_data(
            csv_file=target_csv,
            max_points=max(max_timeline, 1)
        )

    raw_metrics = {
        "cpu": cpu,
        "gpu": gpu,
        "ram": ram,
        "tps": tps,
    }

    result = {
        "_model_name": model_name,
        "_model_meta": model_meta,
    }

    for name, chart_cfg in config.charts.items():
        should_update = True
        if state is not None:
            last_t = state.last_refresh_time.get(name)
            if last_t is not None and (current_time - last_t < chart_cfg.refresh_interval):
                should_update = False

        if should_update:
            metric_data = raw_metrics.get(name, [])
            slice_len = min(len(times), chart_cfg.timeline)
            chart_times = times[-slice_len:] if slice_len > 0 else []
            chart_y = metric_data[-slice_len:] if slice_len > 0 else []
            chart_x = list(range(len(chart_times)))
            
            chart_entry = {
                "x": chart_x,
                "y": chart_y,
                "times": chart_times,
                "model_name": model_name,
                "model_meta": model_meta,
            }
            if state is not None:
                state.cached_data[name] = chart_entry
                state.last_refresh_time[name] = current_time
            result[name] = chart_entry
        else:
            cached = state.cached_data.get(name, {"x": [], "y": [], "times": [], "model_name": "None", "model_meta": "None"})
            result[name] = cached
            if result["_model_name"] == "None" and cached.get("model_name") != "None":
                result["_model_name"] = cached.get("model_name")
                result["_model_meta"] = cached.get("model_meta")

    return result


def draw_dashboard(config: DashboardConfig = None, state: DashboardState = None):
    if config is None:
        config = DashboardConfig()
    if state is None:
        state = DashboardState()
        
    plt.clear_terminal()
    plt.theme("clear")
    
    chart_data = get_dashboard_data(config, state)
    
    # Check if there is any data in any chart
    has_any_data = any(len(chart_data[name]["times"]) > 0 for name in config.charts if name in chart_data)
    target_csv = config.csv_file if config.csv_file is not None else CSV_FILE
    
    if not has_any_data:
        print(f"Waiting for data in {target_csv}...")
        return

    model_name = chart_data.get("_model_name", "None")
    model_meta = chart_data.get("_model_meta", "None")
    
    # Render Top Row Outlook
    if model_name != "None":
        print(f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n")
    else:
        print("\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n")

    # Adjust plot size to prevent terminal from scrolling and overwriting the top text
    try:
        w, h = plt.terminal_size()
        plt.plotsize(w, h - 3)
    except Exception:
        pass
        
    plt.subplots(2, 2)
    
    layout = [
        (1, 1, "cpu", "CPU Usage (%)", "blue", (0, 100)),
        (1, 2, "gpu", "GPU Load (%)", "red", (0, 100)),
        (2, 1, "ram", "RAM Used (GB)", "green", None),
        (2, 2, "tps", "Tokens Per Second (TPS)", "magenta", None),
    ]

    for row, col, name, fallback_title, fallback_color, fallback_ylim in layout:
        plt.subplot(row, col)
        cfg = config.charts.get(name)
        title = (cfg.title if cfg and cfg.title else fallback_title)
        color = (cfg.color if cfg and cfg.color else fallback_color)
        ylim = (cfg.ylim if cfg and cfg.ylim is not None else fallback_ylim)
        density = (cfg.density if cfg and cfg.density else config.default_density)
        
        plt.title(title)
        entry = chart_data.get(name, {"x": [], "y": [], "times": []})
        x = entry.get("x", [])
        y = entry.get("y", [])
        times = entry.get("times", [])
        
        plt.plot(x, y, color=color, marker=density)
        if ylim is not None:
            plt.ylim(ylim[0], ylim[1])
        if x and times:
            plt.xticks(x, times)
            
    plt.show()


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="Ollama Real-Time Performance Monitor TUI (High-Density SOTA 2026)"
    )
    parser.add_argument(
        "--density", "-d",
        type=str,
        default=DEFAULT_DENSITY,
        choices=["braille", "fhd", "hd", "sd"],
        help="Default graph density/marker (default: braille)",
    )
    parser.add_argument(
        "--timeline", "-t",
        type=int,
        default=DEFAULT_MAX_POINTS,
        help="Default timeline points per chart (default: 60)",
    )
    parser.add_argument(
        "--refresh", "-r",
        type=float,
        default=DEFAULT_REFRESH_INTERVAL,
        help="Global refresh loop interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help=f"Path to continuous monitor CSV (default: {CSV_FILE})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render dashboard once and exit",
    )
    
    # Per-chart density overrides
    parser.add_argument("--cpu-density", type=str, choices=["braille", "fhd", "hd", "sd"], help="CPU chart density")
    parser.add_argument("--gpu-density", type=str, choices=["braille", "fhd", "hd", "sd"], help="GPU chart density")
    parser.add_argument("--ram-density", type=str, choices=["braille", "fhd", "hd", "sd"], help="RAM chart density")
    parser.add_argument("--tps-density", type=str, choices=["braille", "fhd", "hd", "sd"], help="TPS chart density")
    
    # Per-chart timeline overrides
    parser.add_argument("--cpu-timeline", type=int, help="CPU chart timeline points")
    parser.add_argument("--gpu-timeline", type=int, help="GPU chart timeline points")
    parser.add_argument("--ram-timeline", type=int, help="RAM chart timeline points")
    parser.add_argument("--tps-timeline", type=int, help="TPS chart timeline points")
    
    # Per-chart refresh interval overrides
    parser.add_argument("--cpu-refresh", type=float, help="CPU chart refresh interval in seconds")
    parser.add_argument("--gpu-refresh", type=float, help="GPU chart refresh interval in seconds")
    parser.add_argument("--ram-refresh", type=float, help="RAM chart refresh interval in seconds")
    parser.add_argument("--tps-refresh", type=float, help="TPS chart refresh interval in seconds")
    
    return parser.parse_args(args)


def build_config_from_args(args) -> DashboardConfig:
    config = DashboardConfig(
        default_density=args.density,
        default_timeline=args.timeline,
        default_refresh=args.refresh,
        csv_file=args.csv,
    )
    
    chart_names = ["cpu", "gpu", "ram", "tps"]
    for name in chart_names:
        chart_cfg = config.charts[name]
        
        # Override density if specified
        density_val = getattr(args, f"{name}_density", None)
        if density_val:
            chart_cfg.density = density_val
            
        # Override timeline if specified
        timeline_val = getattr(args, f"{name}_timeline", None)
        if timeline_val is not None:
            chart_cfg.timeline = timeline_val
            
        # Override refresh if specified
        refresh_val = getattr(args, f"{name}_refresh", None)
        if refresh_val is not None:
            chart_cfg.refresh_interval = refresh_val
            
    return config


def main():
    args = parse_args()
    config = build_config_from_args(args)
    state = DashboardState()
    
    if args.once:
        draw_dashboard(config=config, state=state)
        return

    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            draw_dashboard(config=config, state=state)
            time.sleep(config.default_refresh)
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()
