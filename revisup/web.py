"""Tableau de bord (http://localhost:8765) + tâches automatiques en arrière-plan."""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from . import (ajouts, config, ia_claude, jeux, journee, notes, notifications, planning, preparation, push, rappels, sante,
               store, synchro, tuteur)
from .ia_locale import IALocale, _similarite
from .store import DOSSIER_COURS, maintenant

STATIC = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 80_000_000  # photos de plusieurs pages prises au téléphone
_tache = {"nom": None, "depuis": None}
_verrou_tache = threading.Lock()


# ── tâches de fond ──────────────────────────────────────────────────────

def tout(cfg: dict) -> None:
    sante.verifier(cfg)  # alerte sur l'iPhone si une connexion a lâché ; relance LM Studio s'il est fermé
    synchro.synchroniser(cfg)
    if notes.configure(cfg):
        try:
            notes.synchroniser(cfg)
        except Exception as e:
            store.journal(f"Notes : lecture des mails impossible ({e})", "erreur")
    preparation.preparer_tout(cfg)
    jeux.cartes_a_creer(cfg)  # cartes mémoire des nouveaux packs, en arrière-plan
    tuteur.lecons_a_creer(cfg)  # leçons vivantes du prochain examen, en arrière-plan
    tuteur.annales_a_creer(cfg)  # annales corrigées du prochain examen qui en a
    planning.generer(cfg)
    rappels.verifier(cfg)


def lancer(nom: str, fonction, *args) -> bool:
    if not _verrou_tache.acquire(blocking=False):
        return False

    def travail():
        _tache.update(nom=nom, depuis=maintenant().isoformat(timespec="seconds"))
        try:
            fonction(*args)
        except Exception as e:
            store.journal(f"{nom} : {type(e).__name__}: {e}", "erreur")
            traceback.print_exc()
        finally:
            _tache.update(nom=None, depuis=None)
            _verrou_tache.release()

    threading.Thread(target=travail, daemon=True).start()
    return True


def planificateur(cfg: dict) -> None:
    derniere = 0.0
    periode = cfg["web"].get("sync_toutes_les_heures", 3) * 3600
    while True:
        try:
            if time.time() - derniere >= periode and lancer("Synchronisation automatique", tout, cfg):
                derniere = time.time()
            elif _tache["nom"] is None:
                rappels.verifier(cfg)
        except Exception as e:
            print(f"[planificateur] {e}")
        time.sleep(60)


# ── accès depuis l'iPhone : code facultatif ─────────────────────────────

@app.before_request
def verifier_acces():
    code = app.config["CFG"]["web"].get("code_acces")
    if not code or request.remote_addr in ("127.0.0.1", "::1"):
        return None
    if request.args.get("code") == code:
        return None
    if request.cookies.get("revisup_code") == code:
        return None
    return Response("Accès protégé : ajoute ?code=TON_CODE à l'adresse.", 401)


@app.after_request
def memoriser_code(rep):
    code = app.config["CFG"]["web"].get("code_acces")
    if code and request.args.get("code") == code:
        rep.set_cookie("revisup_code", code, max_age=3600 * 24 * 180, samesite="Strict")
    return rep


# ── pages ───────────────────────────────────────────────────────────────

FICHIERS_APP = ("app.js", "jeux.js", "style.css")


def _version_app() -> str:
    """Change dès qu'un fichier de l'app est modifié : la web app de l'iPhone ou du Mac se recharge alors seule."""
    return format(int(sum((STATIC / f).stat().st_mtime for f in FICHIERS_APP)) % 16**8, "x")


@app.get("/")
def accueil():
    version, html = _version_app(), (STATIC / "index.html").read_text(encoding="utf-8")
    for f in FICHIERS_APP:  # l'adresse change à chaque version : aucun cache ne peut servir l'ancien fichier
        html = html.replace(f'"/static/{f}"', f'"/static/{f}?v={version}"')
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.get("/api/version")
def api_version():
    return jsonify(version=_version_app())


