#!/usr/bin/env python3
import socket
import threading
import re
import os
import signal
import sys
import argparse
import time

FORWARD_HOST = '127.0.0.1'

def get_default_tps_file():
    if "OLLAMA_TPS_FILE" in os.environ:
        return os.environ["OLLAMA_TPS_FILE"]
    uid = os.getuid() if hasattr(os, "getuid") else 0
    runtime_dir = os.environ.get("OLLAMA_MONITOR_DIR", f"/tmp/ollama-monitor-{uid}")
    try:
        os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
    except Exception:
        pass
    return os.path.join(runtime_dir, "ollama_current_tps")

TPS_FILE = get_default_tps_file()

def write_tps(tps, tps_file=None):
    """Write TPS value to file, restricting file permissions."""
    if tps_file is None:
        tps_file = TPS_FILE
    try:
        with open(tps_file, 'w') as f:
            f.write(f"{tps:.2f}\n")
        try:
            os.chmod(tps_file, 0o600)
        except Exception:
            pass
    except Exception:
        pass

def extract_tps_from_line(line):
    if '"eval_count"' in line and '"eval_duration"' in line:
        count_match = re.search(r'"eval_count"\s*:\s*(\d+)', line)
        duration_match = re.search(r'"eval_duration"\s*:\s*(\d+)', line)
        if count_match and duration_match:
            count = int(count_match.group(1))
            duration_ns = int(duration_match.group(1))
            if duration_ns > 0:
                return count / (duration_ns / 1e9)
    return None

def process_line(line, state, stream_context):
    """
    Process a single line from the response stream and update TPS.
    
    TPS Methodology:
    - Ollama Native API: uses `eval_count / (eval_duration / 1e9)`. Measures pure token
      generation speed reported by the backend, excluding prompt evaluation.
    - OpenAI streaming API: uses `chunk_count / (now - first_chunk_time)`. Measures
      continuous token generation rate from first emitted token chunk to stream end.
    - OpenAI non-streaming API: uses `completion_tokens / (now - request_start)`. Measures
      generation rate over the full request duration because token count is only available
      upon complete response.
    """
    # Ollama Native API TPS
    tps = extract_tps_from_line(line)
    if tps is not None:
        write_tps(tps)
        state['request_start'] = None
    elif '"done":true' in line or '"done": true' in line:
        state['request_start'] = None

    # OpenAI API Stream tracking
    if '"object":"chat.completion.chunk"' in line:
        current_time = time.time()
        if stream_context['first_chunk_time'] is None:
            stream_context['first_chunk_time'] = current_time
            stream_context['chunk_count'] = 0
            stream_context['last_update_time'] = current_time

        match = re.search(r'"completion_tokens"\s*:\s*(\d+)', line)
        if match:
            stream_context['chunk_count'] = int(match.group(1))
        elif '"content"' in line:
            stream_context['chunk_count'] += 1

        # Continuously update TPS during generation
        if stream_context['chunk_count'] > 0 and (current_time - stream_context['last_update_time'] >= 0.2):
            duration = current_time - stream_context['first_chunk_time']
            if duration > 0:
                write_tps(stream_context['chunk_count'] / duration)
                stream_context['last_update_time'] = current_time

    # End of OpenAI Stream
    if line.strip() == "data: [DONE]" and stream_context['first_chunk_time'] is not None:
        duration = time.time() - stream_context['first_chunk_time']
        if duration > 0 and stream_context['chunk_count'] > 0:
            write_tps(stream_context['chunk_count'] / duration)
        stream_context['first_chunk_time'] = None
        stream_context['chunk_count'] = 0
        stream_context['last_update_time'] = None
        state['request_start'] = None

    # Non-streaming OpenAI API
    if '"object":"chat.completion"' in line and '"usage"' in line and '"completion_tokens"' in line:
        match = re.search(r'"completion_tokens"\s*:\s*(\d+)', line)
        if match and state.get('request_start') is not None:
            completion_tokens = int(match.group(1))
            duration = time.time() - state['request_start']
            if duration > 0 and completion_tokens > 0:
                write_tps(completion_tokens / duration)
        state['request_start'] = None

def forward_data(src, dst, is_response=False, state=None):
    if state is None:
        state = {}

    buffer = ""
    stream_context = {
        'first_chunk_time': None,
        'chunk_count': 0,
        'last_update_time': None,
    }

    try:
        while True:
            data = src.recv(8192)
            if not data:
                break
            dst.sendall(data)

            if not is_response:
                # Set or update request_start on new HTTP request
                is_new_request = any(data.startswith(m) for m in (b'GET ', b'POST ', b'HEAD ', b'PUT ', b'DELETE '))
                if is_new_request or state.get('request_start') is None:
                    state['request_start'] = time.time()

            if is_response:
                try:
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text

                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        process_line(line, state, stream_context)

                    # Safety limit for buffer: keep head (~512 bytes) and tail, drop middle
                    if len(buffer) > 65536:
                        buffer = buffer[:512] + buffer[-32768:]

                except Exception:
                    pass

        # EOF reached: flush any remaining bytes in buffer
        if is_response:
            if buffer.strip():
                try:
                    process_line(buffer, state, stream_context)
                except Exception:
                    pass
            state['request_start'] = None

    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

def handle_client(client_socket, forward_port, forward_host=FORWARD_HOST):
    try:
        server_socket = socket.create_connection((forward_host, forward_port), timeout=5.0)
        server_socket.settimeout(None)
    except Exception as e:
        print(f"Error connecting to backend on port {forward_port}: {e}")
        try:
            client_socket.close()
        except Exception:
            pass
        return

    state = {'request_start': None}

    client_to_server = threading.Thread(target=forward_data, args=(client_socket, server_socket, False, state))
    server_to_client = threading.Thread(target=forward_data, args=(server_socket, client_socket, True, state))

    client_to_server.daemon = True
    server_to_client.daemon = True

    client_to_server.start()
    server_to_client.start()

def main():
    parser = argparse.ArgumentParser(description='Ollama TPS Proxy')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind on (default: 127.0.0.1)')
    parser.add_argument('--listen', type=int, default=11434, help='Port to listen on (default: 11434)')
    parser.add_argument('--forward', type=int, default=11435, help='Port to forward to (default: 11435)')
    parser.add_argument('--pid-file', type=str, default=None, help='File to write PID to after successful bind')
    args = parser.parse_args()

    listen_host = args.host
    listen_port = args.listen
    forward_port = args.forward

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((listen_host, listen_port))
    except OSError as e:
        print(f"Error binding to {listen_host}:{listen_port}: {e}")
        sys.exit(1)

    server.listen(100)
    print(f"Listening on {listen_host}:{listen_port} and forwarding to {forward_port}...")

    if args.pid_file:
        try:
            with open(args.pid_file, 'w') as f:
                f.write(f"{os.getpid()}\n")
        except Exception as e:
            print(f"Warning: could not write PID file: {e}")

    write_tps(0.0)

    def shutdown(sig, frame):
        print("\nShutting down proxy.")
        if args.pid_file:
            try:
                os.remove(args.pid_file)
            except Exception:
                pass
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            client_socket, addr = server.accept()
            client_thread = threading.Thread(target=handle_client, args=(client_socket, forward_port, FORWARD_HOST))
            client_thread.daemon = True
            client_thread.start()
    except Exception:
        server.close()

if __name__ == "__main__":
    main()
