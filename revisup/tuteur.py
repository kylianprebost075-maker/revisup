"""Tuteur : l'IA répond aux questions de l'étudiant sur l'exercice ou la leçon en cours, et Claude transforme la
fiche d'un pack (exacte mais indigeste) en leçons vivantes : accroche, analogie, exemple, piège, défi.
"""
from __future__ import annotations

import threading

from . import ajouts, ia_claude, store
from .ia_locale import IALocale
from .store import journal, maintenant

SYSTEME_AIDE = """Tu es le tuteur d'un étudiant de BUT Réseaux & Télécoms (1re année) qui révise. Il travaille sur l'exercice ou la leçon décrite plus bas et te pose une question.
- Tutoie-le, en français. Réponses courtes (5 à 12 lignes), claires, avec un exemple concret quand ça aide.
- S'il bloque : donne d'abord un indice ou la méthode, pas la réponse complète, sauf s'il la demande.
- S'il propose une réponse : dis si elle est juste et pourquoi ; sinon montre précisément où est l'erreur.
- Le corrigé fourni est la référence de son prof : appuie-toi dessus sans le recopier d'un bloc.
- Markdown simple (gras, listes, `code`, blocs ```). Formules en $...$ uniquement (jamais \\( \\) ni \\[ \\]). Une balise HTML s'écrit entre ` `.
- Si la question n'a rien à voir avec ses révisions, ramène-le gentiment à l'exercice."""
SCHEMA_AIDE = {"type": "object", "properties": {"reponse": {"type": "string"}}, "required": ["reponse"],
               "additionalProperties": False}
NATURES = {"exercice": "Exercice", "exo_jeu": "Exercice d'entraînement", "lecon": "Leçon", "qcm": "Question de QCM"}

SCHEMA_LECONS = {
    "type": "object",
    "properties": {"lecons": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "titre": {"type": "string"},
            "accroche": {"type": "string"},
            "analogie": {"type": "string"},
            "explication_markdown": {"type": "string"},
            "exemple_markdown": {"type": "string"},
            "piege": {"type": "string"},
            "a_retenir": {"type": "string"},
            "defi_question": {"type": "string"},
            "defi_reponse_markdown": {"type": "string"},
            "minutes": {"type": "integer"},
        },
        "required": ["titre", "accroche", "analogie", "explication_markdown", "exemple_markdown", "piege",
                     "a_retenir", "defi_question", "defi_reponse_markdown", "minutes"],
        "additionalProperties": False}}},
    "required": ["lecons"],
    "additionalProperties": False,
}

SYSTEME_LECONS = """Tu es le prof de BUT Réseaux & Télécoms que tout étudiant rêve d'avoir : clair, vivant, concret. Tu transformes sa fiche de révision (exacte mais indigeste : des listes à puces) en leçons courtes qui donnent envie d'apprendre et qui font comprendre, pas juste retenir.

Une leçon par chapitre (titre « ## ») de la fiche, dans le même ordre. Titre : celui du chapitre, sans « Chapitre N — » ni numéro.
- accroche : 1 ou 2 phrases. Une situation concrète ou une question intrigante tirée de son quotidien (box internet, Wi-Fi de l'IUT, Netflix, Discord, jeux en ligne, téléphone, site web qu'il visite…) qui montre à quoi sert le chapitre.
- analogie : une image du quotidien qui fait comprendre l'idée centrale (2 ou 3 phrases), avec sa limite si elle peut tromper.
- explication_markdown : le chapitre expliqué pas à pas, 250 à 450 mots, paragraphes courts, tutoiement, **gras** sur les mots-clés, un petit schéma dans un bloc ``` si ça aide. Garde TOUTES les notions exigibles de la fiche (définitions, valeurs, commandes, formules, méthodes) : c'est un vrai cours, pas un résumé vague.
- exemple_markdown : un exemple concret résolu étape par étape, du type de ceux de l'examen (calcul, commande, code, trace, schéma…).
- piege : l'erreur que font la plupart des étudiants sur ce chapitre, et comment l'éviter (1 ou 2 phrases).
- a_retenir : LA phrase à savoir par cœur (moins de 200 caractères).
- defi_question / defi_reponse_markdown : une petite question ouverte pour vérifier qu'il a compris (pas un QCM), et sa réponse expliquée.
- minutes : temps estimé pour lire et comprendre la leçon (5 à 20).

Règles : en français ; fidèle à la fiche (n'invente aucune valeur ; une connaissance ajoutée hors fiche doit être sûre et utile) ; pas de références de fichiers entre crochets ; formules en $...$ ; code dans des blocs ``` avec le langage ; une balise HTML citée en exemple s'écrit toujours entre ` ` (exemple : `<p>`)."""

