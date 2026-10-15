import sys
import os
import pytest
from unittest.mock import Mock, patch

# Add src to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from ollama_proxy import extract_tps_from_line, forward_data

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

@patch('ollama_proxy.time.time')
def test_forward_data_openai_continuous_tps(mock_time, tmp_path):
    import ollama_proxy
    # Redirect TPS_FILE to a temp file
    temp_tps = tmp_path / "tps.txt"
    original_tps_file = ollama_proxy.TPS_FILE
    ollama_proxy.TPS_FILE = str(temp_tps)
    
    src = Mock()
    dst = Mock()
    
    # 0.0: first chunk (start)
    # 0.1: second chunk (no update because 0.1 - 0.0 < 0.2)
    # 0.3: third chunk (update because 0.3 - 0.0 >= 0.2)
    # 0.4: DONE (final update)
    
    times = [0.0, 0.1, 0.3, 0.4]
    mock_time.side_effect = times + [0.4] * 10
    
    src.recv.side_effect = [
        b'data: {"id":"1","object":"chat.completion.chunk","choices":[{"delta":{"content":"A"}}]}\n',
        b'data: {"id":"1","object":"chat.completion.chunk","choices":[{"delta":{"content":"B"}}]}\n',
        b'data: {"id":"1","object":"chat.completion.chunk","choices":[{"delta":{"content":"C"}}]}\n',
        b'data: [DONE]\n',
        b'' # EOF
    ]
    
    state = {'request_start': None}
    forward_data(src, dst, is_response=True, state=state)
    
    # Restore original path
    ollama_proxy.TPS_FILE = original_tps_file
    
    assert temp_tps.exists()
    content = temp_tps.read_text().strip()
    assert content == "7.50"


def test_proxy_version_defined_and_matches_tui():
    import re
    import monitor_tui
    import ollama_proxy

    assert hasattr(ollama_proxy, "__version__")
    assert isinstance(ollama_proxy.__version__, str)
    assert re.match(
        r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        ollama_proxy.__version__,
    )
    assert ollama_proxy.__version__ == monitor_tui.__version__


def test_proxy_version_flag(capsys):
    import ollama_proxy

    with pytest.raises(SystemExit) as exc_info:
        ollama_proxy.main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert ollama_proxy.__version__ in captured.out


def test_proxy_short_version_flag(capsys):
    import ollama_proxy

    with pytest.raises(SystemExit) as exc_info:
        ollama_proxy.main(["-V"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert ollama_proxy.__version__ in captured.out


@pytest.mark.parametrize("release_version", ["0.2.0", "1.0.0", "2.3.4-rc.1"])
def test_proxy_version_future_releases(monkeypatch, capsys, release_version):
    import ollama_proxy

    monkeypatch.setattr(ollama_proxy, "__version__", release_version)

    with pytest.raises(SystemExit) as exc_info:
        ollama_proxy.main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert release_version in captured.out


def test_proxy_cli_subprocess_version():
    import subprocess
    import ollama_proxy

    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../src/ollama_proxy.py")
    )
    result = subprocess.run(
        [sys.executable, script_path, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0
    assert ollama_proxy.__version__ in result.stdout

