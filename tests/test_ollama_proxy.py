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

def test_forward_data_native_eval_tps(tmp_path):
    import ollama_proxy
    temp_tps = tmp_path / "tps.txt"
    original_tps_file = ollama_proxy.TPS_FILE
    ollama_proxy.TPS_FILE = str(temp_tps)
    
    src = Mock()
    dst = Mock()
    src.recv.side_effect = [
        b'{"model":"llama3","done":true,"eval_count":60,"eval_duration":1000000000}\n',
        b''
    ]
    state = {'request_start': None}
    
    try:
        forward_data(src, dst, is_response=True, state=state)
        assert temp_tps.exists()
        assert temp_tps.read_text().strip() == "60.00"
    finally:
        ollama_proxy.TPS_FILE = original_tps_file

def test_forward_data_eof_without_newline(tmp_path):
    import ollama_proxy
    temp_tps = tmp_path / "tps.txt"
    original_tps_file = ollama_proxy.TPS_FILE
    ollama_proxy.TPS_FILE = str(temp_tps)
    
    src = Mock()
    dst = Mock()
    # Note: No trailing newline before EOF
    src.recv.side_effect = [
        b'{"model":"llama3","done":true,"eval_count":80,"eval_duration":2000000000}',
        b''
    ]
    state = {'request_start': None}
    
    try:
        forward_data(src, dst, is_response=True, state=state)
        assert temp_tps.exists()
        assert temp_tps.read_text().strip() == "40.00"
    finally:
        ollama_proxy.TPS_FILE = original_tps_file

@patch('ollama_proxy.time.time')
def test_forward_data_lines_over_64kb(mock_time, tmp_path):
    import ollama_proxy
    temp_tps = tmp_path / "tps.txt"
    original_tps_file = ollama_proxy.TPS_FILE
    ollama_proxy.TPS_FILE = str(temp_tps)
    
    src = Mock()
    dst = Mock()
    
    # 70KB of content inside one chunk
    big_content = "x" * 70000
    mock_time.side_effect = [0.0, 0.5, 0.5, 0.5, 0.5]
    
    chunk = f'data: {{"id":"1","object":"chat.completion.chunk","choices":[{{"delta":{{"content":"{big_content}"}}}}]}}\n'.encode()
    src.recv.side_effect = [
        chunk,
        b'data: [DONE]\n',
        b''
    ]
    state = {'request_start': None}
    
    try:
        forward_data(src, dst, is_response=True, state=state)
        assert temp_tps.exists()
        # Should record TPS even with line over 64KB
        val = float(temp_tps.read_text().strip())
        assert val > 0
    finally:
        ollama_proxy.TPS_FILE = original_tps_file

@patch('ollama_proxy.time.time')
def test_forward_data_keep_alive_request_start(mock_time, tmp_path):
    import ollama_proxy
    temp_tps = tmp_path / "tps.txt"
    original_tps_file = ollama_proxy.TPS_FILE
    ollama_proxy.TPS_FILE = str(temp_tps)
    
    # Request 1 at t=0.0
    mock_time.return_value = 0.0
    src_client1 = Mock()
    dst_server1 = Mock()
    src_client1.recv.side_effect = [b'POST /api/chat HTTP/1.1\r\n\r\n', b'']
    state = {'request_start': None}
    forward_data(src_client1, dst_server1, is_response=False, state=state)
    assert state['request_start'] == 0.0
    
    # Response 1 completes at t=1.0
    mock_time.return_value = 1.0
    src_resp1 = Mock()
    dst_client1 = Mock()
    src_resp1.recv.side_effect = [
        b'data: {"id":"1","object":"chat.completion.chunk","choices":[{"delta":{"content":"A"}}]}\n',
        b'data: [DONE]\n',
        b''
    ]
    forward_data(src_resp1, dst_client1, is_response=True, state=state)
    assert state.get('request_start') is None
    
    # Request 2 arrives on keep-alive connection at t=10.0
    mock_time.return_value = 10.0
    src_client2 = Mock()
    dst_server2 = Mock()
    src_client2.recv.side_effect = [b'POST /v1/chat/completions HTTP/1.1\r\n\r\n', b'']
    forward_data(src_client2, dst_server2, is_response=False, state=state)
    assert state['request_start'] == 10.0
    
    # Non-streaming response completes at t=11.0
    # Expected duration: 11.0 - 10.0 = 1.0s, tokens = 20 -> TPS = 20.00
    mock_time.return_value = 11.0
    src_resp2 = Mock()
    dst_client2 = Mock()
    src_resp2.recv.side_effect = [
        b'{"object":"chat.completion","usage":{"completion_tokens":20}}\n',
        b''
    ]
    try:
        forward_data(src_resp2, dst_client2, is_response=True, state=state)
        assert temp_tps.exists()
        assert temp_tps.read_text().strip() == "20.00"
        assert state.get('request_start') is None
    finally:
        ollama_proxy.TPS_FILE = original_tps_file

def test_handle_client_backend_timeout():
    import ollama_proxy
    mock_client = Mock()
    with patch('socket.create_connection', side_effect=TimeoutError("Connection timed out")):
        ollama_proxy.handle_client(mock_client, 99999, '127.0.0.1')
        mock_client.close.assert_called_once()

def test_default_bind_host_and_cli():
    import ollama_proxy
    import argparse
    parser = argparse.ArgumentParser()
    # Check default host is 127.0.0.1 in proxy
    import inspect
    source = inspect.getsource(ollama_proxy.main)
    assert "127.0.0.1" in source
    assert "--host" in source

def test_write_tps_helper(tmp_path):
    import ollama_proxy
    temp_tps = tmp_path / "tps.txt"
    ollama_proxy.write_tps(35.123, str(temp_tps))
    assert temp_tps.read_text().strip() == "35.12"

def test_proxy_real_socket_connection():
    import socket
    import threading
    import ollama_proxy
    
    # 1. Start a mock backend
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend.bind(('127.0.0.1', 0))
    backend_port = backend.getsockname()[1]
    backend.listen(1)
    
    backend_received = []
    def backend_worker():
        conn, _ = backend.accept()
        data = conn.recv(1024)
        backend_received.append(data)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 18\r\n\r\nHello from backend")
        conn.close()
    
    t_backend = threading.Thread(target=backend_worker)
    t_backend.daemon = True
    t_backend.start()
    
    # 2. Accept client socket via handle_client
    server_side, client_side = socket.socketpair()
    t_proxy = threading.Thread(target=ollama_proxy.handle_client, args=(server_side, backend_port, '127.0.0.1'))
    t_proxy.daemon = True
    t_proxy.start()
    
    # 3. User sends request through client socket
    client_side.settimeout(2.0)
    client_side.sendall(b"GET /api/tags HTTP/1.1\r\nHost: localhost\r\n\r\n")
    response = client_side.recv(1024)
    
    assert b"Hello from backend" in response
    assert b"GET /api/tags" in backend_received[0]
    
    client_side.close()
    backend.close()

