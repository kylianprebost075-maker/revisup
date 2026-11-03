"""Jeux pour apprendre : quiz chrono (QCM des packs), cartes mémoire et associations (cartes tirées des packs
par l'IA locale), exercices R&T générés à l'infini (dans le navigateur). Points d'expérience, série de jours,
records, et les erreurs qui reviennent tant qu'elles ne sont pas réussies.
"""
from __future__ import annotations

import hashlib
import random
import threading
from datetime import timedelta

from . import store
from .store import journal, maintenant

NB_QUESTIONS = 10
INTERVALLES_LEITNER = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}  # boîte → jours avant de revoir la carte
EXOS = {  # exercices générés dans le navigateur (static/jeux.js) ; ici seulement pour le menu et les records
    "ip": ("Adressage IP et sous-réseaux", "R1.01 · R1.02 · R1.03"),
    "binaire": ("Binaire, hexa, décimal", "R1.06"),
    "ohm": ("Loi d'Ohm, diviseur, puissance", "R1.04"),
    "db": ("Décibels et atténuation", "R1.05 · R1.14"),
    "linux": ("Commandes et droits Linux", "R1.08"),
}
_generations: set = set()


def _vide() -> dict:
    return {"xp": 0, "jours": {}, "records": {}, "stats": {}, "erreurs": {}, "cartes": {}, "leitner": {}}


def _etat_jeux(e: dict) -> dict:
    j = e.setdefault("jeux", _vide())
    for k, v in _vide().items():
        j.setdefault(k, v)
    return j


def _id(*morceaux: str) -> str:
    return hashlib.sha1(":".join(morceaux).encode()).hexdigest()[:10]


def _serie(jours: dict) -> int:
    """Nombre de jours d'affilée avec au moins une partie (aujourd'hui ou hier compris)."""
    j = maintenant().date()
    if j.isoformat() not in jours:
        j -= timedelta(days=1)
    n = 0
    while j.isoformat() in jours:
        n += 1
        j -= timedelta(days=1)
    return n


def modules() -> list[dict]:
    """Un module par matière qui a un pack (le pack de l'examen le plus proche s'il y en a plusieurs)."""
    etat = store.lire()
    jeux = etat.get("jeux") or _vide()
    aujourd_hui = maintenant().date().isoformat()
    vus, res = set(), []
    examens = sorted(etat["examens"].values(), key=lambda e: (e["debut"] < maintenant().isoformat(), e["debut"]))
    for ex in examens:
        if ex["matiere"] in vus or not store.chemin_pack(ex["id"]).exists():
            continue
        pack = store.lire_pack(ex["id"]) or {}
        vus.add(ex["matiere"])
        cartes = jeux["cartes"].get(ex["id"], [])
        dues = [c for c in cartes if jeux["leitner"].get(c["id"], {}).get("prochaine", "") <= aujourd_hui]
        res.append({"examen_id": ex["id"], "matiere": ex["matiere"], "date": ex["debut"][:10],
                    "nb_qcm": len(pack.get("qcm", [])), "nb_cartes": len(cartes), "cartes_dues": len(dues),
                    "a_revoir": sum(1 for q in _qcm(ex["id"], pack) if jeux["erreurs"].get(q["id"])),
                    "record_quiz": jeux["records"].get(f"quiz:{ex['id']}", 0),
                    "record_associations": jeux["records"].get(f"associations:{ex['id']}", 0),
                    "generation": ex["id"] in _generations})
    return res


def tableau() -> dict:
    jeux = store.lire().get("jeux") or _vide()
    aujourd_hui = maintenant().date().isoformat()
    exos = [{"type": t, "titre": titre, "modules": mods, "record": jeux["records"].get(f"exo:{t}", 0),
             **jeux["stats"].get(f"exo:{t}", {"faits": 0, "justes": 0})} for t, (titre, mods) in EXOS.items()]
    return {"xp": jeux["xp"], "xp_aujourdhui": jeux["jours"].get(aujourd_hui, 0), "serie": _serie(jeux["jours"]),
            "modules": modules(), "exos": exos}


