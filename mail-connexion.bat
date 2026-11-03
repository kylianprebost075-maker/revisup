@echo off
rem Connexion à la messagerie de l'université (pour lire les mails de notes) : une petite fenêtre s'ouvre
cd /d "%~dp0"
start "" "%USERPROFILE%\.revisup\venv\Scripts\pythonw.exe" -W ignore -m revisup mail-connexion --fenetre
