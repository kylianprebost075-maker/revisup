# 📚 RevisUP — ton assistant de révision (Université de Poitiers)

RevisUP tourne sur ton PC et fait tout seul :

1. **Emploi du temps** : il lit ton EDT UPplanning (ADE) et repère les examens (partiel, CC, DS, contrôle, soutenance…).
2. **UPdago** : il lit tes cours, les annonces, les forums et tes messages privés. Si un prof annonce un examen
   par message (« le CC aura lieu le 19/11 à 10h15 en amphi Descartes »), l'examen est ajouté automatiquement.
3. **IA locale (LM Studio)** : elle trie tout sur ton PC. Elle trouve le cours UPdago de l'examen, classe les fichiers
   (cours, TD, TP, annales, corrigés) et extrait des messages des profs la salle, la durée, les documents autorisés et le programme.
4. **Claude** : à partir des fichiers téléchargés, il produit une **fiche de synthèse**, des **exercices corrigés**
   dans le style des annales, un **QCM** interactif et une estimation du temps de révision par chapitre.
5. **Planning** : tes sessions de révision sont placées dans tes trous d'EDT, avec une révision finale la veille de chaque examen.
6. **Notifications** sur Windows et sur l'iPhone (app ntfy) : nouvel examen, examen déplacé, J-14/J-7/J-3/J-1,
   programme du matin, début de session.

Tout se consulte sur le tableau de bord **http://localhost:8765**.

## Installation

1. Double-clique sur **`installer.bat`**.
2. Double-clique sur **`connexion.bat`** : une fenêtre Edge s'ouvre sur le CAS de l'université et tu te connectes.
   RevisUP récupère le jeton de l'app mobile Moodle (comme l'app officielle). Ton mot de passe n'est jamais lu.
3. Ouvre **`config.toml`** et colle l'URL iCal de ton emploi du temps dans `ical_url` :
   UPplanning ([lien](https://upplanning.appli.univ-poitiers.fr/direct/myPlanningUP.html)), puis choisis tes groupes,
   l'icône **Exporter l'agenda**, **Générer l'URL**, et copie le lien.
4. Dans **LM Studio**, télécharge le modèle `openai/gpt-oss-20b`. RevisUP démarre ensuite lui-même le serveur
   de LM Studio (commande `lms`) quand il en a besoin.
5. Double-clique sur **`demarrage-auto.bat`** : RevisUP démarre sans fenêtre, maintenant et à chaque ouverture de
   session Windows (journal dans `data\serveur.log`). Pour le lancer une seule fois avec une console : `lancer.bat`.
6. Messagerie (pour tes notes) : onglet **Notes** du tableau de bord, bouton **Se connecter avec l'ENT**.
7. Si Claude Code se déconnecte : **`claude-connexion.bat`**.

### Connexions

RevisUP vérifie UPdago, la messagerie, Claude, l'IA locale et l'emploi du temps au démarrage puis toutes les 3 h.
Si l'une lâche, tu reçois une notification, et **Réglages → Connexions** a le bouton pour la réparer.

### Claude : trois modes (`[claude] mode` dans config.toml)

| Mode | Ce qu'il faut | Coût |
|---|---|---|
| `api` | une clé API Anthropic dans la variable `ANTHROPIC_API_KEY` | ~0,50 à 1 $ par examen avec Opus 5.5 |
| `cli` | Claude Code installé (commande `claude`) | inclus dans ton abonnement Claude |
| `manuel` | rien | tu copies le prompt dans claude.ai, puis tu recolles la réponse sur le tableau de bord |

En `auto`, RevisUP prend l'API si une clé existe, sinon Claude Code, sinon le mode manuel.

### L'app sur l'iPhone (web app + notifications)

1. Installe **Tailscale** sur le PC et l'iPhone (même compte), puis double-clique sur **`acces-iphone.bat`** :
   l'app devient accessible en HTTPS sur ton réseau privé Tailscale seulement (adresse dans `url_publique`).
2. Sur l'iPhone, ouvre cette adresse dans **Safari** → **Partager** → **Sur l'écran d'accueil**.
3. Ouvre RevisUP depuis son icône → **Réglages** → **Activer les notifications** (iOS 16.4 minimum).

Tu reçois alors les rappels d'examen, le programme du matin, la question de midi (« qu'est-ce que tu fais
aujourd'hui ? ») et les alertes de connexion. L'onglet **Aujourd'hui** adapte le planning à ta réponse, ou à ce
que tu écris librement (« jeudi pas de course, ciné de 20h à 23h »).

### Jeux

L'onglet **Jeux** propose un quiz chrono (QCM des packs, les erreurs reviennent), des exercices R&T générés
à l'infini et corrigés pas à pas (adressage IP, binaire/hexa, loi d'Ohm, décibels, Linux), des cartes mémoire
(boîtes de Leitner) et un jeu d'associations. Les cartes sont créées par l'IA locale à partir de chaque pack,
automatiquement à la synchronisation. Points d'expérience, série de jours et records.

Sans Tailscale : `hote = "0.0.0.0"` et `code_acces` dans `[web]`, puis `http://IP-DU-PC:8765/?code=…` sur le même Wi-Fi
(sans notifications : iOS les exige en HTTPS). Le fichier `planning.ics` s'importe aussi dans le Calendrier.

## Commandes

```
python -m revisup statut          état des connexions et examens détectés
python -m revisup tout            synchro + préparation + planning + rappels
python -m revisup examen "Anglais" 2026-12-10 10:00 --duree 90 --salle C012
python -m revisup preparer ID     (re)préparer le pack d'un examen
python -m revisup demo            essai avec des données fictives (dossier data-demo)
```

## Où sont mes données ?

Tout reste dans le dossier `data/` : `etat.json`, les packs dans `packs/` et les fichiers de cours téléchargés
dans `cours/`, rangés par matière et par catégorie. Le jeton UPdago est dans `data/secrets.json`.
Seuls les documents du cours concerné et les messages liés à l'examen partent chez Claude, au moment de générer le pack.