@app.get("/static/<path:nom>")
def statique(nom):
    return send_from_directory(STATIC, nom)


@app.get("/manifest.webmanifest")
def manifeste():
    return send_from_directory(STATIC, "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    """À la racine : le service worker ne gère que les pages sous son propre dossier."""
    rep = send_from_directory(STATIC, "sw.js", mimetype="text/javascript")
    rep.headers["Cache-Control"] = "no-cache"
    return rep


@app.get("/planning.ics")
def ics():
    return Response(planning.export_ics(app.config["CFG"]), mimetype="text/calendar",
                    headers={"Content-Disposition": "inline; filename=revisions.ics"})


@app.get("/fichiers/<path:rel>")
def fichier(rel):
    chemin = (DOSSIER_COURS / rel).resolve()
    if not chemin.is_file() or DOSSIER_COURS.resolve() not in chemin.parents:
        abort(404)
    return send_file(chemin)


# ── API ─────────────────────────────────────────────────────────────────

def _resume_examen(ex: dict) -> dict:
    pack = store.lire_pack(ex["id"])
    return {**ex, "jours": store.jours_avant(ex["debut"]),
            "pack": None if not pack else {"chapitres": len(pack.get("chapitres", [])), "qcm": len(pack.get("qcm", [])),
                                           "exercices": len(pack.get("exercices", [])), "genere_le": pack["_meta"].get("genere_le")}}


@app.get("/api/etat")
def api_etat():
    cfg = app.config["CFG"]
    etat = store.lire()
    now = maintenant()
    examens = sorted((_resume_examen(e) for e in etat["examens"].values()
                      if datetime.fromisoformat(e["fin"]) >= now - timedelta(days=1)), key=lambda e: e["debut"])
    debut, fin = (now - timedelta(days=7)).isoformat(), (now + timedelta(days=21)).isoformat()
    return jsonify({
        "demo": bool(cfg.get("demo")),
        "maintenant": now.isoformat(timespec="seconds"),
        "examens": examens,
        "sessions": [s for s in etat["planning"].get("sessions", []) if debut <= s["debut"] <= fin],
        "planning_genere_le": etat["planning"].get("genere_le"),
        "alertes": etat["planning"].get("alertes", []),
        "cours_edt": [e for e in etat["edt"]["evenements"] if now.isoformat()[:10] <= e["debut"] <= fin],
        "echeances": [e for e in etat["updago"].get("calendrier", [])
                      if e.get("debut") and e["debut"] >= now.isoformat()][:15],
        "services": {
            "edt": {"ok": bool(cfg["edt"].get("ical_url")), "maj": etat["edt"].get("maj"),
                    "nb": len(etat["edt"]["evenements"])},
            "updago": {"ok": bool(store.lire_secrets().get("updago_jeton")), "maj": etat["updago"].get("maj"),
                       "utilisateur": etat["updago"].get("utilisateur"), "nb_cours": len(etat["updago"].get("cours", []))},
            "ia_locale": {"ok": IALocale.depuis_config(cfg).disponible(),
                          "modele": cfg["ia_locale"]["modele"]},
            "claude": {"mode": ia_claude.mode_effectif(cfg), "modele": cfg["claude"]["modele"]},
            "ntfy": cfg["notifications"].get("ntfy_sujet"),
        },
        "sante": {**etat.get("sante", {}),
                  "en_cours": sorted(_reparations | ({"messagerie"} if _connexion_mail["en_cours"] else set()))},
        "tache": _tache,
        "journal": etat["journal"][-60:][::-1],
    })


@app.get("/api/examen/<eid>")
def api_examen(eid):
    etat = store.lire()
    ex = etat["examens"].get(eid) or abort(404)
    messages = preparation.messages_lies(etat, ex)
    docs = []
    for f in preparation.fichiers_examen(etat, ex):  # son cours, et les fichiers d'autres cours au code du module
        cat = etat["classements_fichiers"].get(f["cle"], "?")
        local = preparation._chemin_local(f, cat) if cat != "?" else None
        docs.append({"nom": f["nom"], "categorie": cat, "section": f["section"], "taille": f["taille"],
                     "local": str(local.relative_to(DOSSIER_COURS)).replace("\\", "/") if local and local.exists() else None})
    for a in etat.get("ajouts", {}).get(eid, []):  # ajoutés à la main (fichiers du PC, photos)
        docs.append({"nom": a["nom"], "categorie": a["categorie"], "section": "ajouté par toi", "taille": a["taille"],
                     "local": a["local"] if (DOSSIER_COURS / a["local"]).exists() else None, "ajout_id": a["id"],
                     "lecture": a.get("texte"), "erreur": a.get("erreur"), "photos": a.get("photos", 0)})
    cours = sorted(etat["updago"].get("cours", []), key=lambda c: -_similarite(ex["matiere"], c["nom"]))
    return jsonify({"examen": _resume_examen(ex), "pack": store.lire_pack(eid), "messages": messages,
                    "documents": docs, "cours": [{"id": c["id"], "nom": c["nom"]} for c in cours],
                    "lecons_en_cours": tuteur.en_cours(eid), "lecons_lues": etat.get("lecons_lues", {}).get(eid, []),
                    "annales_en_cours": tuteur.annales_en_cours(eid), "a_des_annales": tuteur.a_des_annales(ex)})


@app.post("/api/examen/<eid>/documents")
def api_ajouter_documents(eid):
    """Fichiers du PC ou photos (plusieurs photos envoyées ensemble = un seul document)."""
    if eid not in store.lire()["examens"]:
        abort(404)
    try:
        nouveaux = ajouts.ajouter(app.config["CFG"], eid, request.form.get("categorie", "cours"), request.form.get("titre", ""),
                                  [(f.filename or "document", f.read()) for f in request.files.getlist("fichiers")])
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    return jsonify({"ok": True, "ajouts": nouveaux, "pack": bool(store.lire_pack(eid))})


@app.delete("/api/examen/<eid>/documents/<aid>")
def api_supprimer_document(eid, aid):
    try:
        ajouts.supprimer(eid, aid)
    except KeyError:
        abort(404)
    return jsonify({"ok": True})


@app.post("/api/examen/<eid>/annales")
def api_annales(eid):
    if not store.lire_pack(eid):
        abort(404)
    ok = tuteur.lancer_annales(app.config["CFG"], eid)
    return jsonify({"ok": ok, "message": None if ok else "L'annale corrigée est déjà en préparation."})


@app.post("/api/examen/<eid>/lecons")
def api_lecons(eid):
    if not store.lire_pack(eid):
        abort(404)
    ok = tuteur.lancer(app.config["CFG"], eid)
    return jsonify({"ok": ok, "message": None if ok else "Les leçons sont déjà en préparation."})


@app.post("/api/examen/<eid>/lecon-lue")
def api_lecon_lue(eid):
    c = request.get_json(force=True) or {}
    return jsonify({"ok": True, "lues": tuteur.marquer_lue(eid, int(c.get("index", 0)), bool(c.get("lue", True)))})


@app.post("/api/aide")
def api_aide():
    """Question de l'étudiant sur l'exercice ou la leçon qu'il a sous les yeux."""
    c = request.get_json(force=True) or {}
    try:
        reponse = tuteur.aide(app.config["CFG"], c.get("contexte") or {}, c.get("question", ""), c.get("historique") or [])
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "message": f"L'IA ne répond pas ({type(e).__name__}) : réessaie dans un instant."}), 503
    return jsonify({"ok": True, "reponse": reponse})


