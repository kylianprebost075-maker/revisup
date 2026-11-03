"""Chargement de la configuration (config.toml) avec des valeurs par défaut."""
from __future__ import annotations

import copy
import os
import secrets
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
# REVISUP_DATA permet d'utiliser un autre dossier (la démo utilise data-demo)
DOSSIER_DATA = RACINE / os.environ.get("REVISUP_DATA", "data")
FICHIER_CONFIG = RACINE / "config.toml"
FICHIER_EXEMPLE = RACINE / "config.exemple.toml"
FUSEAU = ZoneInfo("Europe/Paris")


def _defauts() -> dict:
    with open(FICHIER_EXEMPLE, "rb") as f:
        return tomllib.load(f)


def _fusion(base: dict, ajout: dict) -> dict:
    res = copy.deepcopy(base)
    for cle, val in ajout.items():
        if isinstance(val, dict) and isinstance(res.get(cle), dict):
            res[cle] = _fusion(res[cle], val)
        else:
            res[cle] = val
    return res


def charger() -> dict:
    cfg = _defauts()
    if FICHIER_CONFIG.exists():
        with open(FICHIER_CONFIG, "rb") as f:
            cfg = _fusion(cfg, tomllib.load(f))
    DOSSIER_DATA.mkdir(exist_ok=True)
    return cfg


def initialiser() -> Path:
    """Crée config.toml depuis l'exemple, avec un sujet ntfy aléatoire."""
    if FICHIER_CONFIG.exists():
        return FICHIER_CONFIG
    texte = FICHIER_EXEMPLE.read_text(encoding="utf-8")
    sujet = "revisup-" + secrets.token_urlsafe(9).replace("_", "x").replace("-", "y").lower()
    texte = texte.replace('ntfy_sujet = ""', f'ntfy_sujet = "{sujet}"', 1)
    FICHIER_CONFIG.write_text(texte, encoding="utf-8")
    return FICHIER_CONFIG


def memoriser_identifiant_mail(cfg: dict, ident: str) -> None:
    """Écrit l'identifiant accepté par la messagerie dans config.toml (section [mail])."""
    import re
    if ident != cfg["mail"].get("identifiant"):
        texte = FICHIER_CONFIG.read_text(encoding="utf-8")
        texte = re.sub(r'(?m)^(identifiant\s*=\s*)"[^"]*"', lambda x: f'{x.group(1)}"{ident}"', texte, count=1)
        FICHIER_CONFIG.write_text(texte, encoding="utf-8")
    cfg["mail"]["identifiant"] = ident
