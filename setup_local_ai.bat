@echo off
rem Windows: install a free AI that runs on this PC (Ollama), used when the online AI can't be reached. About 2 GB, once.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run.py --local-ai) || (python run.py --local-ai)
if errorlevel 1 pause