@app.post("/api/examen/<eid>/preparer")
def api_preparer(eid):
    if eid not in store.lire()["examens"]:
        abort(404)
    ok = lancer("Préparation de l'examen", preparation.preparer_examen, app.config["CFG"], eid)
    if ok:
        lancer_planning_apres()
    return jsonify({"ok": ok, "message": None if ok else "Une tâche est déjà en cours, réessaie dans un instant."})


def lancer_planning_apres():
    def attendre():
        time.sleep(1)
        with _verrou_tache:
            planning.generer(app.config["CFG"])
    threading.Thread(target=attendre, daemon=True).start()


@app.post("/api/examen/<eid>/modifier")
def api_modifier(eid):
    corps = request.get_json(force=True)
    with store.modifier() as etat:
        ex = etat["examens"].get(eid) or abort(404)
        if "cours_id" in corps:
            c = next((c for c in etat["updago"]["cours"] if c["id"] == int(corps["cours_id"])), None)
            ex.update(cours_id=c["id"] if c else None, cours_nom=c["nom"] if c else None, statut="a_preparer")
        if "ignore" in corps:
            ex["ignore"] = bool(corps["ignore"])
        if "infos" in corps:
            ex["infos_manuelles"] = {k: v for k, v in corps["infos"].items() if v}
            ex["infos"] = {**ex.get("infos", {}), **ex["infos_manuelles"]}
    planning.generer(app.config["CFG"])
    return jsonify({"ok": True})


