#!/bin/bash

echo "============================================================"
echo "NexusDoc AI - Chat & Insights App Startup Script (Linux/Mac)"
echo "============================================================"
echo

# 1. Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed or not in PATH."
    echo "Please install Python 3.8+ and try again."
    exit 1
fi

# 2. Check Ollama status
echo "Checking Ollama status..."
if pgrep -x "ollama" > /dev/null; then
    echo "[OK] Ollama is running."
elif command -v ollama &> /dev/null; then
    echo "[WARNING] Ollama is not running. Starting Ollama in background..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
    echo "[OK] Ollama started."
else
    echo "[WARNING] Ollama command not found. Please make sure Ollama is installed and running manually."
fi

# 3. Install Python dependencies
echo
echo "Installing/verifying Python dependencies..."
python3 -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[WARNING] pip install failed, trying fallback with --user flag..."
    python3 -m pip install -r requirements.txt --user
fi

# 4. Start backend
echo
echo "============================================================"
echo "Starting NexusDoc AI RAG server..."
echo "Access the application web interface at: http://localhost:8000"
echo "============================================================"
echo
python3 run.py
