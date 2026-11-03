"""IA locale (LM Studio / Ollama, API compatible OpenAI) : le "tri" fait sur ton PC.

Elle associe un examen au bon cours UPdago, classe les fichiers (cours, TD, TP, annales...),
et lit les messages des profs pour en extraire les infos d'examen (date, salle, documents autorisés...).
Si elle n'est pas lancée, des règles simples (mots-clés) prennent le relais.
"""
from __future__ import annotations

import difflib
import json
import re

import requests

from .edt import normaliser

CATEGORIES = ["annale", "corrige", "cours", "td", "tp", "autre"]

SCHEMA_COURS = {
    "type": "object",
    "properties": {"index": {"type": "integer"}, "raison": {"type": "string"}},
    "required": ["index", "raison"],
}
SCHEMA_FICHIERS = {
    "type": "object",
    "properties": {"fichiers": {"type": "array", "items": {
        "type": "object",
        "properties": {"i": {"type": "integer"}, "categorie": {"type": "string", "enum": CATEGORIES}},
        "required": ["i", "categorie"]}}},
    "required": ["fichiers"],
}
SCHEMA_MESSAGE = {
    "type": "object",
    "properties": {
        "concerne_examen": {"type": "boolean"},
        "matiere": {"type": "string"},
        "nature": {"type": "string", "enum": ["annonce_date", "consignes", "programme", "changement", "annulation", "autre"]},
        "date": {"type": "string", "description": "AAAA-MM-JJ ou vide"},
        "heure": {"type": "string", "description": "HH:MM ou vide"},
        "duree_min": {"type": "integer"},
        "salle": {"type": "string"},
        "documents_autorises": {"type": "string"},
        "programme": {"type": "string"},
        "consignes": {"type": "string"},
        "resume": {"type": "string"},
    },
    "required": ["concerne_examen", "matiere", "nature", "date", "heure", "duree_min", "salle",
                 "documents_autorises", "programme", "consignes", "resume"],
}

SCHEMA_NOTES = {
    "type": "object",
    "properties": {
        "contient_mes_notes": {"type": "boolean"},
        "notes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "code": {"type": "string", "description": "code du module (R108, SAE105...) ou vide"},
                "evaluation": {"type": "string", "description": "ctrl, ctrl TP, DS1, oral, projet..."},
                "note": {"type": "number"},
                "sur": {"type": "number"},
                "coefficient": {"type": "number", "description": "0 si inconnu"},
                "moyenne_classe": {"type": "number", "description": "0 si inconnue"},
                "date_evaluation": {"type": "string", "description": "AAAA-MM-JJ ou vide"},
            },
            "required": ["module", "code", "evaluation", "note", "sur", "coefficient", "moyenne_classe", "date_evaluation"]}},
    },
    "required": ["contient_mes_notes", "notes"],
}

MOTS_EXAMEN_MESSAGE = re.compile(
    r"examen|partiel|controle|contrôle|\bcc\d?\b|\bct\b|\bds\d?\b|epreuve|épreuve|evaluation|évaluation|"
    r"soutenance|rattrapage|interro|qcm|annale|reviser|réviser|révision|calculatrice|documents? autoris", re.I)


