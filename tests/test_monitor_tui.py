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


def _create_sample_csv(num_rows=50):
    temp = tempfile.NamedTemporaryFile(mode='w', delete=False)
    temp.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
    for i in range(num_rows):
        temp.write(f"12:{i//60:02d}:{i%60:02d},{10.0 + i*0.5},{2000 + i*10},{4.0 + i*0.1},{20.0 + i*0.2},llama3,8B|Q4|4.7GB\n")
    temp.close()
    return temp.name


def test_read_data_custom_max_points():
    csv_path = _create_sample_csv(100)
    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = csv_path
    try:
        times, cpu, gpu, ram, tps, _, _ = monitor_tui.read_data(max_points=80)
        assert len(times) == 80
        assert len(cpu) == 80

        times_20, _, _, _, _, _, _ = monitor_tui.read_data(max_points=20)
        assert len(times_20) == 20

        times_default, _, _, _, _, _, _ = monitor_tui.read_data()
        assert len(times_default) == monitor_tui.MAX_POINTS
    finally:
        monitor_tui.CSV_FILE = original_csv
        os.remove(csv_path)


def test_default_marker_doubles_resolution():
    # SOTA 2026 canonical TUI resolution: Braille (2x4 subpixel density per cell)
    # compared to half-block 'hd' (2x2 subpixel density per cell).
    assert monitor_tui.DEFAULT_MARKER == "braille"
    
    res_braille = monitor_tui.get_marker_resolution("braille")
    res_hd = monitor_tui.get_marker_resolution("hd")
    res_sd = monitor_tui.get_marker_resolution("sd")

    # Braille gives (2, 4) subpixels per cell -> 8 subpixels
    assert res_braille == (2, 4)
    # HD gives (2, 2) subpixels per cell -> 4 subpixels
    assert res_hd == (2, 2)
    # SD gives (1, 1) subpixels per cell -> 1 subpixel
    assert res_sd == (1, 1)

    # Resolution is at least doubled compared to original 'hd' (8 vs 4 dots per char cell)
    subpixels_braille = res_braille[0] * res_braille[1]
    subpixels_hd = res_hd[0] * res_hd[1]
    assert subpixels_braille >= 2 * subpixels_hd


def test_draw_dashboard_renders_braille_by_default():
    csv_path = _create_sample_csv(30)
    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = csv_path
    try:
        output = monitor_tui.draw_dashboard(build_only=True)
        assert isinstance(output, str)
        assert "CPU Usage (%)" in output
        assert "GPU Load (%)" in output
        assert "RAM Used (GB)" in output
        assert "Tokens Per Second (TPS)" in output

        # Check for Unicode Braille Pattern characters (U+2800 to U+28FF)
        braille_chars = [c for c in output if 0x2800 <= ord(c) <= 0x28FF]
        assert len(braille_chars) > 0, "Default dashboard output must contain Braille characters for increased density"
    finally:
        monitor_tui.CSV_FILE = original_csv
        os.remove(csv_path)


def test_per_chart_configurable_density_marker():
    csv_path = _create_sample_csv(30)
    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = csv_path
    try:
        # All HD markers: no Braille characters
        output_hd = monitor_tui.draw_dashboard(
            marker={"cpu": "hd", "gpu": "hd", "ram": "hd", "tps": "hd"},
            build_only=True
        )
        braille_in_hd = [c for c in output_hd if 0x2800 <= ord(c) <= 0x28FF]
        assert len(braille_in_hd) == 0

        # CPU alone with braille, others HD
        output_mixed = monitor_tui.draw_dashboard(
            marker={"cpu": "braille", "gpu": "hd", "ram": "hd", "tps": "hd"},
            build_only=True
        )
        braille_in_mixed = [c for c in output_mixed if 0x2800 <= ord(c) <= 0x28FF]
        assert len(braille_in_mixed) > 0
    finally:
        monitor_tui.CSV_FILE = original_csv
        os.remove(csv_path)


def test_per_chart_configurable_timeline():
    csv_path = _create_sample_csv(50)
    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = csv_path
    try:
        state = monitor_tui.DashboardState(timeline={"cpu": 10, "gpu": 20, "ram": 30, "tps": 5})
        data = state.get_chart_slices()
        assert len(data["cpu"]["y"]) == 10
        assert len(data["gpu"]["y"]) == 20
        assert len(data["ram"]["y"]) == 30
        assert len(data["tps"]["y"]) == 5
    finally:
        monitor_tui.CSV_FILE = original_csv
        os.remove(csv_path)


def test_per_chart_configurable_refresh():
    csv_path = _create_sample_csv(50)
    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = csv_path
    try:
        state = monitor_tui.DashboardState(
            timeline={"cpu": 20, "ram": 20},
            refresh={"cpu": 1.0, "ram": 5.0}
        )
        # At t=0.0: initial fetch
        slices_t0 = state.get_chart_slices(current_time=0.0)
        assert len(slices_t0["cpu"]["y"]) == 20
        cpu_val_t0 = slices_t0["cpu"]["y"][-1]
        ram_val_t0 = slices_t0["ram"]["y"][-1]

        # Append new row with changed values
        with open(csv_path, 'a') as f:
            f.write("12:01:00,99.9,2000,99.9,20.0,llama3,8B|Q4|4.7GB\n")

        # At t=1.0: CPU should update (1.0s elapsed), RAM should stay cached (needs 5.0s)
        slices_t1 = state.get_chart_slices(current_time=1.0)
        assert slices_t1["cpu"]["y"][-1] == 99.9
        assert slices_t1["ram"]["y"][-1] == ram_val_t0

        # At t=5.0: RAM should now update
        slices_t5 = state.get_chart_slices(current_time=5.0)
        assert slices_t5["ram"]["y"][-1] == 99.9
    finally:
        monitor_tui.CSV_FILE = original_csv
        os.remove(csv_path)


def test_cli_and_env_configuration_parsing(monkeypatch):
    # Test env vars
    monkeypatch.setenv("TUI_DENSITY", "sd")
    monkeypatch.setenv("TIMELINE_POINTS", "45")
    monkeypatch.setenv("TIMELINE_RAM", "90")
    monkeypatch.setenv("REFRESH_INTERVAL", "2.5")
    monkeypatch.setenv("REFRESH_CPU", "0.5")

    cfg = monitor_tui.parse_config([])
    assert cfg.marker["cpu"] == "sd"
    assert cfg.marker["ram"] == "sd"
    assert cfg.timeline["cpu"] == 45
    assert cfg.timeline["ram"] == 90
    assert cfg.refresh["cpu"] == 0.5
    assert cfg.refresh["ram"] == 2.5

    # Test CLI overrides
    cli_cfg = monitor_tui.parse_config([
        "--density", "braille",
        "--density-gpu", "hd",
        "--timeline-cpu", "15",
        "--refresh-ram", "10.0"
    ])
    assert cli_cfg.marker["cpu"] == "braille"
    assert cli_cfg.marker["gpu"] == "hd"
    assert cli_cfg.timeline["cpu"] == 15
    assert cli_cfg.refresh["ram"] == 10.0

