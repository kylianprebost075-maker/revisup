"""Emploi du temps UPplanning (ADE) : récupération iCal, détection des examens, créneaux libres."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta

import requests
from icalendar import Calendar

from .config import FUSEAU
from .store import slug

ACCENTS = {"a": "aàâä", "e": "eéèêë", "i": "iîï", "o": "oôö", "u": "uùûü", "c": "cç"}


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


def _motif_mot_cle(mot: str) -> str:
    """'controle continu' -> regex tolérante aux accents, au pluriel et aux numéros (CC1, DS2...)."""
    morceaux = []
    for car in normaliser(mot):
        if car == " ":
            morceaux.append(r"[\s\-_]+")
        elif car in ACCENTS:
            morceaux.append(f"[{ACCENTS[car]}{ACCENTS[car].upper()}]")
        else:
            morceaux.append(re.escape(car))
    return r"(?<![a-zA-Z0-9À-ÿ])" + "".join(morceaux) + r"s?\s?\d*(?![a-zA-Z0-9À-ÿ])"


def regex_examen(mots_cles: list[str]) -> re.Pattern:
    # les expressions longues d'abord ("controle continu" avant "controle")
    tries = sorted(set(mots_cles), key=len, reverse=True)
    return re.compile("|".join(_motif_mot_cle(m) for m in tries), re.IGNORECASE)


def est_examen(titre: str, motif: re.Pattern) -> bool:
    return bool(motif.search(titre or ""))


def matiere_depuis_titre(titre: str, motif: re.Pattern) -> str:
    reste = motif.sub(" ", titre)
    reste = re.sub(r"^[\s\-–—:|/.,()]+|[\s\-–—:|/.,(]+$", "", reste)
    reste = re.sub(r"^(de la |de l'|du |des |de |d'|en )", "", reste, flags=re.I)
    reste = re.sub(r"\s+(TP|TD|CM)$", "", reste)  # « R108 ... ctrl TP » -> « R108 ... »
    reste = re.sub(r"\s{2,}", " ", reste).strip()
    return reste or titre.strip()


# ── iCal ────────────────────────────────────────────────────────────────

def telecharger_ical(url: str) -> str:
    r = requests.get(url, timeout=60, headers={"User-Agent": "RevisUP/1.0"})
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text


def _vers_paris(valeur) -> datetime | None:
    if isinstance(valeur, datetime):
        return valeur.replace(tzinfo=FUSEAU) if valeur.tzinfo is None else valeur.astimezone(FUSEAU)
    return None  # journée entière : ignorée (les examens ont toujours une heure)


def _nettoyer_description(desc: str) -> str:
    lignes = [l.strip() for l in (desc or "").splitlines()]
    lignes = [l for l in lignes if l and not re.match(r"^\(?(export|modifi)", l, re.I)]
    return "\n".join(lignes)


def lire_ical(texte: str) -> list[dict]:
    cal = Calendar.from_ical(texte)
    evenements = []
    for ev in cal.walk("VEVENT"):
        debut = _vers_paris(ev.get("DTSTART").dt) if ev.get("DTSTART") else None
        fin = _vers_paris(ev.get("DTEND").dt) if ev.get("DTEND") else None
        if not debut:
            continue
        fin = fin or debut + timedelta(hours=1)
        evenements.append({
            "uid": str(ev.get("UID", "")) or f"{debut.isoformat()}-{ev.get('SUMMARY')}",
            "titre": str(ev.get("SUMMARY", "")).strip(),
            "debut": debut.isoformat(),
            "fin": fin.isoformat(),
            "lieu": str(ev.get("LOCATION", "")).strip(),
            "description": _nettoyer_description(str(ev.get("DESCRIPTION", ""))),
        })
    evenements.sort(key=lambda e: e["debut"])
    return evenements


def id_examen(matiere: str, debut_iso: str, prefixe: str = "ex") -> str:
    return f"{prefixe}-{slug(matiere, 40)}-{debut_iso[:10].replace('-', '')}"


def detecter_examens(evenements: list[dict], mots_cles: list[str], mots_exclus: list[str] = ()) -> list[dict]:
    motif = regex_examen(mots_cles)
    exclus = [normaliser(m) for m in mots_exclus]
    examens = []
    for ev in evenements:
        if not est_examen(ev["titre"], motif) or any(m in normaliser(ev["titre"]) for m in exclus):
            continue
        matiere = matiere_depuis_titre(ev["titre"], motif)
        examens.append({
            "id": id_examen(matiere, ev["debut"], "edt"),
            "uid": ev["uid"],
            "matiere": matiere,
            "titre": ev["titre"],
            "debut": ev["debut"],
            "fin": ev["fin"],
            "salle": ev["lieu"],
            "description": ev["description"],
            "source": "edt",
        })
    return examens


# ── créneaux libres pour réviser ────────────────────────────────────────

def _plages_du_jour(jour: date, cfg_planning: dict) -> list[tuple[time, time]]:
    cle = "samedi" if jour.weekday() == 5 else "dimanche" if jour.weekday() == 6 else "semaine"
    plages = []
    for p in cfg_planning.get(cle, []):
        a, b = p.split("-")
        plages.append((time.fromisoformat(a.strip()), time.fromisoformat(b.strip())))
    return plages


def _soustraire(intervalle, occupes):
    morceaux = [intervalle]
    for oa, ob in occupes:
        nouveaux = []
        for a, b in morceaux:
            if ob <= a or oa >= b:
                nouveaux.append((a, b))
                continue
            if oa > a:
                nouveaux.append((a, oa))
            if ob < b:
                nouveaux.append((ob, b))
        morceaux = nouveaux
    return morceaux


JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def activites_du_jour(jour: date, cfg_planning: dict) -> list[dict]:
    """Ce que l'étudiant a répondu pour ce jour-là, sinon ses activités habituelles de ce jour de la semaine."""
    reponse = cfg_planning.get("journees", {}).get(jour.isoformat())
    if reponse is not None:
        return reponse["activites"]
    nom_jour = JOURS_SEMAINE[jour.weekday()]
    return [a for a in cfg_planning.get("activites", []) if nom_jour in [normaliser(j) for j in a.get("jours", [])]]