_en_cours: set = set()


def _court(v, n: int) -> str:
    return str(v or "").strip()[:n]


def aide(cfg: dict, contexte: dict, question: str, historique: list[dict]) -> str:
    """Réponse du tuteur : IA locale (rapide, gratuite), sinon Claude."""
    question = _court(question, 1500)
    if not question:
        raise ValueError("écris ta question")
    c = contexte if isinstance(contexte, dict) else {}
    morceaux = [
        f"Matière : {_court(c.get('matiere'), 120)}" if c.get("matiere") else "",
        f"{NATURES.get(c.get('type'), 'Exercice')} : {_court(c.get('titre'), 200)}",
        f"Énoncé / contenu :\n{_court(c.get('enonce'), 8000)}",
        f"Corrigé du prof (référence) :\n{_court(c.get('corrige'), 6000)}" if c.get("corrige") else "",
        f"Sa réponse : {_court(c.get('reponse_eleve'), 600)}" if c.get("reponse_eleve") else "",
        "Il n'a pas encore répondu : ne donne pas la réponse finale, sauf s'il la demande." if c.get("pas_encore_repondu") else "",
    ]
    situation = "\n\n".join(m for m in morceaux if m)
    fil = [{"role": m["role"], "content": _court(m.get("content"), 3000)}
           for m in (historique or [])[-6:] if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    ia = IALocale(cfg["ia_locale"]["url"], cfg["ia_locale"]["modele"], timeout=180, effort="low")
    if ia.disponible():
        reponse = ia.discuter(f"{SYSTEME_AIDE}\n\n# Ce sur quoi il travaille\n{situation}",
                              fil + [{"role": "user", "content": question}], 900)
    else:
        conversation = "\n".join(f"{'Étudiant' if m['role'] == 'user' else 'Tuteur'} : {m['content']}" for m in fil)
        rep, _ = ia_claude.demander_json(cfg, SYSTEME_AIDE, f"# Ce sur quoi il travaille\n{situation}\n\n# Conversation\n"
                                         f"{conversation}\nÉtudiant : {question}", SCHEMA_AIDE)
        reponse = str(rep.get("reponse", "")).strip()
    if not reponse:
        raise RuntimeError("l'IA n'a rien répondu, réessaie")
    return reponse


# ── leçons vivantes ─────────────────────────────────────────────────────

def generer_lecons(cfg: dict, examen_id: str) -> int:
    pack, ex = store.lire_pack(examen_id), store.lire()["examens"].get(examen_id)
    if not pack or not ex:
        raise KeyError(examen_id)
    version = (pack.get("_meta") or {}).get("genere_le")
    texte = (f"Matière : {ex['matiere']}\n\n# Pièges connus\n" + "\n".join(f"- {p}" for p in pack.get("pieges", []))
             + f"\n\n# Fiche de révision\n{pack.get('synthese_markdown', '')}")
    try:
        rep, _ = ia_claude.demander_json(cfg, SYSTEME_LECONS, texte, SCHEMA_LECONS)
    except Exception as e:  # Claude indisponible : l'IA locale, plus lente et moins fine, fait le travail
        ia = IALocale(cfg["ia_locale"]["url"], cfg["ia_locale"]["modele"], timeout=3600, effort="low")
        if not ia.disponible():
            raise
        journal(f"Leçons : Claude indisponible ({e}), l'IA locale prend le relais", "erreur")
        rep = ia._json(SYSTEME_LECONS, texte, SCHEMA_LECONS, 20000)
    cles = SCHEMA_LECONS["properties"]["lecons"]["items"]["required"]
    lecons = [{k: (int(l.get(k) or 10) if k == "minutes" else str(l.get(k) or "").strip()) for k in cles}
              for l in rep.get("lecons", []) if isinstance(l, dict) and l.get("titre") and l.get("explication_markdown")]
    if not lecons:
        raise RuntimeError("aucune leçon reçue")
    pack = store.lire_pack(examen_id)  # relu : le pack a pu être régénéré pendant ce temps
    if not pack or (pack.get("_meta") or {}).get("genere_le") != version:
        return 0
    pack["lecons"] = lecons
    store.ecrire_pack(examen_id, pack)
    journal(f"Leçons : {len(lecons)} leçons vivantes pour {ex['matiere']}")
    return len(lecons)


def en_cours(examen_id: str) -> bool:
    return f"leçons:{examen_id}" in _en_cours


def lancer(cfg: dict, examen_id: str) -> bool:
    return _lancer(f"leçons:{examen_id}", generer_lecons, cfg, examen_id)


def lecons_a_creer(cfg: dict) -> None:
    """À chaque synchro : les leçons du prochain examen qui a un pack mais pas encore de leçons (une à la fois)."""
    if any(c.startswith("leçons:") for c in _en_cours):
        return
    etat = store.lire()
    for ex in sorted(etat["examens"].values(), key=lambda e: e["debut"]):
        if ex["debut"] < maintenant().isoformat() or ex.get("ignore"):
            continue
        pack = store.lire_pack(ex["id"]) if store.chemin_pack(ex["id"]).exists() else None
        if pack and not pack.get("lecons"):
            lancer(cfg, ex["id"])
            return


# ── annales corrigées ───────────────────────────────────────────────────

SCHEMA_ANNALES = {
    "type": "object",
    "properties": {"annales": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "titre": {"type": "string"},
            "fichier": {"type": "string"},
            "parties": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "titre": {"type": "string"},
                    "questions": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "numero": {"type": "string"},
                            "intitule": {"type": "string"},
                            "enonce_markdown": {"type": "string"},
                            "reponse_markdown": {"type": "string"},
                            "corrige_du_prof": {"type": "boolean"},
                        },
                        "required": ["numero", "intitule", "enonce_markdown", "reponse_markdown", "corrige_du_prof"],
                        "additionalProperties": False}},
                },
                "required": ["titre", "questions"],
                "additionalProperties": False}},
        },
        "required": ["titre", "fichier", "parties"],
        "additionalProperties": False}}},
    "required": ["annales"],
    "additionalProperties": False,
}

