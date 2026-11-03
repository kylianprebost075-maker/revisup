"""Préparation d'un examen : l'IA locale rassemble tout (cours UPdago, messages des profs, fichiers),
puis Claude produit la synthèse, les exercices corrigés et le QCM."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from . import extraction, ia_claude, notifications, store
from .ia_locale import IALocale, _similarite
from .store import DOSSIER_COURS, jolie_date, journal, maintenant, slug
from .synchro import client_updago

TAILLE_MAX_FICHIER = 50_000_000
MIMES_IGNORES = ("video/", "audio/", "image/")
CHAMPS_INFOS = ("salle", "documents_autorises", "programme", "consignes")


def examens_a_preparer(cfg: dict, force: bool = False) -> list[dict]:
    horizon = maintenant() + timedelta(days=cfg["preparation"].get("horizon_jours", 45))
    res = []
    for ex in store.lire()["examens"].values():
        debut = datetime.fromisoformat(ex["debut"])
        if maintenant() < debut <= horizon and (force or ex.get("statut") in (None, "a_preparer", "erreur")):
            res.append(ex)
    return sorted(res, key=lambda e: e["debut"])


def preparer_tout(cfg: dict, force: bool = False) -> None:
    for ex in examens_a_preparer(cfg, force):
        preparer_examen(cfg, ex["id"], reutiliser=not force)


def _pack_recent_du_meme_cours(examen: dict, jours: int = 14):
    """Deux contrôles du même module à quelques semaines d'écart : on réutilise le pack déjà généré."""
    if not examen.get("cours_id"):
        return None, None
    limite = (maintenant() - timedelta(days=jours)).isoformat()
    for autre in store.lire()["examens"].values():
        if autre["id"] != examen["id"] and autre.get("cours_id") == examen["cours_id"] and autre.get("statut") == "pret":
            pack = store.lire_pack(autre["id"])
            if pack and pack.get("_meta", {}).get("genere_le", "") >= limite and not pack["_meta"].get("copie_de"):
                return autre, pack
    return None, None


def _maj_examen(examen_id: str, **champs) -> dict:
    with store.modifier() as etat:
        etat["examens"][examen_id].update(champs)
        return dict(etat["examens"][examen_id])


def messages_lies(etat: dict, examen: dict) -> list[dict]:
    """Messages du cours associé + messages (privés ou autres cours) dont l'IA dit qu'ils parlent de cette matière."""
    analyses = etat["analyses_messages"]
    res = []
    for m in etat["updago"].get("messages", []):
        a = analyses.get(m["id"], {})
        du_cours = examen.get("cours_id") and m.get("cours_id") == examen["cours_id"]
        cite = a.get("concerne_examen") and _similarite(examen["matiere"], a.get("matiere") or m.get("cours_nom", "")) >= 0.5
        if (du_cours and a.get("concerne_examen")) or cite or m["id"] in examen.get("autres_sources", []):
            res.append({**m, "analyse": a})
    res.sort(key=lambda m: m.get("date") or "", reverse=True)
    return res[:30]


def infos_depuis_messages(messages: list[dict]) -> dict:
    """Le message le plus récent qui précise une info l'emporte."""
    infos = {}
    for m in sorted(messages, key=lambda m: m.get("date") or ""):
        a = m.get("analyse", {})
        for champ in CHAMPS_INFOS:
            if a.get(champ):
                infos[champ] = a[champ]
        if a.get("duree_min"):
            infos["duree"] = f"{a['duree_min']} min"
    return infos


def _chemin_local(fichier: dict, categorie: str) -> Path:
    dossier = DOSSIER_COURS / f"{slug(fichier['cours_nom'], 50)}-{fichier['cours_id']}" / categorie
    nom = Path(fichier["nom"])
    return dossier / f"{slug(nom.stem, 80)}{nom.suffix.lower()}"


def _texte_en_cache(chemin: Path, fichier: dict) -> dict:
    cache = chemin.with_name(chemin.name + ".texte.json")
    if cache.exists():
        donnees = json.loads(cache.read_text(encoding="utf-8"))
        if donnees.get("modifie") == fichier.get("modifie"):
            return donnees
    donnees = {**extraction.extraire(chemin), "modifie": fichier.get("modifie")}
    cache.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    return donnees


def rassembler_documents(cfg: dict, examen: dict, ia: IALocale) -> list[dict]:
    etat = store.lire()
    fichiers = [f for f in etat["updago"].get("fichiers", []) if f["cours_id"] == examen.get("cours_id")]
    fichiers = [f for f in fichiers if not f.get("mime", "").startswith(MIMES_IGNORES) and f.get("taille", 0) <= TAILLE_MAX_FICHIER]
    if not fichiers:
        return []

    # classement (mis en cache : un fichier n'est classé qu'une fois)
    cache = etat["classements_fichiers"]
    a_classer = [f for f in fichiers if f["cle"] not in cache]
    if a_classer:
        categories = ia.classer_fichiers(examen["matiere"], a_classer)
        with store.modifier() as e:
            e["classements_fichiers"].update({f["cle"]: c for f, c in zip(a_classer, categories)})
        cache = store.lire()["classements_fichiers"]

    client = client_updago(cfg)
    documents = []
    for f in fichiers:
        categorie = cache.get(f["cle"], "autre")
        chemin = _chemin_local(f, categorie)
        marque = chemin.with_name(chemin.name + ".modifie")
        a_jour = chemin.exists() and marque.exists() and marque.read_text() == (f.get("modifie") or "")
        if not a_jour:
            if client is None:
                continue
            try:
                client.telecharger(f["url"], chemin)
                marque.write_text(f.get("modifie") or "")
            except Exception as e:  # un fichier qui échoue ne bloque pas les autres
                journal(f"Téléchargement impossible : {f['nom']} ({e})", "avertissement")
                continue
        texte = _texte_en_cache(chemin, f)
        documents.append({"nom": f["nom"], "categorie": categorie, "section": f["section"], "chemin": str(chemin),
                          "url": f["url"], **{k: texte.get(k) for k in ("texte", "pages", "scanne", "erreur")}})
    return documents


