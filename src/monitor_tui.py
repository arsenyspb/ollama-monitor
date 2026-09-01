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
        return [], [], [], [], []
    
    try:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()[1:] # Skip header
    except Exception:
        return [], [], [], [], []

    # Get last MAX_POINTS lines
    lines = lines[-MAX_POINTS:]
    
    times = []
    cpu = []
    gpu = []
    ram = []
    tps = []
    
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) == 5:
            t, c, g, r, p = parts
            try:
                times.append(t)
                cpu.append(float(c))
                gpu.append(float(g))
                ram.append(float(r))
                tps.append(float(p))
            except ValueError:
                continue
                
    return times, cpu, gpu, ram, tps

def draw_dashboard():
    plt.clear_terminal()
    plt.theme("clear")
    
    times, cpu, gpu, ram, tps = read_data()
    
    if not times:
        print(f"Waiting for data in {CSV_FILE}...")
        return

    # Use generic indices for x-axis to avoid overlapping time labels if too many
    x = list(range(len(times)))
    
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