class IALocale:
    def __init__(self, url: str, modele: str, timeout: int = 900, effort: str = ""):
        self.url = url.rstrip("/")
        self.modele = modele
        self.timeout = timeout
        self.effort = effort  # modèles qui "réfléchissent" (gpt-oss) : low / medium / high
        self._dispo: bool | None = None

    @classmethod
    def depuis_config(cls, cfg: dict) -> "IALocale":
        c = cfg["ia_locale"]
        return cls(c["url"], c["modele"], effort=c.get("effort_raisonnement", ""))

    def disponible(self) -> bool:
        if self._dispo is None:
            try:
                r = requests.get(f"{self.url}/models", timeout=3)
                self._dispo = r.ok
            except requests.RequestException:
                self._dispo = False
        return self._dispo

    def _json(self, systeme: str, utilisateur: str, schema: dict, max_tokens: int = 2000) -> dict:
        corps = {
            "model": self.modele,
            "messages": [{"role": "system", "content": systeme}, {"role": "user", "content": utilisateur}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "reponse", "strict": True, "schema": schema}},
        }
        if self.effort:
            # la réflexion compte dans max_tokens : on laisse de la marge pour qu'elle ne mange pas la réponse
            corps["reasoning_effort"] = self.effort
            corps["max_tokens"] = max_tokens + 6000
        r = requests.post(f"{self.url}/chat/completions", json=corps, timeout=self.timeout)
        if r.status_code == 400:  # serveur sans sortie structurée : on demande juste du JSON
            corps.pop("response_format")
            corps["messages"][0]["content"] += "\nRéponds uniquement avec un objet JSON valide, sans texte autour."
            r = requests.post(f"{self.url}/chat/completions", json=corps, timeout=self.timeout)
        r.raise_for_status()
        texte = r.json()["choices"][0]["message"].get("content") or ""
        texte = re.sub(r"(?s)<think>.*?</think>", "", texte).strip()
        m = re.search(r"(?s)\{.*\}", texte)
        return json.loads(m.group(0) if m else texte)

    def discuter(self, systeme: str, messages: list[dict], max_tokens: int = 1000) -> str:
        """Réponse en texte libre (tuteur) ; messages : [{"role": "user" | "assistant", "content": ...}]."""
        corps = {"model": self.modele, "messages": [{"role": "system", "content": systeme}, *messages],
                 "temperature": 0.4, "max_tokens": max_tokens}
        if self.effort:
            corps["reasoning_effort"] = self.effort
            corps["max_tokens"] = max_tokens + 3000
        r = requests.post(f"{self.url}/chat/completions", json=corps, timeout=self.timeout)
        r.raise_for_status()
        texte = r.json()["choices"][0]["message"].get("content") or ""
        return re.sub(r"(?s)<think>.*?</think>", "", texte).strip()

    # ── 1. quel cours UPdago correspond à l'examen ? ──
    def associer_cours(self, matiere: str, titre: str, cours: list[dict]) -> dict | None:
        if not cours:
            return None
        # BUT : le code du module (R108, R1.02, SAé 1.04...) suffit quand il est présent des deux côtés
        code = code_module(f"{matiere} {titre}")
        if code:
            memes = [c for c in cours if code_module(f"{c['nom']} {c['code']}") == code]
            if len(memes) == 1:
                return memes[0]
        candidats = sorted(cours, key=lambda c: -_similarite(matiere, c["nom"] + " " + c["code"]))[:25]
        if self.disponible():
            try:
                liste = "\n".join(f"{i}. {c['nom']} ({c['code']}) — {c['categorie']}" for i, c in enumerate(candidats))
                rep = self._json(
                    "Tu aides un étudiant de l'Université de Poitiers. On te donne un examen et la liste de ses "
                    "cours sur la plateforme UPdago (Moodle). Donne l'index du cours qui correspond à la matière "
                    "de l'examen, ou -1 si aucun ne correspond.",
                    f"Examen : « {titre} » (matière : {matiere})\n\nCours :\n{liste}",
                    SCHEMA_COURS, 300)
                i = int(rep.get("index", -1))
                return candidats[i] if 0 <= i < len(candidats) else None
            except Exception:
                pass
        meilleur = candidats[0]
        return meilleur if _similarite(matiere, meilleur["nom"] + " " + meilleur["code"]) >= 0.45 else None

    # ── 2. classement des fichiers ──
    def classer_fichiers(self, matiere: str, fichiers: list[dict]) -> list[str]:
        categories = [classer_par_nom(f) for f in fichiers]
        if not self.disponible() or not fichiers:
            return categories
        for debut in range(0, len(fichiers), 40):
            lot = fichiers[debut:debut + 40]
            liste = "\n".join(f"{debut + i}. {f['nom']} — section « {f['section']} » — ressource « {f['module']} »"
                              for i, f in enumerate(lot))
            try:
                rep = self._json(
                    "Classe chaque fichier d'un cours universitaire dans une catégorie :\n"
                    "- annale : sujet d'examen ou de contrôle des années précédentes (partiel, CC, DS, CT, sujet...)\n"
                    "- corrige : correction / solution d'un examen, TD ou TP\n"
                    "- cours : support de cours magistral (CM, chapitre, poly, diaporama)\n"
                    "- td : feuille d'exercices de travaux dirigés\n"
                    "- tp : sujet de travaux pratiques\n"
                    "- autre : planning, modalités, formulaire administratif...\n"
                    "Utilise le nom du fichier ET le nom de la section/ressource.",
                    f"Matière : {matiere}\n\n{liste}", SCHEMA_FICHIERS, 2500)
                for item in rep.get("fichiers", []):
                    i = int(item.get("i", -1))
                    if 0 <= i < len(fichiers) and item.get("categorie") in CATEGORIES:
                        categories[i] = item["categorie"]
            except Exception:
                continue
        return categories

    # ── 3. lecture d'un message de prof ──
    def analyser_message(self, message: dict, aujourd_hui: str) -> dict:
        texte = f"{message.get('sujet', '')}\n{message.get('texte', '')}"
        if not MOTS_EXAMEN_MESSAGE.search(texte):
            return _message_hors_sujet()
        if not self.disponible():
            return {**_message_hors_sujet(), "concerne_examen": True, "nature": "autre",
                    "matiere": message.get("cours_nom", ""), "resume": message.get("sujet", "")}
        try:
            rep = self._json(
                "Tu lis les messages qu'un étudiant de l'Université de Poitiers reçoit sur UPdago (Moodle). "
                "Dis si le message concerne un examen (partiel, CC, DS, contrôle, soutenance, rattrapage...) et "
                "extrais les informations utiles. Les dates relatives (« jeudi prochain ») se calculent à partir "
                "de la date du message. Laisse vide ce qui n'est pas dit ; duree_min = 0 si inconnue. "
                "« resume » : une phrase en français.",
                f"Date d'aujourd'hui : {aujourd_hui}\nDate du message : {message.get('date') or 'inconnue'}\n"
                f"Cours : {message.get('cours_nom') or 'non précisé'}\nAuteur : {message.get('auteur', '')}\n"
                f"Sujet : {message.get('sujet', '')}\n\n{message.get('texte', '')[:5000]}",
                SCHEMA_MESSAGE, 800)
            return _normaliser_analyse({**_message_hors_sujet(), **rep}, texte)
        except Exception:
            return {**_message_hors_sujet(), "concerne_examen": True, "nature": "autre",
                    "matiere": message.get("cours_nom", ""), "resume": message.get("sujet", "")}


    # ── 4. notes reçues par mail ──
    def extraire_notes(self, mail: dict, texte: str, nom_etudiant: str, modules: list[str]) -> list[dict]:
        if not self.disponible():
            return notes_par_regex(mail, texte)
        try:
            rep = self._json(
                f"Tu lis un mail reçu par l'étudiant {nom_etudiant} (BUT, Université de Poitiers). Extrais "
                "UNIQUEMENT SES notes à lui (jamais celles d'autres étudiants). Les extraits de pièces jointes "
                "ne contiennent que les lignes à son nom et l'en-tête du tableau : sers-toi de l'en-tête pour savoir "
                "quelle colonne est la note. Si le mail dit seulement que les notes sont disponibles ailleurs, "
                "ou ne contient pas de note chiffrée, contient_mes_notes = false. Utilise un des modules connus "
                "quand c'est possible (même code).",
                f"Modules connus : {'; '.join(modules[:40])}\n\nDate du mail : {mail['date'][:10]}\n"
                f"De : {mail['expediteur']}\nSujet : {mail['sujet']}\n\n{texte[:9000]}",
                SCHEMA_NOTES, 1500)
        except Exception:
            return notes_par_regex(mail, texte)
        if not rep.get("contient_mes_notes"):
            return []
        propres = []
        for n in rep.get("notes", []):
            try:
                note, sur = float(n["note"]), float(n.get("sur") or 20)
            except (TypeError, ValueError):
                continue
            if sur <= 0 or not 0 <= note <= sur:
                continue
            propres.append({**n, "note": note, "sur": sur,
                            "code": code_module(f"{n.get('code', '')} {n.get('module', '')}") or ""})
        return propres


