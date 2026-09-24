@echo off
schtasks /Delete /F /TN "Jervis Wake Listener"
echo Jervis Wake Listener removed from automatic startup.
pause
