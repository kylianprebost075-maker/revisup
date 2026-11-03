"""Santé des connexions : UPdago, messagerie, Claude, IA locale, emploi du temps.

Vérifiées au démarrage puis à chaque synchronisation. Quand l'une lâche (session expirée, LM Studio fermé…),
une notification arrive sur l'iPhone (une par jour et par connexion) et Réglages montre comment la réparer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from . import ia_claude, notifications, store
from .ia_locale import IALocale
from .store import maintenant

# titre de l'alerte, et ce qu'il faut faire (le bouton est dans Réglages, la fenêtre s'ouvre sur le PC)
CONSEILS = {
    "updago": ("UPdago est déconnecté", "Plus de nouveaux cours ni messages des profs. Réglages → Se reconnecter (sur le PC)."),
    "messagerie": ("Ta messagerie est déconnectée", "Plus de nouvelles notes. Réglages → Se reconnecter avec l'ENT (sur le PC)."),
    "claude": ("Claude est déconnecté", "Les packs de révision ne se font plus. Réglages → Reconnecter Claude (sur le PC)."),
    "ia_locale": ("L'IA locale ne répond pas", "LM Studio est fermé : Réglages → Démarrer LM Studio, ou ouvre-le sur le PC."),
    "edt": ("Emploi du temps pas mis à jour", "Le lien UPplanning ne répond plus depuis plus d'un jour."),
}


def lm_studio() -> str | None:
    for chemin in (Path.home() / ".lmstudio" / "bin" / "lms.exe", Path.home() / ".lmstudio" / "bin" / "lms"):
        if chemin.exists():
            return str(chemin)
    return shutil.which("lms")


def demarrer_ia_locale(cfg: dict) -> bool:
    """Démarre le serveur de LM Studio et charge le modèle (au démarrage du PC, LM Studio peut être fermé)."""
    ia = IALocale.depuis_config(cfg)
    if ia.disponible():
        return True
    lms = lm_studio()
    if not lms:
        return False
    options = {"capture_output": True, "text": True, "timeout": 300, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        subprocess.run([lms, "server", "start"], **options)
        subprocess.run([lms, "load", cfg["ia_locale"]["modele"], "-y"], **options)
    except (OSError, subprocess.TimeoutExpired) as e:
        store.journal(f"LM Studio : démarrage impossible ({e})", "erreur")
        return False
    return IALocale.depuis_config(cfg).disponible()


def _claude(cfg: dict) -> tuple[bool, str]:
    mode = ia_claude.mode_effectif(cfg)
    if mode != "cli":
        return True, {"api": "clé API", "manuel": "mode manuel (copier-coller)"}.get(mode, mode)
    exe = ia_claude.trouver_cli(cfg)
    if not exe:
        return False, "Claude Code introuvable sur ce PC"
    ia_claude.DOSSIER_PROMPTS.mkdir(parents=True, exist_ok=True)  # un dossier vide peut manquer (projet déplacé)
    try:  # un vrai appel minuscule : « auth status » dit connecté même quand le jeton ne se renouvelle plus
        proc = subprocess.run([exe, "-p", "--output-format", "json", "--model", "haiku"], input="Réponds OK.",
                              capture_output=True, text=True, encoding="utf-8", timeout=120,
                              cwd=ia_claude.DOSSIER_PROMPTS, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rep = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return False, f"Claude Code ne répond pas ({type(e).__name__})"
    if rep.get("is_error") or proc.returncode:
        return False, str(rep.get("result") or proc.stderr)[:160]
    return True, "Claude Code (abonnement)"


def _messagerie(cfg: dict) -> tuple[bool | None, str]:
    from . import mail
    if not mail.connectee(cfg):
        # jamais connectée : pas d'alerte ; déconnectée (session expirée et pas renouvelable) : alerte
        return (False, "session expirée") if cfg["mail"].get("identifiant", "").count("@") else (None, "pas connectée")
    try:
        boite = mail.ouvrir(cfg)  # le webmail tente de renouveler sa session sans fenêtre
        adresse = boite.adresse() if hasattr(boite, "adresse") else cfg["mail"].get("identifiant", "")
        boite.fermer()
        return True, adresse
    except Exception as e:
        return False, str(e)[:160]


def _updago(cfg: dict) -> tuple[bool, str]:
    from .updago import UPdago
    jeton = store.lire_secrets().get("updago_jeton")
    if not jeton:
        return False, "pas connecté"
    try:
        return True, UPdago(cfg["updago"]["url"], jeton).infos_site().get("fullname", "connecté")
    except Exception as e:
        return False, str(e)[:160]


def _edt(cfg: dict) -> tuple[bool, str]:
    maj = store.lire()["edt"].get("maj")
    if not cfg["edt"].get("ical_url"):
        return False, "pas de lien UPplanning dans config.toml"
    if maj and maintenant() - datetime.fromisoformat(maj) > timedelta(hours=26):
        return False, f"dernière mise à jour le {maj[:10]}"
    return True, f"mis à jour le {maj[:10]} à {maj[11:16]}" if maj else "jamais mis à jour"


def verifier(cfg: dict, alerter: bool = True) -> dict:
    resultats = {}
    for nom, test in (("updago", _updago), ("messagerie", _messagerie), ("claude", _claude),
                      ("ia_locale", lambda c: (demarrer_ia_locale(c), c["ia_locale"]["modele"])), ("edt", _edt)):
        try:
            ok, detail = test(cfg)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"[:160]
        resultats[nom] = {"ok": ok, "detail": detail}
    with store.modifier() as e:
        e["sante"] = {"verifie_le": maintenant().isoformat(timespec="seconds"), "services": resultats}
    if alerter:
        for nom, r in resultats.items():
            if r["ok"] is False:
                titre, conseil = CONSEILS[nom]
                notifications.envoyer(cfg, f"⚠️ {titre}", conseil, cle=f"sante-{nom}-{maintenant().date()}",
                                      tags="warning", priorite=4, page="/#/reglages")
    return resultats
