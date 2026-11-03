"""Notifications Web Push vers l'app installée sur l'iPhone (iOS 16.4+) ou un navigateur abonné.

Les clés VAPID (qui signent nos envois) sont créées une fois, dans data/ ; les abonnements des appareils
sont rangés dans data/secrets.json (chaque abonnement permet d'envoyer des notifications à l'appareil).
"""
from __future__ import annotations

import base64
import json

from . import store
from .config import DOSSIER_DATA

FICHIER_CLE = DOSSIER_DATA / "vapid_prive.pem"


def _vapid():
    from py_vapid import Vapid02
    if FICHIER_CLE.exists():
        return Vapid02.from_file(str(FICHIER_CLE))
    v = Vapid02()
    v.generate_keys()
    v.save_key(str(FICHIER_CLE))
    return v


def cle_publique() -> str:
    """applicationServerKey du navigateur : point public brut, en base64url."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    brut = _vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(brut).rstrip(b"=").decode()


def abonnements() -> list[dict]:
    return store.lire_secrets().get("push_abonnements", [])


def abonner(abonnement: dict, appareil: str) -> int:
    if not str(abonnement.get("endpoint", "")).startswith("https://") or "keys" not in abonnement:
        raise ValueError("abonnement invalide")
    autres = [a for a in abonnements() if a["abonnement"]["endpoint"] != abonnement["endpoint"]]
    store.ecrire_secret("push_abonnements", autres + [{"abonnement": abonnement, "appareil": appareil[:60],
                                                       "depuis": store.maintenant().isoformat(timespec="seconds")}])
    return len(autres) + 1


def desabonner(endpoint: str) -> None:
    store.ecrire_secret("push_abonnements", [a for a in abonnements() if a["abonnement"]["endpoint"] != endpoint])


def envoyer(cfg: dict, titre: str, texte: str, url: str = "/#/", tag: str | None = None,
            actions: list[dict] | None = None, urgent: bool = False) -> int:
    """Envoie à tous les appareils abonnés ; oublie ceux qui ont retiré l'app (404/410). Renvoie le nombre reçu."""
    liste = abonnements()
    if not liste:
        return 0
    from pywebpush import WebPushException, webpush
    _vapid()  # crée la clé au premier envoi
    sujet = cfg["web"].get("url_publique") or "mailto:revisup@example.com"  # contact exigé par Apple : https ou mailto
    donnees = json.dumps({"titre": titre, "texte": texte[:400], "url": url, "tag": tag, "actions": actions or []},
                         ensure_ascii=False)
    recus, perimes = 0, []
    for a in liste:
        try:
            webpush(a["abonnement"], donnees, vapid_private_key=str(FICHIER_CLE), vapid_claims={"sub": sujet},
                    ttl=12 * 3600, headers={"Urgency": "high" if urgent else "normal"}, timeout=15)
            recus += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                perimes.append(a["abonnement"]["endpoint"])
            else:
                print(f"[push] {a['appareil']} : {e}")
        except Exception as e:
            print(f"[push] {a['appareil']} : {type(e).__name__}: {e}")
    for endpoint in perimes:
        desabonner(endpoint)
    return recus