# ── quiz chrono ─────────────────────────────────────────────────────────

def _qcm(examen_id: str, pack: dict) -> list[dict]:
    return [{**q, "id": _id(examen_id, q["question"])} for q in pack.get("qcm", [])
            if len(q.get("choix", [])) >= 2 and 0 <= q.get("bonne_reponse", -1) < len(q["choix"])]


def quiz(examen_id: str) -> dict:
    """10 questions : d'abord celles ratées avant, puis des nouvelles, puis le reste au hasard."""
    ex = store.lire()["examens"].get(examen_id)
    pack = store.lire_pack(examen_id)
    if not ex or not pack:
        raise KeyError(examen_id)
    erreurs = (store.lire().get("jeux") or _vide())["erreurs"]
    questions = _qcm(examen_id, pack)
    random.shuffle(questions)
    questions.sort(key=lambda q: -erreurs.get(q["id"], 0))
    choisies = questions[:NB_QUESTIONS]
    random.shuffle(choisies)
    for q in choisies:  # on mélange aussi l'ordre des réponses
        ordre = list(range(len(q["choix"])))
        random.shuffle(ordre)
        q["bonne_reponse"] = ordre.index(q["bonne_reponse"])
        q["choix"] = [q["choix"][i] for i in ordre]
        q["a_revoir"] = bool(erreurs.get(q["id"]))
    return {"examen_id": examen_id, "matiere": ex["matiere"], "questions": choisies}