SYSTEME_ANNALES = """Tu corriges les anciens sujets d'examen (annales) d'un étudiant de BUT Réseaux & Télécoms, la veille de son examen. Il veut lire chaque question puis dérouler une réponse juste, claire et complète, comme un corrigé de prof.

Pour chaque annale fournie (un fichier = une annale) :
- titre : court et parlant (ex. « Examen final — 2022-2023 », « Test 1 — Modèle OSI ») ; fichier : le nom du fichier tel que donné.
- parties : les parties du sujet dans l'ordre (ex. « 1. Modèle OSI et TCP/IP ») ; s'il n'y en a pas, une seule partie « Questions ».
- TOUTES les questions, dans l'ordre, sans en sauter aucune. numero : « Q1 », « Q2 »… comme dans le sujet. intitule : 3 à 8 mots qui résument la question (ex. « Protocole pour transférer des pages web »).
- enonce_markdown : l'énoncé complet et fidèle (données, adresses, tableaux en Markdown). Si une figure ou une capture manque dans le texte, écris-le : « (capture non lisible ici) ».
- reponse_markdown : la réponse attendue d'abord (en gras), puis la justification ou la méthode pas à pas, les calculs détaillés (binaire si utile), et un tableau complet et corrigé quand la question est un tableau. Vérifie chaque calcul deux fois. Si une capture manque, réponds avec le cas le plus probable et dis-le.
- corrige_du_prof : true si la réponse vient d'un corrigé fourni par l'enseignant (reprends-le fidèlement, complète l'explication si elle est trop sèche), false si c'est ta correction.
Appuie-toi sur la fiche de révision du cours pour employer les mêmes notions et notations que le prof.
En français ; formules en $...$ ; code et commandes entre ` ` ou dans des blocs ``` ; une balise HTML s'écrit entre ` `."""


def _documents_annales(examen: dict) -> tuple[list[dict], list[dict]]:
    """Annales et corrigés du cours de l'examen, avec leur texte (fichiers déjà téléchargés par la préparation)."""
    from .preparation import _chemin_local, _texte_en_cache
    etat = store.lire()
    annales, corriges = [], []
    for f in etat["updago"].get("fichiers", []):
        cat = etat["classements_fichiers"].get(f["cle"])
        if f["cours_id"] != examen.get("cours_id") or cat not in ("annale", "corrige"):
            continue
        chemin = _chemin_local(f, cat)
        if not chemin.exists():
            continue
        texte = (_texte_en_cache(chemin, f).get("texte") or "").strip()
        if texte:
            (annales if cat == "annale" else corriges).append({"nom": f["nom"], "texte": texte[:40000]})
    for d in ajouts.documents(examen["id"], ("annale", "corrige")):  # sujets ajoutés à la main (photos…)
        if d.get("texte"):
            (annales if d["categorie"] == "annale" else corriges).append({"nom": d["nom"], "texte": d["texte"][:40000]})
    return annales, corriges