def preparer_examen(cfg: dict, examen_id: str, reutiliser: bool = False) -> dict | None:
    etat = store.lire()
    examen = etat["examens"][examen_id]
    ia = IALocale.depuis_config(cfg)
    _maj_examen(examen_id, statut="en_cours", erreur=None)
    journal(f"Préparation de « {examen['matiere']} » ({jolie_date(examen['debut'])})…")

    try:
        # 1. le bon cours UPdago
        if not examen.get("cours_id"):
            cours = ia.associer_cours(examen["matiere"], examen.get("titre", ""), etat["updago"].get("cours", []))
            if cours:
                examen = _maj_examen(examen_id, cours_id=cours["id"], cours_nom=cours["nom"])
                journal(f"  cours UPdago associé : {cours['nom']}")
            else:
                journal("  aucun cours UPdago trouvé — choisis-le sur le tableau de bord", "avertissement")

        # 2. messages des profs et infos pratiques
        messages = messages_lies(store.lire(), examen)
        infos = {**infos_depuis_messages(messages), **examen.get("infos_manuelles", {})}
        examen = _maj_examen(examen_id, infos=infos, messages_ids=[m["id"] for m in messages])
        journal(f"  {len(messages)} message(s) d'enseignant lié(s)")

        # 3. fichiers (cours, TD, TP, annales, corrigés)
        documents = rassembler_documents(cfg, examen, ia)
        par_cat = {}
        for d in documents:
            par_cat[d["categorie"]] = par_cat.get(d["categorie"], 0) + 1
        journal("  fichiers : " + (", ".join(f"{n} {c}" for c, n in par_cat.items()) or "aucun"))

        # 4. Claude (ou le pack récent d'un autre contrôle du même module)
        demande = ia_claude.construire_demande(cfg, examen, infos, messages, documents)
        jumeau, pack_jumeau = _pack_recent_du_meme_cours(examen) if reutiliser else (None, None)
        if pack_jumeau:
            journal(f"  pack repris de « {jumeau.get('titre') or jumeau['matiere']} » ({jolie_date(jumeau['debut'], False)}) "
                    "— « Régénérer » pour un pack dédié")
            pack = {**pack_jumeau, "_meta": {**pack_jumeau["_meta"], "copie_de": jumeau["id"]}}
        else:
            pack = ia_claude.valider_pack(ia_claude.generer_pack(cfg, examen, demande))
    except ia_claude.ClaudeManuel as m:
        _maj_examen(examen_id, statut="prompt_manuel", prompt=str(m.chemin))
        journal(f"  prompt prêt pour Claude (mode manuel) : {m.chemin}")
        notifications.envoyer(cfg, f"✍️ {examen['matiere']} : prompt prêt",
                              "Colle-le dans Claude puis recolle la réponse sur le tableau de bord.",
                              cle=f"manuel-{examen_id}", tags="pencil")
        return None
    except Exception as e:
        _maj_examen(examen_id, statut="erreur", erreur=f"{type(e).__name__}: {e}")
        journal(f"  échec : {e}", "erreur")
        return None

    return enregistrer_pack(cfg, examen_id, pack, demande)


def enregistrer_pack(cfg: dict, examen_id: str, pack: dict, demande: dict | None = None) -> dict:
    examen = store.lire()["examens"][examen_id]
    pack["_meta"] = {**pack.get("_meta", {}), "genere_le": maintenant().isoformat(timespec="seconds"),
                     "documents_inclus": (demande or {}).get("inclus", pack.get("_meta", {}).get("documents_inclus", [])),
                     "documents_non_inclus": (demande or {}).get("non_inclus", pack.get("_meta", {}).get("documents_non_inclus", []))}
    store.ecrire_pack(examen_id, pack)
    heures = round(sum(float(c.get("heures_estimees") or 0) for c in pack.get("chapitres", [])), 1)
    _maj_examen(examen_id, statut="pret", heures_estimees=heures or None, pack_le=pack["_meta"]["genere_le"])
    journal(f"  ✅ pack prêt : {len(pack.get('chapitres', []))} chapitres, {len(pack.get('exercices', []))} exercices, "
            f"{len(pack.get('qcm', []))} QCM, ~{heures} h de révision estimées")
    notifications.envoyer(cfg, f"✅ Pack prêt : {examen['matiere']}",
                          f"Fiche de synthèse, {len(pack.get('exercices', []))} exercices corrigés et "
                          f"{len(pack.get('qcm', []))} QCM. Examen {jolie_date(examen['debut'])}.",
                          cle=f"pack-{examen_id}-{pack['_meta']['genere_le'][:10]}", tags="white_check_mark")
    return pack
