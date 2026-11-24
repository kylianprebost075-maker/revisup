"""Claude : synthèse, exercices corrigés, QCM et estimation du temps de révision par chapitre.

Trois façons d'appeler Claude (config [claude] mode) :
  - "api"    : SDK Anthropic avec ta clé API (ANTHROPIC_API_KEY) — le plus complet (lit aussi les PDF scannés)
  - "cli"    : Claude Code installé sur le PC (commande `claude`), utilise ton abonnement
  - "manuel" : RevisUP écrit le prompt dans data/prompts/, tu le colles dans claude.ai puis tu recolles la réponse
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import DOSSIER_DATA

ORDRE_CATEGORIES = ["annale", "corrige", "cours", "td", "tp", "autre"]
NOMS_CATEGORIES = {"annale": "ANCIEN EXAMEN", "corrige": "CORRIGÉ", "cours": "COURS", "td": "TD", "tp": "TP", "autre": "AUTRE"}
DOSSIER_PROMPTS = DOSSIER_DATA / "prompts"

SCHEMA_PACK = {
    "type": "object",
    "properties": {
        "synthese_markdown": {"type": "string"},
        "chapitres": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "titre": {"type": "string"},
                "importance": {"type": "integer"},
                "heures_estimees": {"type": "number"},
                "resume": {"type": "string"},
            },
            "required": ["titre", "importance", "heures_estimees", "resume"],
            "additionalProperties": False}},
        "points_cles": {"type": "array", "items": {"type": "string"}},
        "pieges": {"type": "array", "items": {"type": "string"}},
        "analyse_annales": {"type": "string"},
        "exercices": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "titre": {"type": "string"},
                "chapitre": {"type": "string"},
                "difficulte": {"type": "string", "enum": ["facile", "moyen", "difficile"]},
                "enonce_markdown": {"type": "string"},
                "corrige_markdown": {"type": "string"},
            },
            "required": ["titre", "chapitre", "difficulte", "enonce_markdown", "corrige_markdown"],
            "additionalProperties": False}},
        "qcm": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "chapitre": {"type": "string"},
                "choix": {"type": "array", "items": {"type": "string"}},
                "bonne_reponse": {"type": "integer"},
                "explication": {"type": "string"},
            },
            "required": ["question", "chapitre", "choix", "bonne_reponse", "explication"],
            "additionalProperties": False}},
        "methode_jour_j": {"type": "string"},
    },
    "required": ["synthese_markdown", "chapitres", "points_cles", "pieges", "analyse_annales",
                 "exercices", "qcm", "methode_jour_j"],
    "additionalProperties": False,
}

REGLES_SVG = """Schémas : un schéma s'écrit en SVG dans un bloc ```svg qui contient un seul élément <svg viewBox='0 0 L H'> (L de 300 à 640), sans width ni height, sans script, sans image, sans lien ni style.
- Attributs entre apostrophes (stroke='currentColor'), jamais entre guillemets doubles : la réponse est du JSON.
- Traits stroke='currentColor' stroke-width='2' fill='none' ; textes fill='currentColor' stroke='none' font-size='14' font-family='sans-serif' ; points des nœuds en cercles pleins r='4' fill='currentColor' ; un composant posé sur un fil a fill='white' pour cacher le fil (le blanc devient la couleur du fond en mode sombre).
- Ce que l'étudiant doit ajouter ou retenir (nœuds à placer, flèches de courant et de tension, éléments redessinés) est en orange '#e8590c', le reste en currentColor.
- Flèches : des <marker> dans <defs>, un en currentColor et un en orange, avec des id courts.
- Électricité, norme européenne : résistance = rectangle avec son nom à côté, source de tension = cercle traversé par le fil avec la flèche de E, source de courant = cercle avec la flèche dans le fil, fils horizontaux et verticaux, flèche de tension à côté du dipôle et flèche de courant sur le fil.
- Lisible : aucun texte ne chevauche un trait ou un autre texte, marge de 20 autour du dessin. Fidèle au sujet : mêmes composants, mêmes noms, même disposition."""

SYSTEME = """Tu es un tuteur universitaire exigeant et bienveillant. Tu prépares un étudiant de l'Université de Poitiers à un examen précis, à partir de SES documents de cours et des messages de SES enseignants.

