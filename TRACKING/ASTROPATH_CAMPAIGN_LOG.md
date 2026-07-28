# ASTROPATH - Annales du Bot
# ============================
# Ce fichier consigne l'histoire du developlement du bot ASTROPATH lui-meme.
# Ce n'est PAS le campaign_log d'un projet cible (OMNIS_WATCH etc.) -- celui-la
# vit dans le repo cible correspondant. Ici on parle du bot pont Vox.
#
# Format : un entree par session, par ordre chronologique, plus recent en bas.
# OpenCode doit lire ce fichier au demarrage de toute session sur ASTROPATH.

---

## 2026-07-27 — Session 00 — Bootstrap & Doctrine

### Contexte initial
- Operateur : kioka8877-ux
- Projet etanche : ASTROPATH ne depend pas de OMNIS_WATCH / CRUSADER / PERTURABO
- Objectif : bot Telegram = interface Vox, OpenCode = bras arme, GitHub = memoire
- Aucune memoire locale metier. Aucune ecriture GitHub par le bot.

### Realisations session 00
- Analyse du cahier des charges initial `tav.md`
- Lecture des projets cibles (OMNIS_WATCH, CRUSADER/gamma, PERTURABO/MONDES_FORGES)
- Confirmation de la doctrine Fregate des projets cibles → ASTROPATH N'EST PAS une fregate
- Doctrine ASTROPATH definie : thin Vox bridge, memoire deleguee
- Creation du repo GitHub `kioka8877-ux/ASTROPATH` (public)
- Structure tree initiale :
  ```
  ASTROPATH/
  ├── README.md
  ├── bridge.py                    (squelette)
  ├── requirements.txt
  ├── .env.example
  ├── .gitignore
  ├── DOCTRINE/
  │   ├── COLD_START.md
  │   └── registre_topics.yml
  ├── TRACKING/
  │   └── ASTROPATH_CAMPAIGN_LOG.md  (ce fichier)
  └── TELEMETRY/
      └── sessions.json              (gitignore - local state)
  ```

### Decisions
- Nom code : ASTROPATH (lore 40K : relais telepathique imperial)
- PAS de structure fregate F0X : ce n'est pas un pipeline c'est un pont
- Un seul fichier `bridge.py` (~350 lignes max)
- Stack : python-telegram-bot v20, groq (whisper), python-dotenv, stdlib
- Pas de PAT dans le bot. OpenCode herite de `gh auth login`
- ASTROPATH ne touche jamais aux repos cibles (zero gh api direct)
- Le campaign log metier vit dans chaque repo cible, pas dans ASTROPATH

### A faire next session
- [x] Implementer `bridge.py` squelette avec handlers vides
- [x] Implementer handler `/session` : launch subprocess OpenCode
- [x] Implementer handler texte libre : forward vers stdin OpenCode
- [x] Implementer transcription vocale via Groq
- [x] Implementer `/doctrine` (instruction reprise contextuelle)
- [x] Implementer `/kill` et `/statut`
- [x] Implementer download media -> dossier cible SHARED/IN/
- [x] Implementer stream stdout OpenCode -> message Telegram
- [ ] Installer Python 3.10+ sur la machine operateur (currently absent)
- [ ] Verifier la syntaxe : `python bridge.py --check` puis `python -m py_compile bridge.py`
- [ ] Setup Telegram cote operateur : BotFather + groupe avec topics + note des topic IDs
- [ ] Remplir .env (TELEGRAM_BOT_TOKEN, GROQ_API_KEY optionnel)
- [ ] Ajuster DOCTRINE/registre_topics.yml avec les vrais topic IDs et dossier_local
- [ ] Test end-to-end sur un topic (OMNIS_WATCH prefere)

### Axiomes tenus pendant la session
1. Pas de complexite sans besoin
2. Pas de memoire locale metier
3. Le bot ne commit jamais sur les repos cibles
4. Un seul daemon Python, un seul fichier bridge.py

---

