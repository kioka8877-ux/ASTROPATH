# ASTROPATH

> *"Per Verba, Vox Imperatoris."* — La vox traverse les étoiles ; la mémoire s'écrit sur Terra.

---

## Doctrine

**ASTROPATH** est un **Pont Vox** entre Telegram (interface opérateur) et OpenCode CLI (bras armé). Aucun stockage local d'état. Aucune écriture directe sur les repos GitHub cibles : c'est OpenCode qui manipule le Git. La mémoire du travail réside dans le `TRACKING/<PROJ>_CAMPAIGN_LOG.md` de **chaque repo cible**, jamais dans le bot lui-même.

L'Astropathe ne se souvient pas. Il prie Terra (le repo), retourne la réponse du Chapitre (OpenCode) à l'Opérateur (toi sur Telegram), et se tait.

---

## Axiomes

1. **Telegram = interface Vox** — tous tes messages (texte, voix, médias) vivent dans un topic Telegram dédié
2. **1 Topic = 1 Repo GitHub cible** — mappé via `DOCTRINE/registre_topics.yml`
3. **OpenCode = bras armé** — c'est lui qui commit, push, déclenche workflows GitHub Actions
4. **ASTROPATH est muet sur GitHub** — zéro appel API GitHub vers les repos cibles ; il ne fait que relayer Vox
5. **La mémoire EST le repo** — `TRACKING/<PROJ>_CAMPAIGN_LOG.md` alimenté par OpenCode lui-même
6. **Reprise après crash** — si la session OpenCode meurt, tu relances et l'Opérateur dit : *"La session précédente est morte. Lis le CAMPAIGN_LOG et reprends."*

---

## Pile technologique

| Composant | Technologie | Rôle |
|---|---|---|
| Bot Telegram | `python-telegram-bot` v20 (async) | Daemon principal unique |
| Transcription vocale | Groq Whisper API (free tier) | Voice messages → texte |
| Pont OpenCode | `asyncio.create_subprocess_exec` | Stream stdout → Telegram |
| Secrets | `python-dotenv` | `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY` |
| Orchestration | Python stdlib uniquement | Pas d'autre dépendance |
| Mémoire | GitHub repos cibles | Via OpenCode, jamais direct |

---

## Structure du repo

```
ASTROPATH/
├── README.md                    # ce fichier
├── bridge.py                    # le bot complet (~350 lignes)
├── requirements.txt             # 3 dépendances
├── .env.example                 # modèle de secrets
├── .gitignore
│
├── DOCTRINE/
│   ├── COLD_START.md            # doctrine d'exécution du bot
│   └── registre_topics.yml      # mapping Topic Telegram ↔ Repo GitHub
│
├── TRACKING/
│   └── ASTROPATH_CAMPAIGN_LOG.md  # annales du bot lui-même (dev/sessions)
│
└── TELEMETRY/
    └── sessions.json            # état des sessions OpenCode en cours (local-only, gitignored)
```

**Note** : `TELEMETRY/` est local-only (jamais commité). Il permet au bot de savoir quel handle de session OpenCode est vivant pour quel topic — pure mémoire RAM persistée sur disque pour reprise post-crash du bot, **pas** mémoire métier.

---

## Setup — 5 minutes

### 1. Créer le bot Telegram

1. Ouvre Telegram, va sur `@BotFather`
2. `/newbot` → nomme-le `Astropath Bot` (username au choix, ex: `kioka_astropath_bot`)
3. **Copie le token** donné par BotFather (format `123456789:ABCdefGHI...`)

### 2. Créer le groupe Telegram avec Topics

1. Crée un **Nouveau Groupe** Telegram
2. Groupe → **Edit** → **Topics** → activés
3. Ajoute ton bot au groupe
4. Donné-lui les droits d'admin (sinon il ne peut pas lire les messages en mode Topics)
5. Note l'ID de chaque topic (visible via l'API Telegram ou un bot comme `@getidsbot`)

