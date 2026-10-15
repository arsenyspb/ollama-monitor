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


def test_version_defined_and_valid_semver():
    import re

    assert hasattr(monitor_tui, "__version__")
    assert isinstance(monitor_tui.__version__, str)
    assert re.match(
        r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        monitor_tui.__version__,
    )


def test_monitor_tui_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        monitor_tui.main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert monitor_tui.__version__ in captured.out


def test_monitor_tui_short_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        monitor_tui.main(["-V"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert monitor_tui.__version__ in captured.out


@pytest.mark.parametrize("release_version", ["0.2.0", "1.0.0", "2.3.4-rc.1"])
def test_monitor_tui_version_future_releases(monkeypatch, capsys, release_version):
    monkeypatch.setattr(monitor_tui, "__version__", release_version)

    with pytest.raises(SystemExit) as exc_info:
        monitor_tui.main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert release_version in captured.out


def test_monitor_tui_cli_subprocess_version():
    import subprocess

    assert hasattr(monitor_tui, "__version__")
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../src/monitor_tui.py")
    )
    result = subprocess.run(
        [sys.executable, script_path, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0
    assert monitor_tui.__version__ in result.stdout


@pytest.mark.parametrize(
    "script_name", ["bench_monitor.sh", "continuous_monitor.sh"]
)
def test_shell_scripts_version_flag(script_name):
    import subprocess

    assert hasattr(monitor_tui, "__version__")
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../src", script_name)
    )
    result = subprocess.run(
        ["bash", script_path, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0
    assert monitor_tui.__version__ in result.stdout