def resultat(jeu: str, cle: str, score: int, justes: int, total: int, reponses: list[dict]) -> dict:
    """Enregistre une partie : XP, série, record, et les questions ratées à revoir."""
    aujourd_hui = maintenant().date().isoformat()
    xp = max(0, int(justes * 10 + score // 100))
    with store.modifier() as e:
        j = _etat_jeux(e)
        j["xp"] += xp
        j["jours"][aujourd_hui] = j["jours"].get(aujourd_hui, 0) + xp
        nom = f"{jeu}:{cle}"
        ancien = j["records"].get(nom, 0)
        if score > ancien:
            j["records"][nom] = score
        stats = j["stats"].setdefault(nom, {"faits": 0, "justes": 0})
        stats["faits"] += total
        stats["justes"] += justes
        for r in reponses:  # quiz : une question ratée revient, réussie elle sort de la liste « à revoir »
            qid = str(r.get("id", ""))[:20]
            if not qid:
                continue
            if r.get("juste"):
                j["erreurs"].pop(qid, None)
            else:
                j["erreurs"][qid] = j["erreurs"].get(qid, 0) + 1
        serie = _serie(j["jours"])
    return {"xp_gagne": xp, "record": max(score, ancien), "nouveau_record": score > ancien and ancien > 0,
            "premier": ancien == 0, "serie": serie}


# ── cartes mémoire (Leitner) ────────────────────────────────────────────

SCHEMA_CARTES = {
    "type": "object",
    "properties": {"cartes": {"type": "array", "items": {
        "type": "object",
        "properties": {"recto": {"type": "string"}, "verso": {"type": "string"}, "chapitre": {"type": "string"}},
        "required": ["recto", "verso", "chapitre"], "additionalProperties": False}}},
    "required": ["cartes"],
    "additionalProperties": False,
}

SYSTEME_CARTES = """Tu fabriques des cartes mémoire pour un étudiant de BUT Réseaux & Télécoms, à partir de son pack de révision.
- 24 cartes. recto : une notion, un sigle, une commande ou une formule à connaître (2 à 6 mots).
- verso : sa définition ou sa réponse, exacte, en une phrase courte (moins de 120 caractères), sans répéter le recto.
- Seulement ce qui peut tomber à l'examen : définitions, rôles, valeurs, formules, commandes. Pas de doublons.
- chapitre : le titre du chapitre du pack concerné.
- En français."""


def generer_cartes(cfg: dict, examen_id: str) -> int:
    from . import ia_claude
    from .ia_locale import IALocale
    pack = store.lire_pack(examen_id)
    ex = store.lire()["examens"].get(examen_id)
    if not pack or not ex:
        raise KeyError(examen_id)
    texte = (f"Matière : {ex['matiere']}\n\n# Chapitres\n"
             + "\n".join(f"- {c['titre']} : {c['resume']}" for c in pack.get("chapitres", []))
             + "\n\n# Points clés\n" + "\n".join(f"- {p}" for p in pack.get("points_cles", []))
             + "\n\n# Pièges\n" + "\n".join(f"- {p}" for p in pack.get("pieges", []))
             + "\n\n# Synthèse\n" + pack.get("synthese_markdown", "")[:12000])
    ia = IALocale(cfg["ia_locale"]["url"], cfg["ia_locale"]["modele"], timeout=900, effort="low")
    if ia.disponible():
        rep = ia._json(SYSTEME_CARTES, texte, SCHEMA_CARTES, 4000)
    else:
        rep, _ = ia_claude.demander_json(cfg, SYSTEME_CARTES, texte, SCHEMA_CARTES)
    cartes, vus = [], set()
    for c in rep.get("cartes", []):
        recto, verso = str(c.get("recto", "")).strip()[:80], str(c.get("verso", "")).strip()[:200]
        if recto and verso and recto.lower() not in vus:
            vus.add(recto.lower())
            cartes.append({"id": _id(examen_id, recto), "recto": recto, "verso": verso,
                           "chapitre": str(c.get("chapitre", ""))[:80]})
    with store.modifier() as e:
        _etat_jeux(e)["cartes"][examen_id] = cartes
    journal(f"Jeux : {len(cartes)} cartes mémoire pour {ex['matiere']}")
    return len(cartes)


def lancer_generation(cfg: dict, examen_id: str) -> bool:
    """En arrière-plan (l'IA locale met une ou deux minutes) ; une seule à la fois par matière."""
    if examen_id in _generations:
        return False
    _generations.add(examen_id)

    def travail():
        try:
            generer_cartes(cfg, examen_id)
        except Exception as e:
            journal(f"Jeux : cartes impossibles à créer ({type(e).__name__}: {e})", "erreur")
        finally:
            _generations.discard(examen_id)

    threading.Thread(target=travail, daemon=True).start()
    return True


def cartes(examen_id: str, toutes: bool = False) -> list[dict]:
    """À réviser aujourd'hui (jamais vues ou arrivées à échéance), ou toutes (associations)."""
    jeux = store.lire().get("jeux") or _vide()
    liste = jeux["cartes"].get(examen_id, [])
    aujourd_hui = maintenant().date().isoformat()
    res = [{**c, "boite": jeux["leitner"].get(c["id"], {}).get("boite", 0)} for c in liste
           if toutes or jeux["leitner"].get(c["id"], {}).get("prochaine", "") <= aujourd_hui]
    random.shuffle(res)
    res.sort(key=lambda c: c["boite"])  # les plus mal sues d'abord
    return res


def reponse_carte(carte_id: str, su: bool) -> dict:
    with store.modifier() as e:
        leitner = _etat_jeux(e)["leitner"]
        boite = min(5, leitner.get(carte_id, {}).get("boite", 0) + 1) if su else 1
        prochaine = maintenant().date() + timedelta(days=INTERVALLES_LEITNER[boite] if su else 0)
        leitner[carte_id] = {"boite": boite, "prochaine": prochaine.isoformat()}
    return {"boite": boite, "prochaine": prochaine.isoformat()}


def cartes_a_creer(cfg: dict) -> None:
    """À chaque synchro : crée les cartes des packs qui n'en ont pas encore (sans bloquer)."""
    for m in modules():
        if not m["nb_cartes"] and m["nb_qcm"]:
            lancer_generation(cfg, m["examen_id"])
            return  # une matière à la fois : l'IA locale est lente