def a_des_annales(examen: dict) -> bool:
    etat = store.lire()
    if any(a["categorie"] == "annale" for a in ajouts.liste(examen["id"])):
        return True
    return any(f["cours_id"] == examen.get("cours_id") and etat["classements_fichiers"].get(f["cle"]) == "annale"
               for f in etat["updago"].get("fichiers", []))


def generer_annales(cfg: dict, examen_id: str) -> int:
    pack, ex = store.lire_pack(examen_id), store.lire()["examens"].get(examen_id)
    if not pack or not ex:
        raise KeyError(examen_id)
    annales, corriges = _documents_annales(ex)
    if not annales:
        raise RuntimeError("aucune annale lisible pour cet examen")
    version = (pack.get("_meta") or {}).get("genere_le")
    texte = (f"Matière : {ex['matiere']}\n\n"
             + "".join(f"# ANNALE — fichier : {a['nom']}\n{a['texte']}\n\n" for a in annales)
             + "".join(f"# CORRIGÉ DU PROF — fichier : {c['nom']}\n{c['texte']}\n\n" for c in corriges)
             + f"# Fiche de révision du cours (référence)\n{pack.get('synthese_markdown', '')[:30000]}")
    rep, _ = ia_claude.demander_json(cfg, SYSTEME_ANNALES, texte, SCHEMA_ANNALES)
    resultat = []
    for a in rep.get("annales", []):
        parties = [{"titre": str(p.get("titre") or "Questions"), "questions": [
            {k: (bool(q.get(k)) if k == "corrige_du_prof" else str(q.get(k) or "").strip())
             for k in ("numero", "intitule", "enonce_markdown", "reponse_markdown", "corrige_du_prof")}
            for q in p.get("questions", []) if q.get("reponse_markdown")]} for p in a.get("parties", [])]
        parties = [p for p in parties if p["questions"]]
        if parties:
            resultat.append({"titre": str(a.get("titre") or a.get("fichier")), "fichier": str(a.get("fichier") or ""),
                             "parties": parties})
    if not resultat:
        raise RuntimeError("aucune question corrigée reçue")
    pack = store.lire_pack(examen_id)
    if not pack or (pack.get("_meta") or {}).get("genere_le") != version:
        return 0
    pack["annales"] = resultat
    store.ecrire_pack(examen_id, pack)
    nb = sum(len(p["questions"]) for a in resultat for p in a["parties"])
    journal(f"Annales : {len(resultat)} annale(s) corrigée(s), {nb} questions, pour {ex['matiere']}")
    return nb


def lancer_annales(cfg: dict, examen_id: str) -> bool:
    return _lancer(f"annales:{examen_id}", generer_annales, cfg, examen_id)


def annales_en_cours(examen_id: str) -> bool:
    return f"annales:{examen_id}" in _en_cours


def annales_a_creer(cfg: dict) -> None:
    """À chaque synchro : l'annale corrigée du prochain examen qui a des annales mais pas encore de corrigé."""
    if any(c.startswith("annales:") for c in _en_cours):
        return
    for ex in sorted(store.lire()["examens"].values(), key=lambda e: e["debut"]):
        if ex["debut"] < maintenant().isoformat() or ex.get("ignore") or not store.chemin_pack(ex["id"]).exists():
            continue
        pack = store.lire_pack(ex["id"])
        if pack and not pack.get("annales") and a_des_annales(ex):
            lancer_annales(cfg, ex["id"])
            return


def _lancer(cle: str, fonction, cfg: dict, examen_id: str) -> bool:
    """En arrière-plan (Claude met quelques minutes) ; une seule tâche de chaque sorte par examen."""
    if cle in _en_cours:
        return False
    _en_cours.add(cle)

    def travail():
        try:
            fonction(cfg, examen_id)
        except Exception as e:
            journal(f"{cle.split(':')[0].capitalize()} impossibles à créer ({type(e).__name__}: {e})", "erreur")
        finally:
            _en_cours.discard(cle)

    threading.Thread(target=travail, daemon=True).start()
    return True


def marquer_lue(examen_id: str, index: int, lue: bool) -> list[int]:
    with store.modifier() as e:
        lues = set(e.setdefault("lecons_lues", {}).get(examen_id, []))
        (lues.add if lue else lues.discard)(index)
        e["lecons_lues"][examen_id] = sorted(lues)
    return sorted(lues)