def notes_par_regex(mail: dict, texte: str) -> list[dict]:
    """Sans IA : une note « 12,5/20 » dans un mail dont le sujet nomme un module."""
    m = re.search(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s*/\s*20\b", texte)
    code = code_module(mail["sujet"])
    if not m or not code:
        return []
    return [{"module": mail["sujet"], "code": code, "evaluation": "", "note": float(m.group(1).replace(",", ".")),
             "sur": 20.0, "coefficient": 0, "moyenne_classe": 0, "date_evaluation": ""}]


def _normaliser_analyse(rep: dict, texte: str) -> dict:
    """Les petits modèles écrivent la date/l'heure à leur façon ('2026-11-19T10:15', '10h15'...) : on uniformise."""
    brut_date, brut_heure = str(rep.get("date") or ""), str(rep.get("heure") or "")
    m = re.search(r"\d{4}-\d{2}-\d{2}", brut_date)
    rep["date"] = m.group(0) if m else ""
    h = re.search(r"(\d{1,2})\s*[h:H]\s*(\d{2})?", brut_heure) or re.search(r"T(\d{2}):(\d{2})", brut_date)
    rep["heure"] = f"{int(h.group(1)):02d}:{h.group(2) or '00'}" if h and int(h.group(1)) < 24 else ""
    try:
        rep["duree_min"] = int(rep.get("duree_min") or 0)
    except (TypeError, ValueError):
        rep["duree_min"] = 0
    if not rep["duree_min"]:  # « de 10h15 à 12h15 »
        p = re.search(r"(\d{1,2})\s*h\s*(\d{2})?\s*(?:à|a|-|–|jusqu'à)\s*(\d{1,2})\s*h\s*(\d{2})?", texte)
        if p:
            debut = int(p.group(1)) * 60 + int(p.group(2) or 0)
            fin = int(p.group(3)) * 60 + int(p.group(4) or 0)
            rep["duree_min"] = fin - debut if 0 < fin - debut <= 8 * 60 else 0
        else:
            d = re.search(r"(?:dur[ée]e\s*(?:de)?\s*:?\s*)(\d)\s*h(?:eures?)?\s*(\d{2})?", texte, re.I)
            rep["duree_min"] = int(d.group(1)) * 60 + int(d.group(2) or 0) if d else 0
    return rep


def _message_hors_sujet() -> dict:
    return {"concerne_examen": False, "matiere": "", "nature": "autre", "date": "", "heure": "", "duree_min": 0,
            "salle": "", "documents_autorises": "", "programme": "", "consignes": "", "resume": ""}


def code_module(texte: str) -> str | None:
    """'R1.02 - Principes...' -> 'r102' ; 'Portfolio-SAé 1.04' -> 'sae104' ; 'R 106 archi...' -> 'r106'"""
    m = re.search(r"(?<![a-z0-9])(r|sae)\s?(\d)\s?\.?\s?(\d{2})(?!\d)", normaliser(texte))
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


def _similarite(a: str, b: str) -> float:
    a, b = normaliser(a), normaliser(b)
    if not a or not b:
        return 0.0
    mots_a = {m for m in re.findall(r"[a-z0-9]{3,}", a)}
    mots_b = {m for m in re.findall(r"[a-z0-9]{3,}", b)}
    commun = len(mots_a & mots_b) / max(1, len(mots_a))
    return max(commun, difflib.SequenceMatcher(None, a, b).ratio())


def classer_par_nom(f: dict) -> str:
    t = normaliser(f"{f.get('nom', '')} {f.get('module', '')} {f.get('section', '')}")
    if re.search(r"corrig|correction|solution|\bsol\b", t):
        return "corrige"
    if re.search(r"annale|examen|partiel|\bds\d*\b|\bcc\d*\b|\bct\b|controle|epreuve", t):
        return "annale"
    if re.search(r"\btd\d*\b|exercice|feuille", t):
        return "td"
    if re.search(r"\btp\d*\b|pratique|projet|\blab", t):
        return "tp"
    if re.search(r"sujet|session \d", t):
        return "annale"
    if re.search(r"cours|chapitre|\bch\d+|\bcm\d*\b|slides|diapo|poly|lecture|notes", t):
        return "cours"
    return "autre"