## 2026-07-28 - Session 01 - Implementation bridge.py

### Contexte
- Reprise apres crash de la session precedente (chat Telegram perdu, sauve par copie `sesion.txt`)
- Le repo GitHub https://github.com/kioka8877-ux/ASTROPATH existe deja avec squelette session 00
- Token GitHub encore operationnel (PAT utilisateur fourni par l'operateur)

### Decisions importantes
- **Decouverte cle : `opencode run` supporte `-c` (continue) et `--dir`**
  - Cela change l'architecture : pas besoin de gerer un ID de session nous-memes
  - 1 topic = 1 dossier_local = 1 session OpenCode persistee par opencode lui-meme
  - `opencode run --dir <dossier> -c "<msg>"` reprend automatiquement la derniere session du dossier
- **Groq Whisper via urllib natif** (pas de SDK groq requis -> doctrine "stdlib first")
- **Handler voice transcrit puis forward a OpenCode** (pas seulement transcription)
- **Handler document depose le media dans `SHARED/IN/` sans invoquer OpenCode**
  (l'operateur le dit dans son prochain message si besoin)
- **Filtre topic strict** : messages hors topic declare dans le registre -> ignores

### Realisations session 01
- Implementation complete de `bridge.py` (~420 lignes) :
  - `cmd_session` : ouvre nouvelle session OpenCode (sans -c) avec instruction doctrine
  - `cmd_doctrine` : continue session + demande a OpenCode de relire campaign_log
  - `cmd_kill` : marque session morte dans TELEMETRY (pas de kill hard, OpenCode termine de toute facon apres chaque `run`)
  - `cmd_statut` : lit TELEMETRY/sessions.json
  - `cmd_forge` : liste les topics connus
  - `on_text` : forward texte vers `opencode run -c` (mode continue)
  - `on_voice` : download .ogg -> transcription Groq -> forward texte a OpenCode
  - `on_document` : download -> dossier_local/SHARED/IN/<filename>
  - `_wrap` : handler exception-safe (jamais crash le bot)
  - `cmd_check` : verif env (`--check`) avant lancement
- Mise a jour de `requirements.txt` (retrait de `groq` SDK, urinary natif)
- Mise a jour de ce CAMPAIGN_LOG

### Limites connues / a surveiller
- **Python absent de la machine** : la syntaxe n'a pas pu etre testee. A faire apres install.
- **Variable `group_id` / `GROUP_ID`** declaree dans le doctrinaire mais non utilisee dans le code.
  Le filtre par `message_thread_id` gere deja le scope. Si message_thread_id est None -> ignore.
  C'est suffisant. Si probleme bruit, ajouter filtre sur `chat_id`.
- **OpenCode timeout** : 600s par defaut. Peut etre trop court pour longues operations.
  Ajuster via OPENCODE_TIMEOUT dans .env.
- **messages de tres longue reponse** : decoupes en chunks de 4000 caracteres (limite Telegram 4096).

### A faire next session
- [ ] Verifier syntaxe avec `python -m py_compile bridge.py` et corriger les typos eventuels
- [ ] Installer Python 3.10+ si pas encore fait
- [ ] Setup Telegram : BotFather, groupe + topics, ajout du bot admin, note des topic IDs
- [ ] Remplir .env (TELEGRAM_BOT_TOKEN, GROQ_API_KEY optionnel)
- [ ] Ajuster DOCTRINE/registre_topics.yml avec les vrais topic IDs
- [ ] Lancer `python bridge.py --check` pour pre-flight
- [ ] Lancer `python bridge.py` et tester /forge, /session, /doctrine, puis texte libre

### Axiomes tenus pendant la session
1. Pas de complexite sans besoin
2. Pas de memoire locale metier
3. Le bot ne commit jamais sur les repos cibles
4. Un seul daemon Python, un seul fichier bridge.py
5. OpenCode est le seul a toucher au Git
6. stdlib first, dependances tierce minimum (3 au total)
