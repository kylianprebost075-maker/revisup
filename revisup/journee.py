"""Ma journée : la réponse à « qu'est-ce que tu fais aujourd'hui ? » remplace les activités habituelles du jour,
puis le planning de révision est recalculé."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from . import edt, planning, store
from .config import FUSEAU
from .store import maintenant

CHOIX = {
    "salle": "🏋️ Salle de sport",
    "course": "🏃 Course à pied",
    "rien": "📚 Rien de prévu, je peux réviser",
    "soiree": "😴 Pas dispo ce soir",
    "autre": "🎯 Autre chose",
    "habituel": "↺ Comme d'habitude",
}
SOIREE = {"nom": "Pas dispo ce soir", "debut": "18:00", "fin": "23:59"}


def _habituelle(cfg: dict, mot: str, defaut: dict) -> dict:
    """L'activité de config.toml dont le nom contient `mot` (pour garder la même durée), sinon `defaut`."""
    for a in cfg["planning"].get("activites", []):
        if mot in edt.normaliser(a.get("nom", "")):
            return {k: v for k, v in a.items() if k != "jours"}
    return defaut


def _heure(h: str | None) -> str | None:
    if h and re.fullmatch(r"\d{1,2}:\d{2}", h.strip()):
        return time.fromisoformat(h.strip().zfill(5)).strftime("%H:%M")
    return None


def repondre(cfg: dict, choix: str, debut: str | None = None, fin: str | None = None, nom: str = "",
             jour: date | None = None) -> dict:
    jour = jour or maintenant().date()
    debut, fin = _heure(debut), _heure(fin)
    if choix not in CHOIX:
        raise ValueError("choix inconnu")
    if debut and fin and debut >= fin:
        raise ValueError("l'heure de fin doit être après l'heure de début")
    plage = {"debut": debut, "fin": fin} if debut and fin else None
    if choix == "salle":
        activites = [{"nom": "Salle de sport", **plage} if plage
                     else _habituelle(cfg, "salle", {"nom": "Salle de sport", "apres_les_cours": True, "duree_min": 90})]
    elif choix == "course":
        activites = [{"nom": "Course à pied", **plage} if plage
                     else _habituelle(cfg, "course", {"nom": "Course à pied", "debut": "18:45", "fin": "20:00"})]
    elif choix == "soiree":
        activites = [SOIREE]
    elif choix == "autre":
        if not plage:
            raise ValueError("indique de quelle heure à quelle heure tu es pris")
        activites = [{"nom": nom.strip()[:40] or "Autre activité", **plage}]
    else:
        activites = []
    with store.modifier() as e:
        if choix == "habituel":
            e.setdefault("journees", {}).pop(jour.isoformat(), None)
        else:
            e.setdefault("journees", {})[jour.isoformat()] = {
                "choix": choix, "activites": activites, "repondu_le": maintenant().isoformat(timespec="seconds")}
    planning.generer(cfg)
    return du_jour(cfg, jour)


# ── message libre : « ce soir ciné de 20h à 23h », « jeudi pas de course », « demain je suis malade » ──

SCHEMA_TEXTE = {
    "type": "object",
    "properties": {
        "jours": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "garder_habitudes": {"type": "boolean"},
                "journee_sans_revision": {"type": "boolean"},
                "activites": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"nom": {"type": "string"}, "debut": {"type": "string"}, "fin": {"type": "string"}},
                    "required": ["nom", "debut", "fin"], "additionalProperties": False}},
            },
            "required": ["date", "garder_habitudes", "journee_sans_revision", "activites"], "additionalProperties": False}},
        "resume": {"type": "string"},
    },
    "required": ["jours", "resume"],
    "additionalProperties": False,
}

SYSTEME_TEXTE = """Tu aides un étudiant à tenir son planning de révision. Il t'écrit ce qui change dans ses journées.
Transforme son message en moments où il NE PEUT PAS réviser, jour par jour.

Règles :
- date au format AAAA-MM-JJ, choisie dans la liste des prochains jours fournie (« ce soir » = aujourd'hui, « demain », « jeudi »…).
- activites : seulement ce que le MESSAGE ajoute (jamais les cours ni les habitudes, déjà connus), heures au format HH:MM
  sur 24 h. Sans heure précise : « ce soir » = 18:00-23:59,
  « le matin » = 08:00-12:00, « l'après-midi » = 13:00-18:00, « à midi » = 12:00-14:00.
- garder_habitudes = false si le message annule ou remplace son activité habituelle de ce jour-là (« pas de salle »,
  « pas de course », « je suis dispo ce soir ») ; sinon true.
- journee_sans_revision = true s'il ne pourra pas réviser du tout ce jour-là (malade, voyage, journée prise).
- S'il dit qu'il est libre ou veut réviser plus, activites vide et garder_habitudes = false.
- Seulement les jours dont parle le message. N'invente rien.
- resume : une phrase courte qui lui dit ce que tu as compris (ce qui est ajouté ET ce qui est annulé), en le tutoyant,
  avec les jours et les heures. Ne parle pas des cours."""


