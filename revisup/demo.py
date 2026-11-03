"""Données fictives (dossier data-demo) pour essayer le tableau de bord sans compte ni IA."""
from __future__ import annotations

import shutil
from datetime import datetime, time, timedelta

from . import planning, store, synchro
from .config import DOSSIER_DATA, FUSEAU

SEMAINE_TYPE = {  # jour de semaine -> créneaux (début, fin, titre, salle)
    0: [("08:30", "10:30", "CM Analyse 1", "Amphi A"), ("10:45", "12:45", "TD Algèbre linéaire - Gr 2", "B104"),
        ("14:00", "16:00", "TP Programmation Python", "TP3")],
    1: [("09:00", "12:00", "CM Algèbre linéaire", "Amphi B"), ("13:30", "15:30", "TD Analyse 1 - Gr 2", "B201")],
    2: [("08:30", "10:30", "CM Programmation Python", "Amphi A"), ("10:45", "12:15", "Anglais", "C012")],
    3: [("10:15", "12:15", "TD Analyse 1 - Gr 2", "B201"), ("14:00", "17:00", "TP Programmation Python", "TP3")],
    4: [("08:30", "10:30", "TD Algèbre linéaire - Gr 2", "B104"), ("13:30", "15:30", "Méthodologie du travail universitaire", "D3")],
}

