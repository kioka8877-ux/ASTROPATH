"""
bridge.py - ASTROPATH : Pont Vox Telegram <-> OpenCode CLI
==========================================================
Daemon unique. Charge DOCTRINE/registre_topics.yml au demarrage.
Forward les messages Telegram vers OpenCode (subprocess async).
Forward les voice messages via transcription Groq Whisper.
Forward les medias vers dossier_local/SHARED/IN/ du projet cible.
NE TOUCHE JAMAIS aux repos GitHub cibles (zero gh api direct).

Usage:
    python bridge.py                 # lance le daemon
    python bridge.py --doctrine      # affiche la doctrine chargee
    python bridge.py --forge         # liste les topics connus

Variables d'environnement requises (.env) :
    TELEGRAM_BOT_TOKEN   - token donne par @BotFather
    GROQ_API_KEY         - cle pour transcription vocale (https://console.groq.com)
    OPENCODE_TIMEOUT     - timeout OpenCode en secondes (default 300)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

#  --- Configuration ----------------------------------------------------------

REPO_ROOT = Path(__file__).parent.resolve()
REGISTRE_PATH = REPO_ROOT / "DOCTRINE" / "registre_topics.yml"
TELEMETRY_DIR = REPO_ROOT / "TELEMETRY"
SESSIONS_FILE = TELEMETRY_DIR / "sessions.json"
LOG_FILE = TELEMETRY_DIR / "astropath.log"

OPENCODE_TIMEOUT = int(os.getenv("OPENCODE_TIMEOUT", "300"))

#  --- Logging ----------------------------------------------------------------

TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("astropath")

#  --- Registre topics --------------------------------------------------------

def load_registre():
    """Charge DOCTRINE/registre_topics.yml et retourne le mapping topic_id -> config."""
    import yaml
    if not REGISTRE_PATH.exists():
        log.error(f"Registre introuvable : {REGISTRE_PATH}")
        sys.exit(1)
    with open(REGISTRE_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    topics = {}
    for t in data.get("topics", []):
        topics[int(t["telegram_topic_id"])] = t
    log.info(f"Registre charge : {len(topics)} topic(s) connus")
    return topics

#  --- Sessions telemetry ----------------------------------------------------

def load_sessions():
    """Charge TELEMETRY/sessions.json (local only). Cree vide si absent."""
    if not SESSIONS_FILE.exists():
        return {}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_sessions(sessions):
    """ Persiste l'etat des sessions OpenCode (PID + alive)."""
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)

#  --- OpenCode subprocess ----------------------------------------------------

async def start_opencode_session(topic_config, instruction_initiale=None):
    """Lance une session OpenCode en subprocess async pour le topic donne.
    Retourne le handle (Process) + stocke dans sessions.json.
    """
    dossier_local = topic_config.get("dossier_local")
    if not dossier_local or not Path(dossier_local).exists():
        log.warning(f"dossier_local introuvable : {dossier_local}")

    cmd = ["opencode"]
    if instruction_initiale:
        cmd += ["--prompt", instruction_initiale]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=dossier_local,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )

    sessions = load_sessions()
    sessions[str(topic_config["telegram_topic_id"])] = {
        "pid": proc.pid,
        "alive": True,
        "repo": topic_config["repo"],
        "nom": topic_config["nom"],
        "started_at": asyncio.get_event_loop().time(),
    }
    save_sessions(sessions)
    log.info(f"Session OpenCode demarree pour {topic_config['nom']} (PID {proc.pid})")
    return proc

async def stream_opencode_to_telegram(proc, telegram_send_callable):
    """Boucle qui lit stdout OpenCode et push vers Telegram en streaming.
    Termine quand OpenCode ferme stdout (process mort).
    """
    buffer = b""
    try:
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    await telegram_send_callable(text)
    except asyncio.CancelledError:
        log.info("Stream OpenCode -> Telegram annule")
        raise
    finally:
        # Marquer session comme morte si process termine
        # (a implementer : update sessions.json[topic].alive = false)
        pass

#  --- Telegram handlers -----------------------------------------------------

# TODO : handlers /doctrine, /session, /kill, /statut, /forge
# TODO : handler texte libre -> forward stdin OpenCode
# TODO : handler voice message -> Groq transcription -> forward
# TODO : handler document/photo/video -> download vers dossier_local/SHARED/IN/

def main():
    parser = argparse.ArgumentParser(description="ASTROPATH - Pont Vox Telegram <-> OpenCode")
    parser.add_argument("--doctrine", action="store_true", help="Affiche la doctrine chargee et quitte")
    parser.add_argument("--forge", action="store_true", help="Liste les topics connus et quitte")
    args = parser.parse_args()

    load_dotenv()

    if args.doctrine:
        doctrine = (REPO_ROOT / "DOCTRINE" / "COLD_START.md").read_text(encoding="utf-8")
        print(doctrine[:3000] + ("\n..." if len(doctrine) > 3000 else ""))
        return

    topics = load_registre()

    if args.forge:
        print(f"\n  ASTROPATH - {len(topics)} flotte(s) declaree(s) :\n")
        for tid, cfg in topics.items():
            print(f"  [{tid:>5}]  {cfg['nom']:<14} -> {cfg['repo']}  ({cfg.get('branche','main')})")
        print()
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN manquant dans .env")
        sys.exit(1)

    # Lancement daemon Telegram (a implementer avec python-telegram-bot v20)
    log.error("Daemon Telegram non encore implemente. Squelette Bridge seulement.")
    print("\n  ASTROPATH pret - daemon non encore code.")
    print("  Etat : SQUELETTE. Voir TRACKING/ASTROPATH_CAMPAIGN_LOG.md pour la roadmap.")
    print()

if __name__ == "__main__":
    main()
