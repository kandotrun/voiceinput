#!/bin/zsh
# Manual start (same as launchd). Normally managed by com.kan.transcribe-endpoint.
cd "$(dirname "$0")"
exec ./venv/bin/python -m uvicorn app:app --host 100.72.208.31 --port 8791 --workers 1
