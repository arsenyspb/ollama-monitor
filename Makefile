# Agents: see AGENTS.md section 4. Targets marked HUMAN-ONLY need sudo or change
# system services and must not be run by AI agents. Safe targets: setup, test.
#
# HUMAN-ONLY: monitor-start, monitor-stop, tps-proxy-start, tps-proxy-stop, dashboard

.PHONY: setup test monitor-start monitor-stop tps-proxy-start tps-proxy-stop dashboard clean

PY ?= .venv/bin/python

USER_ID ?= $(shell id -u 2>/dev/null || echo 0)
RUNTIME_DIR ?= /tmp/ollama-monitor-$(USER_ID)
MONITOR_PID_FILE ?= $(RUNTIME_DIR)/ollama_monitor.pid
PROXY_PID_FILE ?= $(RUNTIME_DIR)/ollama_proxy.pid

# Create the development environment (safe for agents)
setup:
	@python3 -m venv .venv
	@.venv/bin/pip install -r requirements-dev.txt

# Run the test suite (safe for agents)
test:
	@test -x $(PY) || { echo "Run 'make setup' first."; exit 1; }
	@$(PY) -m pytest tests/

# Start the continuous monitor in the background (HUMAN-ONLY)
monitor-start:
	@mkdir -p $(RUNTIME_DIR) && chmod 700 $(RUNTIME_DIR) 2>/dev/null || true
	@if [ -f $(MONITOR_PID_FILE) ] && kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
		echo "Continuous monitor is already running (PID $$(cat $(MONITOR_PID_FILE)))."; \
		exit 1; \
	fi
	@echo "Prompting for sudo password to read GPU stats via powermetrics..."
	@sudo -v
	@echo "Starting continuous monitor..."
	@nohup ./src/continuous_monitor.sh > /dev/null 2>&1 &

# Stop the continuous monitor
monitor-stop:
	@PID=""; \
	if [ -f $(MONITOR_PID_FILE) ]; then PID=$$(cat $(MONITOR_PID_FILE)); \
	elif [ -f /tmp/ollama_monitor.pid ]; then PID=$$(cat /tmp/ollama_monitor.pid); fi; \
	if [ -n "$$PID" ] && kill -0 "$$PID" 2>/dev/null; then \
		echo "Stopping continuous monitor (PID $$PID)..."; \
		kill -TERM "$$PID" || true; \
		rm -f $(MONITOR_PID_FILE) /tmp/ollama_monitor.pid; \
	else \
		echo "Continuous monitor is not running or PID file is missing."; \
		rm -f $(MONITOR_PID_FILE) /tmp/ollama_monitor.pid; \
	fi

# Start the Ollama TPS proxy
tps-proxy-start:
	@mkdir -p $(RUNTIME_DIR) && chmod 700 $(RUNTIME_DIR) 2>/dev/null || true
	@if [ -f $(PROXY_PID_FILE) ] && kill -0 $$(cat $(PROXY_PID_FILE)) 2>/dev/null; then \
		echo "Ollama proxy is already running (PID $$(cat $(PROXY_PID_FILE)))."; \
		exit 1; \
	fi
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
	@rm -f $(PROXY_PID_FILE) /tmp/ollama_proxy.pid
	@nohup ./src/ollama_proxy.py --listen 11434 --forward 11435 --pid-file $(PROXY_PID_FILE) > /dev/null 2>&1 &
	@sleep 1
	@if [ -f $(PROXY_PID_FILE) ] && kill -0 $$(cat $(PROXY_PID_FILE)) 2>/dev/null; then \
		echo "Proxy started (PID $$(cat $(PROXY_PID_FILE))). Clients can use default port 11434 with zero configuration."; \
	else \
		echo "Failed to start proxy. Check if port 11434 is already in use."; \
		exit 1; \
	fi

# Stop the Ollama TPS proxy
tps-proxy-stop:
	@PID=""; \
	if [ -f $(PROXY_PID_FILE) ]; then PID=$$(cat $(PROXY_PID_FILE)); \
	elif [ -f /tmp/ollama_proxy.pid ]; then PID=$$(cat /tmp/ollama_proxy.pid); fi; \
	if [ -n "$$PID" ] && kill -0 "$$PID" 2>/dev/null; then \
		echo "Stopping Ollama proxy (PID $$PID)..."; \
		kill -TERM "$$PID" || true; \
		rm -f $(PROXY_PID_FILE) /tmp/ollama_proxy.pid; \
	else \
		echo "Ollama proxy is not running or PID file is missing."; \
		rm -f $(PROXY_PID_FILE) /tmp/ollama_proxy.pid; \
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

dashboard: monitor-start tps-proxy-start
	@echo "Ensuring plotext is installed..."
	@python3 -c "import plotext" || pip3 install plotext==5.2.8
	@echo "Starting TUI dashboard..."
	@python3 ./src/monitor_tui.py

clean:
	@echo "Cleaning up benchmark data..."
	@rm -rf benchmark_data/
