"""Extraction du texte des fichiers de cours (PDF, PowerPoint, Word, texte, HTML, archives ZIP)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from .updago import texte_brut

EXTENSIONS_TEXTE = {".txt", ".md", ".tex", ".csv", ".py", ".c", ".h", ".cpp", ".java", ".js", ".ts",
                    ".sql", ".r", ".m", ".ml", ".hs", ".ipynb", ".json", ".xml", ".sh", ".php", ".go", ".rs"}


def extraire(chemin: Path) -> dict:
    """-> {"texte": str, "pages": int, "scanne": bool, "erreur": str|None}"""
    ext = chemin.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(chemin)
        if ext in (".pptx", ".ppsx"):
            return _pptx(chemin)
        if ext == ".docx":
            return _docx(chemin)
        if ext in (".html", ".htm"):
            return _ok(texte_brut(chemin.read_text(encoding="utf-8", errors="ignore")))
        if ext in EXTENSIONS_TEXTE:
            return _ok(chemin.read_text(encoding="utf-8", errors="ignore"))
        if ext == ".zip":
            return _zip(chemin)
        return {"texte": "", "pages": 0, "scanne": False, "erreur": f"format {ext or '?'} non lu"}
    except Exception as e:  # un fichier corrompu ne doit pas bloquer tout le pack
        return {"texte": "", "pages": 0, "scanne": False, "erreur": f"{type(e).__name__}: {e}"}


def _ok(texte: str, pages: int = 1, scanne: bool = False) -> dict:
    return {"texte": texte.strip(), "pages": pages, "scanne": scanne, "erreur": None}


def _pdf(chemin: Path) -> dict:
    from pypdf import PdfReader

    lecteur = PdfReader(str(chemin))
    pages = []
    for i, page in enumerate(lecteur.pages, 1):
        t = (page.extract_text() or "").strip()
        if t:
            pages.append(f"[page {i}]\n{t}")
    texte = "\n\n".join(pages)
    n = len(lecteur.pages)
    # moins de ~150 caractères par page : probablement un scan (sujet d'examen photographié...)
    return _ok(texte, n, scanne=n > 0 and len(texte) < 150 * n)


def _pptx(chemin: Path) -> dict:
    from pptx import Presentation

    pres = Presentation(str(chemin))
    diapos = []
    for i, diapo in enumerate(pres.slides, 1):
        morceaux = []
        for forme in diapo.shapes:
            if forme.has_text_frame:
                morceaux.append(forme.text_frame.text)
            if getattr(forme, "has_table", False) and forme.has_table:
                for ligne in forme.table.rows:
                    morceaux.append(" | ".join(c.text for c in ligne.cells))
        if diapo.has_notes_slide and diapo.notes_slide.notes_text_frame:
            notes = diapo.notes_slide.notes_text_frame.text.strip()
            if notes:
                morceaux.append(f"(notes) {notes}")
        if any(m.strip() for m in morceaux):
            diapos.append(f"[diapo {i}]\n" + "\n".join(m for m in morceaux if m.strip()))
    return _ok("\n\n".join(diapos), len(pres.slides))


def _docx(chemin: Path) -> dict:
    from docx import Document

    doc = Document(str(chemin))
    lignes = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for ligne in table.rows:
            lignes.append(" | ".join(c.text.strip() for c in ligne.cells))
    return _ok("\n".join(lignes))


def _zip(chemin: Path) -> dict:
    morceaux = []
    with zipfile.ZipFile(chemin) as z:
        for info in z.infolist()[:60]:
            ext = Path(info.filename).suffix.lower()
            if info.is_dir() or info.file_size > 2_000_000 or ext not in EXTENSIONS_TEXTE:
                continue
            contenu = z.read(info).decode("utf-8", errors="ignore")
            morceaux.append(f"--- {info.filename} ---\n{contenu}")
    return _ok("\n\n".join(morceaux))
