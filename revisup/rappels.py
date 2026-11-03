"""Rappels : J-14 / J-7 / J-3 / J-1 avant chaque examen, résumé du matin, question du midi, début de session."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from . import notifications, store
from .store import jolie_date, jours_avant, maintenant

# réponses rapides à « Qu'est-ce que tu fais aujourd'hui ? » (boutons sur ordinateur ; sur iPhone, dans la page)
CHOIX_JOURNEE = [{"action": "salle", "title": "🏋️ Salle"}, {"action": "course", "title": "🏃 Course"},
                 {"action": "rien", "title": "📚 Rien, je révise"}]


def verifier(cfg: dict) -> None:
    etat = store.lire()
    n = cfg["notifications"]
    maintenant_ = maintenant()
    lien = (cfg["web"].get("url_publique") or f"http://localhost:{cfg['web']['port']}").rstrip("/")

    # 1. compte à rebours des examens (on n'envoie que le palier le plus proche)
    paliers = sorted(n.get("rappels_jours", [14, 7, 3, 1]))
    for ex in etat["examens"].values():
        if ex.get("ignore") or datetime.fromisoformat(ex["debut"]) < maintenant_:
            continue
        j = jours_avant(ex["debut"])
        atteints = [p for p in paliers if j <= p]
        if not atteints:
            continue
        palier = atteints[0]
        cles = [f"rappel-{ex['id']}-J{p}" for p in atteints]
        if cles[0] in etat["notifs"]:
            continue
        with store.modifier() as e:  # les paliers plus lointains déjà dépassés ne seront pas envoyés après coup
            for c in cles[1:]:
                e["notifs"].setdefault(c, maintenant_.isoformat(timespec="seconds"))
        infos = ex.get("infos", {})
        details = [jolie_date(ex["debut"])]
        if ex.get("salle") or infos.get("salle"):
            details.append(f"salle {infos.get('salle') or ex['salle']}")
        if infos.get("documents_autorises"):
            details.append(f"documents : {infos['documents_autorises']}")
        quand = "demain" if j == 1 else "aujourd'hui" if j == 0 else f"dans {j} jours"
        etat_pack = {"pret": "Ton pack de révision est prêt.", "prompt_manuel": "Prompt Claude à lancer.",
                     "erreur": "La préparation a échoué, regarde le tableau de bord."}.get(ex.get("statut"), "")
        page = f"/#/examen/{ex['id']}"
        notifications.envoyer(cfg, f"⏰ J-{j} : {ex['matiere']} {quand}", " · ".join(details) + ". " + etat_pack,
                              cle=cles[0], tags="alarm_clock", priorite=5 if j <= 1 else 4, lien=lien + page, page=page)

    sessions = etat["planning"].get("sessions", [])

    # 2. résumé du matin
    heure_resume = time.fromisoformat(n.get("resume_quotidien", "07:30"))
    if maintenant_.time() >= heure_resume:
        aujourd_hui = maintenant_.date()
        du_jour = [s for s in sessions if datetime.fromisoformat(s["debut"]).date() == aujourd_hui and not s.get("ratee")]
        examens_du_jour = [e for e in etat["examens"].values() if datetime.fromisoformat(e["debut"]).date() == aujourd_hui]
        if du_jour or examens_du_jour:
            lignes = [f"🎓 {e['matiere']} à {datetime.fromisoformat(e['debut']):%Hh%M}" for e in examens_du_jour]
            lignes += [f"{datetime.fromisoformat(s['debut']):%Hh%M} {s['matiere']} — {s['tache']}" for s in du_jour]
            notifications.envoyer(cfg, f"📚 Programme du jour ({len(du_jour)} session(s))", "\n".join(lignes),
                                  cle=f"resume-{aujourd_hui}", tags="sunrise", lien=lien + "/#/journee", page="/#/journee")

    # 3. question du midi : qu'est-ce que tu fais aujourd'hui ? (le planning du jour s'adapte à la réponse)
    heure_question = n.get("question_du_jour", "12:00")
    aujourd_hui = maintenant_.date().isoformat()
    if heure_question and maintenant_.time() >= time.fromisoformat(heure_question) \
            and aujourd_hui not in etat.get("journees", {}) and maintenant_.hour < 21:
        notifications.envoyer(cfg, "🗓️ Qu'est-ce que tu fais aujourd'hui ?",
                              "Salle, course, autre chose ? Réponds et ton planning de révision s'adapte.",
                              cle=f"journee-{aujourd_hui}", tags="calendar", priorite=4,
                              lien=lien + "/#/journee", page="/#/journee", actions=CHOIX_JOURNEE)

    # 4. début de session
    avance = n.get("rappel_session_min", 10)
    if avance:
        for s in sessions:
            debut = datetime.fromisoformat(s["debut"])
            if not s.get("ratee") and timedelta(0) <= debut - maintenant_ <= timedelta(minutes=avance):
                page = f"/#/examen/{s['examen_id']}"
                notifications.envoyer(cfg, f"▶️ {s['matiere']} à {debut:%Hh%M}", s["tache"],
                                      cle=f"session-{s['cle']}-{s['debut']}", tags="books", lien=lien + page, page=page)
