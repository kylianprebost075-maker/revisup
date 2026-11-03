"""Planning de révision : répartit les sessions dans tes créneaux libres (EDT retiré), examen par examen.

Principe :
- chaque examen = une file de tâches (apprendre chapitre → exercices → QCM de rappel → annale → révision finale),
  dimensionnée par l'estimation d'heures de Claude (ou une valeur par défaut) ;
- à chaque créneau libre, on place la tâche de l'examen le plus "en retard" (travail restant / créneaux restants),
  en évitant d'enchaîner trop de sessions de la même matière ;
- la veille de chaque examen : révision finale (fiche + points clés + pièges) ;
- les sessions passées sont considérées comme faites, sauf si tu les marques "ratées".
"""
from __future__ import annotations

import bisect
import hashlib
from datetime import datetime, timedelta

from icalendar import Alarm, Calendar, Event

from . import edt, store
from .config import FUSEAU
from .store import maintenant

MARGE_AVANT_EXAMEN = timedelta(hours=2)


def _tache(examen: dict, type_: str, intitule: str, cle: str, chapitre: str = "") -> dict:
    return {"examen_id": examen["id"], "matiere": examen["matiere"], "type": type_, "tache": intitule,
            "chapitre": chapitre, "cle": f"{examen['id']}:{cle}"}


def taches_examen(cfg: dict, examen: dict, pack: dict | None) -> tuple[list[dict], dict]:
    duree_h = cfg["planning"]["duree_session_min"] / 60
    chapitres = (pack or {}).get("chapitres") or []
    taches = []
    if chapitres:
        for i, ch in enumerate(chapitres):
            n = max(1, round(max(0.5, float(ch.get("heures_estimees") or 1)) / duree_h))
            n_app = max(1, round(n * 0.5))
            for k in range(n_app):
                suffixe = f" ({k + 1}/{n_app})" if n_app > 1 else ""
                taches.append(_tache(examen, "apprendre", f"Apprendre : {ch['titre']}{suffixe}", f"app:{i}:{k}", ch["titre"]))
            for k in range(max(1, n - n_app)):
                taches.append(_tache(examen, "exercices", f"Exercices : {ch['titre']}", f"exo:{i}:{k}", ch["titre"]))
            if i % 2 == 1:
                taches.append(_tache(examen, "qcm", f"QCM de rappel (chapitres 1 à {i + 1})", f"qcm:{i}"))
    else:
        n = max(3, round(float(examen.get("heures_estimees") or cfg["preparation"]["heures_par_examen"]) / duree_h))
        for k in range(max(1, round(n * 0.4))):
            taches.append(_tache(examen, "apprendre", f"Relire le cours et faire ta fiche (partie {k + 1})", f"app:g:{k}"))
        for k in range(max(1, round(n * 0.4))):
            taches.append(_tache(examen, "exercices", f"Refaire les exercices de TD (série {k + 1})", f"exo:g:{k}"))
        taches.append(_tache(examen, "qcm", "Questions de cours / QCM", "qcm:g"))

    annales = pack and "pas d'annale" not in (pack.get("analyse_annales") or "").lower()
    taches.append(_tache(examen, "annale",
                         "Annale en conditions réelles (chronométrée)" if annales else "Exercices difficiles du pack, chronométrés",
                         "annale:0"))
    if pack:
        taches.append(_tache(examen, "qcm", "QCM complet du pack + revoir les erreurs", "qcm:final"))
    finale = _tache(examen, "final", "Révision finale : fiche, points clés, pièges", "final")
    return taches, finale


def _decouper(libres: list[tuple[datetime, datetime]], cfg: dict) -> list[tuple[datetime, datetime]]:
    duree = timedelta(minutes=cfg["planning"]["duree_session_min"])
    pause = timedelta(minutes=cfg["planning"]["pause_min"])
    creneaux = []
    for a, b in libres:
        # on démarre au quart d'heure suivant
        a = a + timedelta(minutes=(-a.minute) % 15, seconds=-a.second, microseconds=-a.microsecond)
        while a + duree <= b:
            creneaux.append((a, a + duree))
            a += duree + pause
    return creneaux


