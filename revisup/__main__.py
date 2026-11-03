"""RevisUP — ligne de commande.

  python -m revisup init           crée config.toml
  python -m revisup connexion      connexion à UPdago (fenêtre de navigateur, tu tapes ton mot de passe)
  python -m revisup statut         vérifie EDT, UPdago, IA locale, Claude
  python -m revisup sync           récupère EDT + UPdago, détecte les examens
  python -m revisup preparer [ID]  prépare les packs de révision (tous ceux à venir, ou un seul)
  python -m revisup planning       recalcule le planning de révision
  python -m revisup tout           sync + préparer + planning + rappels
  python -m revisup web            tableau de bord + automatisation (à laisser tourner)
  python -m revisup examen "Analyse 1" 2026-12-15 08:30 [--duree 120] [--salle B12]
  python -m revisup demo           données fictives pour essayer le tableau de bord
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

if sys.argv[1:2] == ["demo"]:  # avant d'importer le stockage : la démo ne touche pas à tes vraies données
    os.environ["REVISUP_DATA"] = "data-demo"

from . import config, ia_claude, planning, preparation, rappels, store, synchro
from .ia_locale import IALocale
from .store import jolie_date
from .updago import ErreurUPdago, UPdago, connexion_navigateur, decoder_lien_app, url_lancement


def cmd_connexion(cfg, args):
    url = cfg["updago"]["url"]
    if args.manuel:
        import secrets as s
        passeport = s.token_hex(8)
        print("1. Connecte-toi à UPdago dans ton navigateur habituel.")
        print("2. Ouvre ce lien dans le même navigateur :\n")
        print("   " + url_lancement(url, passeport) + "\n")
        print("3. Le navigateur essaie d'ouvrir l'app Moodle et échoue : appuie sur F12 > onglet Console,")
        print("   copie le lien qui commence par moodlemobile://token=... et colle-le ici.")
        lien = input("\nLien moodlemobile:// (ou jeton) : ").strip()
        res = decoder_lien_app(lien, url, passeport if lien.startswith("moodlemobile") else None)
    else:
        print("Une fenêtre Edge/Chrome va s'ouvrir sur la page de connexion de l'université.")
        print("Connecte-toi normalement (CAS) : RevisUP récupère seulement le jeton UPdago, jamais ton mot de passe.")
        res = connexion_navigateur(url)
    client = UPdago(url, res["jeton"])
    info = client.infos_site()
    store.ecrire_secret("updago_jeton", res["jeton"])
    print(f"\n✅ Connecté à {info.get('sitename')} en tant que {info.get('fullname')}.")


_memoriser_identifiant = config.memoriser_identifiant_mail


def fenetre_mail_connexion(cfg):
    """Petite fenêtre : identifiant + mot de passe (masqué), testés puis rangés dans le coffre de Windows."""
    import tkinter as tk

    from .mail import ErreurMail, connexion_mot_de_passe
    m = cfg["mail"]
    racine = tk.Tk()
    racine.title("RevisUP — messagerie de l'université")
    racine.attributes("-topmost", True)
    racine.resizable(False, False)
    cadre = tk.Frame(racine, padx=18, pady=14)
    cadre.pack()
    tk.Label(cadre, text="Connexion à la messagerie Zimbra", font=("Segoe UI", 11, "bold")).grid(row=0, columnspan=2, pady=(0, 10))
    tk.Label(cadre, text="Identifiant ou adresse mail :").grid(row=1, column=0, sticky="e")
    ident = tk.Entry(cadre, width=32)
    ident.insert(0, m["identifiant"])
    ident.grid(row=1, column=1, pady=3)
    tk.Label(cadre, text="Mot de passe :").grid(row=2, column=0, sticky="e")
    mdp = tk.Entry(cadre, width=32, show="•")
    mdp.grid(row=2, column=1, pady=3)
    etat = tk.Label(cadre, text="Rangé dans le coffre de Windows, jamais dans un fichier.", fg="#555")
    etat.grid(row=4, columnspan=2, pady=(8, 0))

    def valider(_=None):
        etat.config(text="Connexion…", fg="#555")
        racine.update()
        nom = (store.lire()["updago"].get("utilisateur") or {}).get("nom", "")
        try:
            essai = connexion_mot_de_passe(cfg, ident.get().strip(), mdp.get().strip("\r\n"), nom)
        except ErreurMail as e:
            etat.config(text=f"Refusé par le serveur : {str(e)[:90]}\nVérifie le mot de passe, ou tape ton adresse mail complète.",
                        fg="#b91c1c")
            return
        _memoriser_identifiant(cfg, essai)
        etat.config(text=f"✅ Connectée avec {essai} ! La fenêtre va se fermer.", fg="#15803d")
        print(f"OK messagerie connectée ({essai})")
        racine.after(2500, racine.destroy)

    tk.Button(cadre, text="Connexion", width=14, command=valider).grid(row=3, columnspan=2, pady=(10, 0))
    mdp.bind("<Return>", valider)
    mdp.focus_set()
    racine.lift()
    racine.focus_force()
    racine.mainloop()


def _message(titre, texte, erreur=False):
    """Boîte de dialogue (mail-connexion.bat tourne sans console)."""
    print(texte)
    import tkinter as tk
    from tkinter import messagebox
    racine = tk.Tk()
    racine.withdraw()
    racine.attributes("-topmost", True)
    (messagebox.showerror if erreur else messagebox.showinfo)(titre, texte, parent=racine)
    racine.destroy()


def cmd_mail_connexion(cfg, args):
    import getpass
    import re as _re

    from .mail import Boite, ErreurMail, connexion_microsoft, connexion_webmail, enregistrer_mot_de_passe, fournisseur, microsoft
    m = cfg["mail"]
    if fournisseur(cfg) == "webmail":
        print("Une fenêtre Edge s'ouvre sur le webmail de l'université : connecte-toi avec l'ENT.")
        try:
            adresse = connexion_webmail()
        except (ErreurMail, OSError) as e:
            store.journal(f"Messagerie : {e}", "erreur")
            return _message("RevisUP — messagerie", f"❌ {e}", erreur=True)
        _memoriser_identifiant(cfg, adresse)
        return _message("RevisUP — messagerie", f"✅ Messagerie connectée ({adresse}).\n"
                        "RevisUP garde seulement la session du webmail, jamais ton mot de passe.")
    if microsoft(cfg):
        print("Une fenêtre Edge s'ouvre sur la page Microsoft de l'université : connecte-toi normalement.")
        try:
            adresse = connexion_microsoft()
        except (ErreurMail, OSError) as e:
            store.journal(f"Messagerie : {e}", "erreur")
            return _message("RevisUP — messagerie", f"❌ {e}", erreur=True)
        _memoriser_identifiant(cfg, adresse)
        return _message("RevisUP — messagerie", f"✅ Messagerie connectée ({adresse}).\n"
                        "RevisUP garde seulement un jeton de lecture, jamais ton mot de passe.")
    if args.fenetre or not sys.stdin or not sys.stdin.isatty():
        return fenetre_mail_connexion(cfg)
    print(f"Messagerie de l'université : {m['serveur']}")
    ident = input(f"Identifiant (celui de l'ENT) [{m['identifiant']}] : ").strip() or m["identifiant"]
    mdp = getpass.getpass("Mot de passe de l'université (rien ne s'affiche pendant la frappe, c'est normal) : ")
    try:
        Boite(m["serveur"], int(m["port"]), ident, mdp).fermer()
    except ErreurMail as e:
        print(f"\n❌ {e}\nVérifie l'identifiant (essaie aussi prenom.nom@etu.univ-poitiers.fr) et le mot de passe.")
        sys.exit(1)
    enregistrer_mot_de_passe(ident, mdp)
    if ident != m["identifiant"]:
        texte = config.FICHIER_CONFIG.read_text(encoding="utf-8")
        texte = _re.sub(r'(?m)^(identifiant\s*=\s*)"[^"]*"', lambda x: f'{x.group(1)}"{ident}"', texte, count=1)
        config.FICHIER_CONFIG.write_text(texte, encoding="utf-8")
    print("\n✅ Messagerie connectée. Le mot de passe est rangé dans le coffre de Windows (pas dans un fichier).")


def cmd_statut(cfg, args):
    etat = store.lire()
    print(f"EDT        : {'URL configurée' if cfg['edt']['ical_url'] else '❌ ical_url vide dans config.toml'}"
          f" — {len(etat['edt']['evenements'])} créneaux (maj {etat['edt']['maj'] or 'jamais'})")
    jeton = store.lire_secrets().get("updago_jeton")
    if jeton:
        try:
            info = UPdago(cfg["updago"]["url"], jeton).infos_site()
            print(f"UPdago     : ✅ {info.get('fullname')} (maj {etat['updago']['maj'] or 'jamais'})")
        except (ErreurUPdago, Exception) as e:
            print(f"UPdago     : ❌ jeton refusé ({e}) → python -m revisup connexion")
    else:
        print("UPdago     : ❌ non connecté → python -m revisup connexion")
    ia = IALocale.depuis_config(cfg)
    print(f"IA locale  : {'✅' if ia.disponible() else '❌ éteinte (lance LM Studio > serveur local)'} {cfg['ia_locale']['url']} · {ia.modele}")
    print(f"Claude     : mode {ia_claude.mode_effectif(cfg)} · {cfg['claude']['modele']}")
    print(f"ntfy       : {cfg['notifications'].get('ntfy_sujet') or '❌ pas de sujet'}")
    futurs = sorted((e for e in etat["examens"].values() if store.jours_avant(e["debut"]) >= 0), key=lambda e: e["debut"])
    print(f"\n{len(futurs)} examen(s) à venir :")
    for e in futurs:
        print(f"  [{e['id']}] {jolie_date(e['debut'])} — {e['matiere']} ({e.get('statut')}, source {e['source']})")


def cmd_examen(cfg, args):
    debut = datetime.fromisoformat(f"{args.date}T{args.heure}").replace(tzinfo=config.FUSEAU)
    ex = synchro.ajouter_examen_manuel(args.matiere, debut, args.duree, args.salle)
    print(f"Examen ajouté : {ex['id']}")
    planning.generer(cfg)


def cmd_preparer(cfg, args):
    if args.id:
        preparation.preparer_examen(cfg, args.id)
    else:
        preparation.preparer_tout(cfg, force=args.force)
    planning.generer(cfg)


def cmd_tout(cfg, args):
    synchro.synchroniser(cfg)
    preparation.preparer_tout(cfg)
    p = planning.generer(cfg)
    rappels.verifier(cfg)
    print(f"Planning : {len(p['sessions'])} sessions.")
    for a in p["alertes"]:
        print("⚠️ ", a)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="revisup", description="Assistant de révision — Université de Poitiers")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init")
    c = sp.add_parser("connexion")
    c.add_argument("--manuel", action="store_true", help="copier-coller du jeton au lieu d'ouvrir un navigateur")
    sp.add_parser("statut")
    sp.add_parser("sync")
    mc = sp.add_parser("mail-connexion")
    mc.add_argument("--fenetre", action="store_true", help="petite fenêtre au lieu du terminal")
    sp.add_parser("claude-connexion", help="reconnecte Claude Code (packs et analyses automatiques)")
    sp.add_parser("notes")
    sp.add_parser("notes-analyse")
    pr = sp.add_parser("preparer")
    pr.add_argument("id", nargs="?")
    pr.add_argument("--force", action="store_true", help="refaire aussi les packs déjà prêts")
    sp.add_parser("planning")
    sp.add_parser("rappels")
    sp.add_parser("tout")
    w = sp.add_parser("web")
    w.add_argument("--sans-auto", action="store_true", help="ne pas synchroniser automatiquement")
    e = sp.add_parser("examen")
    e.add_argument("matiere")
    e.add_argument("date", help="AAAA-MM-JJ")
    e.add_argument("heure", nargs="?", default="08:00", help="HH:MM")
    e.add_argument("--duree", type=int, default=120)
    e.add_argument("--salle", default="")
    sp.add_parser("demo")
    args = p.parse_args(argv)

    if args.cmd == "init":
        chemin = config.initialiser()
        cfg = config.charger()
        print(f"Configuration : {chemin}")
        print(f"Sujet ntfy pour ton iPhone : {cfg['notifications']['ntfy_sujet']}")
        return
    cfg = config.charger()
    if args.cmd == "connexion":
        cmd_connexion(cfg, args)
    elif args.cmd == "statut":
        cmd_statut(cfg, args)
    elif args.cmd == "sync":
        print(synchro.synchroniser(cfg))
    elif args.cmd == "mail-connexion":
        cmd_mail_connexion(cfg, args)
    elif args.cmd == "claude-connexion":
        import subprocess
        exe = ia_claude.trouver_cli(cfg)
        if not exe:
            sys.exit("Claude Code introuvable : installe-le, ou passe [claude] mode = \"api\" ou \"manuel\" dans config.toml.")
        print("Ton navigateur va s'ouvrir sur claude.ai : connecte-toi avec ton compte Claude.")
        subprocess.run([exe, "auth", "login"])
        subprocess.run([exe, "auth", "status"])
    elif args.cmd == "notes":
        from . import notes
        print(notes.synchroniser(cfg))
    elif args.cmd == "notes-analyse":
        from . import notes
        print(notes.analyser(cfg)["situation"])
    elif args.cmd == "preparer":
        cmd_preparer(cfg, args)
    elif args.cmd == "planning":
        res = planning.generer(cfg)
        print(f"{len(res['sessions'])} sessions planifiées.")
        for a in res["alertes"]:
            print("⚠️ ", a)
    elif args.cmd == "rappels":
        rappels.verifier(cfg)
    elif args.cmd == "tout":
        cmd_tout(cfg, args)
    elif args.cmd == "web":
        from . import web
        if sys.stdout is None:  # lancé sans console (démarrage avec Windows) : journal dans data/serveur.log
            import logging
            log = config.DOSSIER_DATA / "serveur.log"
            if log.exists() and log.stat().st_size > 2_000_000:
                log.replace(log.with_suffix(".log.1"))
            sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
            logging.getLogger("werkzeug").setLevel(logging.WARNING)  # pas une ligne par requête
            print(f"\n=== démarrage {datetime.now():%d/%m/%Y %H:%M} ===")
        web.demarrer(cfg, automatique=not args.sans_auto)
    elif args.cmd == "examen":
        cmd_examen(cfg, args)
    elif args.cmd == "demo":
        from . import demo, web
        cfg = demo.charger(cfg)
        web.demarrer(cfg, automatique=False)


if __name__ == "__main__":
    main()
