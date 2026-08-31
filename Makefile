.PHONY: monitor-start monitor-stop clean

# Start the continuous monitor in the background
monitor-start:
	@echo "Prompting for sudo password to read GPU stats via powermetrics..."
	@sudo -v
	@echo "Starting continuous monitor..."
	@nohup ./continuous_monitor.sh > /dev/null 2>&1 &

# Stop the continuous monitor
monitor-stop:
	@if [ -f /tmp/ollama_monitor.pid ]; then \
		echo "Stopping continuous monitor (PID $$(cat /tmp/ollama_monitor.pid))..."; \
		kill -TERM $$(cat /tmp/ollama_monitor.pid) || true; \
		rm -f /tmp/ollama_monitor.pid; \
	else \
		echo "Continuous monitor is not running or PID file is missing."; \
	fi

clean:
	@echo "Cleaning up benchmark data..."
	@rm -rf benchmark_data/
