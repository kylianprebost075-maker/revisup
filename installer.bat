@echo off
rem Installe (ou répare) l'environnement Python de RevisUP.
rem Il est rangé dans %USERPROFILE%\.revisup\venv : un chemin court, sinon Windows refuse
rem de charger certains modules quand le dossier du projet est profond.
cd /d "%~dp0"
set "VENV=%USERPROFILE%\.revisup\venv"
if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if not exist config.toml "%VENV%\Scripts\python.exe" -m revisup init
echo.
echo Installation terminee. Prochaine etape : connexion.bat puis lancer.bat
pause
