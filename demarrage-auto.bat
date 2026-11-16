@echo off
rem Fait demarrer RevisUP tout seul, sans fenetre, a chaque ouverture de ta session Windows,
rem puis le lance tout de suite. Le journal du serveur est dans data\serveur.log.
rem Inscrit dans le registre (cle Run, comme Google Drive ou LG Hub) : visible dans
rem Gestionnaire des taches > Applications de demarrage. Pour l'arreter : desactive "RevisUP" la-bas.
cd /d "%~dp0"
set "PYW=%USERPROFILE%\.revisup\venv\Scripts\pythonw.exe"
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v RevisUP /t REG_SZ /d "\"%PYW%\" -W ignore \"%CD%\revisup.pyw\"" /f >nul
if errorlevel 1 (
  echo.
  echo ERREUR : impossible d'inscrire RevisUP au demarrage de Windows.
  pause
  exit /b 1
)
rem ancien raccourci du dossier Demarrage (remplace par la cle Run)
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RevisUP.lnk" >nul 2>&1
start "" "%PYW%" -W ignore "%CD%\revisup.pyw"
echo.
echo OK : RevisUP tourne en arriere-plan et redemarrera tout seul avec Windows.
echo Tableau de bord : http://localhost:8765
timeout /t 5 >nul
start "" http://localhost:8765
