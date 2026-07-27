# ASTROPATH - Cold Start Doctrine
# =================================
# A lire par OpenCode au demarrage de toute session pilotee par ASTROPATH.
# Ce fichier FAIT LOI. Tant que tu n'as pas lu et compris ce fichier,
# tu ne peux pas travailler sur le projet ASTROPATH.

---

## 1. IDENTITE DU PROJET

- **Nom canonique** : ASTROPATH
- **Role** : Pont Vox entre Telegram (operateur) et OpenCode CLI (bras arme)
- **Runner** : Local daemon unique (python-telegram-bot), sur PC operateur
- **Compute** : Zero compute local hors bot. OpenCode fait tout le travail
- **Memoire** : Zero memoire locale. La memoire vit dans les repos GitHub cibles

ASTROPATH est un **projet etanche** : il n'est pas couple a OMNIS_WATCH,
a CRUSADER, ni a PERTURABO. Il les utilise via leur repo GitHub, mais il
n'herite pas de leur code. Quand on travaille sur ASTROPATH, on bosse
sur le bot. Point.

---

## 2. AXIOMES (NE JAMAIS ENFREINDRE)

1. **ASTROPATH est muet sur GitHub.** Zero appel `gh api`, zero `git push`,
   zero commit sur les repos cibles. C'est OpenCode qui manipule Git.
2. **ASTROPATH ne garde rien en local.** Ni contexte metier, ni historique.
   Le seul fichier d'etat est `TELEMETRY/sessions.json` (PID + topic), gitignore.
3. **ASTROPATH ne decide jamais.** II ne fait que forwarder Vox. Les
   decisions sont prises par OpenCode ou par l'operateur (toi sur Telegram).
4. **ASTROPATH ne lit pas les tokens GitHub.** OpenCode herite de `gh auth`
   deja configure. PAS de PAT stocke dans le .env du bot.

---

## 3. ARCHITECTURE TECHNIQUE

```
Telegram (Vox)
    |
    v
[ASTROPATH bridge.py - daemon local unique]
    |
    |-- transcription voice -> texte (Groq Whisper API)
    |-- download media -> dossier_local/SHARED/IN/ du projet cible
    |-- appelle OpenCode en subprocess : `opencode --prompt "..."`
    |-- stream stdout OpenCode -> message Telegram
    |-- write nothing dans les repos GitHub cibles
    v
OpenCode CLI (bras arme)
    |-- lit TRACKING/<PROJ>_CAMPAIGN_LOG.md sur le repo cible
    |-- lit DOCTRINE/<PROJ>_COLD_START.md sur le repo cible
    |-- fait le travail : code, commit, push, workflow_run, generation
    |-- met a jour TRACKING/<PROJ>_CAMPAIGN_LOG.md lui-meme
    `-- stdout -> ASTROPATH -> Telegram
```

---

## 4. CORRESPONDANCE TOPIC TELEGRAM <-> REPO GITHUB

Le mapping est defini dans `DOCTRINE/registre_topics.yml`. Format :

```yaml
topics:
  - telegram_topic_id: 42           # ID du topic dans le groupe Telegram
    nom: OMNIS_WATCH                 # nom canonique court
    repo: kioka8877-ux/OMNIS_WATCH   # repo GitHub complet
    branche: main
    dossier_local: D:\Projects\OMNIS_WATCH  # chemin absolu local
    campaign_log: TRACKING/OMNIS_CAMPAIGN_LOG.md  # chemin relatif dans le repo