def generer(cfg: dict) -> dict:
    etat = store.lire()
    maintenant_ = maintenant()
    precedent = etat["planning"].get("sessions", [])
    ratees = {s["cle"] for s in precedent if s.get("ratee")}
    historique = [s for s in precedent if datetime.fromisoformat(s["fin"]) <= maintenant_ and s["cle"] not in ratees]
    faites = {s["cle"] for s in historique} | set(etat.get("taches_faites", []))

    examens = sorted((e for e in etat["examens"].values()
                      if datetime.fromisoformat(e["debut"]) > maintenant_ and not e.get("ignore")),
                     key=lambda e: e["debut"])
    if not examens:
        return _sauver(historique, [], [])

    files, finales = {}, {}
    for ex in examens:
        taches, finale = taches_examen(cfg, ex, store.lire_pack(ex["id"]))
        files[ex["id"]] = [t for t in taches if t["cle"] not in faites]
        finales[ex["id"]] = None if finale["cle"] in faites else finale

    fin = max(datetime.fromisoformat(e["debut"]) for e in examens)
    occupes = etat["edt"]["evenements"] + [{"debut": e["debut"], "fin": e["fin"]} for e in examens]
    cfg_planning = {**cfg["planning"], "journees": etat.get("journees", {})}  # « aujourd'hui je fais… » prime
    creneaux = _decouper(edt.creneaux_libres(occupes, maintenant_ + timedelta(minutes=10), fin, cfg_planning), cfg)
    fins = [b for _, b in creneaux]

    debut_ex = {e["id"]: datetime.fromisoformat(e["debut"]) for e in examens}
    limite = {i: d - MARGE_AVANT_EXAMEN for i, d in debut_ex.items()}
    # jour de la révision finale = dernier jour (avant celui de l'examen si possible) qui a un créneau
    jour_final = {}
    for i, lim in limite.items():
        jours = sorted({a.date() for a, b in creneaux if b <= lim})
        avant = [j for j in jours if j < debut_ex[i].date()]
        jour_final[i] = (avant or jours or [None])[-1]

    max_min_jour = cfg["planning"]["max_heures_par_jour"] * 60
    duree = cfg["planning"]["duree_session_min"]
    minutes_jour: dict = {}
    nouvelles = []
    derniers: list[str] = []
    for idx, (a, b) in enumerate(creneaux):
        jour = a.date()
        if minutes_jour.get(jour, 0) + duree > max_min_jour:
            continue
        meilleur, score_max = None, 0.0
        for ex in examens:
            i = ex["id"]
            if b > limite[i] or not (files[i] or finales[i]):
                continue
            if finales[i] and jour == jour_final[i]:
                score = 1e6  # la veille : révision finale en priorité
            elif files[i]:
                restants = bisect.bisect_right(fins, limite[i]) - idx
                score = len(files[i]) / max(1, restants)
                if derniers[-2:] == [i, i]:
                    score *= 0.5  # pas plus de deux sessions d'affilée sur la même matière
            else:
                continue
            if score > score_max:
                meilleur, score_max = ex, score
        if not meilleur:
            continue
        i = meilleur["id"]
        if finales[i] and jour == jour_final[i]:
            tache, finales[i] = finales[i], None
        else:
            tache = files[i].pop(0)
        nouvelles.append({**tache, "debut": a.isoformat(), "fin": b.isoformat()})
        minutes_jour[jour] = minutes_jour.get(jour, 0) + duree
        derniers.append(i)

    alertes = []
    for ex in examens:
        manque = len(files[ex["id"]]) + (1 if finales[ex["id"]] else 0)
        if manque:
            alertes.append(f"{ex['matiere']} : il manque ~{manque * duree / 60:.0f} h de révision avant le "
                           f"{store.jolie_date(ex['debut'], False)}. Ajoute des plages dans config.toml "
                           "(section [planning]) ou augmente max_heures_par_jour.")
    return _sauver(historique, nouvelles, alertes)


def _sauver(historique, nouvelles, alertes) -> dict:
    planning = {"sessions": historique + nouvelles, "genere_le": maintenant().isoformat(timespec="seconds"), "alertes": alertes}
    with store.modifier() as etat:
        etat["planning"] = planning
    return planning


def marquer(cle: str, statut: str) -> None:
    """statut : 'faite' (en avance), 'ratee' (à replanifier) ou 'annuler' (efface la marque)."""
    with store.modifier() as etat:
        faites = set(etat.get("taches_faites", []))
        for s in etat["planning"]["sessions"]:
            if s["cle"] == cle:
                s["ratee"] = statut == "ratee"
                s["faite"] = statut == "faite"
        if statut == "faite":
            faites.add(cle)
        else:
            faites.discard(cle)
        etat["taches_faites"] = sorted(faites)


def export_ics(cfg: dict) -> bytes:
    etat = store.lire()
    cal = Calendar()
    cal.add("prodid", "-//RevisUP//Universite de Poitiers//FR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Révisions (RevisUP)")
    depuis = maintenant() - timedelta(days=14)
    rappel = cfg["notifications"].get("rappel_session_min", 10)
    for s in etat["planning"]["sessions"]:
        if datetime.fromisoformat(s["fin"]) < depuis or s.get("ratee"):
            continue
        ev = Event()
        ev.add("uid", hashlib.sha1(s["cle"].encode()).hexdigest()[:20] + "@revisup")
        ev.add("summary", f"📚 {s['matiere']} — {s['tache']}")
        ev.add("dtstart", datetime.fromisoformat(s["debut"]).astimezone(FUSEAU))
        ev.add("dtend", datetime.fromisoformat(s["fin"]).astimezone(FUSEAU))
        ev.add("description", f"Session de révision RevisUP ({s['type']}).")
        if rappel:
            al = Alarm()
            al.add("action", "DISPLAY")
            al.add("description", s["tache"])
            al.add("trigger", timedelta(minutes=-rappel))
            ev.add_component(al)
        cal.add_component(ev)
    for e in etat["examens"].values():
        if datetime.fromisoformat(e["fin"]) < depuis or e.get("ignore"):
            continue
        ev = Event()
        ev.add("uid", hashlib.sha1(e["id"].encode()).hexdigest()[:20] + "@revisup-examen")
        ev.add("summary", f"🎓 EXAMEN {e['matiere']}")
        ev.add("dtstart", datetime.fromisoformat(e["debut"]).astimezone(FUSEAU))
        ev.add("dtend", datetime.fromisoformat(e["fin"]).astimezone(FUSEAU))
        if e.get("salle"):
            ev.add("location", e["salle"])
        cal.add_component(ev)
    return cal.to_ical()