def _contexte_jours(cfg: dict, etat: dict, nb: int = 8) -> str:
    cfg_planning = {**cfg["planning"], "journees": etat.get("journees", {})}
    aujourd_hui = maintenant().date()
    lignes = []
    for i in range(nb):
        j = aujourd_hui + timedelta(days=i)
        cours = sorted(datetime.fromisoformat(e["debut"]).astimezone(FUSEAU) for e in etat["edt"]["evenements"]
                       if datetime.fromisoformat(e["debut"]).astimezone(FUSEAU).date() == j)
        fins = sorted(datetime.fromisoformat(e["fin"]).astimezone(FUSEAU) for e in etat["edt"]["evenements"]
                      if datetime.fromisoformat(e["debut"]).astimezone(FUSEAU).date() == j)
        habitudes = [a.get("nom", "") + (f" {a['debut']}-{a['fin']}" if a.get("debut") else " après les cours")
                     for a in edt.activites_du_jour(j, cfg_planning)]
        lignes.append(f"- {edt.JOURS_SEMAINE[j.weekday()]} {j.isoformat()}{' (aujourd’hui)' if i == 0 else ''} : "
                      + (f"cours {cours[0]:%H:%M}-{fins[-1]:%H:%M}" if cours else "pas de cours")
                      + (f" ; prévu : {', '.join(habitudes)}" if habitudes else ""))
    return "\n".join(lignes)


def interpreter(cfg: dict, texte: str) -> dict:
    """Comprend le message (IA locale, sinon Claude), l'applique aux jours concernés et recalcule le planning."""
    from . import ia_claude
    from .ia_locale import IALocale
    texte = texte.strip()[:600]
    if not texte:
        raise ValueError("écris d'abord ce qui change")
    etat = store.lire()
    demande = f"Prochains jours :\n{_contexte_jours(cfg, etat)}\n\nMessage de l'étudiant : « {texte} »"
    ia = IALocale(cfg["ia_locale"]["url"], cfg["ia_locale"]["modele"], timeout=240, effort="low")
    if ia.disponible():
        rep = ia._json(SYSTEME_TEXTE, demande, SCHEMA_TEXTE, 800)
    else:
        rep, _ = ia_claude.demander_json(cfg, SYSTEME_TEXTE, demande, SCHEMA_TEXTE)

    aujourd_hui = maintenant().date()
    cfg_planning = {**cfg["planning"], "journees": etat.get("journees", {})}
    appliques = []
    with store.modifier() as e:
        journees = e.setdefault("journees", {})
        for j in rep.get("jours", []):
            try:
                jour = date.fromisoformat(j["date"])
            except (KeyError, ValueError):
                continue
            if not aujourd_hui <= jour <= aujourd_hui + timedelta(days=30):
                continue
            activites = list(edt.activites_du_jour(jour, cfg_planning)) if j.get("garder_habitudes") else []
            for a in j.get("activites", []):
                debut, fin = _heure(a.get("debut")), _heure(a.get("fin"))
                if edt.normaliser(str(a.get("nom", ""))).startswith("cours"):
                    continue  # les cours viennent déjà de l'emploi du temps
                if debut and fin and debut < fin:
                    activites.append({"nom": str(a.get("nom") or "Occupé")[:40], "debut": debut, "fin": fin})
            if j.get("journee_sans_revision"):
                activites.append({"nom": "Pas de révision aujourd'hui", "debut": "00:00", "fin": "23:59"})
            journees[jour.isoformat()] = {"choix": "texte", "texte": texte, "activites": activites,
                                         "repondu_le": maintenant().isoformat(timespec="seconds")}
            appliques.append(jour.isoformat())
    if appliques:
        planning.generer(cfg)
    return {"resume": rep.get("resume", ""), "jours": appliques, **du_jour(cfg)}


def du_jour(cfg: dict, jour: date | None = None) -> dict:
    jour = jour or maintenant().date()
    etat = store.lire()
    cfg_planning = {**cfg["planning"], "journees": etat.get("journees", {})}
    debut = datetime.combine(jour, time(0, 0), FUSEAU)
    fin = debut + timedelta(days=1) - timedelta(seconds=1)
    cours = sorted((datetime.fromisoformat(e["debut"]).astimezone(FUSEAU), datetime.fromisoformat(e["fin"]).astimezone(FUSEAU))
                   for e in etat["edt"]["evenements"] if datetime.fromisoformat(e["debut"]).astimezone(FUSEAU).date() == jour)
    bloque = [{"nom": n, "debut": a.isoformat(), "fin": b.isoformat()}
              for a, b, n in edt.occupations_perso(etat["edt"]["evenements"], debut, fin, cfg_planning)]
    sessions = [s for s in etat["planning"].get("sessions", []) if datetime.fromisoformat(s["debut"]).date() == jour]
    reponse = etat.get("journees", {}).get(jour.isoformat())
    a_venir = sorted((d, r) for d, r in etat.get("journees", {}).items() if d > jour.isoformat())
    return {"date": jour.isoformat(), "jour": edt.JOURS_SEMAINE[jour.weekday()], "choix": reponse and reponse["choix"],
            "texte": reponse and reponse.get("texte"),
            "prochains": [{"date": d, "jour": edt.JOURS_SEMAINE[date.fromisoformat(d).weekday()], "texte": r.get("texte"),
                           "choix": r["choix"], "activites": r["activites"]} for d, r in a_venir],
            "libelles": CHOIX, "cours": {"debut": cours[0][0].isoformat(), "fin": cours[-1][1].isoformat()} if cours else None,
            "bloque": sorted(bloque, key=lambda b: b["debut"]), "sessions": sessions,
            "habituel": [a.get("nom") for a in edt.activites_du_jour(jour, cfg["planning"])]}
