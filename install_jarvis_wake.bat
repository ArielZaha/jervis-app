@echo off
rem Windows: start the Jarvis wake listener automatically when you sign in, so you can just say "Hey Jarvis".
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
  echo Run start_jarvis.bat once first, so Jarvis can set itself up.
  pause
  exit /b 1
)
schtasks /Create /F /SC ONLOGON /TN "Jarvis Wake Listener" /TR "\"%~dp0venv\Scripts\pythonw.exe\" \"%~dp0wake_listener.py\"" /RL LIMITED
if errorlevel 1 (echo Could not create the startup task. & pause & exit /b 1)
schtasks /Run /TN "Jarvis Wake Listener" >nul
echo Jarvis will now start listening for "Hey Jarvis" whenever you sign in.
pause
