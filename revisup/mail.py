"""Messagerie universitaire : repérage des mails de notes.

Trois façons d'y accéder (config.toml, [mail] fournisseur) :
  "webmail"   : webmail Zimbra (upmail). L'étudiant se connecte lui-même par le CAS dans Edge, comme pour
                l'ENT ; RevisUP garde seulement le jeton de session du webmail, jamais le mot de passe.
  "zimbra"    : IMAP Zimbra avec mot de passe, rangé dans le coffre de Windows.
  "microsoft" : IMAP Microsoft 365 avec un jeton OAuth2 (page de connexion Microsoft).
Les pièces jointes (listes de notes de toute la promo) ne sont jamais envoyées ailleurs : on n'en
garde que les lignes qui concernent l'étudiant, sur le PC.
"""
from __future__ import annotations

import base64
import email
import email.header
import email.utils
import imaplib
import io
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

import requests

from . import store
from .config import FUSEAU
from .edt import normaliser
from .updago import texte_brut

SERVICE_COFFRE = "revisup-zimbra"
WEBMAIL = "https://upmail.univ-poitiers.fr"
PROFIL_NAVIGATEUR = Path.home() / ".revisup" / "navigateur"
# Connexion OAuth2 à Microsoft 365, comme Thunderbird (application publique, lecture IMAP seulement)
MS_CLIENT = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
MS_AUTORITE = "https://login.microsoftonline.com/organizations/oauth2/v2.0"
MS_SCOPES = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
MS_RETOUR = "https://localhost"
DOSSIERS_IGNORES = re.compile(r"trash|corbeille|junk|spam|ind[ée]sirable|sent|envoy|draft|brouillon|contacts|chats|emailed"
                              r"|supprim|deleted|calendri|t[âa]ches|journal|flux rss|synchroni|historique|bo[iî]te d.envoi"
                              r"|outbox|^notes$", re.I)
# un mail de notes parle de notes ET contient quelque chose qui ressemble à une note (/20, sur 20...)
MOTS_NOTES = re.compile(r"\bnotes?\b|r[ée]sultats?|relev[ée]|bar[eè]me|moyenne|correction|copies?\b|\bctrl\b|contr[ôo]le|\bds\b|partiel|examen|[ée]valuation", re.I)
FORME_NOTE = re.compile(r"\d{1,2}(?:[.,]\d{1,2})?\s*(?:/\s*20|sur\s*20|pts|points)|\bnotes?\s*:\s*\d", re.I)
EXT_PJ = {".pdf", ".xlsx", ".xls", ".csv", ".txt", ".ods", ".docx"}


class ErreurMail(Exception):
    pass


def mot_de_passe(identifiant: str) -> str | None:
    import keyring
    return keyring.get_password(SERVICE_COFFRE, identifiant)


def enregistrer_mot_de_passe(identifiant: str, mdp: str) -> None:
    import keyring
    keyring.set_password(SERVICE_COFFRE, identifiant, mdp)


def variantes_identifiant(saisi: str, nom_etudiant: str) -> list[str]:
    """L'identifiant de l'ENT, puis l'adresse prenom.nom@etu.univ-poitiers.fr (2 essais max : pas de blocage du compte)."""
    if "@" in saisi:
        return [saisi]
    mots = [w for w in re.sub(r"[^a-z ]", "", normaliser(nom_etudiant)).split() if w]
    return [saisi] + ([f"{'.'.join(mots[:1] + mots[-1:])}@etu.univ-poitiers.fr"] if len(mots) >= 2 else [])


def connexion_mot_de_passe(cfg: dict, saisi: str, mdp: str, nom_etudiant: str) -> str:
    """Teste l'identifiant et le mot de passe, les range dans le coffre de Windows ; renvoie l'identifiant accepté."""
    m = cfg["mail"]
    if not saisi or not mdp:
        raise ErreurMail("identifiant ou mot de passe vide.")
    erreur = ""
    for essai in variantes_identifiant(saisi, nom_etudiant):
        try:
            Boite(m["serveur"], int(m["port"]), essai, mdp).fermer()
        except (ErreurMail, OSError) as e:
            erreur = str(e)
            print(f"Refusé pour {essai} : {erreur}", flush=True)
            continue
        enregistrer_mot_de_passe(essai, mdp)
        return essai
    raise ErreurMail(erreur)


