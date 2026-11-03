@echo off
rem Fait demarrer RevisUP tout seul, sans fenetre, a chaque ouverture de ta session Windows,
rem puis le lance tout de suite. Le journal du serveur est dans data\serveur.log.
rem Pour arreter le demarrage automatique : Win+R, tape shell:startup, supprime "RevisUP".
cd /d "%~dp0"
set "DOSSIER=%CD%"
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\RevisUP.lnk'); $s.TargetPath = $env:USERPROFILE + '\.revisup\venv\Scripts\pythonw.exe'; $s.Arguments = '-W ignore -m revisup web'; $s.WorkingDirectory = $env:DOSSIER; $s.WindowStyle = 7; $s.Description = 'RevisUP'; $s.Save()"
if errorlevel 1 (
  echo.
  echo ERREUR : impossible de creer le raccourci de demarrage.
  pause
  exit /b 1
)
start "" "%USERPROFILE%\.revisup\venv\Scripts\pythonw.exe" -W ignore -m revisup web
echo.
echo OK : RevisUP tourne en arriere-plan et redemarrera tout seul avec Windows.
echo Tableau de bord : http://localhost:8765
timeout /t 5 >nul
start "" http://localhost:8765
