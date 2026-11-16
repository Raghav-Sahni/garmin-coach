@echo off
rem Builds dist\GarminCoach.exe  (needs: pip install pyinstaller, and this package installed)
cd /d "%~dp0\.."
python -m PyInstaller --noconfirm --onefile --windowed --name GarminCoach ^
  --collect-submodules garminconnect --collect-submodules garmin_coach ^
  packaging\launch.py