PACK_ANALYSE = {
    "synthese_markdown": """## Chapitre 1 — Suites réelles

**Définition (convergence).** $(u_n)$ converge vers $\\ell$ si $\\forall \\varepsilon>0,\\ \\exists N,\\ \\forall n\\ge N,\\ |u_n-\\ell|<\\varepsilon$.

- Toute suite convergente est **bornée** (la réciproque est fausse : $(-1)^n$).
- **Théorème des gendarmes** : si $v_n \\le u_n \\le w_n$ et $v_n, w_n \\to \\ell$, alors $u_n \\to \\ell$.
- **Suite monotone bornée** ⇒ convergente.

> **À savoir par cœur** : limites usuelles $\\frac{\\ln n}{n}\\to 0$, $\\frac{n^k}{a^n}\\to 0$ pour $a>1$, $\\left(1+\\frac1n\\right)^n \\to e$. [CM1_suites.pdf]

## Chapitre 2 — Limites et continuité

$$\\lim_{x\\to 0}\\frac{\\sin x}{x}=1 \\qquad \\lim_{x\\to 0}\\frac{e^x-1}{x}=1 \\qquad \\lim_{x\\to 0}\\frac{\\ln(1+x)}{x}=1$$

**Théorème des valeurs intermédiaires** : $f$ continue sur $[a,b]$ et $f(a)f(b)<0$ ⇒ $f$ s'annule sur $]a,b[$.

**Méthode type — montrer qu'une équation a une solution** : 1) poser $g(x)=\\dots$ 2) vérifier la continuité 3) trouver deux valeurs de signes opposés 4) conclure par le TVI. [TD2_continuite.pdf]

## Chapitre 3 — Dérivation

- $(uv)'=u'v+uv'$, $\\left(\\frac uv\\right)'=\\frac{u'v-uv'}{v^2}$, $(f\\circ g)'=g'\\cdot f'\\circ g$.
- **Théorème de Rolle**, puis **accroissements finis** : $f(b)-f(a)=f'(c)(b-a)$.

> **À savoir par cœur** : dérivées usuelles et tableau de variations complet (c'est 6 points sur 20 dans les annales). [CC1_2025.pdf]
""",
    "chapitres": [
        {"titre": "Suites réelles", "importance": 4, "heures_estimees": 3, "resume": "Convergence, gendarmes, suites monotones."},
        {"titre": "Limites et continuité", "importance": 3, "heures_estimees": 2.5, "resume": "Limites usuelles, TVI."},
        {"titre": "Dérivation", "importance": 5, "heures_estimees": 3.5, "resume": "Règles de calcul, Rolle, accroissements finis."},
    ],
    "points_cles": ["Rédiger le **TVI** complètement : continuité + signes + conclusion.",
                    "Les limites usuelles $\\frac{\\sin x}{x}$, $\\frac{e^x-1}{x}$ reviennent chaque année."],
    "pieges": ["Oublier de vérifier la continuité avant d'appliquer le TVI.",
               "Confondre « bornée » et « convergente »."],
    "analyse_annales": "Les CC des deux dernières années : 1 exercice de suites (6 pts), 1 de limites (4 pts), 1 étude de fonction complète (10 pts). Calculatrice interdite. (données de démonstration)",
    "exercices": [
        {"titre": "Gendarmes", "chapitre": "Suites réelles", "difficulte": "facile",
         "enonce_markdown": "Montrer que $u_n=\\dfrac{\\sin n}{n}$ converge et donner sa limite.",
         "corrige_markdown": "$-\\frac1n \\le u_n \\le \\frac1n$ et $\\pm\\frac1n\\to 0$, donc par le théorème des gendarmes $u_n\\to 0$."},
        {"titre": "TVI", "chapitre": "Limites et continuité", "difficulte": "moyen",
         "enonce_markdown": "Montrer que l'équation $x^3+x-1=0$ admet une solution dans $]0,1[$.",
         "corrige_markdown": "$g(x)=x^3+x-1$ est continue (polynôme), $g(0)=-1<0$, $g(1)=1>0$. Par le TVI, $\\exists c\\in]0,1[$, $g(c)=0$."},
        {"titre": "Accroissements finis", "chapitre": "Dérivation", "difficulte": "difficile",
         "enonce_markdown": "Montrer que pour tout $x>0$ : $\\dfrac{x}{1+x} < \\ln(1+x) < x$.",
         "corrige_markdown": "On applique les accroissements finis à $\\ln$ sur $[1,1+x]$ : $\\ln(1+x)=\\frac{x}{c}$ avec $1<c<1+x$, d'où l'encadrement."},
    ],
    "qcm": [
        {"question": "Une suite bornée est-elle toujours convergente ?", "chapitre": "Suites réelles",
         "choix": ["Oui", "Non", "Seulement si elle est positive", "Seulement si elle est périodique"], "bonne_reponse": 1,
         "explication": "Contre-exemple : $(-1)^n$ est bornée mais diverge."},
        {"question": "$\\lim_{x\\to0} \\frac{e^x-1}{x}$ vaut :", "chapitre": "Limites et continuité",
         "choix": ["$0$", "$1$", "$e$", "$+\\infty$"], "bonne_reponse": 1, "explication": "C'est le nombre dérivé de $e^x$ en 0."},
        {"question": "Le TVI nécessite que $f$ soit :", "chapitre": "Limites et continuité",
         "choix": ["dérivable", "continue sur $[a,b]$", "croissante", "bornée"], "bonne_reponse": 1,
         "explication": "La continuité sur l'intervalle fermé suffit."},
        {"question": "$(f\\circ g)'$ vaut :", "chapitre": "Dérivation",
         "choix": ["$f'\\circ g'$", "$g'\\cdot (f'\\circ g)$", "$f'\\cdot g'$", "$f'\\circ g$"], "bonne_reponse": 1,
         "explication": "Règle de dérivation d'une composée."},
    ],
    "methode_jour_j": "Commence par l'étude de fonction (10 pts), garde 15 min pour relire. Calculatrice interdite : entraîne-toi au calcul à la main.",
    "_meta": {"mode": "démo", "modele": "données fictives",
              "documents_inclus": [{"nom": "CM1_suites.pdf", "categorie": "cours", "mode": "texte"}],
              "documents_non_inclus": []},
}


