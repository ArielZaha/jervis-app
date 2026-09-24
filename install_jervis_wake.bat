@echo off
rem Windows: start the Jervis wake listener automatically when you sign in, so you can just say "Hey Jervis".
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
  echo Run start_jervis.bat once first, so Jervis can set itself up.
  pause
  exit /b 1
)
schtasks /Create /F /SC ONLOGON /TN "Jervis Wake Listener" /TR "\"%~dp0venv\Scripts\pythonw.exe\" \"%~dp0wake_listener.py\"" /RL LIMITED
if errorlevel 1 (echo Could not create the startup task. & pause & exit /b 1)
schtasks /Run /TN "Jervis Wake Listener" >nul
echo Jervis will now start listening for "Hey Jervis" whenever you sign in.
pause
