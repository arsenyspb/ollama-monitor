import os
import tempfile
import sys
import pytest

# Add the src directory to the path so we can import monitor_tui
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import monitor_tui

def test_read_data_with_model_info():
    # Create a temporary CSV file
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_csv:
        # Write header
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        # Write rows
        temp_csv.write("12:00:00,10.5,2000,4.5,25.4\n")  # Old format without model
        temp_csv.write("12:00:01,15.2,3000,5.1,30.1,llama3,8B|Q4|4.7GB\n") # New format with model
        temp_csv_path = temp_csv.name

    # Patch the CSV_FILE path in the module
    original_csv_file = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = temp_csv_path

    try:
        times, cpu, gpu, ram, tps, model_name, model_meta = monitor_tui.read_data()
        
        # Check parsed metrics (last 60 lines max)
        assert len(times) == 2
        assert times == ["12:00:00", "12:00:01"]
        assert cpu == [10.5, 15.2]
        assert gpu == [2000.0, 3000.0]
        assert ram == [4.5, 5.1]
        assert tps == [25.4, 30.1]
        
        # Check parsed model info
        assert model_name == "llama3"
        assert model_meta == "8B|Q4|4.7GB"
    finally:
        # Restore and cleanup
        monitor_tui.CSV_FILE = original_csv_file
        os.remove(temp_csv_path)

def test_read_data_empty_or_missing_file():
    original_csv_file = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = "non_existent_file.csv"
    
    try:
        times, cpu, gpu, ram, tps, model_name, model_meta = monitor_tui.read_data()
        assert times == []
        assert cpu == []
        assert gpu == []
        assert ram == []
        assert tps == []
        assert model_name == "None"
        assert model_meta == "None"
    finally:
        monitor_tui.CSV_FILE = original_csv_file


def test_subpixel_resolution_and_braille_density_doubles_hd():
    assert monitor_tui.DEFAULT_MARKER == "braille"
    assert monitor_tui.MAX_POINTS == 120
    assert monitor_tui.SUBPIXEL_RESOLUTION == {
        "sd": (1, 1),
        "hd": (2, 2),
        "fhd": (2, 3),
        "braille": (2, 4),
    }

    hd_sub_x, hd_sub_y, hd_density = monitor_tui.get_subpixel_density("hd")
    br_sub_x, br_sub_y, br_density = monitor_tui.get_subpixel_density("braille")
    assert (hd_sub_x, hd_sub_y, hd_density) == (2, 2, 4)
    assert (br_sub_x, br_sub_y, br_density) == (2, 4, 8)
    assert br_density >= 2 * hd_density

    # Same terminal dimensions (cols:chars = 80x24)
    hd_w, hd_h, hd_total = monitor_tui.calculate_effective_resolution(80, 24, marker="hd")
    br_w, br_h, br_total = monitor_tui.calculate_effective_resolution(80, 24, marker="braille")
    assert (hd_w, hd_h, hd_total) == (160, 48, 7680)
    assert (br_w, br_h, br_total) == (160, 96, 15360)
    assert br_h >= 2 * hd_h
    assert br_total >= 2 * hd_total


def test_upsample_series_resolution_and_edge_cases():
    # Empty series
    assert monitor_tui.upsample_series([], [], factor=2) == ([], [])

    # Single-point series
    assert monitor_tui.upsample_series(["12:00:00"], [42.0], factor=3) == (["12:00:00"], [42.0])

    # Factor <= 1 leaves series unchanged
    assert monitor_tui.upsample_series(
        ["12:00:00", "12:00:01"], [10.0, 20.0], factor=1
    ) == (["12:00:00", "12:00:01"], [10.0, 20.0])

    # Multi-point linear interpolation with factor=2
    times, vals = monitor_tui.upsample_series(
        ["12:00:00", "12:00:01", "12:00:02"], [10.0, 20.0, 40.0], factor=2
    )
    assert len(vals) == 5
    assert vals == [10.0, 15.0, 20.0, 30.0, 40.0]
    assert len(times) == 5
    assert times[0] == "12:00:00"
    assert times[2] == "12:00:01"
    assert times[4] == "12:00:02"