def charger(cfg: dict) -> dict:
    if DOSSIER_DATA.name != "data-demo":
        raise SystemExit("La démo doit utiliser le dossier data-demo.")
    shutil.rmtree(DOSSIER_DATA, ignore_errors=True)
    DOSSIER_DATA.mkdir()
    cfg = {**cfg, "demo": True,
           "web": {**cfg["web"], "port": 8766},  # jamais en conflit avec la vraie appli (8765)
           "mail": {**cfg.get("mail", {}), "identifiant": ""},
           "notifications": {**cfg["notifications"], "ntfy_sujet": "", "windows": False},
           "claude": {**cfg["claude"], "mode": "manuel"},
           "edt": {**cfg["edt"], "ical_url": ""}}

    aujourd_hui = datetime.now(FUSEAU).date()
    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())
    a = lambda jour, h: datetime.combine(jour, time.fromisoformat(h), FUSEAU).isoformat()

    evenements = []
    for semaine in range(5):
        for wd, creneaux in SEMAINE_TYPE.items():
            jour = lundi + timedelta(days=7 * semaine + wd)
            for debut, fin, titre, salle in creneaux:
                evenements.append({"uid": f"demo-{jour}-{debut}", "titre": titre, "debut": a(jour, debut),
                                   "fin": a(jour, fin), "lieu": salle, "description": "L1 Mathématiques\nGr 2"})
    prochain_lundi = lundi + timedelta(days=7)
    j_cc = prochain_lundi + timedelta(days=9)        # mercredi dans 2 semaines
    j_python = prochain_lundi + timedelta(days=11)   # vendredi dans 2 semaines (annoncé par message)
    j_partiel = prochain_lundi + timedelta(days=17)  # jeudi dans 3 semaines
    evenements += [
        {"uid": "demo-cc-analyse", "titre": "Contrôle continu 1 - Analyse 1", "debut": a(j_cc, "13:30"), "fin": a(j_cc, "15:30"),
         "lieu": "Amphi A", "description": "L1 Mathématiques"},
        {"uid": "demo-partiel-algebre", "titre": "Partiel Algèbre linéaire", "debut": a(j_partiel, "08:30"),
         "fin": a(j_partiel, "11:30"), "lieu": "Amphi B", "description": "L1 Mathématiques"},
    ]
    evenements.sort(key=lambda e: e["debut"])

    cours = [
        {"id": 101, "nom": "Analyse 1 - L1 Mathématiques", "code": "L1MA-ANA1", "categorie": "L1 Mathématiques", "dernier_acces": None, "fin": None, "masque": False},
        {"id": 102, "nom": "Algèbre linéaire - L1 Mathématiques", "code": "L1MA-ALG", "categorie": "L1 Mathématiques", "dernier_acces": None, "fin": None, "masque": False},
        {"id": 103, "nom": "Programmation Python", "code": "L1-PYTH", "categorie": "L1 Informatique", "dernier_acces": None, "fin": None, "masque": False},
    ]
    messages = [
        {"id": "demo-m1", "source": "annonces", "cours_id": 101, "cours_nom": cours[0]["nom"], "auteur": "M. Dupont",
         "sujet": "CC1 : modalités", "date": (datetime.now(FUSEAU) - timedelta(days=3)).isoformat(),
         "texte": "Bonjour à tous,\nLe CC1 portera sur les chapitres 1 à 3 (suites, limites, dérivation). Durée 2h, aucun document ni calculatrice autorisés. Les annales 2024 et 2025 sont en ligne dans la section « Examens ».\nBon courage."},
        {"id": "demo-m2", "source": "message privé", "cours_id": None, "cours_nom": "", "auteur": "Mme Martin",
         "sujet": "Programmation Python", "date": (datetime.now(FUSEAU) - timedelta(days=1)).isoformat(),
         "texte": f"Le CC de Python aura lieu le {j_python:%d/%m} à 14h en salle TP3, sur machine. Documents autorisés : la feuille mémo Python fournie."},
    ]
    analyses = {
        "demo-m1": {"concerne_examen": True, "matiere": "Analyse 1", "nature": "programme", "date": "", "heure": "",
                    "duree_min": 120, "salle": "", "documents_autorises": "aucun (ni calculatrice)",
                    "programme": "chapitres 1 à 3 : suites, limites, dérivation", "consignes": "",
                    "resume": "Le CC1 couvre les chapitres 1 à 3, 2 h, sans document ni calculatrice.", "ia": True},
        "demo-m2": {"concerne_examen": True, "matiere": "Programmation Python", "nature": "annonce_date",
                    "date": j_python.isoformat(), "heure": "14:00", "duree_min": 120, "salle": "TP3",
                    "documents_autorises": "feuille mémo Python fournie", "programme": "", "consignes": "Épreuve sur machine",
                    "resume": f"CC de Python le {j_python:%d/%m} à 14h en TP3, sur machine.", "ia": True},
    }
    fichiers = [
        {"cle": f"101:{i}:/{nom}", "cours_id": 101, "cours_nom": cours[0]["nom"], "section": sec, "module": nom,
         "type_module": "resource", "nom": nom, "chemin": "/", "url": "", "taille": 1, "modifie": None, "mime": "application/pdf"}
        for i, (nom, sec) in enumerate([("CM1_suites.pdf", "Cours"), ("CM2_limites.pdf", "Cours"), ("CM3_derivation.pdf", "Cours"),
                                        ("TD1.pdf", "TD"), ("TD2_continuite.pdf", "TD"), ("CC1_2025.pdf", "Examens"),
                                        ("CC1_2025_corrige.pdf", "Examens")])
    ]
    classements = {f["cle"]: c for f, c in zip(fichiers, ["cours", "cours", "cours", "td", "td", "annale", "corrige"])}

    with store.modifier() as etat:
        etat["edt"] = {"evenements": evenements, "maj": datetime.now(FUSEAU).isoformat(timespec="seconds")}
        etat["updago"] = {"utilisateur": {"id": 1, "nom": "Étudiant Démo", "site": "UPdago (démo)"}, "cours": cours,
                          "fichiers": fichiers, "messages": messages, "maj": datetime.now(FUSEAU).isoformat(timespec="seconds"),
                          "calendrier": [{"id": "cal-1", "titre": "Rendu TP4 Python", "cours_id": 103, "cours_nom": "Programmation Python",
                                          "debut": a(lundi + timedelta(days=8), "23:59"), "duree_min": 0, "type": "assign", "description": ""}]}
        etat["analyses_messages"] = analyses
        etat["classements_fichiers"] = classements

    synchro._fusionner_examens(cfg)
    with store.modifier() as etat:
        for ex in etat["examens"].values():
            if "analyse" in ex["matiere"].lower():
                ex.update(cours_id=101, cours_nom=cours[0]["nom"], statut="pret", heures_estimees=9,
                          infos={"duree": "120 min", "documents_autorises": "aucun (ni calculatrice)",
                                 "programme": "chapitres 1 à 3 : suites, limites, dérivation"},
                          messages_ids=["demo-m1"])
                store.ecrire_pack(ex["id"], {**PACK_ANALYSE, "_meta": {**PACK_ANALYSE["_meta"],
                                             "genere_le": datetime.now(FUSEAU).isoformat(timespec="seconds")}})
            elif "algebre" in store.slug(ex["matiere"]):
                ex.update(cours_id=102, cours_nom=cours[1]["nom"])
    planning.generer(cfg)
    _notes_fictives()
    store.journal("Démo chargée : 3 examens fictifs (dont un annoncé par message privé), un pack prêt, des notes.")
    return cfg


def _notes_fictives() -> None:
    from . import notes
    an_dernier = [("R1.01 Initiation aux réseaux", "2025-10-08", 8.5), ("R1.07 Fondamentaux de la programmation", "2025-10-20", 6),
                  ("R1.14 Mathématiques des transmissions", "2025-11-05", 7.5), ("R1.03 Réseaux locaux", "2025-11-19", 11),
                  ("R1.01 Initiation aux réseaux", "2025-12-03", 9), ("R1.07 Fondamentaux de la programmation", "2025-12-15", 8),
                  ("R1.14 Mathématiques des transmissions", "2026-01-12", 9.5), ("R1.03 Réseaux locaux", "2026-01-20", 10.5),
                  ("R1.08 Bases des systèmes d'exploitation", "2026-01-22", 12)]
    cette_annee = [("R1.01 Initiation aux réseaux", "2026-09-30", 12.5), ("R1.07 Fondamentaux de la programmation", "2026-10-07", 9),
                   ("R1.14 Mathématiques des transmissions", "2026-10-14", 11), ("R1.03 Réseaux locaux", "2026-10-21", 13.5)]
    for module, date, note in an_dernier + cette_annee:
        notes.ajouter_manuelle(module, note, 20, date, "ctrl")
