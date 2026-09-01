#!/usr/bin/env python3
import socket
import threading
import re
import os
import signal
import sys
import argparse

FORWARD_HOST = '127.0.0.1'
TPS_FILE = '/tmp/ollama_current_tps'

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

def forward_data(src, dst, is_response=False):
    buffer = ""
    try:
        while True:
            data = src.recv(8192)
            if not data:
                break
            dst.sendall(data)
            
            if is_response:
                try:
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        tps = extract_tps_from_line(line)
                        if tps is not None:
                            with open(TPS_FILE, 'w') as f:
                                f.write(f"{tps:.2f}\n")
                                        
                    # Safety limit for buffer in case of non-newline streaming
                    if len(buffer) > 65536:
                        buffer = buffer[-65536:]
                        
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        try:
            src.close()
        except:
            pass
        try:
            dst.close()
        except:
            pass

def handle_client(client_socket, forward_port):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server_socket.connect((FORWARD_HOST, forward_port))
    except Exception as e:
        print(f"Error connecting to backend on port {forward_port}: {e}")
        client_socket.close()
        return

    client_to_server = threading.Thread(target=forward_data, args=(client_socket, server_socket, False))
    server_to_client = threading.Thread(target=forward_data, args=(server_socket, client_socket, True))

    client_to_server.daemon = True
    server_to_client.daemon = True
    
    client_to_server.start()
    server_to_client.start()

def main():
    parser = argparse.ArgumentParser(description='Ollama TPS Proxy')
    parser.add_argument('--listen', type=int, default=11434, help='Port to listen on (default: 11434)')
    parser.add_argument('--forward', type=int, default=11435, help='Port to forward to (default: 11435)')
    args = parser.parse_args()

    listen_port = args.listen
    forward_port = args.forward

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', listen_port))
    except OSError as e:
        print(f"Error binding to port {listen_port}: {e}")
        sys.exit(1)
        
    server.listen(100)
    print(f"Listening on port {listen_port} and forwarding to {forward_port}...")

    # Ensure TPS file exists and is 0
    try:
        with open(TPS_FILE, 'w') as f:
            f.write("0\n")
        os.chmod(TPS_FILE, 0o666)
    except:
        pass

    def shutdown(sig, frame):
        print("\nShutting down proxy.")
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            client_socket, addr = server.accept()
            client_thread = threading.Thread(target=handle_client, args=(client_socket, forward_port))
            client_thread.daemon = True
            client_thread.start()
    except Exception:
        server.close()

if __name__ == "__main__":
    main()