Règles :
- Tout en français.
- Les consignes des enseignants priment : programme, chapitres exclus, documents autorisés, format de l'épreuve.
- Les anciens examens (annales) montrent ce qui tombe vraiment : reprends leur style, leur niveau et leurs types de questions.
- Appuie-toi d'abord sur les documents fournis. Si tu complètes avec tes propres connaissances, signale-le avec « (hors documents) ».
- Cite les fichiers sources entre crochets, par exemple [CM3_integrales.pdf].
- Formules en LaTeX : $...$ en ligne, $$...$$ en bloc. Code dans des blocs ``` avec le langage.
- Quand la matière s'appuie sur des schémas (montages électriques, chronogrammes, topologies réseau, diagrammes…), mets-en dans la fiche et dans les énoncés et corrigés des exercices : un exercice qui demande de compléter ou de dessiner un schéma a son schéma corrigé.

""" + REGLES_SVG


class ClaudeManuel(Exception):
    """Mode manuel : le prompt est prêt dans un fichier, l'étudiant doit le passer à Claude lui-même."""

    def __init__(self, chemin: Path):
        super().__init__(str(chemin))
        self.chemin = chemin


class ErreurClaude(Exception):
    pass


def trouver_cli(cfg: dict) -> str | None:
    """Commande `claude` : celle du PATH, sinon le Claude Code intégré à l'application Claude pour Windows."""
    chemin = cfg["claude"].get("chemin_cli")
    if chemin and Path(chemin).exists():
        return chemin
    if shutil.which("claude"):
        return shutil.which("claude")
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Claude-Data"
    candidats = sorted(base.glob("*/claude-code/*/*/claude.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidats[0]) if candidats else None


def mode_effectif(cfg: dict) -> str:
    mode = cfg["claude"].get("mode", "auto")
    if mode != "auto":
        return mode
    if cfg["claude"].get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "api"
    if trouver_cli(cfg):
        return "cli"
    return "manuel"


# ── construction de la demande ──────────────────────────────────────────

def construire_demande(cfg: dict, examen: dict, infos: dict, messages: list[dict], documents: list[dict]) -> dict:
    """Assemble le texte envoyé à Claude dans la limite du budget, sans rien couper en silence :
    ce qui ne rentre pas est listé dans "non_inclus" et affiché sur le tableau de bord."""
    budget = int(cfg["claude"].get("budget_caracteres", 400_000))
    mode = mode_effectif(cfg)
    inclus, non_inclus, pdfs = [], [], []
    taille_pdfs = 0
    morceaux = []

    tries = sorted(documents, key=lambda d: ORDRE_CATEGORIES.index(d.get("categorie", "autre")))
    for doc in tries:
        texte = doc.get("texte", "")
        est_pdf = doc["chemin"].lower().endswith(".pdf")
        # les annales et corrigés sont joints en PDF : leurs schémas et figures n'existent pas dans le texte extrait
        figures = doc["categorie"] in ("annale", "corrige") and doc.get("pages", 0) <= 30
        joint = False
        if est_pdf and mode in ("api", "cli") and (figures or (doc.get("scanne") and mode == "api")):
            taille = Path(doc["chemin"]).stat().st_size
            if len(pdfs) < 8 and taille_pdfs + taille < 20_000_000 and doc.get("pages", 0) <= 100:
                pdfs.append(doc)
                taille_pdfs += taille
                joint = True
                if mode == "api" or not texte:  # l'API lit le texte du PDF elle-même
                    inclus.append({"nom": doc["nom"], "categorie": doc["categorie"],
                                   "mode": "PDF (scan)" if doc.get("scanne") else "PDF (avec figures)"})
                    continue
        if not texte:
            non_inclus.append({"nom": doc["nom"], "raison": doc.get("erreur") or "aucun texte lisible"})
            continue
        if len(texte) > budget:
            if budget > 30_000 and doc["categorie"] in ("annale", "corrige", "cours"):
                # on garde de la place pour les TD/TP qui suivent
                texte = texte[:int(budget * 0.6)] + "\n[… document tronqué faute de place]"
                inclus.append({"nom": doc["nom"], "categorie": doc["categorie"], "mode": "texte (tronqué)"})
            else:
                non_inclus.append({"nom": doc["nom"], "raison": "budget de texte atteint"})
                continue
        else:
            inclus.append({"nom": doc["nom"], "categorie": doc["categorie"],
                           "mode": "texte + PDF (avec figures)" if joint else "texte"})
        budget -= len(texte)
        morceaux.append(f"### [{NOMS_CATEGORIES[doc['categorie']]}] {doc['nom']}\n"
                        f"(section : {doc.get('section') or '—'})\n\n{texte}")

    lignes_infos = [f"- {k.replace('_', ' ')} : {v}" for k, v in infos.items() if v]
    msgs = "\n\n".join(
        f"**{m.get('auteur') or 'Enseignant'}** — {m.get('source')} — {(m.get('date') or '')[:10]}\n"
        f"Sujet : {m.get('sujet', '')}\n{m.get('texte', '')}"
        for m in messages) or "(aucun message trouvé)"

    nb_qcm = cfg["claude"].get("nb_qcm", 20)
    nb_ex = cfg["claude"].get("nb_exercices", 10)
    texte = f"""# Examen à préparer
- Intitulé : {examen.get('titre') or examen['matiere']}
- Matière : {examen['matiere']}
- Date : {examen['debut']}
- Salle : {examen.get('salle') or 'non précisée'}
{chr(10).join(lignes_infos)}

# Messages des enseignants liés à cet examen
{msgs}

# Documents du cours ({len(morceaux)} en texte, {len(pdfs)} PDF scannés joints)
{chr(10).join(morceaux) if morceaux else '(aucun document texte)'}

# Ce que je te demande
1. **synthese_markdown** : une fiche de révision complète, organisée par chapitre : définitions, théorèmes/propriétés, méthodes types pas à pas, exemples courts, et un encadré « À savoir par cœur » par chapitre. Elle doit suffire pour réviser.
2. **chapitres** : la liste ordonnée des chapitres au programme de cet examen. importance de 1 à 5 = poids probable à l'examen (d'après annales et consignes) ; heures_estimees = temps de révision réaliste pour un étudiant moyen ; resume = 1 à 2 phrases.
3. **points_cles** et **pieges** : ce qu'il ne faut surtout pas rater, et les erreurs classiques.
4. **analyse_annales** : ce qui tombe souvent, le format et le barème habituels (ou « pas d'annale fournie »).
5. **exercices** : {nb_ex} exercices du plus facile au plus difficile, dans le style des annales et des TD, chacun avec un corrigé détaillé et rédigé comme attendu à l'examen.
6. **qcm** : {nb_qcm} questions à 4 choix couvrant tous les chapitres ; bonne_reponse = index (0 à 3) du bon choix ; explication courte.
7. **methode_jour_j** : gestion du temps, ordre de traitement, vérifications, matériel autorisé.
"""
    return {"texte": texte, "pdfs": pdfs, "inclus": inclus, "non_inclus": non_inclus}


# ── appel ───────────────────────────────────────────────────────────────

def generer_pack(cfg: dict, examen: dict, demande: dict) -> dict:
    if mode_effectif(cfg) == "manuel":
        raise ClaudeManuel(ecrire_prompt_manuel(examen, demande))
    resultat, details = demander_json(cfg, SYSTEME, demande["texte"], SCHEMA_PACK, demande["pdfs"])
    return {**resultat, "_meta": details}


def demander_json(cfg: dict, systeme: str, texte: str, schema: dict, pdfs: list[dict] | None = None) -> tuple[dict, dict]:
    """Une demande à Claude dont la réponse est un objet JSON conforme à `schema`."""
    mode = mode_effectif(cfg)
    if mode == "api":
        resultat, details = _via_api(cfg, systeme, texte, schema, pdfs or [])
    elif mode == "cli":
        resultat, details = _via_cli(cfg, systeme, texte, schema, pdfs or [])
    else:
        raise ErreurClaude("Claude n'est pas disponible (ni clé API, ni Claude Code) : mode manuel uniquement.")
    return resultat, {"mode": mode, **details}


def _via_api(cfg: dict, systeme: str, texte: str, schema: dict, pdfs: list[dict]) -> tuple[dict, dict]:
    import anthropic

    cle = cfg["claude"].get("api_key") or None
    client = anthropic.Anthropic(api_key=cle) if cle else anthropic.Anthropic()

    contenu = []
    for doc in pdfs:
        donnees = base64.standard_b64encode(Path(doc["chemin"]).read_bytes()).decode()
        contenu.append({"type": "document", "title": f"[{NOMS_CATEGORIES[doc['categorie']]}] {doc['nom']}",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": donnees}})
    contenu.append({"type": "text", "text": texte})

    modele = cfg["claude"].get("modele", "claude-opus-5-5")
    try:
        # streaming : la réponse est longue (fiche + exercices + QCM), on évite les délais HTTP
        with client.beta.messages.stream(
            model=modele,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # si un filtre de sécurité refuse à tort, Anthropic relance sur un autre modèle
            system=systeme,
            output_config={"effort": cfg["claude"].get("effort", "high"),
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": contenu}],
        ) as flux:
            message = flux.get_final_message()
    except anthropic.AuthenticationError:
        raise ErreurClaude("Clé API Anthropic invalide (ANTHROPIC_API_KEY).")
    except anthropic.RateLimitError:
        raise ErreurClaude("Limite d'utilisation de l'API atteinte, réessaie plus tard.")
    except anthropic.BadRequestError as e:
        raise ErreurClaude(f"Requête refusée par l'API : {e.message}")
    except anthropic.APIStatusError as e:
        raise ErreurClaude(f"Erreur de l'API Claude ({e.status_code}) : {e.message}")
    except anthropic.APIConnectionError:
        raise ErreurClaude("Impossible de joindre l'API Claude (connexion Internet ?).")

    if message.stop_reason == "refusal":
        raise ErreurClaude("Claude a refusé de traiter ces documents.")
    if message.stop_reason == "max_tokens":
        raise ErreurClaude("Réponse trop longue, coupée. Baisse nb_qcm / nb_exercices dans config.toml.")
    texte = "".join(b.text for b in message.content if b.type == "text")
    u = message.usage
    return json.loads(texte), {"modele": message.model, "jetons_entree": u.input_tokens, "jetons_sortie": u.output_tokens}


def _via_cli(cfg: dict, systeme: str, texte: str, schema: dict, pdfs: list[dict] | None = None) -> tuple[dict, dict]:
    """Claude Code en mode non interactif. Les PDF joints sont copiés dans un dossier de travail et lus avec
    l'outil Read (seul outil autorisé) : Claude voit alors les pages, schémas et figures compris."""
    exe = trouver_cli(cfg)
    if not exe:
        raise ErreurClaude("Commande `claude` introuvable (installe Claude Code ou passe en mode api/manuel).")
    DOSSIER_PROMPTS.mkdir(parents=True, exist_ok=True)
    dossier, commande = DOSSIER_PROMPTS, [exe, "-p", "--output-format", "json",
                                          "--model", cfg["claude"].get("modele", "claude-opus-5-5")]
    if pdfs:
        dossier = Path(tempfile.mkdtemp(prefix="joints-", dir=DOSSIER_PROMPTS))
        lignes = []
        for i, doc in enumerate(pdfs, 1):
            nom = f"document{i}.pdf"
            shutil.copyfile(doc["chemin"], dossier / nom)
            lignes.append(f"- {nom} : [{NOMS_CATEGORIES.get(doc.get('categorie'), 'DOCUMENT')}] {doc['nom']}")
        consigne = ("Commence par lire avec l'outil Read chacun de ces fichiers du dossier courant : ce sont les "
                    "documents originaux, avec les schémas, montages et figures que le texte ci-dessus ne montre pas.\n"
                    + "\n".join(lignes) + "\nN'utilise aucun autre outil.")
        commande += ["--allowedTools", "Read"]
    else:
        consigne = "N'utilise aucun outil : tout est dans ce message."
    prompt = (f"{systeme}\n\n{texte}\n\n{consigne} "
              f"Réponds UNIQUEMENT avec un objet JSON valide (sans texte autour, sans bloc ```), "
              f"conforme à ce schéma JSON :\n{json.dumps(schema, ensure_ascii=False)}")
    env = {**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}  # schémas SVG : réponses longues
    try:
        proc = subprocess.run(commande, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=2400,
                              cwd=dossier, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        if dossier != DOSSIER_PROMPTS:
            shutil.rmtree(dossier, ignore_errors=True)
    if proc.returncode != 0:
        try:  # en --output-format json, l'erreur est dans la sortie standard
            detail = json.loads(proc.stdout).get("result", "")
        except (json.JSONDecodeError, AttributeError):
            detail = proc.stdout
        raise ErreurClaude(f"Claude Code a échoué (code {proc.returncode}) : {(proc.stderr.strip() or str(detail).strip())[:400]}")
    enveloppe = json.loads(proc.stdout)
    if enveloppe.get("is_error"):
        raise ErreurClaude(f"Claude Code : {enveloppe.get('result', '')[:400]}")
    return extraire_json(enveloppe.get("result", "")), {"modele": cfg["claude"].get("modele"), "cout_usd": enveloppe.get("total_cost_usd")}


def ecrire_prompt_manuel(examen: dict, demande: dict) -> Path:
    DOSSIER_PROMPTS.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_PROMPTS / f"{examen['id']}.md"
    joints = "".join(f"\n- {d['chemin']}" for d in demande["pdfs"])
    chemin.write_text(
        f"{SYSTEME}\n\n{demande['texte']}\n\n"
        + (f"(Joins aussi ces PDF scannés à la conversation :{joints})\n\n" if joints else "")
        + "Réponds UNIQUEMENT avec un objet JSON valide conforme à ce schéma :\n"
        + json.dumps(SCHEMA_PACK, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return chemin


def extraire_json(texte: str) -> dict:
    """L'objet JSON de la réponse, même entouré de texte (« J'ai lu les documents… ») ou d'un bloc ```json."""
    brut = texte
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte.strip())
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass
    decodeur, meilleur, pos = json.JSONDecoder(), None, 0
    while (debut := texte.find("{", pos)) >= 0:  # le plus grand objet qui se décode, où qu'il commence
        try:
            obj, fin = decodeur.raw_decode(texte, debut)
        except json.JSONDecodeError:
            pos = debut + 1
            continue
        if isinstance(obj, dict) and (meilleur is None or fin - debut > meilleur[1]):
            meilleur = (obj, fin - debut)
        pos = fin
    if meilleur:
        return meilleur[0]
    DOSSIER_PROMPTS.mkdir(parents=True, exist_ok=True)
    (DOSSIER_PROMPTS / "derniere-reponse-illisible.txt").write_text(brut, encoding="utf-8")
    raise ErreurClaude("La réponse de Claude ne contient pas de JSON lisible (copie dans data/prompts/derniere-reponse-illisible.txt).")


def valider_pack(pack: dict) -> dict:
    """Vérifie une réponse collée à la main (mode manuel) ou venant de la CLI."""
    manquants = [c for c in SCHEMA_PACK["required"] if c not in pack]
    if manquants:
        raise ErreurClaude(f"Champs manquants dans la réponse : {', '.join(manquants)}")
    pack["qcm"] = [q for q in pack.get("qcm", []) if isinstance(q.get("choix"), list)
                   and 0 <= int(q.get("bonne_reponse", -1)) < len(q["choix"])]
    return pack