@app.post("/api/examen/<eid>/pack")
def api_importer_pack(eid):
    """Mode manuel : on recolle la réponse JSON de Claude."""
    if eid not in store.lire()["examens"]:
        abort(404)
    try:
        pack = ia_claude.valider_pack(ia_claude.extraire_json(request.get_data(as_text=True)))
    except (ia_claude.ErreurClaude, json.JSONDecodeError) as e:
        return jsonify({"ok": False, "message": f"Réponse illisible : {e}"}), 400
    pack["_meta"] = {"mode": "manuel"}
    preparation.enregistrer_pack(app.config["CFG"], eid, pack)
    planning.generer(app.config["CFG"])
    return jsonify({"ok": True})


@app.get("/api/examen/<eid>/prompt")
def api_prompt(eid):
    ex = store.lire()["examens"].get(eid) or abort(404)
    chemin = Path(ex.get("prompt") or "")
    if not chemin.is_file():
        abort(404)
    return Response(chemin.read_text(encoding="utf-8"), mimetype="text/plain; charset=utf-8")


@app.post("/api/examens")
def api_ajouter():
    c = request.get_json(force=True)
    try:
        debut = datetime.fromisoformat(f"{c['date']}T{c.get('heure') or '08:00'}").replace(tzinfo=config.FUSEAU)
    except (KeyError, ValueError):
        return jsonify({"ok": False, "message": "Date ou heure invalide."}), 400
    ex = synchro.ajouter_examen_manuel(c["matiere"].strip(), debut, int(c.get("duree") or 120), c.get("salle", ""))
    planning.generer(app.config["CFG"])
    return jsonify({"ok": True, "id": ex["id"]})


@app.post("/api/synchro")
def api_synchro():
    ok = lancer("Synchronisation", tout, app.config["CFG"])
    return jsonify({"ok": ok, "message": None if ok else "Une tâche est déjà en cours."})


@app.post("/api/planning")
def api_planning():
    planning.generer(app.config["CFG"])
    return jsonify({"ok": True})


@app.get("/api/journee")
def api_journee():
    return jsonify(journee.du_jour(app.config["CFG"]))


@app.post("/api/journee")
def api_journee_repondre():
    """Réponse rapide (salle, course, rien…) pour aujourd'hui, ou pour `date` (annuler un message, par exemple)."""
    from datetime import date as date_
    c = request.get_json(force=True) or {}
    try:
        jour = date_.fromisoformat(c["date"]) if c.get("date") else None
        return jsonify(journee.repondre(app.config["CFG"], c.get("choix", ""), c.get("debut"), c.get("fin"),
                                        c.get("nom", ""), jour))
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.post("/api/journee/texte")
def api_journee_texte():
    """Message libre : l'IA locale comprend ce qui change et le planning s'adapte (de quelques secondes à 1 min)."""
    c = request.get_json(force=True) or {}
    try:
        return jsonify(journee.interpreter(app.config["CFG"], str(c.get("texte", ""))))
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    except Exception as e:
        store.journal(f"Ma journée : message non compris ({type(e).__name__}: {e})", "erreur")
        return jsonify({"ok": False, "message": "L'IA n'a pas réussi à lire ton message. Réessaie, ou utilise les boutons."}), 500