### 3. Récupérer une clé Groq (pour la voix)

1. Va sur https://console.groq.com
2. Crée une clé API gratuite (free tier confortable)
3. Copie `gsk_xxxxxxxxxxxxxxxx`

### 4. Configurer les secrets locaux

```powershell
git clone https://github.com/kioka8877-ux/ASTROPATH.git
cd ASTROPATH
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Remplis `.env` avec :

```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...
GROQ_API_KEY=gsk_xxxxxxxx
```

### 5. Authentifier GitHub pour OpenCode

```powershell
gh auth login
# Choisis HTTPS, authenticate via browser
```

OpenCode (lancé par ASTROPATH) héritera de cette auth — pas de PAT à stocker.

### 6. Déclarer tes topics dans le registre

Édite `DOCTRINE/registre_topics.yml` :

```yaml
topics:
  - telegram_topic_id: 42
    nom: OMNIS_WATCH
    repo: kioka8877-ux/OMNIS_WATCH
    branche: main
    dossier_local: D:\Projects\OMNIS_WATCH
    campaign_log: TRACKING/OMNIS_CAMPAIGN_LOG.md
```

### 7. Lancer le bot

```powershell
python bridge.py
```

Tu peux désormais parler à OpenCode depuis le topic Telegram `OMNIS_WATCH`.

---

## Commandes Telegram natives

| Commande | Effet |
|---|---|
| `/doctrine` | Envoie à OpenCode une demande de lecture du `CAMPAIGN_LOG` + reprise |
| `/session` | Démarre / réveille une session OpenCode pour le topic courant |
| `/kill` | Tue la session OpenCode du topic courant (en cas de blocage) |
| `/statut` | Affiche l'état de la session (vivante/morte) du topic courant |
| `/forge` | Liste les topics/repos enregistrés dans le registre |

Tout le reste (texte libre, voice messages, médias uploadés) est juste relayé vers la session OpenCode du topic courant.

---

## Reprise après crash

Si OpenCode plante (erreur API, timeout, etc.) :

1. ASTROPATH détecte la fin anormale du subprocess
2. Envoie un message sur le topic Telegram : *"⚠️ OpenCode est mort. Tape `/session` pour le relancer."*
3. Tu tapes `/session`
4. ASTROPATH déclenche OpenCode en lui injectant :  
   *"La session précédente est morte. Va lire `TRACKING/<PROJ>_CAMPAIGN_LOG.md` du dépôt `<repo>`, regarde où on en était, et reprends le travail."*
5. OpenCode lit, comprend, continue. Pas de perte.

---

## Limites strictes (ne jamais enfreindre)

1. **ASTROPATH ne commit jamais** dans un repo cible. Zéro appel `gh api`, zéro `git push`.
2. **ASTROPATH ne stocke pas** de contexte métier en local. Seul `TELEMETRY/sessions.json` (PID + topic) est stocké, et il est gitignored.
3. **ASTROPATH ne décide jamais** à la place d'OpenCode. Il ne fait que forwarder.
4. **ASTROPATH ne lit pas** tes tokens GitHub. OpenCode utilise `gh auth` déjà configuré sur ta machine.

---

## Nomenclature 40K

- **Astropath** — relayeur télépathique Imperial ; ici : le bot
- **Terra** — centre de l'Imperium ; ici : GitHub (mémoire centrale)
- **Chapitre** — unité de Space Marines ; ici : chaque projet (OMNIS_WATCH, CRUSADER, PERTURABO)
- **Vox** — système de communication ; ici : Telegram
- **Gate** — point de validation opérateur (cf. doctrine Fregate des projets cibles)
- **Scriptorium** — lieu où l'on consigne les annales ; ici : `TRACKING/CAMPAIGN_LOG.md`

---

*Héritier de la doctrine Fregate — OMNIS_WATCH / CRUSADER / PERTURABO.  
Projet étanche : autonome, non couplé aux projets cibles qu'il sert.*