def occupations_perso(evenements: list[dict], debut: datetime, fin: datetime, cfg_planning: dict) -> list[tuple[datetime, datetime, str]]:
    """Trajet avant le premier cours et après le dernier, activités régulières ([planning] trajet_min, activites)."""
    tampon = timedelta(minutes=cfg_planning.get("tampon_min", 15))
    trajet = timedelta(minutes=cfg_planning.get("trajet_min", 0))
    par_jour: dict = {}
    for e in evenements:
        a = datetime.fromisoformat(e["debut"]).astimezone(FUSEAU)
        b = datetime.fromisoformat(e["fin"]).astimezone(FUSEAU)
        par_jour.setdefault(a.date(), []).append((a, b))
    res = []
    jour = debut.date()
    while jour <= fin.date():
        cours = par_jour.get(jour)
        fin_journee = None
        if cours:
            premier, dernier = min(a for a, _ in cours), max(b for _, b in cours)
            if trajet:
                res.append((premier - tampon - trajet, premier, "Trajet"))
            fin_journee = dernier + tampon
        for act in activites_du_jour(jour, cfg_planning):
            if act.get("apres_les_cours"):  # seulement les jours de cours, juste après le dernier
                if fin_journee:
                    duree = timedelta(minutes=act.get("duree_min", 60))
                    res.append((fin_journee, fin_journee + duree, act.get("nom", "Activité")))
                    fin_journee += duree
            else:
                res.append((datetime.combine(jour, time.fromisoformat(act["debut"]), FUSEAU),
                            datetime.combine(jour, time.fromisoformat(act["fin"]), FUSEAU), act.get("nom", "Activité")))
        if fin_journee and trajet:
            res.append((fin_journee, fin_journee + trajet, "Trajet"))  # retour à la maison
        jour += timedelta(days=1)
    return res


def creneaux_libres(evenements: list[dict], debut: datetime, fin: datetime, cfg_planning: dict) -> list[tuple[datetime, datetime]]:
    tampon = timedelta(minutes=cfg_planning.get("tampon_min", 15))
    minimum = timedelta(minutes=cfg_planning.get("duree_session_min", 60))
    occupes = sorted(
        [(datetime.fromisoformat(e["debut"]) - tampon, datetime.fromisoformat(e["fin"]) + tampon) for e in evenements]
        + [(a, b) for a, b, _ in occupations_perso(evenements, debut, fin, cfg_planning)]
    )
    libres = []
    jour = debut.date()
    while jour <= fin.date():
        for ha, hb in _plages_du_jour(jour, cfg_planning):
            a = max(datetime.combine(jour, ha, FUSEAU), debut)
            b = min(datetime.combine(jour, hb, FUSEAU), fin)
            if b - a < minimum:
                continue
            du_jour = [(oa, ob) for oa, ob in occupes if ob > a and oa < b]
            libres += [(x, y) for x, y in _soustraire((a, b), du_jour) if y - x >= minimum]
        jour += timedelta(days=1)
    return libres