# ── Microsoft 365 ──────────────────────────────────────────────────────

def _jetons_microsoft(donnees: dict) -> dict:
    r = requests.post(f"{MS_AUTORITE}/token", data={"client_id": MS_CLIENT, "scope": MS_SCOPES, **donnees}, timeout=30)
    j = r.json()
    if "access_token" not in j:
        raise ErreurMail(f"Microsoft refuse le jeton : {j.get('error_description') or j.get('error') or r.status_code}")
    return j


def _adresse_du_jeton(jeton: str) -> str:
    try:
        charge = jeton.split(".")[1]
        infos = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
    except Exception:
        return ""
    return infos.get("upn") or infos.get("unique_name") or infos.get("preferred_username") or infos.get("email") or ""


def connexion_microsoft(delai_s: int = 900) -> str:
    """Ouvre Edge sur la page de connexion Microsoft ; l'étudiant se connecte lui-même. Renvoie son adresse."""
    import hashlib
    import secrets
    import time

    from playwright.sync_api import sync_playwright

    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=").decode()
    etat = secrets.token_urlsafe(12)
    url = f"{MS_AUTORITE}/authorize?" + urlencode({
        "client_id": MS_CLIENT, "response_type": "code", "redirect_uri": MS_RETOUR, "response_mode": "query",
        "scope": MS_SCOPES, "state": etat, "code_challenge": defi, "code_challenge_method": "S256",
        "domain_hint": "etu.univ-poitiers.fr", "prompt": "select_account"})
    trouve: dict = {}

    def noter(adresse: str):
        if adresse.startswith(MS_RETOUR + "/") or adresse.startswith(MS_RETOUR + "?"):
            trouve.setdefault("url", adresse)

    with sync_playwright() as p:
        navigateur = None
        for canal in ("msedge", "chrome", None):
            try:
                options = {"headless": False, "args": ["--start-maximized"]}  # grande fenêtre : impossible de la rater
                navigateur = p.chromium.launch(channel=canal, **options) if canal else p.chromium.launch(**options)
                break
            except Exception:
                continue
        if navigateur is None:
            raise ErreurMail("Impossible d'ouvrir Edge ou Chrome.")
        page = navigateur.new_page(no_viewport=True)
        page.bring_to_front()
        page.on("request", lambda req: noter(req.url))
        page.on("requestfailed", lambda req: noter(req.url))
        page.on("response", lambda rep: noter(rep.headers.get("location", "")))
        page.on("framenavigated", lambda f: print("page :", urlparse(f.url).netloc + urlparse(f.url).path, flush=True)
                if f == page.main_frame else None)  # étapes de la connexion, sans les paramètres
        try:
            page.goto(url)
        except Exception:
            pass
        fin = time.time() + delai_s
        while "url" not in trouve and time.time() < fin:
            try:
                page.wait_for_timeout(500)
            except Exception:  # fenêtre fermée par l'étudiant
                break
        navigateur.close()

    if "url" not in trouve:
        raise ErreurMail("Connexion Microsoft non terminée (fenêtre fermée ou délai dépassé).")
    print("Retour de Microsoft reçu, échange du code contre un jeton…", flush=True)
    q = dict(parse_qsl(urlparse(trouve["url"]).query))
    if q.get("state") != etat:
        raise ErreurMail("Réponse de Microsoft inattendue, réessaie.")
    if "error" in q:
        raise ErreurMail(f"Microsoft a refusé : {q.get('error_description') or q['error']}")
    j = _jetons_microsoft({"grant_type": "authorization_code", "code": q["code"],
                           "code_verifier": verificateur, "redirect_uri": MS_RETOUR})
    adresse = _adresse_du_jeton(j["access_token"])
    if not adresse:
        raise ErreurMail("Adresse mail introuvable dans le jeton Microsoft.")
    store.ecrire_secret("mail_adresse", adresse)  # gardé même si l'IMAP refuse : pas besoin de se reconnecter pour réessayer
    store.ecrire_secret("mail_jeton_refresh", j["refresh_token"])
    print(f"Jeton reçu pour {adresse}, test de la boîte IMAP…", flush=True)
    Boite("outlook.office365.com", 993, adresse, jeton=j["access_token"]).fermer()  # vérifie que l'IMAP répond
    return adresse


