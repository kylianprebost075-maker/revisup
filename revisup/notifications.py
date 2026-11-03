"""Notifications : iPhone (app RevisUP installée, ou app ntfy) et Windows."""
from __future__ import annotations

import os
import subprocess

import requests

from . import store

_TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:REVISUP_TITRE)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:REVISUP_TEXTE)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def envoyer(cfg: dict, titre: str, texte: str, *, cle: str | None = None, tags: str = "books",
            priorite: int = 3, lien: str | None = None, page: str = "/#/", actions: list[dict] | None = None) -> bool:
    """Envoie une notification une seule fois par `cle` (si fournie). Renvoie True si envoyée.

    page : où ouvre la notification dans l'app ; actions : boutons [{"action", "title"}] (pas affichés sur iPhone)."""
    if cle:
        if cle in store.lire()["notifs"]:
            return False
        with store.modifier() as etat:
            etat["notifs"][cle] = store.maintenant().isoformat(timespec="seconds")

    n = cfg["notifications"]
    envoyee = False
    try:
        from . import push
        envoyee = push.envoyer(cfg, titre, texte, url=page, tag=cle, actions=actions, urgent=priorite >= 4) > 0
    except Exception as e:
        print(f"[notif] Web Push impossible : {e}")
    if n.get("ntfy_sujet"):
        try:
            # publication JSON : gère les accents dans le titre (les en-têtes HTTP ne le font pas)
            corps = {"topic": n["ntfy_sujet"], "title": titre, "message": texte,
                     "tags": tags.split(","), "priority": priorite}
            if lien:
                corps["click"] = lien
            requests.post(n.get("ntfy_serveur", "https://ntfy.sh").rstrip("/"), json=corps, timeout=15).raise_for_status()
            envoyee = True
        except requests.RequestException as e:
            print(f"[notif] ntfy indisponible : {e}")
    if n.get("windows", True) and os.name == "nt":
        try:
            env = {**os.environ, "REVISUP_TITRE": titre, "REVISUP_TEXTE": texte[:250]}
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST_PS],
                           env=env, capture_output=True, timeout=20, creationflags=0x08000000)
            envoyee = True
        except Exception as e:
            print(f"[notif] toast Windows impossible : {e}")
    print(f"[notif] {titre} — {texte}")
    return envoyee
