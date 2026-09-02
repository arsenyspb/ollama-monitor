#!/usr/bin/env python3
import time
import os
import sys

try:
    import plotext as plt
except ImportError:
    print("plotext is not installed. Run: pip install plotext")
    sys.exit(1)

CSV_FILE = "benchmark_data/continuous_monitor.csv"
MAX_POINTS = 60 # Show last 60 seconds of data

def read_data():
    if not os.path.exists(CSV_FILE):
        return [], [], [], [], [], "None", "None"
    
    try:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()[1:] # Skip header
    except Exception:
        return [], [], [], [], [], "None", "None"

    # Get last MAX_POINTS lines
    lines = lines[-MAX_POINTS:]
    
    times = []
    cpu = []
    gpu = []
    ram = []
    tps = []
    last_model_name = "None"
    last_model_meta = "None"
    
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 5:
            t, c, g, r, p = parts[:5]
            try:
                times.append(t)
                cpu.append(float(c))
                gpu.append(float(g))
                ram.append(float(r))
                tps.append(float(p))
            except ValueError:
                continue
            
            if len(parts) >= 7:
                last_model_name = parts[5]
                last_model_meta = parts[6]
                
    return times, cpu, gpu, ram, tps, last_model_name, last_model_meta

def draw_dashboard():
    plt.clear_terminal()
    plt.theme("clear")
    
    times, cpu, gpu, ram, tps, model_name, model_meta = read_data()
    
    if not times:
        print(f"Waiting for data in {CSV_FILE}...")
        return

    # Render Top Row Outlook
    if model_name != "None":
        print(f"\033[1m\033[96mCURRENT OLLAMA MODEL:\033[0m {model_name} \033[90m[{model_meta}]\033[0m\n")
    else:
        print("\033[1m\033[91mCURRENT OLLAMA MODEL:\033[0m No model currently loaded\n")

    # Use generic indices for x-axis to avoid overlapping time labels if too many
    x = list(range(len(times)))
    
    # Adjust plot size to prevent terminal from scrolling and overwriting the top text
    try:
        w, h = plt.terminal_size()
        plt.plotsize(w, h - 3)
    except Exception:
        pass
        
    plt.subplots(2, 2)
    
    # 1, 1: CPU Usage
    plt.subplot(1, 1)
    plt.title("CPU Usage (%)")
    plt.plot(x, cpu, color="blue")
    plt.ylim(0, 100)
    plt.xticks(x, times)
    
    # 1, 2: GPU Load
    plt.subplot(1, 2)
    plt.title("GPU Load (%)")
    plt.plot(x, gpu, color="red")
    plt.ylim(0, 100)
    plt.xticks(x, times)
    
    # 2, 1: RAM Usage
    plt.subplot(2, 1)
    plt.title("RAM Used (GB)")
    plt.plot(x, ram, color="green")
    plt.xticks(x, times)
    
    # 2, 2: TPS
    plt.subplot(2, 2)
    plt.title("Tokens Per Second (TPS)")
    plt.plot(x, tps, color="magenta")
    plt.xticks(x, times)
    
    plt.show()

def main():
    print("Starting dashboard... Press Ctrl+C to stop.")
    try:
        while True:
            draw_dashboard()
            time.sleep(1)
    except KeyboardInterrupt:
        plt.clear_terminal()
        print("Dashboard stopped.")

if __name__ == "__main__":
    main()