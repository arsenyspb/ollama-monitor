import os
import signal
import subprocess
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


def test_monitor_tui_version_attribute_and_cli_flag():
    assert hasattr(monitor_tui, "__version__")
    assert isinstance(monitor_tui.__version__, str)
    assert len(monitor_tui.__version__.strip()) > 0

    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../src/monitor_tui.py")
    )
    result = subprocess.run(
        [sys.executable, script_path, "--version"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert "monitor_tui.py" in result.stdout
    assert monitor_tui.__version__ in result.stdout
    assert result.stderr == ""


def test_monitor_tui_version_no_side_effects(monkeypatch, capsys):
    def forbid_draw(*args, **kwargs):
        raise AssertionError("draw_dashboard must not run when --version is passed")

    monkeypatch.setattr(monitor_tui, "draw_dashboard", forbid_draw)
    monkeypatch.setattr(sys, "argv", ["monitor_tui.py", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        monitor_tui.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert monitor_tui.__version__ in captured.out


def test_chart_density_at_least_2x_and_upsampling(tmp_path):
    # Default window size is doubled from 60 to 120 points
    assert monitor_tui.MAX_POINTS >= 120
    assert monitor_tui.DEFAULT_MARKER == "braille"
    # Braille (2x4 = 8 subpixels/cell) vs HD (2x2 = 4 subpixels/cell) is >= 2x density
    assert monitor_tui.chart_density_ratio("braille", upsample_factor=2) >= 2.0

    # Upsampling doubles series point count while preserving endpoints & linearity
    x = [0, 1, 2, 3]
    y = [10.0, 20.0, 30.0, 40.0]
    x_up, y_up = monitor_tui.upsample_series(x, y, factor=2)
    assert len(x_up) == 2 * len(x)
    assert len(y_up) == 2 * len(y)
    assert x_up[0] == pytest.approx(0.0)
    assert x_up[-1] == pytest.approx(3.0)
    assert y_up[0] == pytest.approx(10.0)
    assert y_up[-1] == pytest.approx(40.0)
    # Check linearity
    for xi, yi in zip(x_up, y_up):
        assert yi == pytest.approx(10.0 + 10.0 * xi)

    # Verify read_data reads up to MAX_POINTS (120) by default and supports custom max_points
    csv_file = tmp_path / "metrics.csv"
    lines = ["Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n"]
    for i in range(150):
        lines.append(f"12:00:{i:02d},{i % 100},{i % 80},16.5,{i % 50},qwen,30B|Q4|18GB\n")
    csv_file.write_text("".join(lines))

    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = str(csv_file)
    try:
        times, cpu, gpu, ram, tps, model_name, model_meta = monitor_tui.read_data()
        assert len(times) == 120
        assert len(cpu) == 120

        times_custom, *_ = monitor_tui.read_data(max_points=45)
        assert len(times_custom) == 45
    finally:
        monitor_tui.CSV_FILE = original_csv


def test_adaptive_xticks_decimation():
    times = [f"12:{i // 60:02d}:{i % 60:02d}" for i in range(120)]
    tick_pos_narrow, tick_labels_narrow = monitor_tui.compute_xticks(times, width=80)
    tick_pos_wide, tick_labels_wide = monitor_tui.compute_xticks(times, width=200)

    assert 2 <= len(tick_pos_narrow) <= 6
    assert len(tick_pos_narrow) == len(tick_labels_narrow)
    assert tick_pos_narrow[0] == 0
    assert tick_pos_narrow[-1] == 119
    assert tick_labels_narrow[0] == times[0]
    assert tick_labels_narrow[-1] == times[-1]
    assert len(tick_pos_wide) >= len(tick_pos_narrow)


def test_per_chart_refresh_scheduler_and_windows(tmp_path):
    csv_file = tmp_path / "continuous_monitor.csv"

    def write_rows(count, base_val):
        rows = ["Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n"]
        for i in range(count):
            rows.append(
                f"12:00:{i:02d},{base_val + 1},{base_val + 2},{base_val + 3},{base_val + 4},llama3,8B|Q4|4.7GB\n"
            )
        csv_file.write_text("".join(rows))

    write_rows(20, 10.0)

    scheduler = monitor_tui.ChartRefreshScheduler(
        refresh_intervals={"cpu": 1.0, "gpu": 2.0, "ram": 5.0, "tps": 0.5},
        window_sizes={"cpu": 12, "gpu": 8, "ram": 6, "tps": 4},
        csv_file=str(csv_file),
    )

    # Initial tick at t=0.0 updates all charts with their configured window sizes
    updated_t0 = scheduler.update(now=0.0)
    assert updated_t0 == {"cpu", "gpu", "ram", "tps"}
    assert len(scheduler.get_series("cpu")[1]) == 12
    assert len(scheduler.get_series("gpu")[1]) == 8
    assert len(scheduler.get_series("ram")[1]) == 6
    assert len(scheduler.get_series("tps")[1]) == 4
    assert scheduler.get_series("cpu")[1][-1] == 11.0
    assert scheduler.get_series("tps")[1][-1] == 14.0

    # Write new values to CSV
    write_rows(20, 50.0)

    # At t=0.6, only TPS (0.5s refresh) is due
    updated_t06 = scheduler.update(now=0.6)
    assert updated_t06 == {"tps"}
    assert scheduler.get_series("tps")[1][-1] == 54.0
    assert scheduler.get_series("cpu")[1][-1] == 11.0
    assert scheduler.get_series("gpu")[1][-1] == 12.0
    assert scheduler.get_series("ram")[1][-1] == 13.0

    # At t=1.1, CPU (1.0s) and TPS (0.5s since 0.6) are due; GPU and RAM stay cached
    updated_t11 = scheduler.update(now=1.1)
    assert updated_t11 == {"cpu", "tps"}
    assert scheduler.get_series("cpu")[1][-1] == 51.0
    assert scheduler.get_series("gpu")[1][-1] == 12.0
    assert scheduler.get_series("ram")[1][-1] == 13.0

    # At t=2.1, GPU (2.0s) is now due; RAM (5.0s) still cached
    updated_t21 = scheduler.update(now=2.1)
    assert "gpu" in updated_t21
    assert "ram" not in updated_t21
    assert scheduler.get_series("gpu")[1][-1] == 52.0
    assert scheduler.get_series("ram")[1][-1] == 13.0

    # At t=5.1, RAM (5.0s) finally updates
    updated_t51 = scheduler.update(now=5.1)
    assert "ram" in updated_t51
    assert scheduler.get_series("ram")[1][-1] == 53.0


def test_cli_per_chart_flags_parsing():
    args = monitor_tui.parse_args(
        [
            "--refresh",
            "1.5",
            "--cpu-refresh",
            "0.5",
            "--gpu-refresh",
            "2.5",
            "--ram-refresh",
            "4.0",
            "--tps-refresh",
            "0.25",
            "--window",
            "120",
            "--cpu-window",
            "240",
            "--gpu-window",
            "90",
            "--ram-window",
            "180",
            "--tps-window",
            "60",
            "--marker",
            "braille",
            "--upsample",
            "3",
        ]
    )
    scheduler = monitor_tui.scheduler_from_args(args)
    assert scheduler.refresh_intervals == {
        "cpu": 0.5,
        "gpu": 2.5,
        "ram": 4.0,
        "tps": 0.25,
    }
    assert scheduler.window_sizes == {
        "cpu": 240,
        "gpu": 90,
        "ram": 180,
        "tps": 60,
    }
    assert args.marker == "braille"
    assert args.upsample == 3


def test_draw_dashboard_braille_and_sigwinch_resize(monkeypatch, tmp_path):
    csv_file = tmp_path / "continuous_monitor.csv"
    csv_file.write_text(
        "Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n"
        "12:00:00,20.0,30.0,12.0,15.0,llama3,8B|Q4|4.7GB\n"
        "12:00:01,40.0,50.0,12.5,25.0,llama3,8B|Q4|4.7GB\n"
        "12:00:02,60.0,70.0,13.0,35.0,llama3,8B|Q4|4.7GB\n"
    )
    monkeypatch.setattr(monitor_tui, "CSV_FILE", str(csv_file))

    plotted_calls = []
    plotsize_calls = []

    orig_plot = monitor_tui.plt.plot
    orig_plotsize = monitor_tui.plt.plotsize

    def record_plot(x, y, **kwargs):
        plotted_calls.append((list(x), list(y), dict(kwargs)))
        return orig_plot(x, y, **kwargs)

    def record_plotsize(w, h):
        plotsize_calls.append((w, h))
        return orig_plotsize(w, h)

    monkeypatch.setattr(monitor_tui.plt, "plot", record_plot)
    monkeypatch.setattr(monitor_tui.plt, "plotsize", record_plotsize)
    monkeypatch.setattr(monitor_tui.plt, "show", lambda: None)
    monkeypatch.setattr(monitor_tui.plt, "clear_terminal", lambda: None)

    term_size = [100, 30]
    monkeypatch.setattr(
        monitor_tui, "get_terminal_dimensions", lambda fallback=(120, 40): tuple(term_size)
    )

    scheduler = monitor_tui.ChartRefreshScheduler(csv_file=str(csv_file))
    monitor_tui.draw_dashboard(scheduler=scheduler, now=0.0)

    assert len(plotted_calls) == 4
    for x_vals, y_vals, kwargs in plotted_calls:
        assert kwargs.get("marker") == "braille"
        # 3 raw points upsampled by 2x -> 6 points
        assert len(x_vals) == 6
        assert len(y_vals) == 6
    assert plotsize_calls[-1] == (100, 27)

    # Simulate terminal resize via SIGWINCH handler
    term_size[:] = [160, 48]
    monitor_tui.handle_sigwinch(getattr(signal, "SIGWINCH", 28), None)
    assert monitor_tui.consume_resize_event() is True
    monitor_tui.draw_dashboard(scheduler=scheduler, now=0.1)
    assert plotsize_calls[-1] == (160, 45)

