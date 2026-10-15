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


def test_default_resolution_at_least_doubles_original_in_same_cols_chars():
    hd_res = monitor_tui.get_chart_resolution(80, 24, marker="hd")
    default_res = monitor_tui.get_chart_resolution(80, 24, marker=monitor_tui.DEFAULT_MARKER)

    assert monitor_tui.DEFAULT_MARKER == "braille"
    assert default_res["cols"] == hd_res["cols"] == 80
    assert default_res["rows"] == hd_res["rows"] == 24
    assert default_res["subpixels_per_cell"] >= 2 * hd_res["subpixels_per_cell"]
    assert default_res["total_subpixels"] >= 2 * hd_res["total_subpixels"]
    assert monitor_tui.MAX_POINTS >= 120


def test_upsample_series_doubles_point_density():
    x = [0, 1, 2]
    y = [10.0, 20.0, 40.0]
    ux, uy = monitor_tui.upsample_series(x, y, factor=2)

    assert len(ux) == 5
    assert len(uy) == 5
    assert ux == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert uy == [10.0, 15.0, 20.0, 30.0, 40.0]


def test_draw_dashboard_renders_high_density_braille_markers(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        temp_csv.write("12:00:00,10.0,20.0,4.0,15.0,llama3,8B|Q4|4.7GB\n")
        temp_csv.write("12:00:01,20.0,40.0,4.5,25.0,llama3,8B|Q4|4.7GB\n")
        temp_csv.write("12:00:02,30.0,60.0,5.0,35.0,llama3,8B|Q4|4.7GB\n")
        temp_csv_path = temp_csv.name

    original_csv_file = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = temp_csv_path
    monitor_tui.reset_refresh_state()

    plot_calls = []
    orig_plot = monitor_tui.plt.plot

    def spy_plot(x, y, *args, **kwargs):
        plot_calls.append((list(x), list(y), kwargs.copy()))
        return orig_plot(x, y, *args, **kwargs)

    monkeypatch.setattr(monitor_tui.plt, "plot", spy_plot)
    monkeypatch.setattr(monitor_tui.plt, "show", lambda: None)
    monkeypatch.setattr(monitor_tui.plt, "clear_terminal", lambda: None)
    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: (120, 40))

    try:
        monitor_tui.draw_dashboard(now=10.0)
        assert len(plot_calls) == 4
        for xs, ys, kwargs in plot_calls:
            assert kwargs.get("marker") == "braille"
            # 3 raw points upsampled with factor=2 -> 5 plotted points
            assert len(xs) == 5
            assert len(ys) == 5
    finally:
        monitor_tui.CSV_FILE = original_csv_file
        monitor_tui.reset_refresh_state()
        os.remove(temp_csv_path)


def test_configurable_timeline_refresh_per_chart(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        temp_csv.write("12:00:00,10.0,20.0,4.0,5.0,llama3,8B\n")
        temp_csv.write("12:00:01,12.0,22.0,4.2,6.0,llama3,8B\n")
        temp_csv_path = temp_csv.name

    original_csv_file = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = temp_csv_path
    monitor_tui.reset_refresh_state()

    plot_calls = []
    monkeypatch.setattr(
        monitor_tui.plt,
        "plot",
        lambda x, y, *a, **kw: plot_calls.append((list(x), list(y), kw.copy())),
    )
    monkeypatch.setattr(monitor_tui.plt, "show", lambda: None)
    monkeypatch.setattr(monitor_tui.plt, "clear_terminal", lambda: None)
    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: (100, 30))

    refresh_cfg = {"cpu": 1.0, "gpu": 1.0, "ram": 5.0, "tps": 10.0}
    window_cfg = {"cpu": 2, "gpu": 3, "ram": 3, "tps": 3}

    try:
        # Initial draw at t=0.0 populates all 4 charts
        monitor_tui.draw_dashboard(
            now=0.0,
            refresh_intervals=refresh_cfg,
            timeline_points=window_cfg,
            density_factor=1,
        )
        assert len(plot_calls) == 4
        assert plot_calls[0][1] == [10.0, 12.0]  # CPU
        assert plot_calls[2][1] == [4.0, 4.2]    # RAM
        assert plot_calls[3][1] == [5.0, 6.0]    # TPS

        # Append a new row to CSV
        with open(temp_csv_path, "a") as f:
            f.write("12:00:02,50.0,80.0,9.5,42.0,llama3,8B\n")

        # At t=1.5: CPU and GPU refresh (interval 1.0s), RAM (5.0s) and TPS (10.0s) keep cached timeline
        plot_calls.clear()
        monitor_tui.draw_dashboard(
            now=1.5,
            refresh_intervals=refresh_cfg,
            timeline_points=window_cfg,
            density_factor=1,
        )
        assert plot_calls[0][1] == [12.0, 50.0]       # CPU refreshed & sliced to window=2
        assert plot_calls[1][1] == [20.0, 22.0, 80.0] # GPU refreshed & sliced to window=3
        assert plot_calls[2][1] == [4.0, 4.2]         # RAM not due yet
        assert plot_calls[3][1] == [5.0, 6.0]         # TPS not due yet

        # At t=5.5: RAM refreshes (5.5 >= 5.0), TPS still cached (5.5 < 10.0)
        plot_calls.clear()
        monitor_tui.draw_dashboard(
            now=5.5,
            refresh_intervals=refresh_cfg,
            timeline_points=window_cfg,
            density_factor=1,
        )
        assert plot_calls[2][1] == [4.0, 4.2, 9.5]    # RAM refreshed
        assert plot_calls[3][1] == [5.0, 6.0]         # TPS still cached

        assert monitor_tui.get_loop_sleep_interval(refresh_cfg) == 1.0
    finally:
        monitor_tui.CSV_FILE = original_csv_file
        monitor_tui.reset_refresh_state()
        os.remove(temp_csv_path)


def test_parse_args_and_timeline_ticks():
    args = monitor_tui.parse_args([
        "--marker", "fhd",
        "--max-points", "180",
        "--cpu-refresh", "0.5",
        "--ram-refresh", "4.0",
        "--tps-window", "90",
    ])
    assert args.marker == "fhd"
    assert args.max_points == 180
    assert args.cpu_refresh == 0.5
    assert args.ram_refresh == 4.0
    assert args.tps_window == 90

    x = list(range(10))
    times = [f"12:00:0{i}" for i in range(10)]
    tick_pos, tick_labels = monitor_tui.build_timeline_ticks(x, times, max_ticks=4)
    assert len(tick_pos) == 4
    assert tick_labels[0] == "12:00:00"
    assert tick_labels[-1] == "12:00:09"