def jeton_microsoft() -> tuple[str, str]:
    s = store.lire_secrets()
    if not s.get("mail_jeton_refresh"):
        raise ErreurMail("messagerie non connectée (mail-connexion.bat)")
    j = _jetons_microsoft({"grant_type": "refresh_token", "refresh_token": s["mail_jeton_refresh"]})
    if j.get("refresh_token"):  # Microsoft renouvelle le jeton à chaque usage
        store.ecrire_secret("mail_jeton_refresh", j["refresh_token"])
    return s["mail_adresse"], j["access_token"]


def fournisseur(cfg: dict) -> str:
    return cfg.get("mail", {}).get("fournisseur", "webmail")


def microsoft(cfg: dict) -> bool:
    return fournisseur(cfg) == "microsoft"


def connectee(cfg: dict) -> bool:
    if fournisseur(cfg) == "webmail":
        return bool(store.lire_secrets().get("webmail_jeton"))
    if microsoft(cfg):
        return bool(store.lire_secrets().get("mail_jeton_refresh"))
    ident = cfg.get("mail", {}).get("identifiant")
    return bool(ident and mot_de_passe(ident))


def ouvrir(cfg: dict) -> "Boite | BoiteWeb":
    m = cfg["mail"]
    if fournisseur(cfg) == "webmail":
        boite = BoiteWeb(store.lire_secrets().get("webmail_jeton", ""))
        try:
            boite.adresse()
        except (ErreurMail, requests.RequestException):
            try:  # session du webmail expirée : la session CAS du profil Edge suffit souvent, sans fenêtre
                connexion_webmail(visible=False, delai_s=45)
            except ErreurMail:
                store.ecrire_secret("webmail_jeton", "")
                raise ErreurMail("session du webmail expirée : reconnecte-toi dans l'onglet Notes")
            boite = BoiteWeb(store.lire_secrets()["webmail_jeton"])
        return boite
    if microsoft(cfg):
        adresse, jeton = jeton_microsoft()
        return Boite(m.get("serveur") or "outlook.office365.com", int(m.get("port", 993)), adresse, jeton=jeton)
    mdp = mot_de_passe(m["identifiant"])
    if not mdp:
        raise ErreurMail("messagerie non connectée (mail-connexion.bat)")
    return Boite(m.get("serveur", "zimbra.univ-poitiers.fr"), int(m.get("port", 993)), m["identifiant"], mdp)


def _nom_dossier(brut: str) -> str:
    """Noms de dossiers IMAP en UTF-7 modifié (« &AMk-l&AOk-ments » → « Éléments »)."""
    def decoder(m):
        if not m.group(1):
            return "&"
        b = m.group(1).replace(",", "/")
        return base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be", errors="replace")
    return re.sub(r"&([A-Za-z0-9+,]*)-", decoder, brut)


def _decoder(valeur) -> str:
    if valeur is None:
        return ""
    morceaux = []
    for texte, enc in email.header.decode_header(str(valeur)):
        morceaux.append(texte.decode(enc or "utf-8", errors="replace") if isinstance(texte, bytes) else texte)
    return "".join(morceaux).strip()


def annee_universitaire(d: datetime) -> str:
    return f"{d.year}-{d.year + 1}" if d.month >= 8 else f"{d.year - 1}-{d.year}"


