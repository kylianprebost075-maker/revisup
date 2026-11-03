"""Notes : lecture des mails de notes, moyennes, comparaison avec l'année précédente, analyse par Claude."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime

from . import ia_claude, notifications, store
from .config import FUSEAU
from .edt import normaliser
from .ia_locale import IALocale, code_module
from .mail import FORME_NOTE, ErreurMail, annee_universitaire, connectee, ouvrir
from .store import journal, maintenant

# Relevés ScoDoc (« Relevé de notes du semestre N de ... ») : chaque relevé reprend toutes les notes du semestre,
# on ne lit donc que le plus récent, sans IA (lecture exacte du PDF).
SUJET_RELEVE = re.compile(r"^relev[ée] de notes du semestre (\d+)", re.I)
SUJET_RELEVE_AUTRE = re.compile(r"relev[ée]s? (annuels?|de notes)", re.I)  # relevés annuels : déjà couverts
RE_VALEUR = re.compile(r"^(\d+(?:\.\d+)?|~|ABS|EXC|ATT|NA|NP|DEM|DEF|NI)$")
RE_MODULE = re.compile(r"^((?:R|SAE|S)\s?\d+\.\d+) - (.+)$")
RE_PAGE = r"\[page \d+\]|Édité par ScoDoc.*|Page \d+|Provisoire|Coef\.|Note/20"
RE_ENTETE_EVALS = re.compile(rf"^({RE_PAGE}|Ressources|Situations d'apprentissage et d'évaluation|UE\d+\.|\d|"
                             r"Pas d'absences signalées\.?)$")
RE_ENTETE_UE = re.compile(rf"^({RE_PAGE}|Unités d'enseignement|Promotion|min\.|moy\.|max\.)$")
RE_UE = re.compile(r"^UE(\d+\.\d+) - (.+?)\n(\d+\.\d+|~)\n(?:Rang:\s*(\d+)\s*/\s*(\d+)\n(\d+\.\d+)\n(\d+\.\d+)\n(\d+\.\d+)"
                   r"|Capitalisée le (\S+)\n\d+\.\d+)\nECTS:\s*(\d+)\s*/\s*(\d+)", re.M | re.S)


def configure(cfg: dict) -> bool:
    return connectee(cfg)


def lire_releve(texte: str) -> dict | None:
    """Relevé de notes ScoDoc (PDF) → UE (moyenne, rang, promo) et évaluations (note, coefficient)."""
    annee = re.search(r"Année scolaire:\s*(\d{4})\s*-\s*(\d{4})", texte)
    semestre = re.search(r"semestre\s*(\d+)", texte, re.I)
    lignes = [l.strip() for l in texte.splitlines()]
    if not annee or not semestre or "Ressources" not in lignes:
        return None
    debut = lignes.index("Ressources")

    partie_ue = "\n".join(l for l in lignes[:debut] if l and not RE_ENTETE_UE.match(l))
    ues = []
    for m in RE_UE.finditer(partie_ue):
        ues.append({"code": f"UE{m[1]}", "nom": " ".join(m[2].replace("R&T;", "R&T").split()),
                    "moyenne": float(m[3]) if m[3] != "~" else None,
                    "rang": int(m[4]) if m[4] else None, "effectif": int(m[5]) if m[5] else None,
                    "promo_min": float(m[6]) if m[6] else None, "promo_moy": float(m[7]) if m[7] else None,
                    "promo_max": float(m[8]) if m[8] else None, "capitalisee_le": m[9],
                    "ects": int(m[10]), "ects_max": int(m[11])})

    evaluations, module, nom, valeurs = [], None, [], []

    def clore():
        if module and nom and len(valeurs) >= 2 and re.match(r"\d", valeurs[-1]) and re.match(r"\d", valeurs[-2]):
            evaluations.append({"code": module[0], "module": f"{module[0]} {module[1]}", "evaluation": " ".join(nom),
                                "coefficient": float(valeurs[-2]), "note": float(valeurs[-1])})
        nom.clear()
        valeurs.clear()

    for l in lignes[debut:]:
        if not l or RE_ENTETE_EVALS.match(l):
            continue
        m = RE_MODULE.match(l)
        if m:
            clore()
            module = (m[1].replace(" ", ""), m[2].strip())
        elif RE_VALEUR.match(l):
            valeurs.append(l)
        else:
            if valeurs:
                clore()
            nom.append(l)
    clore()
    return {"annee": f"{annee[1]}-{annee[2]}", "semestre": int(semestre[1]), "ue": ues, "evaluations": evaluations}


def nom_etudiant(cfg: dict) -> str:
    return (store.lire()["updago"].get("utilisateur") or {}).get("nom") or cfg["mail"].get("nom_etudiant", "")


def _modules_connus(etat: dict) -> list[str]:
    noms = {c["nom"] for c in etat["updago"].get("cours", [])}
    noms |= {e["matiere"] for e in etat["examens"].values()}
    return sorted(noms)


def synchroniser(cfg: dict) -> str:
    m = cfg["mail"]
    if not connectee(cfg):
        return "messagerie non connectée (mail-connexion.bat)"
    depuis = datetime.fromisoformat(m.get("depuis", "2025-08-15")).replace(tzinfo=FUSEAU)
    boite = ouvrir(cfg)
    try:
        etat = store.lire()
        deja = etat["notes"]["mails"]
        candidats = [c for d in boite.dossiers() for c in boite.candidats(d, depuis) if c["cle"] not in deja]
        candidats.sort(key=lambda c: c["date"])
        ia = IALocale.depuis_config(cfg)
        nom = nom_etudiant(cfg)
        modules = _modules_connus(etat)
        annee_courante = annee_universitaire(maintenant())
        nouvelles = []
        for c in candidats:
            if SUJET_RELEVE.match(c["sujet"]):
                nouvelles += _lire_mail_releve(boite, c, nom)
                continue
            if SUJET_RELEVE_AUTRE.search(c["sujet"]):  # relevés annuels, annonces : déjà couverts par les relevés de semestre
                with store.modifier() as e:
                    e["notes"]["mails"][c["cle"]] = {**c, "nb_notes": 0, "ignore": "relevé"}
                continue
            try:
                contenu = boite.contenu(c["dossier"], c["uid"], nom, m.get("numero_etudiant", ""))
            except Exception as e:
                journal(f"Notes : mail « {c['sujet'][:60]} » illisible ({e})", "avertissement")
                continue
            texte = contenu["corps"] + "".join(f"\n\n[Pièce jointe {p['nom']} — lignes me concernant]\n{p['extrait']}"
                                               for p in contenu["pieces"] if p["extrait"])
            trouvees = ia.extraire_notes(c, texte, nom, modules) if FORME_NOTE.search(texte) else []
            notes_mail = []
            for i, n in enumerate(trouvees):
                date_eval = n.get("date_evaluation") or ""
                date = date_eval if len(date_eval) == 10 and date_eval[:4].isdigit() else c["date"][:10]
                notes_mail.append({
                    "id": hashlib.sha1(f"{c['cle']}:{i}".encode()).hexdigest()[:12], "source": "mail",
                    "mail": c["cle"], "sujet_mail": c["sujet"], "annee": c["annee"], "date": date,
                    "module": n.get("module", "").strip(), "code": n.get("code", ""),
                    "evaluation": n.get("evaluation", "").strip(), "note": n["note"], "sur": n["sur"],
                    "coefficient": float(n.get("coefficient") or 0), "moyenne_classe": float(n.get("moyenne_classe") or 0),
                })
            with store.modifier() as e:
                e["notes"]["mails"][c["cle"]] = {**c, "nb_notes": len(notes_mail)}
                e["notes"]["liste"] += notes_mail
            nouvelles += notes_mail
        with store.modifier() as e:
            e["notes"]["maj"] = maintenant().isoformat(timespec="seconds")
    finally:
        boite.fermer()

    recentes = [n for n in nouvelles if n["annee"] == annee_courante]
    if 0 < len(recentes) <= 3:
        for n in recentes:
            notifications.envoyer(cfg, f"📝 Nouvelle note : {libelle(n)}", f"{note20(n):.2f}/20".replace(".", ",")
                                  + (f" (moyenne de la promo {n['moyenne_classe']:g})" if n["moyenne_classe"] else ""),
                                  cle=f"note-{n['id']}", tags="memo")
    elif recentes:
        notifications.envoyer(cfg, f"📝 {len(recentes)} nouvelles notes", ", ".join(libelle(n) for n in recentes[:5]),
                              cle=f"notes-{maintenant():%Y%m%d%H%M}", tags="memo")
    bilan = f"{len(candidats)} mail(s) lu(s), {len(nouvelles)} note(s) trouvée(s)"
    journal(f"Notes : {bilan}")
    return bilan


def _lire_mail_releve(boite, c: dict, nom: str) -> list[dict]:
    """Relevés lus du plus ancien au plus récent : une évaluation garde la date du premier relevé où elle apparaît."""
    try:
        contenu = boite.contenu(c["dossier"], c["uid"], nom)
    except Exception as e:
        journal(f"Notes : relevé « {c['sujet'][:60]} » illisible ({e})", "avertissement")
        return []
    releve = lire_releve("\n".join(p["extrait"] for p in contenu["pieces"]))
    if not releve:
        journal(f"Notes : relevé du {c['date'][:10]} au format inconnu", "avertissement")
        with store.modifier() as e:
            e["notes"]["mails"][c["cle"]] = {**c, "nb_notes": 0, "ignore": "format inconnu"}
        return []
    cle_rel = f"{releve['annee']}-S{releve['semestre']}"
    nouvelles = []
    with store.modifier() as e:
        tous = e["notes"].setdefault("releves", {})
        e["notes"]["mails"][c["cle"]] = {**c, "nb_notes": len(releve["evaluations"])}
        if tous.get(cle_rel, {}).get("date", "") > c["date"]:
            return []  # un relevé plus récent de ce semestre est déjà lu
        avant = {n["id"]: n for n in e["notes"]["liste"] if n.get("releve") == cle_rel}
        vus: dict = defaultdict(int)
        notes_rel = []
        for ev in releve["evaluations"]:
            k = vus[(ev["code"], ev["evaluation"])]
            vus[(ev["code"], ev["evaluation"])] += 1
            nid = hashlib.sha1(f"releve:{cle_rel}:{ev['code']}:{ev['evaluation']}:{k}".encode()).hexdigest()[:12]
            ancienne = avant.get(nid)
            n = {"id": nid, "source": "releve", "releve": cle_rel, "semestre": releve["semestre"], "mail": c["cle"],
                 "sujet_mail": c["sujet"], "annee": releve["annee"], "date": ancienne["date"] if ancienne else c["date"][:10],
                 "module": ev["module"], "code": code_module(ev["code"]) or "", "evaluation": ev["evaluation"],
                 "note": ev["note"], "sur": 20.0, "coefficient": ev["coefficient"], "moyenne_classe": 0}
            notes_rel.append(n)
            if not ancienne or ancienne["note"] != n["note"]:
                nouvelles.append(n)
        e["notes"]["liste"] = [n for n in e["notes"]["liste"] if n.get("releve") != cle_rel] + notes_rel
        tous[cle_rel] = {"annee": releve["annee"], "semestre": releve["semestre"], "date": c["date"], "ue": releve["ue"]}
    return nouvelles


def notes_utiles(liste: list[dict]) -> list[dict]:
    """Sans les notes lues dans un mail de prof qui figurent déjà dans un relevé ScoDoc (même module, même note)."""
    officielles = {(n["annee"], cle_module(n), round(note20(n), 1)) for n in liste if n["source"] == "releve"}
    return [n for n in liste if n["source"] == "releve" or (n["annee"], cle_module(n), round(note20(n), 1)) not in officielles]


def libelle(n: dict) -> str:
    return f"{n['module']}{' — ' + n['evaluation'] if n.get('evaluation') else ''}"


def note20(n: dict) -> float:
    return n["note"] / n["sur"] * 20 if n["sur"] else n["note"]


def cle_module(n: dict) -> str:
    return n.get("code") or code_module(n.get("module", "")) or normaliser(n.get("module", ""))[:40]


def ajouter_manuelle(module: str, note: float, sur: float, date: str, evaluation: str = "", coefficient: float = 0,
                     annee: str | None = None) -> dict:
    d = datetime.fromisoformat(date).replace(tzinfo=FUSEAU)
    n = {"id": hashlib.sha1(f"manuel:{module}:{date}:{note}:{maintenant().timestamp()}".encode()).hexdigest()[:12],
         "source": "manuel", "annee": annee or annee_universitaire(d), "date": date, "module": module.strip(),
         "code": code_module(module) or "", "evaluation": evaluation.strip(), "note": float(note), "sur": float(sur),
         "coefficient": float(coefficient or 0), "moyenne_classe": 0}
    with store.modifier() as e:
        e["notes"]["liste"].append(n)
    return n


def modifier(note_id: str, champs: dict | None) -> None:
    """champs=None : supprime la note (une erreur de l'IA, par exemple)."""
    with store.modifier() as e:
        liste = e["notes"]["liste"]
        if champs is None:
            e["notes"]["liste"] = [n for n in liste if n["id"] != note_id]
            return
        for n in liste:
            if n["id"] == note_id:
                for k in ("module", "evaluation", "date", "annee"):
                    if k in champs:
                        n[k] = str(champs[k]).strip()
                for k in ("note", "sur", "coefficient"):
                    if k in champs:
                        n[k] = float(champs[k])
                n["code"] = code_module(n["module"]) or n.get("code", "")


# ── statistiques ────────────────────────────────────────────────────────

def _moyenne(notes: list[dict]) -> float | None:
    poids = [(note20(n), n["coefficient"] or 1) for n in notes]
    total = sum(p for _, p in poids)
    return round(sum(v * p for v, p in poids) / total, 2) if total else None


def statistiques(etat: dict | None = None) -> dict:
    etat = etat or store.lire()
    liste = sorted(notes_utiles(etat["notes"]["liste"]), key=lambda n: n["date"])
    annees = sorted({n["annee"] for n in liste}, reverse=True)
    courante = annee_universitaire(maintenant())
    precedente = f"{int(courante[:4]) - 1}-{courante[:4]}"

    modules = defaultdict(lambda: {"nom": "", "par_annee": defaultdict(list)})
    for n in liste:
        m = modules[cle_module(n)]
        m["nom"] = n["module"] if len(n["module"]) > len(m["nom"]) else m["nom"]
        m["par_annee"][n["annee"]].append(n)

    lignes = []
    for cle, m in modules.items():
        ligne = {"cle": cle, "nom": m["nom"], "moyennes": {}, "nb": {}, "classe": {}}
        for annee, notes in m["par_annee"].items():
            ligne["moyennes"][annee] = _moyenne(notes)
            ligne["nb"][annee] = len(notes)
            avec_classe = [n for n in notes if n["moyenne_classe"]]
            if avec_classe:
                ligne["classe"][annee] = round(sum(n["moyenne_classe"] / n["sur"] * 20 for n in avec_classe) / len(avec_classe), 2)
        a, b = ligne["moyennes"].get(courante), ligne["moyennes"].get(precedente)
        ligne["evolution"] = round(a - b, 2) if a is not None and b is not None else None
        lignes.append(ligne)
    lignes.sort(key=lambda l: l["cle"])

    generales = {}
    for annee in annees:
        moys = [l["moyennes"][annee] for l in lignes if l["moyennes"].get(annee) is not None]
        generales[annee] = round(sum(moys) / len(moys), 2) if moys else None
    ecarts = [l["evolution"] for l in lignes if l["evolution"] is not None]

    # UE (compétences) des relevés ScoDoc : moyenne, rang, promo ; UE1.1 de cette année face à UE1.1 de l'an dernier
    ues: dict = {}
    for rel in sorted(etat["notes"].get("releves", {}).values(), key=lambda r: (r["annee"], r["semestre"])):
        for u in rel["ue"]:
            ligne = ues.setdefault(u["code"], {"code": u["code"], "nom": u["nom"], "semestre": rel["semestre"], "par_annee": {}})
            case = ligne["par_annee"].setdefault(rel["annee"], {})
            if u["capitalisee_le"]:
                case["capitalisee"] = {"moyenne": u["moyenne"], "le": u["capitalisee_le"]}
            else:
                case.update({k: u[k] for k in ("moyenne", "rang", "effectif", "promo_min", "promo_moy", "promo_max",
                                                "ects", "ects_max")})

    return {"annee_courante": courante, "annee_precedente": precedente, "annees": annees,
            "moyennes_generales": generales, "modules": lignes,
            "ecart_commun": round(sum(ecarts) / len(ecarts), 2) if ecarts else None, "nb_communs": len(ecarts),
            "ue": sorted(ues.values(), key=lambda u: u["code"]),
            "sous_10": [l["nom"] for l in lignes if (l["moyennes"].get(courante) or 99) < 10]}


# ── analyse par Claude ──────────────────────────────────────────────────

SCHEMA_ANALYSE = {
    "type": "object",
    "properties": {
        "situation": {"type": "string"},
        "comparaison_annee_precedente": {"type": "string"},
        "points_forts": {"type": "array", "items": {"type": "string"}},
        "points_a_ameliorer": {"type": "array", "items": {
            "type": "object",
            "properties": {"module": {"type": "string"}, "constat": {"type": "string"},
                           "actions": {"type": "array", "items": {"type": "string"}}},
            "required": ["module", "constat", "actions"], "additionalProperties": False}},
        "objectifs": {"type": "array", "items": {
            "type": "object",
            "properties": {"module": {"type": "string"}, "note_cible": {"type": "number"}, "conseil": {"type": "string"}},
            "required": ["module", "note_cible", "conseil"], "additionalProperties": False}},
        "conseils_generaux": {"type": "string"},
    },
    "required": ["situation", "comparaison_annee_precedente", "points_forts", "points_a_ameliorer",
                 "objectifs", "conseils_generaux"],
    "additionalProperties": False,
}

SYSTEME_ANALYSE = """Tu es un conseiller pédagogique bienveillant mais franc. Tu analyses les notes d'un étudiant de BUT (Université de Poitiers).

Règles :
- Tout en français, en t'adressant à l'étudiant (tutoiement).
- Compare l'année en cours à l'année précédente module par module (s'il a des notes des deux années) : progrès réels, stagnation, rechutes.
- Rappelle qu'en BUT une compétence (UE) se valide avec 10/20 de moyenne : signale les modules qui la mettent en danger.
- Situe l'étudiant par rapport à la promo (rang, moyenne, min, max des UE) quand c'est connu ; sinon dis-le, n'invente rien.
- Une UE capitalisée l'an dernier reste acquise : ne la présente pas comme en danger, mais dis si la note actuelle aurait suffi.
- Conseils concrets et réalisables d'ici les prochains contrôles (cite-les), pas de généralités.
- Markdown simple pour les champs texte."""


def analyser(cfg: dict) -> dict:
    etat = store.lire()
    if not etat["notes"]["liste"]:
        raise ia_claude.ErreurClaude("Aucune note à analyser pour l'instant.")
    contexte = cfg.get("etudiant", {}).get("contexte", "").strip()  # config.toml, privé : formation, situation…
    systeme = SYSTEME_ANALYSE + (f"\n\nCe que l'étudiant dit de lui : {contexte}" if contexte else "")
    resultat, details = ia_claude.demander_json(cfg, systeme, demande_analyse(etat), SCHEMA_ANALYSE)
    return enregistrer_analyse(resultat, details)


def enregistrer_analyse(resultat: dict, details: dict) -> dict:
    """Aussi pour une analyse faite à la main (réponse de Claude collée), avec la même structure."""
    analyse = {**resultat, "_meta": {**details, "genere_le": maintenant().isoformat(timespec="seconds"),
                                     "nb_notes": len(notes_utiles(store.lire()["notes"]["liste"]))}}
    with store.modifier() as e:
        e["notes"]["analyse"] = analyse
    journal("Notes : analyse de Claude mise à jour")
    return analyse


def demande_analyse(etat: dict) -> str:
    stats = statistiques(etat)
    lignes_notes = "\n".join(
        f"- {n['annee']} | {n['date']} | {libelle(n)} | {n['note']:g}/{n['sur']:g}"
        + (f" | coef {n['coefficient']:g}" if n["coefficient"] else "")
        + (f" | moyenne promo {n['moyenne_classe']:g}" if n["moyenne_classe"] else "")
        for n in sorted(notes_utiles(etat["notes"]["liste"]), key=lambda n: n["date"]))
    lignes_ue = "\n".join(
        f"- {u['code']} {u['nom']} : " + " ; ".join(
            f"{a} = {c.get('moyenne')}/20" + (f", rang {c['rang']}/{c['effectif']}" if c.get("rang") else "")
            + (f", promo min {c['promo_min']} / moy {c['promo_moy']} / max {c['promo_max']}" if c.get("promo_moy") else "")
            + (f", UE capitalisée le {c['capitalisee']['le']} avec {c['capitalisee']['moyenne']}/20" if c.get("capitalisee") else "")
            for a, c in sorted(u["par_annee"].items()))
        for u in stats["ue"]) or "(pas de relevé officiel)"
    lignes_modules = "\n".join(
        f"- {l['nom']} : " + ", ".join(f"{a} = {v}/20" for a, v in sorted(l["moyennes"].items()) if v is not None)
        + (f" (évolution {l['evolution']:+.2f})" if l["evolution"] is not None else "")
        for l in stats["modules"])
    a_venir = "\n".join(f"- {e['debut'][:10]} : {e['matiere']}" for e in sorted(etat["examens"].values(), key=lambda e: e["debut"])
                        if e["debut"] >= maintenant().isoformat() and not e.get("ignore")) or "(aucun)"
    texte = f"""# Mes notes ({stats['annee_precedente']} = année précédente, {stats['annee_courante']} = année en cours)
Relevés ScoDoc : notes officielles avec le coefficient de chaque évaluation dans son module. Cette année, seul le semestre 1 est en cours.
{lignes_notes}

# Mes UE (compétences) d'après les relevés officiels, avec mon rang dans la promo
{lignes_ue}

# Moyennes par module (moyenne des évaluations pondérée par leurs coefficients)
{lignes_modules}

# Moyennes générales (moyenne simple des modules, sans les coefficients d'UE)
{', '.join(f'{a} : {v}/20' for a, v in stats['moyennes_generales'].items())}

# Mes prochains contrôles
{a_venir}

Analyse ma situation : où j'en suis, ce qui a changé depuis l'an dernier, mes points forts, ce que je dois améliorer en priorité (avec des actions concrètes) et une note cible réaliste par module pour mes prochains contrôles."""
    return texte
