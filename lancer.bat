@echo off
rem Lance le tableau de bord RevisUP (et la synchro automatique toutes les 3 h)
cd /d "%~dp0"
start "" http://localhost:8765
"%USERPROFILE%\.revisup\venv\Scripts\python.exe" -W ignore -m revisup web
