.PHONY: monitor-start monitor-stop tps-proxy-start tps-proxy-stop dashboard clean

# Start the continuous monitor in the background
monitor-start:
	@echo "Prompting for sudo password to read GPU stats via powermetrics..."
	@sudo -v
	@echo "Starting continuous monitor..."
	@nohup ./src/continuous_monitor.sh > /dev/null 2>&1 &

# Stop the continuous monitor
monitor-stop:
	@if [ -f /tmp/ollama_monitor.pid ]; then \
		echo "Stopping continuous monitor (PID $$(cat /tmp/ollama_monitor.pid))..."; \
		kill -TERM $$(cat /tmp/ollama_monitor.pid) || true; \
		rm -f /tmp/ollama_monitor.pid; \
	else \
		echo "Continuous monitor is not running or PID file is missing."; \
	fi

# Start the Ollama TPS proxy
tps-proxy-start:
	@echo "Configuring Ollama to run on 11435 and starting proxy on 11434..."
	@OS=$$(uname -s); \
	if [ "$$OS" = "Linux" ]; then \
		if [ -z "$$OLLAMA_HOST" ]; then \
			echo "Configuring systemd for Linux..."; \
			sudo mkdir -p /etc/systemd/system/ollama.service.d; \
			echo '[Service]' | sudo tee /etc/systemd/system/ollama.service.d/99-monitor-proxy.conf > /dev/null; \
			echo 'Environment="OLLAMA_HOST=127.0.0.1:11435"' | sudo tee -a /etc/systemd/system/ollama.service.d/99-monitor-proxy.conf > /dev/null; \
			sudo systemctl daemon-reload; \
			sudo systemctl restart ollama; \
		else \
			echo "OLLAMA_HOST already set to $$OLLAMA_HOST, skipping systemd override."; \
		fi \
	elif [ "$$OS" = "Darwin" ]; then \
		echo "Configuring launchctl for macOS..."; \
		launchctl setenv OLLAMA_HOST "127.0.0.1:11435"; \
		killall Ollama || true; \
		sleep 2; \
		open -a Ollama; \
	else \
		echo "Unsupported OS: $$OS"; exit 1; \
	fi
	@echo "Starting Ollama proxy..."
	@nohup ./src/ollama_proxy.py --listen 11434 --forward 11435 > /dev/null 2>&1 &
	@echo $$! > /tmp/ollama_proxy.pid
	@echo "Proxy started. Clients can use default port 11434 with zero configuration."

# Stop the Ollama TPS proxy
tps-proxy-stop:
	@if [ -f /tmp/ollama_proxy.pid ]; then \
		echo "Stopping Ollama proxy (PID $$(cat /tmp/ollama_proxy.pid))..."; \
		kill -TERM $$(cat /tmp/ollama_proxy.pid) || true; \
		rm -f /tmp/ollama_proxy.pid; \
	else \
		echo "Ollama proxy is not running or PID file is missing."; \
	fi
	@echo "Restoring Ollama default configuration..."
	@OS=$$(uname -s); \
	if [ "$$OS" = "Linux" ]; then \
		if [ -f /etc/systemd/system/ollama.service.d/99-monitor-proxy.conf ]; then \
			sudo rm -f /etc/systemd/system/ollama.service.d/99-monitor-proxy.conf; \
			sudo systemctl daemon-reload; \
			sudo systemctl restart ollama; \
		fi \
	elif [ "$$OS" = "Darwin" ]; then \
		launchctl unsetenv OLLAMA_HOST || true; \
		killall Ollama || true; \
		sleep 2; \
		open -a Ollama || true; \
	fi

dashboard:
	@echo "Ensuring plotext is installed..."
	@python3 -c "import plotext" || pip3 install plotext==5.2.8
	@echo "Starting TUI dashboard..."
	@python3 ./src/monitor_tui.py

clean:
	@echo "Cleaning up benchmark data..."
	@rm -rf benchmark_data/
