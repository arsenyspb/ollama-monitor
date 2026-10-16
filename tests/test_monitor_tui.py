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
    # Default marker must be braille (2x4 = 8 subpixels/cell vs 2x2 = 4 in hd and 1x1 = 1 in sd)
    assert monitor_tui.DEFAULT_MARKER == "braille"
    assert monitor_tui.MAX_POINTS >= 120

    hd_subcols, hd_subrows = monitor_tui.get_marker_subpixels("hd")
    br_subcols, br_subrows = monitor_tui.get_marker_subpixels("braille")
    assert (hd_subcols, hd_subrows) == (2, 2)
    assert (br_subcols, br_subrows) == (2, 4)

    cols, rows = 80, 24
    hd_w, hd_h = monitor_tui.get_effective_resolution(cols, rows, marker="hd")
    br_w, br_h = monitor_tui.get_effective_resolution(cols, rows, marker="braille")

    # In the exact same cols:chars (80x24), braille doubles vertical resolution and total subpixel density over hd
    assert br_w == hd_w == cols * 2
    assert br_h >= hd_h * 2
    assert (br_w * br_h) >= 2 * (hd_w * hd_h)


def test_draw_dashboard_uses_braille_and_configurable_per_chart_windows(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        for i in range(100):
            temp_csv.write(f"12:00:{i % 60:02d},{10 + (i % 70)},{20 + (i % 60)},{8.0 + (i * 0.05):.2f},{15.0 + (i % 25):.2f},llama3,8B|Q4|4.7GB\n")
        temp_csv_path = temp_csv.name

    monkeypatch.setattr(monitor_tui, "CSV_FILE", temp_csv_path)
    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: [100, 30])

    plotted = []
    orig_plot = monitor_tui.plt.plot

    def spy_plot(x, y, *args, **kwargs):
        plotted.append((list(x), list(y), kwargs.get("marker"), kwargs.get("color")))
        return orig_plot(x, y, *args, **kwargs)

    monkeypatch.setattr(monitor_tui.plt, "plot", spy_plot)

    try:
        monitor_tui.reset_chart_cache()
        windows = {"cpu": 20, "gpu": 35, "ram": 50, "tps": 75}
        monitor_tui.draw_dashboard(chart_windows=windows)

        assert len(plotted) == 4
        assert [len(call[1]) for call in plotted] == [20, 35, 50, 75]
        assert all(call[2] == "braille" for call in plotted)

        # Verify rendered canvas contains Unicode Braille characters (U+2800..U+28FF)
        canvas = monitor_tui.plt.uncolorize(monitor_tui.plt.build())
        assert any(0x2800 <= ord(ch) <= 0x28FF for ch in canvas)
    finally:
        os.remove(temp_csv_path)


def test_draw_dashboard_configurable_per_chart_refresh_intervals(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        temp_csv.write("12:00:00,10.0,20.0,4.0,12.0,llama3,8B|Q4|4.7GB\n")
        temp_csv_path = temp_csv.name

    monkeypatch.setattr(monitor_tui, "CSV_FILE", temp_csv_path)
    monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: [100, 30])

    plotted = []
    orig_plot = monitor_tui.plt.plot

    def spy_plot(x, y, *args, **kwargs):
        plotted.append((list(x), list(y)))
        return orig_plot(x, y, *args, **kwargs)

    monkeypatch.setattr(monitor_tui.plt, "plot", spy_plot)

    intervals = {"cpu": 1.0, "gpu": 1.0, "ram": 5.0, "tps": 5.0}

    try:
        monitor_tui.reset_chart_cache()

        # Initial draw at t=100.0 populates all charts
        monitor_tui.draw_dashboard(chart_refresh_intervals=intervals, now=100.0)
        assert [call[1][-1] for call in plotted] == [10.0, 20.0, 4.0, 12.0]
        plotted.clear()

        # Append a new row
        with open(temp_csv_path, "a") as f:
            f.write("12:00:01,85.0,75.0,9.5,42.0,llama3,8B|Q4|4.7GB\n")

        # At t=101.2, only cpu and gpu (1.0s refresh) should update; ram and tps (5.0s refresh) remain cached
        monitor_tui.draw_dashboard(chart_refresh_intervals=intervals, now=101.2)
        assert [call[1][-1] for call in plotted] == [85.0, 75.0, 4.0, 12.0]
        plotted.clear()

        # At t=105.5, ram and tps refresh intervals have elapsed and update to the new row
        monitor_tui.draw_dashboard(chart_refresh_intervals=intervals, now=105.5)
        assert [call[1][-1] for call in plotted] == [85.0, 75.0, 9.5, 42.0]
    finally:
        os.remove(temp_csv_path)


def test_draw_dashboard_handles_modern_terminal_resizing(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        temp_csv.write("12:00:00,25.0,30.0,6.0,18.0,llama3,8B|Q4|4.7GB\n")
        temp_csv.write("12:00:01,55.0,60.0,6.5,24.0,llama3,8B|Q4|4.7GB\n")
        temp_csv_path = temp_csv.name

    monkeypatch.setattr(monitor_tui, "CSV_FILE", temp_csv_path)

    try:
        monitor_tui.reset_chart_cache()

        # Start at 80x24
        monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: [80, 24])
        monitor_tui.draw_dashboard()
        lines_small = monitor_tui.plt.uncolorize(monitor_tui.plt.build()).splitlines()
        assert len(lines_small[0]) == 80
        assert len(lines_small) == 21  # h - 3

        # Resize upward to modern 160x48 terminal
        monkeypatch.setattr(monitor_tui.plt, "terminal_size", lambda: [160, 48])
        monitor_tui.draw_dashboard()
        lines_large = monitor_tui.plt.uncolorize(monitor_tui.plt.build()).splitlines()
        assert len(lines_large[0]) == 160
        assert len(lines_large) == 45  # h - 3
        # Ensure previous frame's signals were cleared rather than duplicated
        assert len(monitor_tui.plt._global.figure._get_subplot(1, 1).monitor.x) == 1
    finally:
        os.remove(temp_csv_path)


def test_parse_args_per_chart_configuration():
    args = monitor_tui.parse_args([
        "--window", "120",
        "--tps-window", "240",
        "--refresh", "0.5",
        "--ram-refresh", "3.0",
        "--marker", "braille",
    ])
    assert args.window == 120
    assert args.tps_window == 240
    assert args.refresh == 0.5
    assert args.ram_refresh == 3.0
    assert args.marker == "braille"

