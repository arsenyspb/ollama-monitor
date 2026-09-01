import sys
import os
import pytest

# Add src to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from ollama_proxy import extract_tps_from_line

def test_extract_tps_from_line_valid_json():
    # Arrange
    line = '{"model":"mixtral:8x7b","created_at":"2023-11-09T08:59:22.23Z","done":true,"eval_count":57,"eval_duration":991130000}'
    
    # Act
    tps = extract_tps_from_line(line)
    
    # Assert
    # 57 / (991130000 / 1e9) = 57.5101147175
    assert tps is not None
    assert round(tps, 2) == 57.51

def test_extract_tps_from_line_incomplete():
    # Arrange
    line = '{"model":"mixtral:8x7b","done":false,"response":"Hello"}'
    
    # Act
    tps = extract_tps_from_line(line)
    
    # Assert
    assert tps is None

def test_extract_tps_from_line_zero_duration():
    # Arrange
    line = '{"eval_count":10,"eval_duration":0}'
    
    # Act
    tps = extract_tps_from_line(line)
    
    # Assert
    assert tps is None
