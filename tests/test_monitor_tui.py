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

def test_density_resolution_doubling():
    # SOTA 2026: Braille (2x4 dot matrix = 8 subpixels per char) doubles resolution over HD (2x2 = 4)
    res_braille = monitor_tui.get_marker_resolution("braille")
    res_hd = monitor_tui.get_marker_resolution("hd")
    assert res_braille["subpixels"] >= 2 * res_hd["subpixels"]
    assert res_braille["vertical_factor"] >= 2 * res_hd["vertical_factor"]
    assert monitor_tui.DEFAULT_DENSITY == "braille"

def test_chart_config_per_chart():
    config = monitor_tui.DashboardConfig(
        default_density="braille",
        charts={
            "cpu": monitor_tui.ChartConfig(name="cpu", density="braille", timeline=30, refresh_interval=1.0),
            "gpu": monitor_tui.ChartConfig(name="gpu", density="hd", timeline=15, refresh_interval=2.0),
            "ram": monitor_tui.ChartConfig(name="ram", density="braille", timeline=60, refresh_interval=5.0),
            "tps": monitor_tui.ChartConfig(name="tps", density="braille", timeline=20, refresh_interval=0.5),
        }
    )
    assert config.charts["cpu"].density == "braille"
    assert config.charts["cpu"].timeline == 30
    assert config.charts["gpu"].density == "hd"
    assert config.charts["gpu"].refresh_interval == 2.0

def test_per_chart_timeline_and_refresh():
    # Setup test CSV with 5 data rows
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        for i in range(5):
            temp_csv.write(f"12:00:0{i},{10.0 + i},{2000 + i * 100},{4.0 + i * 0.1},{20.0 + i},m,m\n")
        temp_csv_path = temp_csv.name

    original_csv_file = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = temp_csv_path

    try:
        config = monitor_tui.DashboardConfig(
            charts={
                "cpu": monitor_tui.ChartConfig(name="cpu", timeline=3, refresh_interval=1.0),
                "gpu": monitor_tui.ChartConfig(name="gpu", timeline=5, refresh_interval=1.0),
                "ram": monitor_tui.ChartConfig(name="ram", timeline=2, refresh_interval=10.0),
                "tps": monitor_tui.ChartConfig(name="tps", timeline=4, refresh_interval=1.0),
            }
        )
        state = monitor_tui.DashboardState()

        # First refresh at t=100.0
        chart_data_1 = monitor_tui.get_dashboard_data(config, state, current_time=100.0)
        # CPU timeline is 3
        assert len(chart_data_1["cpu"]["y"]) == 3
        assert chart_data_1["cpu"]["y"] == [12.0, 13.0, 14.0]
        # GPU timeline is 5
        assert len(chart_data_1["gpu"]["y"]) == 5
        # RAM timeline is 2
        assert len(chart_data_1["ram"]["y"]) == 2
        assert chart_data_1["ram"]["y"] == [4.3, 4.4]

        # Add a new line to CSV
        with open(temp_csv_path, 'a') as f:
            f.write("12:00:05,99.0,5000,9.9,50.0,m,m\n")

        # Second refresh at t=101.5: CPU should update (refresh 1.0 elapsed), RAM should NOT update (refresh 10.0 not elapsed)
        chart_data_2 = monitor_tui.get_dashboard_data(config, state, current_time=101.5)
        # CPU updated with new value 99.0
        assert chart_data_2["cpu"]["y"][-1] == 99.0
        # RAM retained cached data (did not update yet)
        assert chart_data_2["ram"]["y"] == [4.3, 4.4]

        # Third refresh at t=111.0: RAM refresh interval (10.0s) has now elapsed
        chart_data_3 = monitor_tui.get_dashboard_data(config, state, current_time=111.0)
        assert chart_data_3["ram"]["y"][-1] == 9.9
    finally:
        monitor_tui.CSV_FILE = original_csv_file
        os.remove(temp_csv_path)

def test_cli_argument_parsing():
    args = monitor_tui.parse_args([
        "--density", "braille",
        "--timeline", "45",
        "--refresh", "2.5",
        "--cpu-density", "fhd",
        "--gpu-timeline", "15",
        "--ram-refresh", "5.0",
        "--once"
    ])
    assert args.density == "braille"
    assert args.timeline == 45
    assert args.refresh == 2.5
    assert args.cpu_density == "fhd"
    assert args.gpu_timeline == 15
    assert args.ram_refresh == 5.0
    assert args.once is True

def test_draw_dashboard_once_runs_without_error():
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_csv:
        temp_csv.write("Timestamp,CPU_Usage_%,GPU_Power_mW,RAM_Used_GB,Eval_TPS,Model_Name,Model_Metadata\n")
        temp_csv.write("12:00:00,10.0,2000,4.0,25.0,test_model,meta\n")
        temp_csv_path = temp_csv.name

    original_csv = monitor_tui.CSV_FILE
    monitor_tui.CSV_FILE = temp_csv_path
    try:
        config = monitor_tui.DashboardConfig(default_density="braille")
        monitor_tui.draw_dashboard(config=config)
    finally:
        monitor_tui.CSV_FILE = original_csv
        os.remove(temp_csv_path)

