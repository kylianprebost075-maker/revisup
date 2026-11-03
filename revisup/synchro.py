"""Synchronisation : EDT UPplanning + UPdago, puis détection des examens (nouveaux, déplacés, annoncés par mail)."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import edt, notifications, store
from .config import FUSEAU
from .ia_locale import MOTS_EXAMEN_MESSAGE, IALocale, _similarite
from .store import jolie_date, journal, maintenant
from .updago import ErreurUPdago, UPdago

# l'IA locale tourne sur le processeur (~30 s par message) : on lit les plus récents d'abord,
# et le reste aux synchros suivantes
MAX_ANALYSES_PAR_SYNC = 40
MESSAGES_RECENTS_JOURS = 120


def client_updago(cfg: dict) -> UPdago | None:
    jeton = store.lire_secrets().get("updago_jeton")
    return UPdago(cfg["updago"]["url"], jeton) if jeton else None


def synchroniser(cfg: dict) -> dict:
    bilan = {"edt": None, "updago": None, "nouveaux": [], "modifies": []}
    maintenant_ = maintenant()

    # 1. emploi du temps
    if cfg["edt"].get("ical_url"):
        try:
            evts = edt.lire_ical(edt.telecharger_ical(cfg["edt"]["ical_url"]))
            with store.modifier() as etat:
                etat["edt"] = {"evenements": evts, "maj": maintenant_.isoformat(timespec="seconds")}
            bilan["edt"] = f"{len(evts)} créneaux"
        except Exception as e:
            journal(f"EDT : échec du téléchargement ({e})", "erreur")
            bilan["edt"] = f"erreur : {e}"
    else:
        bilan["edt"] = "pas d'URL iCal configurée"

    # 2. UPdago
    client = client_updago(cfg)
    if client:
        try:
            bilan["updago"] = _synchro_updago(cfg, client)
        except ErreurUPdago as e:
            journal(f"UPdago : {e}", "erreur")
            bilan["updago"] = f"erreur : {e}"
            if "invalidtoken" in str(e).lower() or "jeton" in str(e).lower():
                notifications.envoyer(cfg, "UPdago : reconnexion nécessaire",
                                      "Lance « python -m revisup connexion » sur ton PC.",
                                      cle=f"jeton-expire-{maintenant_:%Y%m%d}", tags="warning")
        except Exception as e:
            journal(f"UPdago : erreur inattendue ({type(e).__name__}: {e})", "erreur")
            bilan["updago"] = f"erreur : {e}"
    else:
        bilan["updago"] = "non connecté (python -m revisup connexion)"

    # 3. examens de l'EDT et du calendrier UPdago tout de suite, puis ceux annoncés dans les messages,
    #    une fois que l'IA locale (lente) les a lus
    nouveaux, modifies = _fusionner_examens(cfg)
    _analyser_messages(cfg)
    n2, m2 = _fusionner_examens(cfg)
    nouveaux, modifies = nouveaux + n2, modifies + m2
    bilan["nouveaux"], bilan["modifies"] = nouveaux, modifies
    if len(nouveaux) > 3:  # premier passage : une seule notification récapitulative
        prochains = sorted(nouveaux, key=lambda e: e["debut"])
        notifications.envoyer(
            cfg, f"📅 {len(nouveaux)} examens détectés",
            "\n".join(f"{jolie_date(e['debut'])} — {e['matiere']}" for e in prochains[:6])
            + (f"\n… et {len(prochains) - 6} autres" if len(prochains) > 6 else ""),
            cle=f"lot-{maintenant_:%Y%m%d%H%M}", tags="date", priorite=4)
        for ex in nouveaux:
            with store.modifier() as etat:
                etat["notifs"][f"nouvel-{ex['id']}"] = maintenant_.isoformat(timespec="seconds")
        nouveaux_a_notifier = []
    else:
        nouveaux_a_notifier = nouveaux
    for ex in nouveaux_a_notifier:
        notifications.envoyer(
            cfg, f"📅 Nouvel examen : {ex['matiere']}",
            f"{jolie_date(ex['debut'])}{' — ' + ex['salle'] if ex.get('salle') else ''} (dans {store.jours_avant(ex['debut'])} j). "
            "RevisUP prépare ton pack de révision.",
            cle=f"nouvel-{ex['id']}", tags="date", priorite=4)
    for ex, quoi in modifies:
        notifications.envoyer(cfg, f"⚠️ Examen modifié : {ex['matiere']}", quoi,
                              cle=f"modif-{ex['id']}-{ex['debut']}-{ex.get('salle')}", tags="warning", priorite=4)
    journal(f"Synchro : EDT {bilan['edt']} · UPdago {bilan['updago']} · {len(nouveaux)} nouvel(s) examen(s)")
    return bilan


def _synchro_updago(cfg: dict, client: UPdago) -> str:
    info = client.infos_site()
    userid = info["userid"]
    cours = client.mes_cours(userid)
    limite = (maintenant() - timedelta(days=30)).isoformat()
    actifs = [c for c in cours if not c["masque"] and (not c["fin"] or c["fin"] >= limite)]

    fichiers, messages = [], []
    for c in actifs:
        try:
            f, annonces = client.contenu_cours(c)
            fichiers += f
            messages += annonces
        except ErreurUPdago as e:
            journal(f"UPdago : cours « {c['nom']} » illisible ({e})", "avertissement")
    try:
        messages += client.messages_forums(actifs, cfg["updago"].get("discussions_par_forum", 25))
    except ErreurUPdago as e:
        journal(f"UPdago : forums illisibles ({e})", "avertissement")
    try:
        messages += client.messages_prives(userid)
    except ErreurUPdago as e:
        journal(f"UPdago : messagerie illisible ({e})", "avertissement")
    try:
        calendrier = client.evenements_calendrier(maintenant(), maintenant() + timedelta(days=150))
    except ErreurUPdago:
        calendrier = []

    with store.modifier() as etat:
        etat["updago"] = {
            "utilisateur": {"id": userid, "nom": info.get("fullname", ""), "site": info.get("sitename", "")},
            "cours": actifs, "fichiers": fichiers, "messages": messages, "calendrier": calendrier,
            "maj": maintenant().isoformat(timespec="seconds"),
        }
    return f"{len(actifs)} cours, {len(fichiers)} fichiers, {len(messages)} messages"


def _analyser_messages(cfg: dict) -> None:
    etat = store.lire()
    deja = etat["analyses_messages"]
    recent = (maintenant() - timedelta(days=MESSAGES_RECENTS_JOURS)).isoformat()
    a_faire = [m for m in etat["updago"].get("messages", [])
               if m["id"] not in deja and (not m.get("date") or m["date"] >= recent)]
    if not a_faire:
        return
    a_faire.sort(key=lambda m: m.get("date") or "", reverse=True)
    ia = IALocale.depuis_config(cfg)
    aujourd_hui = maintenant().date().isoformat()
    resultats, appels = {}, 0
    for m in a_faire:
        lu_par_ia = bool(MOTS_EXAMEN_MESSAGE.search(f"{m.get('sujet', '')}\n{m.get('texte', '')}")) and ia.disponible()
        if lu_par_ia and appels >= MAX_ANALYSES_PAR_SYNC:
            continue  # sera lu à la prochaine synchro
        appels += lu_par_ia
        resultats[m["id"]] = {**ia.analyser_message(m, aujourd_hui), "ia": lu_par_ia}
    with store.modifier() as etat:
        etat["analyses_messages"].update(resultats)
    utiles = sum(1 for r in resultats.values() if r["concerne_examen"])
    reste = len(a_faire) - len(resultats)
    journal(f"IA locale : {len(resultats)} message(s) triés ({appels} lus en détail), {utiles} concernent un examen"
            + (f", {reste} restent pour la prochaine synchro" if reste else "")
            + ("" if ia.disponible() else " (IA locale éteinte : tri par mots-clés)"))


def _examens_detectes(cfg: dict, etat: dict) -> list[dict]:
    mots = cfg["edt"]["mots_cles_examen"]
    trouves = edt.detecter_examens(etat["edt"]["evenements"], mots, cfg["edt"].get("mots_exclus", []))

    # examens posés dans le calendrier UPdago (quiz/devoirs nommés "examen", "partiel"...)
    motif = edt.regex_examen(mots)
    for ev in etat["updago"].get("calendrier", []):
        if ev.get("debut") and edt.est_examen(ev["titre"], motif):
            debut = datetime.fromisoformat(ev["debut"])
            trouves.append({
                "id": edt.id_examen(ev["cours_nom"] or ev["titre"], ev["debut"], "upd"), "uid": ev["id"],
                "matiere": ev["cours_nom"] or edt.matiere_depuis_titre(ev["titre"], motif), "titre": ev["titre"],
                "debut": ev["debut"], "fin": (debut + timedelta(minutes=ev["duree_min"] or 60)).isoformat(),
                "salle": "UPdago (en ligne)" if ev["type"] in ("quiz", "assign") else "", "description": ev["description"],
                "source": "updago", "cours_id": ev["cours_id"],
            })

    # examens annoncés dans un message de prof (date précise donnée)
    messages = {m["id"]: m for m in etat["updago"].get("messages", [])}
    for mid, a in etat["analyses_messages"].items():
        if not (a.get("concerne_examen") and a.get("date") and a.get("nature") != "annulation"):
            continue
        try:
            debut = datetime.fromisoformat(f"{a['date']}T{a.get('heure') or '08:00'}").replace(tzinfo=FUSEAU)
        except ValueError:
            continue
        if not maintenant() - timedelta(days=200) < debut < maintenant() + timedelta(days=365):
            continue  # date farfelue de l'IA
        m = messages.get(mid, {})
        matiere = a.get("matiere") or m.get("cours_nom") or "Examen"
        trouves.append({
            "id": edt.id_examen(matiere, debut.isoformat(), "msg"), "uid": mid, "matiere": matiere,
            "titre": f"{matiere} (annoncé par {m.get('auteur') or 'un enseignant'})", "debut": debut.isoformat(),
            "fin": (debut + timedelta(minutes=a.get("duree_min") or 120)).isoformat(), "salle": a.get("salle", ""),
            "description": a.get("resume", ""), "source": "message", "cours_id": m.get("cours_id"),
            "heure_incertaine": not a.get("heure"),
        })
    return trouves


def _meme_examen(a: dict, b: dict) -> bool:
    return a["debut"][:10] == b["debut"][:10] and (
        (a.get("cours_id") and a.get("cours_id") == b.get("cours_id")) or _similarite(a["matiere"], b["matiere"]) >= 0.5)


def _fusionner_examens(cfg: dict) -> tuple[list[dict], list[tuple[dict, str]]]:
    etat = store.lire()
    detectes = _examens_detectes(cfg, etat)
    priorite = {"edt": 0, "updago": 1, "message": 2}
    detectes.sort(key=lambda e: priorite[e["source"]])
    nouveaux, modifies = [], []
    now_iso = maintenant().isoformat(timespec="seconds")

    with store.modifier() as etat:
        examens = etat["examens"]
        par_uid = {e.get("uid"): e for e in examens.values() if e.get("uid")}
        for ex in detectes:
            existant = par_uid.get(ex["uid"])
            if existant:
                changements = []
                if existant["debut"] != ex["debut"]:
                    changements.append(f"nouvelle date : {jolie_date(ex['debut'])} (avant : {jolie_date(existant['debut'])})")
                if ex.get("salle") and existant.get("salle") != ex["salle"]:
                    changements.append(f"salle : {ex['salle']}")
                if changements and not existant.get("manuel"):
                    existant.update({k: ex[k] for k in ("debut", "fin", "salle", "titre") if ex.get(k)})
                    modifies.append((existant, " · ".join(changements)))
                existant["vu_le"] = now_iso
                continue
            # le même examen, vu par une autre source (EDT + message du prof) : on complète au lieu de dupliquer
            jumeau = next((e for e in examens.values() if e["debut"] >= now_iso[:10] and _meme_examen(e, ex)), None)
            if jumeau:
                jumeau.setdefault("autres_sources", [])
                if ex["uid"] not in jumeau["autres_sources"]:
                    jumeau["autres_sources"].append(ex["uid"])
                jumeau["cours_id"] = jumeau.get("cours_id") or ex.get("cours_id")
                if jumeau.get("heure_incertaine") and not ex.get("heure_incertaine"):
                    jumeau.update(debut=ex["debut"], fin=ex["fin"], heure_incertaine=False)
                continue
            ex.update(statut="a_preparer", detecte_le=now_iso, vu_le=now_iso)
            examens[ex["id"]] = ex
            par_uid[ex["uid"]] = ex
            if datetime.fromisoformat(ex["debut"]) >= maintenant():
                nouveaux.append(ex)
    return nouveaux, modifies


def ajouter_examen_manuel(matiere: str, debut: datetime, duree_min: int = 120, salle: str = "",
                          cours_id: int | None = None) -> dict:
    ex = {
        "id": edt.id_examen(matiere, debut.isoformat(), "man"), "uid": None, "matiere": matiere,
        "titre": matiere, "debut": debut.isoformat(), "fin": (debut + timedelta(minutes=duree_min)).isoformat(),
        "salle": salle, "description": "", "source": "manuel", "manuel": True, "cours_id": cours_id,
        "statut": "a_preparer", "detecte_le": maintenant().isoformat(timespec="seconds"),
    }
    with store.modifier() as etat:
        etat["examens"][ex["id"]] = ex
    return ex
