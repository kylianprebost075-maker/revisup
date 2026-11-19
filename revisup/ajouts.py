"""Documents ajoutés à la main pour un examen : un cours absent d'UPdago, des photos d'un polycopié ou d'une annale.

Rangés dans data/cours/ajouts/<examen>/<catégorie>/, ils passent dans le pack et les annales corrigées comme ceux
d'UPdago. Plusieurs photos envoyées ensemble deviennent un seul PDF (une page par photo), que Claude retranscrit
en texte ; un PDF scanné aussi.
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
import threading
import uuid
from pathlib import Path

from . import extraction, ia_claude, store
from .store import DOSSIER_COURS, journal, maintenant, slug

CATEGORIES = ("cours", "td", "tp", "annale", "corrige", "autre")
EXT_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}
EXT_DOCUMENTS = {".pdf", ".docx", ".pptx", ".ppsx", ".txt", ".md", ".html", ".htm", ".zip"}
TAILLE_MAX = 60_000_000
TRANSCRIPTION = ("Transcris fidèlement et entièrement ce document d'un cours de BUT Réseaux & Télécoms, en Markdown : "
                 "titres, textes, questions avec leur numéro, tableaux en Markdown, formules en $...$, code et commandes "
                 "dans des blocs ```. Décris chaque schéma en une ligne entre crochets. Si un passage est illisible, "
                 "écris [illisible]. Réponds uniquement avec la transcription, sans commentaire.")


def liste(examen_id: str) -> list[dict]:
    return store.lire().get("ajouts", {}).get(examen_id, [])


def _photos_en_pdf(photos: list[tuple[str, bytes]]) -> bytes:
    from PIL import Image, ImageOps
    pages = []
    for nom, donnees in photos:
        try:
            image = Image.open(io.BytesIO(donnees))
            image.load()
        except Exception:
            raise ValueError(f"« {nom} » n'est pas une image lisible (photo HEIC ? Réglages de l'iPhone → Appareil photo "
                             "→ Formats → « Le plus compatible »)")
        image = ImageOps.exif_transpose(image).convert("RGB")  # photo de téléphone : la remettre droite
        image.thumbnail((2200, 2200))
        pages.append(image)
    sortie = io.BytesIO()
    pages[0].save(sortie, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return sortie.getvalue()


def ajouter(cfg: dict, examen_id: str, categorie: str, titre: str, fichiers: list[tuple[str, bytes]]) -> list[dict]:
    """Photos → un seul PDF ; autres fichiers gardés tels quels. Le texte est lu ensuite, en arrière-plan."""
    if categorie not in CATEGORIES:
        raise ValueError("catégorie inconnue")
    fichiers = [(n, d) for n, d in fichiers if d]
    if not fichiers:
        raise ValueError("aucun fichier reçu")
    if sum(len(d) for _, d in fichiers) > TAILLE_MAX:
        raise ValueError("trop lourd (60 Mo maximum par envoi)")
    titre = titre.strip()[:80]
    photos = [(n, d) for n, d in fichiers if Path(n).suffix.lower() in EXT_IMAGES]
    autres = [(n, d) for n, d in fichiers if Path(n).suffix.lower() not in EXT_IMAGES]
    for n, _ in autres:
        if Path(n).suffix.lower() not in EXT_DOCUMENTS:
            raise ValueError(f"format non pris en charge : {n} (PDF, Word, PowerPoint, texte ou photos)")
    a_ecrire = []
    if photos:
        a_ecrire.append((titre or f"Photos du {maintenant():%d-%m %Hh%M}", ".pdf", _photos_en_pdf(photos), len(photos)))
    for n, d in autres:
        nom = titre if titre and len(autres) == 1 and not photos else Path(n).stem
        a_ecrire.append((nom, Path(n).suffix.lower(), d, 0))

    dossier = DOSSIER_COURS / "ajouts" / slug(examen_id, 80) / categorie
    dossier.mkdir(parents=True, exist_ok=True)
    nouveaux = []
    for nom, ext, donnees, nb_photos in a_ecrire:
        base = slug(nom, 60) or "document"
        chemin, i = dossier / f"{base}{ext}", 2
        while chemin.exists():
            chemin, i = dossier / f"{base}-{i}{ext}", i + 1
        chemin.write_bytes(donnees)
        nouveaux.append({"id": uuid.uuid4().hex[:10], "nom": f"{nom}{ext}", "categorie": categorie,
                         "local": chemin.relative_to(DOSSIER_COURS).as_posix(), "taille": len(donnees),
                         "photos": nb_photos, "ajoute_le": maintenant().isoformat(timespec="seconds"), "texte": "en_cours"})
    with store.modifier() as e:
        e.setdefault("ajouts", {}).setdefault(examen_id, []).extend(nouveaux)
    for a in nouveaux:
        journal(f"Document ajouté pour {examen_id} : {a['nom']} ({a['categorie']})")
        threading.Thread(target=_lire, args=(cfg, examen_id, a), daemon=True).start()
    return nouveaux


def supprimer(examen_id: str, ajout_id: str) -> None:
    with store.modifier() as e:
        ajouts = e.setdefault("ajouts", {}).get(examen_id, [])
        a = next((x for x in ajouts if x["id"] == ajout_id), None)
        if not a:
            raise KeyError(ajout_id)
        ajouts.remove(a)
    chemin = DOSSIER_COURS / a["local"]
    for f in (chemin, chemin.with_name(chemin.name + ".texte.json")):
        f.unlink(missing_ok=True)


def _maj(examen_id: str, ajout_id: str, **champs) -> None:
    with store.modifier() as e:
        for a in e.get("ajouts", {}).get(examen_id, []):
            if a["id"] == ajout_id:
                a.update(champs)


def _lire(cfg: dict, examen_id: str, ajout: dict) -> None:
    """Texte du document (pour Claude) ; photos et scans : retranscrits par Claude. Puis les annales se mettent à jour."""
    chemin = DOSSIER_COURS / ajout["local"]
    try:
        donnees = extraction.extraire(chemin)
        if chemin.suffix.lower() == ".pdf" and (donnees.get("scanne") or not donnees.get("texte")):
            donnees = {**donnees, "texte": transcrire(cfg, chemin), "scanne": False, "erreur": None}
        chemin.with_name(chemin.name + ".texte.json").write_text(
            json.dumps({**donnees, "modifie": "ajout"}, ensure_ascii=False), encoding="utf-8")
        _maj(examen_id, ajout["id"], texte="ok" if donnees.get("texte") else "vide", erreur=donnees.get("erreur"))
        journal(f"Document ajouté lu : {ajout['nom']} ({len(donnees.get('texte') or '')} caractères)")
    except Exception as e:
        _maj(examen_id, ajout["id"], texte="erreur", erreur=f"{type(e).__name__}: {e}"[:300])
        journal(f"Document ajouté illisible : {ajout['nom']} ({type(e).__name__}: {e})", "erreur")
        return
    if ajout["categorie"] in ("annale", "corrige") and store.lire_pack(examen_id):
        from . import tuteur
        tuteur.lancer_annales(cfg, examen_id)  # l'annale corrigée intègre le nouveau sujet


def transcrire(cfg: dict, chemin: Path) -> str:
    """Photos ou scan (PDF) → texte, lu par Claude : API (document joint) ou Claude Code (outil Read)."""
    mode = ia_claude.mode_effectif(cfg)
    modele = cfg["claude"].get("modele", "claude-opus-5-5")
    if mode == "api":
        import anthropic
        cle = cfg["claude"].get("api_key") or None
        client = anthropic.Anthropic(api_key=cle) if cle else anthropic.Anthropic()
        with client.messages.stream(model=modele, max_tokens=32000, messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.standard_b64encode(chemin.read_bytes()).decode()}},
                {"type": "text", "text": TRANSCRIPTION}]}]) as flux:
            message = flux.get_final_message()
        return "".join(b.text for b in message.content if b.type == "text").strip()
    if mode == "cli":
        exe = ia_claude.trouver_cli(cfg)
        proc = subprocess.run([exe, "-p", "--output-format", "json", "--model", modele, "--allowedTools", "Read"],
                              input=f"Lis le fichier « {chemin.name} » (dossier courant) avec l'outil Read. {TRANSCRIPTION}",
                              capture_output=True, text=True, encoding="utf-8", timeout=1200, cwd=chemin.parent,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        enveloppe = json.loads(proc.stdout or "{}")
        if proc.returncode != 0 or enveloppe.get("is_error"):
            raise ia_claude.ErreurClaude(f"Claude Code : {str(enveloppe.get('result') or proc.stderr)[:300]}")
        return str(enveloppe.get("result", "")).strip()
    raise ia_claude.ErreurClaude("Claude n'est pas disponible pour lire les photos (mode manuel)")


def documents(examen_id: str, categories: tuple[str, ...] | None = None) -> list[dict]:
    """Les ajouts déjà lus, au format des documents de la préparation (nom, catégorie, texte…)."""
    res = []
    for a in liste(examen_id):
        chemin = DOSSIER_COURS / a["local"]
        cache = chemin.with_name(chemin.name + ".texte.json")
        if (categories and a["categorie"] not in categories) or not cache.exists():
            continue
        t = json.loads(cache.read_text(encoding="utf-8"))
        res.append({"nom": a["nom"], "categorie": a["categorie"], "section": "ajouté par toi", "chemin": str(chemin),
                    "url": "", **{k: t.get(k) for k in ("texte", "pages", "scanne", "erreur")}})
    return res
