@echo off
rem Rend RevisUP accessible depuis ton iPhone, uniquement par ton reseau prive Tailscale (pas depuis Internet).
rem Pour arreter : tailscale serve reset
tailscale serve --bg 8765
echo.
tailscale serve status
echo.
echo Sur l'iPhone (Tailscale connecte), ouvre dans Safari l'adresse https://... affichee ci-dessus,
echo puis Partager ^> "Sur l'ecran d'accueil". Mets aussi cette adresse dans url_publique (config.toml).
pause