class Boite:
    def __init__(self, serveur: str, port: int, identifiant: str, mdp: str = "", jeton: str = ""):
        self.imap = imaplib.IMAP4_SSL(serveur, port, timeout=60)
        try:
            if jeton:
                self.imap.authenticate("XOAUTH2", lambda _: f"user={identifiant}\x01auth=Bearer {jeton}\x01\x01".encode())
            else:
                self.imap.login(identifiant, mdp)
        except imaplib.IMAP4.error as e:
            raise ErreurMail(f"Connexion refusée par la messagerie ({e}).")

    def fermer(self):
        try:
            self.imap.logout()
        except Exception:
            pass

    def dossiers(self) -> list[str]:
        typ, lignes = self.imap.list()
        noms = []
        for l in lignes or []:
            l = l.decode(errors="replace")
            m = re.match(r'\((?P<drapeaux>[^)]*)\) "(?P<sep>[^"]*)" (?P<nom>.+)$', l)
            if not m or "\\Noselect" in m["drapeaux"]:
                continue
            nom = m["nom"].strip().strip('"')
            if not DOSSIERS_IGNORES.search(_nom_dossier(nom)):  # « ^notes$ » : le dossier Notes d'Outlook, pas tes sous-dossiers
                noms.append(nom)
        return noms

    def candidats(self, dossier: str, depuis: datetime) -> list[dict]:
        """En-têtes des mails depuis une date, filtrés sur le sujet/expéditeur (rapide, sans lire les corps)."""
        typ, _ = self.imap.select(f'"{dossier}"', readonly=True)
        if typ != "OK":
            return []
        mois = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[depuis.month - 1]  # IMAP : mois en anglais
        typ, donnees = self.imap.uid("search", None, f"SINCE {depuis.day:02d}-{mois}-{depuis.year}")
        uids = (donnees[0] or b"").split()
        res = []
        for i in range(0, len(uids), 200):
            lot = b",".join(uids[i:i + 200]).decode()
            typ, items = self.imap.uid("fetch", lot, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            for item in items or []:
                if not isinstance(item, tuple):
                    continue
                uid = re.search(rb"UID (\d+)", item[0]).group(1).decode()
                msg = email.message_from_bytes(item[1])
                sujet = _decoder(msg["Subject"])
                if not MOTS_NOTES.search(sujet):
                    continue
                try:
                    date = email.utils.parsedate_to_datetime(msg["Date"]).astimezone(FUSEAU)
                except Exception:
                    continue
                res.append({"cle": f"{dossier}:{uid}", "dossier": dossier, "uid": uid, "sujet": sujet,
                            "expediteur": _decoder(msg["From"]), "date": date.isoformat(timespec="seconds"),
                            "annee": annee_universitaire(date)})
        return res

    def contenu(self, dossier: str, uid: str, nom_etudiant: str, numero: str = "") -> dict:
        """Corps du mail + lignes des pièces jointes qui concernent l'étudiant."""
        self.imap.select(f'"{dossier}"', readonly=True)
        typ, items = self.imap.uid("fetch", uid, "(BODY.PEEK[])")
        brut = next((it[1] for it in items or [] if isinstance(it, tuple)), None)
        if brut is None:
            raise ErreurMail("Mail introuvable.")
        return _lire_message(brut, nom_etudiant, numero)


def _lire_message(brut: bytes, nom_etudiant: str, numero: str = "") -> dict:
    """Corps du mail + lignes des pièces jointes qui concernent l'étudiant."""
    msg = email.message_from_bytes(brut)
    corps_txt, corps_html, pieces = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        nom = _decoder(part.get_filename())
        charge = part.get_payload(decode=True) or b""
        if nom:
            if Path(nom).suffix.lower() in EXT_PJ and len(charge) < 15_000_000:
                lignes = lignes_qui_me_concernent(nom, charge, nom_etudiant, numero)
                pieces.append({"nom": nom, "extrait": lignes})
        elif part.get_content_type() == "text/plain":
            corps_txt.append(charge.decode(part.get_content_charset() or "utf-8", errors="replace"))
        elif part.get_content_type() == "text/html":
            corps_html.append(texte_brut(charge.decode(part.get_content_charset() or "utf-8", errors="replace")))
    corps = "\n".join(corps_txt) or "\n".join(corps_html)
    return {"corps": corps[:12000], "pieces": pieces}


# ── Webmail Zimbra (upmail) : connexion CAS dans le navigateur, puis API du webmail ──

class BoiteWeb:
    """Même interface que Boite, mais par l'API du webmail avec le jeton de session (cookie ZM_AUTH_TOKEN)."""

    def __init__(self, jeton: str, base: str = ""):
        self.jeton = jeton
        self.base = base or store.lire_secrets().get("webmail_url") or WEBMAIL
        # pas de cookie pour l'API : jeton en cookie + en en-tête = refusé (Zimbra exige alors le jeton CSRF)
        self.session = requests.Session()

    def _soap(self, requete: str, corps: dict) -> dict:
        r = self.session.post(f"{self.base}/service/soap/{requete}", timeout=90, json={
            "Header": {"context": {"_jsns": "urn:zimbra", "authToken": {"_content": self.jeton}}},
            "Body": {requete: corps}})
        try:
            j = r.json()
        except ValueError:
            raise ErreurMail(f"Webmail : réponse illisible ({r.status_code}).")
        faute = j.get("Body", {}).get("Fault")
        if faute:
            raise ErreurMail(f"Webmail : {faute.get('Reason', {}).get('Text') or faute}")
        return j["Body"][requete.replace("Request", "Response")]

    def adresse(self) -> str:
        return self._soap("GetInfoRequest", {"_jsns": "urn:zimbraAccount", "sections": "mbox"}).get("name", "")

    def fermer(self):
        self.session.close()

    def dossiers(self) -> list[str]:
        return ["webmail"]

    def candidats(self, dossier: str, depuis: datetime) -> list[dict]:
        """Du plus récent au plus ancien, jusqu'à la date demandée (corbeille, spam, envoyés et brouillons exclus)."""
        res, decalage = [], 0
        while True:
            rep = self._soap("SearchRequest", {"_jsns": "urn:zimbraMail", "types": "message", "sortBy": "dateDesc",
                                               "query": "not in:trash not in:junk not in:sent not in:drafts",
                                               "limit": 200, "offset": decalage})
            messages = rep.get("m", [])
            for m in messages:
                date = datetime.fromtimestamp(int(m["d"]) / 1000, FUSEAU)
                if date < depuis:
                    return res
                sujet = m.get("su", "")
                if not MOTS_NOTES.search(sujet):
                    continue
                exp = next((e for e in m.get("e", []) if e.get("t") == "f"), {})
                res.append({"cle": f"{dossier}:{m['id']}", "dossier": dossier, "uid": m["id"], "sujet": sujet,
                            "expediteur": f"{exp.get('p', '')} <{exp.get('a', '')}>".strip(),
                            "date": date.isoformat(timespec="seconds"), "annee": annee_universitaire(date)})
            if not rep.get("more") or not messages:
                return res
            decalage += len(messages)

    def contenu(self, dossier: str, uid: str, nom_etudiant: str, numero: str = "") -> dict:
        r = self.session.get(f"{self.base}/service/home/~/", params={"auth": "co", "id": uid}, timeout=120,
                             cookies={"ZM_AUTH_TOKEN": self.jeton})
        if r.status_code != 200:
            raise ErreurMail(f"Mail introuvable ({r.status_code}).")
        return _lire_message(r.content, nom_etudiant, numero)


def connexion_webmail(visible: bool = True, delai_s: int = 900) -> str:
    """Ouvre le webmail dans Edge : l'étudiant se connecte lui-même (CAS, comme l'ENT). Renvoie son adresse.

    Le profil du navigateur est gardé (~/.revisup/navigateur) : tant que la session CAS est valide,
    le jeton se renouvelle sans fenêtre (visible=False)."""
    import time

    from playwright.sync_api import sync_playwright

    PROFIL_NAVIGATEUR.mkdir(parents=True, exist_ok=True)
    jeton, adresse, testes = "", "", set()
    with sync_playwright() as p:
        contexte = None
        for canal in ("msedge", "chrome", None):
            try:
                options = {"headless": not visible, "no_viewport": True, "args": ["--start-maximized"]}
                contexte = p.chromium.launch_persistent_context(str(PROFIL_NAVIGATEUR), **options,
                                                                **({"channel": canal} if canal else {}))
                break
            except Exception:
                continue
        if contexte is None:
            raise ErreurMail("Impossible d'ouvrir Edge ou Chrome.")
        page = contexte.pages[0] if contexte.pages else contexte.new_page()
        page.bring_to_front()
        try:
            page.goto(WEBMAIL)
        except Exception:
            pass
        fin = time.time() + delai_s
        vu = ""
        while not adresse and time.time() < fin:
            try:
                page.wait_for_timeout(1000)
                hote = urlparse(page.url).hostname or ""
                cookies = contexte.cookies()
            except Exception:  # fenêtre fermée par l'étudiant
                break
            if hote.startswith("auth.") or not hote.endswith("univ-poitiers.fr"):
                continue  # encore sur la page CAS
            jetons = [c for c in cookies if c["name"] == "ZM_AUTH_TOKEN"]
            if f"{hote}{len(jetons)}" != vu:  # diagnostic : où on en est, sans aucune valeur de cookie
                vu = f"{hote}{len(jetons)}"
                print(f"Webmail : page {hote}, cookies {sorted({c['name'] for c in cookies})}", flush=True)
            for c in jetons:
                if c["value"] in testes:
                    continue
                testes.add(c["value"])
                base = f"https://{c['domain'].lstrip('.')}" if c["domain"].lstrip(".").count(".") >= 2 else f"https://{hote}"
                try:
                    adresse, jeton, base_ok = BoiteWeb(c["value"], base).adresse(), c["value"], base
                    break
                except (ErreurMail, requests.RequestException) as e:
                    print(f"Webmail : jeton refusé par {base} ({e})", flush=True)  # ancien jeton du profil ?
        try:
            contexte.close()
        except Exception:
            pass
    if not adresse:
        raise ErreurMail("Connexion au webmail non terminée (fenêtre fermée ou délai dépassé).")
    store.ecrire_secret("webmail_url", base_ok)
    store.ecrire_secret("webmail_jeton", jeton)
    return adresse


# ── pièces jointes : on ne garde que les lignes de l'étudiant (+ l'en-tête du tableau) ──

def _cles_recherche(nom_etudiant: str, numero: str) -> list[str]:
    mots = [m for m in normaliser(nom_etudiant).split() if len(m) >= 3]
    nom_famille = mots[-1] if mots else ""
    return [c for c in [nom_famille, normaliser(numero)] if c]


def lignes_qui_me_concernent(nom: str, charge: bytes, nom_etudiant: str, numero: str = "") -> str:
    ext = Path(nom).suffix.lower()
    cles = _cles_recherche(nom_etudiant, numero)
    try:
        if ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(charge), read_only=True, data_only=True)
            lignes = []
            for ws in wb.worksheets:
                lignes_feuille = [" | ".join("" if c is None else str(c) for c in row) for row in ws.iter_rows(values_only=True)]
                lignes += _filtrer(lignes_feuille, cles, f"[feuille {ws.title}]")
            return "\n".join(lignes)[:4000]
        if ext in (".csv", ".txt"):
            texte = charge.decode("utf-8", errors="replace")
            return "\n".join(_filtrer(texte.splitlines(), cles))[:4000]
        if ext in (".pdf", ".docx"):
            from .extraction import extraire
            with tempfile.TemporaryDirectory() as d:
                chemin = Path(d) / f"pj{ext}"
                chemin.write_bytes(charge)
                texte = extraire(chemin)["texte"]
            lignes = texte.splitlines()
            # un PDF de notes individuel (ma copie, mon relevé) : on garde tout ; une liste de promo : mes lignes seulement
            nom_famille = cles[0] if cles else ""
            if nom_famille and nom_famille in normaliser(" ".join(lignes[:12])) and "releve de notes" in normaliser(texte[:600]):
                return texte[:30000]
            if len(lignes) < 60 and not any(re.search(r"\d{8}", l) for l in lignes[5:]):
                return texte[:4000]
            return "\n".join(_filtrer(lignes, cles))[:4000]
    except Exception as e:
        return f"(pièce jointe illisible : {type(e).__name__})"
    return ""


def _filtrer(lignes: list[str], cles: list[str], titre: str = "") -> list[str]:
    lignes = [l for l in lignes if l.strip(" |")]
    if not lignes or not cles:
        return []
    miennes = [i for i, l in enumerate(lignes) if any(c in normaliser(l) for c in cles)]
    if not miennes:
        return []
    entete = lignes[:2]  # noms des colonnes (Nom | Prénom | Note...)
    garde = entete + [f"... {lignes[i]}" for i in miennes]
    return ([titre] if titre else []) + garde