def test_per_chart_timeline_refresh_intervals_and_window_slicing():
    chart_configs = {
        "cpu": {"refresh_interval": 1.0, "window": 4},
        "gpu": {"refresh_interval": 2.0, "window": 3},
        "ram": {"refresh_interval": 5.0, "window": 2},
        "tps": {"refresh_interval": 1.0, "window": 3},
    }
    state = {}

    times_t0 = ["12:00:00", "12:00:01", "12:00:02", "12:00:03", "12:00:04"]
    series_t0 = {
        "cpu": [10.0, 20.0, 30.0, 40.0, 50.0],
        "gpu": [10.0, 20.0, 30.0, 40.0, 50.0],
        "ram": [10.0, 20.0, 30.0, 40.0, 50.0],
        "tps": [1.0, 2.0, 3.0, 4.0, 5.0],
    }

    # Initial tick at t=10.0 initializes all charts with their respective windows
    monitor_tui.update_chart_timelines(
        times_t0, series_t0, chart_configs=chart_configs, refresh_state=state, now=10.0
    )
    assert state["cpu"]["values"] == [20.0, 30.0, 40.0, 50.0]
    assert state["gpu"]["values"] == [30.0, 40.0, 50.0]
    assert state["ram"]["values"] == [40.0, 50.0]
    assert state["tps"]["values"] == [3.0, 4.0, 5.0]

    # Tick at t=11.0 (+1.0s): cpu and tps update; gpu (2.0s) and ram (5.0s) keep cached series
    times_t1 = times_t0 + ["12:00:05"]
    series_t1 = {
        "cpu": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        "gpu": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        "ram": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        "tps": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    }
    monitor_tui.update_chart_timelines(
        times_t1, series_t1, chart_configs=chart_configs, refresh_state=state, now=11.0
    )
    assert state["cpu"]["values"] == [30.0, 40.0, 50.0, 60.0]
    assert state["tps"]["values"] == [4.0, 5.0, 6.0]
    assert state["gpu"]["values"] == [30.0, 40.0, 50.0]
    assert state["ram"]["values"] == [40.0, 50.0]

    # Tick at t=12.0 (+2.0s): gpu updates; ram still keeps cached series from t=10.0
    times_t2 = times_t1 + ["12:00:06"]
    series_t2 = {
        "cpu": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0],
        "gpu": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0],
        "ram": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0],
        "tps": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
    }
    monitor_tui.update_chart_timelines(
        times_t2, series_t2, chart_configs=chart_configs, refresh_state=state, now=12.0
    )
    assert state["gpu"]["values"] == [50.0, 60.0, 70.0]
    assert state["ram"]["values"] == [40.0, 50.0]

    # Tick at t=15.0 (+5.0s): ram now updates to latest 2 points
    monitor_tui.update_chart_timelines(
        times_t2, series_t2, chart_configs=chart_configs, refresh_state=state, now=15.0
    )
    assert state["ram"]["values"] == [60.0, 70.0]


def test_cli_parse_args_and_chart_config_builder():
    args = monitor_tui.parse_args([
        "--marker", "braille",
        "--resolution-factor", "3",
        "--max-points", "180",
        "--refresh-interval", "1.5",
        "--cpu-refresh", "0.5",
        "--ram-refresh", "4.0",
        "--gpu-window", "90",
        "--tps-window", "240",
    ])
    assert args.marker == "braille"
    assert args.resolution_factor == 3
    assert args.max_points == 180

    configs = monitor_tui.build_chart_configs_from_args(args)
    assert configs["cpu"]["refresh_interval"] == 0.5
    assert configs["cpu"]["window"] == 180
    assert configs["ram"]["refresh_interval"] == 4.0
    assert configs["ram"]["window"] == 180
    assert configs["gpu"]["refresh_interval"] == 1.5
    assert configs["gpu"]["window"] == 90
    assert configs["tps"]["refresh_interval"] == 1.5
    assert configs["tps"]["window"] == 240


