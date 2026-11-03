"""Client UPdago (Moodle de l'Université de Poitiers) via l'API web services de l'app mobile Moodle.

Connexion : UPdago utilise le CAS de l'université. On passe par le même mécanisme que l'app
Moodle officielle (admin/tool/mobile/launch.php) : tu te connectes toi-même dans une fenêtre
de navigateur, et UPdago renvoie un jeton "moodlemobile://token=..." que l'on récupère.
Ton mot de passe n'est jamais lu ni stocké par RevisUP.
"""
from __future__ import annotations

import base64
import hashlib
import html
import re
import secrets
import time as _time
from datetime import datetime
from pathlib import Path

import requests

from .config import FUSEAU


class ErreurUPdago(Exception):
    pass


def texte_brut(fragment_html: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment_html or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _aplatir(params: dict, prefixe: str = "") -> dict:
    """Moodle attend les tableaux sous la forme courseids[0]=12&options[timestart]=..."""
    plat = {}
    for cle, val in params.items():
        nom = f"{prefixe}[{cle}]" if prefixe else str(cle)
        if isinstance(val, dict):
            plat.update(_aplatir(val, nom))
        elif isinstance(val, (list, tuple)):
            plat.update(_aplatir(dict(enumerate(val)), nom))
        elif isinstance(val, bool):
            plat[nom] = int(val)
        elif val is not None:
            plat[nom] = val
    return plat


def _date(ts) -> str | None:
    return datetime.fromtimestamp(int(ts), FUSEAU).isoformat() if ts else None


class UPdago:
    def __init__(self, url: str, jeton: str):
        self.url = url.rstrip("/")
        self.jeton = jeton
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "RevisUP/1.0 (MoodleMobile-compatible)"

    # ── bas niveau ──
    def appel(self, fonction: str, **params):
        donnees = {"wstoken": self.jeton, "wsfunction": fonction, "moodlewsrestformat": "json", **_aplatir(params)}
        r = self.session.post(f"{self.url}/webservice/rest/server.php", data=donnees, timeout=60)
        r.raise_for_status()
        res = r.json()
        if isinstance(res, dict) and res.get("exception"):
            raise ErreurUPdago(f"{fonction} : {res.get('errorcode')} — {res.get('message')}")
        return res

    def telecharger(self, url_fichier: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if "/pluginfile.php" in url_fichier and "/webservice/pluginfile.php" not in url_fichier:
            url_fichier = url_fichier.replace("/pluginfile.php", "/webservice/pluginfile.php", 1)
        sep = "&" if "?" in url_fichier else "?"
        with self.session.get(f"{url_fichier}{sep}token={self.jeton}", stream=True, timeout=120) as r:
            r.raise_for_status()
            if "application/json" in r.headers.get("Content-Type", ""):
                raise ErreurUPdago(f"Téléchargement refusé : {r.text[:200]}")
            tmp = destination.with_suffix(destination.suffix + ".part")
            with open(tmp, "wb") as f:
                for bloc in r.iter_content(1 << 16):
                    f.write(bloc)
            tmp.replace(destination)
        return destination

    # ── fonctions utiles ──
    def infos_site(self) -> dict:
        return self.appel("core_webservice_get_site_info")

    def mes_cours(self, userid: int) -> list[dict]:
        cours = self.appel("core_enrol_get_users_courses", userid=userid)
        return [{
            "id": c["id"],
            "nom": c.get("fullname", ""),
            "code": c.get("shortname", ""),
            "categorie": c.get("categoryname") or "",
            "dernier_acces": _date(c.get("lastaccess")),
            "fin": _date(c.get("enddate")),
            "masque": bool(c.get("hidden")),
        } for c in cours]

    def contenu_cours(self, cours: dict) -> tuple[list[dict], list[dict]]:
        """Renvoie (fichiers, annonces) d'un cours : fichiers des ressources/dossiers/devoirs, textes des étiquettes."""
        sections = self.appel("core_course_get_contents", courseid=cours["id"])
        fichiers, annonces = [], []
        for sec in sections:
            nom_section = texte_brut(sec.get("name", ""))
            if sec.get("summary"):
                txt = texte_brut(sec["summary"])
                if len(txt) > 40:
                    annonces.append(self._annonce(cours, f"Section « {nom_section} »", txt, None, f"sec-{sec.get('id')}"))
            for mod in sec.get("modules", []):
                if not mod.get("uservisible", True):
                    continue
                desc = texte_brut(mod.get("description", ""))
                if mod.get("modname") in ("label", "page", "assign", "quiz") and len(desc) > 40:
                    annonces.append(self._annonce(cours, f"{nom_section} › {texte_brut(mod.get('name', ''))}", desc,
                                                  mod.get("contentsinfo", {}).get("lastmodified"), f"mod-{mod['id']}"))
                for c in mod.get("contents", []) or []:
                    if c.get("type") != "file" or not c.get("fileurl"):
                        continue
                    fichiers.append({
                        "cle": f"{cours['id']}:{mod['id']}:{c.get('filepath', '/')}{c['filename']}",
                        "cours_id": cours["id"],
                        "cours_nom": cours["nom"],
                        "section": nom_section,
                        "module": texte_brut(mod.get("name", "")),
                        "type_module": mod.get("modname"),
                        "nom": c["filename"],
                        "chemin": c.get("filepath", "/"),
                        "url": c["fileurl"],
                        "taille": c.get("filesize", 0),
                        "modifie": _date(c.get("timemodified")),
                        "mime": c.get("mimetype", ""),
                    })
        return fichiers, annonces

    @staticmethod
    def _annonce(cours, titre, texte, ts, cle):
        return {"id": f"annonce-{cours['id']}-{cle}", "source": "page du cours", "cours_id": cours["id"],
                "cours_nom": cours["nom"], "auteur": "", "sujet": titre, "texte": texte[:6000], "date": _date(ts)}

    def messages_forums(self, cours: list[dict], par_forum: int = 25) -> list[dict]:
        if not cours:
            return []
        noms = {c["id"]: c["nom"] for c in cours}
        forums = self.appel("mod_forum_get_forums_by_courses", courseids=[c["id"] for c in cours])
        messages = []
        for forum in forums:
            try:
                res = self.appel("mod_forum_get_forum_discussions", forumid=forum["id"],
                                 sortorder=1, page=0, perpage=par_forum)  # 1 = dernier message d'abord
            except ErreurUPdago:
                res = self.appel("mod_forum_get_forum_discussions_paginated", forumid=forum["id"],
                                 sortby="timemodified", sortdirection="DESC", page=0, perpage=par_forum)
            for d in res.get("discussions", []):
                messages.append({
                    "id": f"forum-{d.get('discussion') or d.get('id')}-{d.get('id')}",
                    "source": "annonces" if forum.get("type") == "news" else f"forum « {forum.get('name', '')} »",
                    "cours_id": forum["course"],
                    "cours_nom": noms.get(forum["course"], ""),
                    "auteur": d.get("userfullname", ""),
                    "sujet": d.get("name") or d.get("subject", ""),
                    "texte": texte_brut(d.get("message", ""))[:8000],
                    "date": _date(d.get("timemodified") or d.get("created")),
                    "pieces_jointes": [{"nom": a.get("filename"), "url": a.get("fileurl")}
                                       for a in (d.get("attachments") or []) if a.get("fileurl")],
                })
        return messages

    def messages_prives(self, userid: int, limite: int = 20, par_conversation: int = 20) -> list[dict]:
        res = self.appel("core_message_get_conversations", userid=userid, limitnum=limite)
        messages = []
        for conv in res.get("conversations", []):
            membres = {m["id"]: m.get("fullname", "") for m in conv.get("members", [])}
            try:
                detail = self.appel("core_message_get_conversation_messages", currentuserid=userid,
                                    convid=conv["id"], limitnum=par_conversation, newest=True)
                membres.update({m["id"]: m.get("fullname", "") for m in detail.get("members", [])})
                liste = detail.get("messages", [])
            except ErreurUPdago:
                liste = conv.get("messages", [])
            for m in liste:
                if m.get("useridfrom") == userid:
                    continue
                messages.append({
                    "id": f"mp-{m['id']}",
                    "source": "message privé" if conv.get("type") == 1 else f"groupe « {conv.get('name', '')} »",
                    "cours_id": None,
                    "cours_nom": "",
                    "auteur": membres.get(m.get("useridfrom"), ""),
                    "sujet": conv.get("name") or "Message",
                    "texte": texte_brut(m.get("text", ""))[:8000],
                    "date": _date(m.get("timecreated")),
                })
        return messages

    def evenements_calendrier(self, debut: datetime, fin: datetime) -> list[dict]:
        res = self.appel("core_calendar_get_action_events_by_timesort",
                         timesortfrom=int(debut.timestamp()), timesortto=int(fin.timestamp()), limitnum=100)
        evts = []
        for e in res.get("events", []):
            evts.append({
                "id": f"cal-{e['id']}",
                "titre": e.get("name", ""),
                "cours_id": (e.get("course") or {}).get("id"),
                "cours_nom": (e.get("course") or {}).get("fullname", ""),
                "debut": _date(e.get("timestart")),
                "duree_min": int(e.get("timeduration") or 0) // 60,
                "type": e.get("modulename") or e.get("eventtype", ""),
                "description": texte_brut(e.get("description", ""))[:2000],
            })
        return evts


# ── obtention du jeton ──────────────────────────────────────────────────

def url_lancement(url_site: str, passeport: str) -> str:
    return (f"{url_site.rstrip('/')}/admin/tool/mobile/launch.php"
            f"?service=moodle_mobile_app&passport={passeport}&urlscheme=moodlemobile")


def decoder_lien_app(lien: str, url_site: str | None = None, passeport: str | None = None) -> dict:
    """moodlemobile://token=BASE64  ->  {"jeton": ..., "prive": ...}. Accepte aussi un jeton brut."""
    lien = lien.strip()
    if re.fullmatch(r"[0-9a-f]{32}", lien):
        return {"jeton": lien, "prive": None}
    m = re.search(r"token=([A-Za-z0-9+/=_\-]+)", lien)
    brut = m.group(1) if m else lien
    brut += "=" * (-len(brut) % 4)
    morceaux = base64.b64decode(brut).decode().split(":::")
    if len(morceaux) < 2:
        raise ErreurUPdago("Lien de jeton illisible.")
    if url_site and passeport:
        attendu = hashlib.md5((url_site.rstrip("/") + passeport).encode()).hexdigest()
        if morceaux[0] != attendu:
            raise ErreurUPdago("Signature du jeton invalide (le lien ne vient pas de cette connexion).")
    return {"jeton": morceaux[1], "prive": morceaux[2] if len(morceaux) > 2 else None}


def connexion_navigateur(url_site: str, delai_s: int = 300) -> dict:
    """Ouvre Edge/Chrome sur la page de connexion UPdago ; l'étudiant se connecte lui-même (CAS)."""
    from playwright.sync_api import sync_playwright

    passeport = secrets.token_hex(8)
    lancement = url_lancement(url_site, passeport)
    trouve: dict = {}

    with sync_playwright() as p:
        navigateur = None
        for canal in ("msedge", "chrome", None):
            try:
                navigateur = p.chromium.launch(channel=canal, headless=False) if canal else p.chromium.launch(headless=False)
                break
            except Exception:
                continue
        if navigateur is None:
            raise ErreurUPdago("Impossible d'ouvrir Edge ou Chrome. Utilise : python -m revisup connexion --manuel")
        page = navigateur.new_page()

        def sur_reponse(rep):
            loc = rep.headers.get("location", "")
            if loc.startswith("moodlemobile://"):
                trouve["lien"] = loc

        def sur_requete(req):
            if req.url.startswith("moodlemobile://"):
                trouve["lien"] = req.url

        page.on("response", sur_reponse)
        page.on("request", sur_requete)
        page.on("requestfailed", sur_requete)
        try:
            page.goto(lancement)
        except Exception:
            pass  # la redirection finale vers moodlemobile:// fait échouer la navigation : normal

        fin = _time.time() + delai_s
        while "lien" not in trouve and _time.time() < fin:
            try:
                lien = page.eval_on_selector("a#launchapp", "a => a.href") if page.query_selector("a#launchapp") else None
                if lien and lien.startswith("moodlemobile://"):
                    trouve["lien"] = lien
                page.wait_for_timeout(500)
            except Exception:
                _time.sleep(0.5)
        navigateur.close()

    if "lien" not in trouve:
        raise ErreurUPdago("Pas de jeton reçu (délai dépassé). Réessaie, ou utilise --manuel.")
    return decoder_lien_app(trouve["lien"], url_site, passeport)
