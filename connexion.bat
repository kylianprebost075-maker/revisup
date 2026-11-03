@echo off
rem Connexion à UPdago : une fenêtre Edge s'ouvre, connecte-toi avec ton compte de l'université
cd /d "%~dp0"
"%USERPROFILE%\.revisup\venv\Scripts\python.exe" -W ignore -m revisup connexion
pause
