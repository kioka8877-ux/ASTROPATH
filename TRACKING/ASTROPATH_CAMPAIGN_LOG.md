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
- [ ] Implementer `bridge.py` squelette avec handlers vides
- [ ] Implementer handler `/session` : launch subprocess OpenCode
- [ ] Implementer handler texte libre : forward vers stdin OpenCode
- [ ] Implementer transcription vocale via Groq
- [ ] Implementer `/doctrine` (instruction reprise contextuelle)
- [ ] Implementer `/kill` et `/statut`
- [ ] Implementer download media -> dossier cible SHARED/IN/
- [ ] Implementer stream stdout OpenCode -> message Telegram
- [ ] Tester avec OMNIS_WATCH en topic 42 (apres setup Telegram operator)

### Axiomes tenus pendant la session
1. Pas de complexite sans besoin
2. Pas de memoire locale metier
3. Le bot ne commit jamais sur les repos cibles
4. Un seul daemon Python, un seul fichier bridge.py