def test_compute_xticks_adaptive_decimation_and_resize(monkeypatch):
    assert monitor_tui.compute_xticks([], term_width=80) == ([], [])
    assert monitor_tui.compute_xticks(["12:00:00"], term_width=80) == ([0], ["12:00:00"])

    many_times = [f"12:00:{i:02d}" for i in range(120)]
    narrow_idx, narrow_labels = monitor_tui.compute_xticks(many_times, term_width=80)
    wide_idx, wide_labels = monitor_tui.compute_xticks(many_times, term_width=200)

    assert narrow_idx[0] == 0
    assert narrow_idx[-1] == 119
    assert narrow_labels[0] == "12:00:00"
    assert narrow_labels[-1] == "12:01:59" if many_times[-1] == "12:01:59" else many_times[-1]
    assert 2 <= len(narrow_idx) <= 5
    assert len(wide_idx) > len(narrow_idx)

    # Verify SIGWINCH resize flag handling and terminal dimension clamping/fallback
    monitor_tui.consume_resize_event()
    monitor_tui.handle_sigwinch(None, None)
    assert monitor_tui.consume_resize_event() is True
    assert monitor_tui.consume_resize_event() is False

    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: (None, None))
    w, h = monitor_tui.get_terminal_dimensions(default_width=100, default_height=30)
    assert w >= 40 and h >= 12

    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: (10, 5))
    w_small, h_small = monitor_tui.get_terminal_dimensions(min_width=40, min_height=12)
    assert (w_small, h_small) == (40, 12)


def test_draw_dashboard_braille_marker_and_refresh_integration(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        temp_csv.write("12:00:00,10.0,20.0,8.0,15.0,qwen3,8B\n")
        temp_csv.write("malformed,row,not_a_float,1,2\n")
        temp_csv.write("12:00:01,30.0,40.0,8.5,25.0,qwen3,8B\n")
        temp_csv_path = temp_csv.name

    original_csv_file = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = temp_csv_path

    plot_calls = []
    monkeypatch.setattr(monitor_tui.plt, "clear_terminal", lambda: None)
    monkeypatch.setattr(monitor_tui.plt, "theme", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: (120, 40))
    monkeypatch.setattr(monitor_tui.plt, "plotsize", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "subplots", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "subplot", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "title", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "ylim", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "xticks", lambda *a, **k: None)
    monkeypatch.setattr(monitor_tui.plt, "show", lambda *a, **k: None)
    monkeypatch.setattr(
        monitor_tui.plt,
        "plot",
        lambda x, y, **kwargs: plot_calls.append((list(x), list(y), dict(kwargs))),
    )

    try:
        state = {}
        configs = {
            "cpu": {"refresh_interval": 1.0, "window": 10},
            "gpu": {"refresh_interval": 1.0, "window": 10},
            "ram": {"refresh_interval": 10.0, "window": 10},
            "tps": {"refresh_interval": 1.0, "window": 10},
        }
        monitor_tui.draw_dashboard(
            chart_configs=configs,
            refresh_state=state,
            now=100.0,
            marker="braille",
            resolution_factor=2,
        )
        assert len(plot_calls) == 4
        for _, y_vals, kwargs in plot_calls:
            assert kwargs.get("marker") == "braille"
            # 2 valid points upsampled with factor=2 -> 3 points
            assert len(y_vals) == 3

        # Append a 3rd valid point and redraw at t=101.0 (+1s): cpu updates to 5 upsampled points, ram stays at 3
        with open(temp_csv_path, "a") as f:
            f.write("12:00:02,50.0,60.0,9.0,35.0,qwen3,8B\n")

        plot_calls.clear()
        monitor_tui.draw_dashboard(
            chart_configs=configs,
            refresh_state=state,
            now=101.0,
            marker="braille",
            resolution_factor=2,
        )
        assert len(plot_calls) == 4
        cpu_call = plot_calls[0]
        ram_call = plot_calls[2]
        assert len(cpu_call[1]) == 5  # 3 points upsampled by factor 2 -> 5 points
        assert len(ram_call[1]) == 3  # Cached 2 points upsampled by factor 2 -> 3 points
    finally:
        monitor_tui.CSV_FILE = original_csv_file
        os.remove(temp_csv_path)