# ── jeux ─────────────────────────────────────────────────────────────────

@app.get("/api/jeux")
def api_jeux():
    return jsonify(jeux.tableau())


@app.get("/api/jeux/quiz/<eid>")
def api_jeux_quiz(eid):
    try:
        return jsonify(jeux.quiz(eid))
    except KeyError:
        abort(404)


@app.post("/api/jeux/resultat")
def api_jeux_resultat():
    c = request.get_json(force=True) or {}
    jeu = str(c.get("jeu", ""))
    if jeu not in ("quiz", "exo", "cartes", "associations"):
        return jsonify({"ok": False, "message": "jeu inconnu"}), 400
    return jsonify(jeux.resultat(jeu, str(c.get("cle", ""))[:80], int(c.get("score") or 0), int(c.get("justes") or 0),
                                 int(c.get("total") or 0), list(c.get("reponses") or [])[:50]))


@app.get("/api/jeux/cartes/<eid>")
def api_jeux_cartes(eid):
    return jsonify({"cartes": jeux.cartes(eid, toutes=request.args.get("toutes") == "1"),
                    "matiere": (store.lire()["examens"].get(eid) or {}).get("matiere", "")})


@app.post("/api/jeux/cartes/<eid>/generer")
def api_jeux_cartes_generer(eid):
    if not store.chemin_pack(eid).exists():
        abort(404)
    ok = jeux.lancer_generation(app.config["CFG"], eid)
    return jsonify({"ok": ok, "message": None if ok else "Déjà en cours."})


@app.post("/api/jeux/carte")
def api_jeux_carte():
    c = request.get_json(force=True) or {}
    return jsonify(jeux.reponse_carte(str(c.get("id", ""))[:20], bool(c.get("su"))))


# ── réparer une connexion (la fenêtre de connexion s'ouvre sur le PC) ─────────────

_reparations: set = set()


def _reparer(nom: str, fonction) -> bool:
    """Hors du verrou des tâches (une connexion ne doit pas attendre la fin d'une synchro), puis revérifie tout."""
    if nom in _reparations:
        return False
    _reparations.add(nom)

    def travail():
        try:
            fonction()
        except Exception as e:
            store.journal(f"Réparation {nom} : {type(e).__name__}: {e}", "erreur")
        finally:
            _reparations.discard(nom)
            sante.verifier(app.config["CFG"], alerter=False)

    threading.Thread(target=travail, daemon=True).start()
    return True


def _connexion_updago():
    from .updago import connexion_navigateur
    res = connexion_navigateur(app.config["CFG"]["updago"]["url"])
    store.ecrire_secret("updago_jeton", res["jeton"])
    store.journal("UPdago reconnecté")


