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
