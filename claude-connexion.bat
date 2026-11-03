@echo off
rem Reconnecte Claude Code (utilisé pour les packs de révision et l'analyse des notes) : ton navigateur s'ouvre sur claude.ai
cd /d "%~dp0"
"%USERPROFILE%\.revisup\venv\Scripts\python.exe" -W ignore -m revisup claude-connexion
pause