```

Au demarrage du bot, ce registre est charge en memoire RAM. C'est la seule
vraie configuration persistante. Tout le reste est du comportement code en dur
dans bridge.py.

---

## 5. COMMANDES TELEGRAM CANONIQUES

| Commande  | Effet |
|-----------|-------|
| `/doctrine` | Demande a OpenCode de lire `TRACKING/<PROJ>_CAMPAIGN_LOG.md` pour reprise contextuelle |
| `/session`  | Demarre ou reveille une session OpenCode pour le topic courant |
| `/kill`     | Tue la session OpenCode du topic (blockage / debug) |
| `/statut`   | Etat de la session (PID vivant / mort) du topic |
| `/forge`    | Liste les topics/repos connus d ASTROPATH |

Tout message texte non-commande est forwarde tel quel a la session OpenCode
du topic. Tout voice message est transcrit puis forwarde. Tout media est
depose dans `dossier_local/SHARED/IN/` du projet cible et vu par OpenCode.

---

## 6. REAPRES CRASH

### Mort d OpenCode

OpenCode peut mourir (timeout API, bug, kill operateur). Detection :
- subprocess.stderr retourne exit code != 0
- OU subprocess.stdout ferme avant /doctrine response

Comportement ASTROPATH :
1. Marquer `TELEMETRY/sessions.json[topic_id].alive = false`
2. Envoyer sur le topic Telegram : *"⚠️ OpenCode est mort. Tape `/session` pour le relancer."*
3. **NE PAS relancer automatiquement.** Decision operateur uniquement.

### Relance operateur

L'operateur tape `/session`. ASTROPATH lance OpenCode en lui injectant
une instruction systematique :
> *"La session precedente est morte. Va sur le depot `<repo>`, lis le fichier `TRACKING/<PROJ>_CAMPAIGN_LOG.md`, regarde ou on en etait, et reprends le travail."*

OpenCode va alire le campaign log, comprendre le contexte, et continuer.
Pas de perte tant que le campaign_log est bien tenu a jour (role d OpenCode).

### Mort d ASTROPATH lui-meme

Si le daemon Python meurt, l'operateur le relance :
```powershell
python bridge.py
```
Au demarrage le bot lit `TELEMETRY/sessions.json`. Pour chaque topic avec
`alive = true`, il envoie un ping : *"ASTROPATH a redemarre. Session OpenCode
still alive ? Reponds pour confirmer."* Si OpenCode repond -> tout va bien.
Sinon -> marquer mort, operateur peut relancer.

---

## 7. CONVENTIONS DE CODE

- **Python 3.10+** (stdlib + python-telegram-bot + groq + dotenv)
- **Un seul fichier** : `bridge.py`. Pas de modules. Si il depasse 500 lignes,
  alors on envisagera le split. Pas avant.
- **Logging** : `logging` stdlib, fichier local `TELEMETRY/astropath.log`
  (gitignore)
- **Async natif** : python-telegram-bot v20 est full async. Tout le pont
  OpenCode doit etre `asyncio.create_subprocess_exec` (pas subprocess.run).
- **Error handling** : un try/except par handler de commande. JAMAIS crasher
  le bot sur une erreur metier. Logger + message Telegram explicatif.
- **Aucune annotation de type** Pas la peine pour un bot de 350 lignes.
  Sauf si le besoin emerge.

---

## 8. LIMITES STRICTES (NE JAMAIS ENFREINDRE)

1. Pas de memoire locale metier
2. Pas d'ecriture GitHub directe
3. Pas de PAT stocke
4. Pas de modules multiples sauf besoin documente
5. Pas de daemon supplementaire (un seul process : bridge.py)
6. Pas de dependance supplementaire sans justification ecrite dans le README

---

## 9. DEMARRAGE D'UNE SESSION DE TRAVAIL

Quand un operateur commence une session ASTROPATH (pour modifier le bot),
il DOIT lire :
1. Ce fichier (`DOCTRINE/COLD_START.md`)
2. `TRACKING/ASTROPATH_CAMPAIGN_LOG.md` (annales du bot)
3. `bridge.py` (le code en cours)

Si une session precedente est morte, la premiere action est d'aller lire le
dernier commit sur `TRACKING/ASTROPATH_CAMPAIGN_LOG.md` pour comprendre ou
on en etait, puis continuer. Pas de "bugsnone reset". On herite.

---

## 10. AXIOME FINAL

> *"L'Astropathe ne se souvient pas. Il prie Terra, porte la vox, et se tait."*