def _connexion_claude():
    import subprocess
    exe = ia_claude.trouver_cli(app.config["CFG"])
    if not exe:
        raise RuntimeError("Claude Code introuvable")
    subprocess.run([exe, "auth", "login"], input="", capture_output=True, text=True, timeout=600,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


@app.post("/api/sante")
def api_sante():
    _reparer("verification", lambda: None)
    return jsonify({"ok": True})


@app.post("/api/reparer/<nom>")
def api_reparer(nom):
    cfg = app.config["CFG"]
    actions = {"updago": _connexion_updago, "claude": _connexion_claude,
               "ia_locale": lambda: sante.demarrer_ia_locale(cfg)}
    if nom == "messagerie":
        return api_mail_connexion_web()
    if nom not in actions:
        abort(404)
    ok = _reparer(nom, actions[nom])
    return jsonify({"ok": ok, "message": None if ok else "C'est déjà en cours."})


@app.get("/api/push/cle")
def api_push_cle():
    return jsonify({"cle": push.cle_publique(), "appareils": [a["appareil"] for a in push.abonnements()]})


@app.post("/api/push/abonner")
def api_push_abonner():
    c = request.get_json(force=True) or {}
    try:
        nb = push.abonner(c.get("abonnement") or {}, str(c.get("appareil", "appareil")))
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    store.journal(f"Notifications activées sur {c.get('appareil', 'un appareil')}")
    return jsonify({"ok": True, "appareils": nb})


@app.post("/api/push/desabonner")
def api_push_desabonner():
    push.desabonner(str((request.get_json(force=True) or {}).get("endpoint", "")))
    return jsonify({"ok": True})


@app.post("/api/push/test")
def api_push_test():
    recus = push.envoyer(app.config["CFG"], "🔔 RevisUP", "Les notifications marchent sur cet appareil !", url="/#/journee")
    return jsonify({"ok": recus > 0, "recus": recus,
                    "message": None if recus else "Aucun appareil n'a reçu la notification."})


@app.post("/api/session/marquer")
def api_marquer():
    c = request.get_json(force=True)
    planning.marquer(c["cle"], c["statut"])
    planning.generer(app.config["CFG"])
    return jsonify({"ok": True})


def _derniere_erreur_connexion(etat: dict) -> str | None:
    for j in reversed(etat["journal"][-40:]):
        if j["texte"].startswith("Messagerie connectée"):
            return None
        if j["texte"].startswith("Connexion à la messagerie"):
            return j["texte"].split(" : ", 1)[-1]
    return None


@app.get("/api/notes")
def api_notes():
    cfg = app.config["CFG"]
    etat = store.lire()
    from .mail import identifiants_ent
    auto = identifiants_ent()
    return jsonify({"configure": notes.configure(cfg), "identifiant": cfg.get("mail", {}).get("identifiant"),
                    "auto": auto[0] if auto else None,
                    "fournisseur": cfg.get("mail", {}).get("fournisseur", "webmail"),
                    "erreur_connexion": _derniere_erreur_connexion(etat), "connexion_en_cours": _connexion_mail["en_cours"],
                    "stats": notes.statistiques(etat), "liste": sorted(notes.notes_utiles(etat["notes"]["liste"]), key=lambda n: n["date"]),
                    "analyse": etat["notes"].get("analyse"), "maj": etat["notes"].get("maj"),
                    "mails_lus": len(etat["notes"]["mails"]), "tache": _tache})


@app.route("/api/mail/auto", methods=["POST", "DELETE"])
def api_mail_auto():
    """Reconnexion automatique : un seul essai sur la page de l'ENT (sans fenêtre), puis le mot de passe va
    dans le coffre de Windows. DELETE : l'oublier."""
    from .mail import ErreurMail, activer_reconnexion_auto, desactiver_reconnexion_auto
    cfg = app.config["CFG"]
    if request.method == "DELETE":
        desactiver_reconnexion_auto()
        store.journal("Messagerie : reconnexion automatique désactivée, mot de passe effacé du coffre")
        return jsonify({"ok": True})
    c = request.get_json(force=True) or {}
    try:
        adresse = activer_reconnexion_auto(str(c.get("identifiant", "")).strip(), str(c.get("mdp", "")).strip("\r\n"))
    except ErreurMail as e:
        return jsonify({"ok": False, "message": f"Connexion refusée : {e}"}), 400
    store.journal(f"Messagerie connectée ({adresse}), reconnexion automatique activée")
    threading.Thread(target=_lire_quand_libre, args=(cfg,), daemon=True).start()
    return jsonify({"ok": True, "adresse": adresse})


def _lire_quand_libre(cfg: dict) -> None:
    while not lancer("Lecture des mails de notes", notes.synchroniser, cfg):
        time.sleep(15)


@app.post("/api/mail/connexion")
def api_mail_connexion():
    """Formulaire de l'onglet Notes : le mot de passe va directement dans le coffre de Windows."""
    from .mail import ErreurMail, connexion_mot_de_passe
    cfg = app.config["CFG"]
    c = request.get_json(force=True) or {}
    try:
        ident = connexion_mot_de_passe(cfg, str(c.get("identifiant", "")).strip(), str(c.get("mdp", "")).strip("\r\n"),
                                       notes.nom_etudiant(cfg))
    except ErreurMail as e:
        return jsonify({"ok": False, "message": f"Refusé par la messagerie : {e}"}), 400
    config.memoriser_identifiant_mail(cfg, ident)
    store.journal(f"Messagerie connectée ({ident})")
    lance = lancer("Lecture des mails de notes", notes.synchroniser, cfg)
    return jsonify({"ok": True, "identifiant": ident, "lecture": lance})


_connexion_mail = {"en_cours": False}


def _connexion_webmail_puis_lecture(cfg: dict) -> None:
    """Hors du verrou des tâches : la fenêtre s'ouvre même pendant une synchro ; la lecture attend son tour."""
    from .mail import connexion_webmail
    try:
        adresse = connexion_webmail(visible=True)
        config.memoriser_identifiant_mail(cfg, adresse)
        store.journal(f"Messagerie connectée par le webmail ({adresse})")
    except Exception as e:
        store.journal(f"Connexion à la messagerie : {e}", "erreur")
        return
    finally:
        _connexion_mail["en_cours"] = False
    _lire_quand_libre(cfg)


@app.post("/api/mail/connexion-web")
def api_mail_connexion_web():
    """Ouvre Edge sur le webmail : l'étudiant se connecte par l'ENT, puis la lecture des notes démarre."""
    if _connexion_mail["en_cours"]:
        return jsonify({"ok": False, "message": "La fenêtre de connexion est déjà ouverte."}), 409
    _connexion_mail["en_cours"] = True
    threading.Thread(target=_connexion_webmail_puis_lecture, args=(app.config["CFG"],), daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/notes/synchro")
def api_notes_synchro():
    if not notes.configure(app.config["CFG"]):
        return jsonify({"ok": False, "message": "Messagerie non connectée : connecte-toi dans l'onglet Notes."}), 400
    ok = lancer("Lecture des mails de notes", notes.synchroniser, app.config["CFG"])
    return jsonify({"ok": ok, "message": None if ok else "Une tâche est déjà en cours."})


@app.post("/api/notes/analyser")
def api_notes_analyser():
    ok = lancer("Analyse des notes par Claude", notes.analyser, app.config["CFG"])
    return jsonify({"ok": ok, "message": None if ok else "Une tâche est déjà en cours."})


@app.post("/api/notes/ajouter")
def api_notes_ajouter():
    c = request.get_json(force=True)
    try:
        n = notes.ajouter_manuelle(c["module"], float(str(c["note"]).replace(",", ".")),
                                   float(str(c.get("sur") or 20).replace(",", ".")), c["date"],
                                   c.get("evaluation", ""), float(c.get("coefficient") or 0))
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "message": f"Note invalide ({e})."}), 400
    return jsonify({"ok": True, "id": n["id"]})


@app.post("/api/notes/<nid>/supprimer")
def api_notes_supprimer(nid):
    notes.modifier(nid, None)
    return jsonify({"ok": True})


def demarrer(cfg: dict, automatique: bool = True) -> None:
    app.config["CFG"] = cfg
    with store.modifier() as etat:  # une préparation interrompue (PC éteint, serveur arrêté) est à refaire
        for ex in etat["examens"].values():
            if ex.get("statut") == "en_cours":
                ex["statut"] = "a_preparer"
    if automatique:
        threading.Thread(target=planificateur, args=(cfg,), daemon=True).start()
    hote, port = cfg["web"]["hote"], cfg["web"]["port"]
    print(f"\n  RevisUP est lancé → http://localhost:{port}\n")
    app.run(host=hote, port=port, debug=False, use_reloader=False, threaded=True)
