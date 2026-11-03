"""Stockage local en JSON (data/etat.json), partagé entre le tableau de bord et les tâches de fond."""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import DOSSIER_DATA, FUSEAU

FICHIER_ETAT = DOSSIER_DATA / "etat.json"
FICHIER_SECRETS = DOSSIER_DATA / "secrets.json"
DOSSIER_PACKS = DOSSIER_DATA / "packs"
DOSSIER_COURS = DOSSIER_DATA / "cours"

_verrou = threading.RLock()

ETAT_VIDE = {
    "edt": {"evenements": [], "maj": None},
    "examens": {},
    "updago": {"utilisateur": None, "cours": [], "fichiers": [], "messages": [], "maj": None},
    "analyses_messages": {},
    "classements_fichiers": {},
    "planning": {"sessions": [], "genere_le": None, "alertes": []},
    "notifs": {},
    "journal": [],
    "notes": {"mails": {}, "liste": [], "maj": None, "analyse": None, "releves": {}},
    "journees": {},  # réponses à « qu'est-ce que tu fais aujourd'hui ? », par date
    "sante": {},  # état des connexions (UPdago, messagerie, Claude, IA locale, EDT)
}


def maintenant() -> datetime:
    return datetime.now(FUSEAU)


JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def jolie_date(iso: str, heure: bool = True) -> str:
    """'2026-12-15T08:30:00+01:00' -> 'lun. 15/12 à 08h30'"""
    d = datetime.fromisoformat(iso).astimezone(FUSEAU)
    txt = f"{JOURS[d.weekday()]} {d:%d/%m}"
    return f"{txt} à {d:%Hh%M}" if heure else txt


def jours_avant(iso: str) -> int:
    return (datetime.fromisoformat(iso).astimezone(FUSEAU).date() - maintenant().date()).days


def slug(texte: str, longueur: int = 60) -> str:
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:longueur] or "x"


def _lire_json(chemin: Path, defaut):
    if not chemin.exists():
        return json.loads(json.dumps(defaut))
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def _ecrire_json(chemin: Path, donnees) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def lire() -> dict:
    with _verrou:
        etat = _lire_json(FICHIER_ETAT, ETAT_VIDE)
        for cle, val in ETAT_VIDE.items():
            etat.setdefault(cle, json.loads(json.dumps(val)))
        return etat


@contextmanager
def modifier():
    """with store.modifier() as etat: ... — relit, laisse modifier, réécrit."""
    with _verrou:
        etat = lire()
        yield etat
        _ecrire_json(FICHIER_ETAT, etat)


def journal(texte: str, niveau: str = "info") -> None:
    print(f"[{niveau}] {texte}", flush=True)
    with modifier() as etat:
        etat["journal"].append({"date": maintenant().isoformat(timespec="seconds"), "niveau": niveau, "texte": texte})
        etat["journal"] = etat["journal"][-300:]


# ── secrets (jeton UPdago) ──────────────────────────────────────────────

def lire_secrets() -> dict:
    with _verrou:
        return _lire_json(FICHIER_SECRETS, {})


def ecrire_secret(cle: str, valeur: str) -> None:
    with _verrou:
        s = lire_secrets()
        s[cle] = valeur
        _ecrire_json(FICHIER_SECRETS, s)


# ── packs de révision ──────────────────────────────────────────────────

def chemin_pack(examen_id: str) -> Path:
    return DOSSIER_PACKS / f"{examen_id}.json"


def lire_pack(examen_id: str) -> dict | None:
    p = chemin_pack(examen_id)
    return _lire_json(p, None) if p.exists() else None


def ecrire_pack(examen_id: str, pack: dict) -> None:
    with _verrou:
        _ecrire_json(chemin_pack(examen_id), pack)
