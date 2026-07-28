"""
bridge.py - ASTROPATH : Pont Vox Telegram <-> OpenCode CLI
==========================================================
Daemon unique. Charge DOCTRINE/registre_topics.yml au demarrage.
Forward les messages Telegram vers OpenCode (opencode run --dir <dossier> -c "<msg>").
Forward les voice messages via transcription Groq Whisper.
Forward les medias vers dossier_local/SHARED/IN/ du projet cible.
NE TOUCHE JAMAIS aux repos GitHub cibles (zero gh api direct).

Doctrine :
    - 1 topic Telegram = 1 dossier_local = 1 session OpenCode (continue)
    - ASTROPATH ne stocke aucun contexte metier. La memoire vit dans le repo cible
      (CAMPAIGN_LOG + code + Git), pas dans le bot.
    - OpenCode herite de `gh auth login` deja configure sur la machine.
    - Aucun PAT GitHub dans le .env du bot.

Usage:
    python bridge.py                 # lance le daemon Telegram
    python bridge.py --doctrine      # affiche la doctrine chargee
    python bridge.py --forge         # liste les topics connus
    python bridge.py --check         # verifie l'env (token, groq, opencode, python)

Variables d'environnement requises (.env) :
    TELEGRAM_BOT_TOKEN   - token donne par @BotFather
    GROQ_API_KEY         - cle pour transcription vocale (https://console.groq.com)
    OPENCODE_TIMEOUT     - timeout opencode run en secondes (default 600)
    OPENCODE_BIN         - chemin absolu vers opencode (default: cherche dans PATH)
    GROUP_ID             - ID du groupe Telegram avec topics (obligatoire pour filtrer)
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import contextlib
from pathlib import Path

from dotenv import load_dotenv

#  --- Configuration ----------------------------------------------------------

REPO_ROOT = Path(__file__).parent.resolve()
REGISTRE_PATH = REPO_ROOT / "DOCTRINE" / "registre_topics.yml"
TELEMETRY_DIR = REPO_ROOT / "TELEMETRY"
SESSIONS_FILE = TELEMETRY_DIR / "sessions.json"
LOG_FILE = TELEMETRY_DIR / "astropath.log"
SHARED_IN_SUBDIR = "SHARED/IN"
AUDIO_TMP_DIR = REPO_ROOT / "audio_tmp"

OPENCODE_TIMEOUT = int(os.getenv("OPENCODE_TIMEOUT", "600"))
OPENCODE_BIN = os.getenv("OPENCODE_BIN") or shutil.which("opencode") or "opencode"

#  --- Logging ----------------------------------------------------------------

TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_TMP_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("astropath")


#  --- Registre topics -------------------------------------------------------

def load_registre():
    """Charge DOCTRINE/registre_topics.yml et retourne le mapping topic_id -> config."""
    import yaml
    if not REGISTRE_PATH.exists():
        log.error(f"Registre introuvable : {REGISTRE_PATH}")
        sys.exit(1)
    with open(REGISTRE_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    topics = {}
    for t in data.get("topics", []) or []:
        topics[int(t["telegram_topic_id"])] = t
    log.info(f"Registre charge : {len(topics)} topic(s) connu(s)")
    return topics


#  --- Sessions telemetry ----------------------------------------------------
# Minimal : juste pour /statut et /kill. Le vrai contexte vit chez OpenCode.

def load_sessions():
    if not SESSIONS_FILE.exists():
        return {}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_sessions(sessions):
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


#  --- OpenCode invocation ---------------------------------------------------

def _opencode_cmd(dossier_local, message, continue_session=True, attach_files=None):
    """Construit la commande `opencode run` alignee sur la doctrine."""
    cmd = [OPENCODE_BIN, "run"]
    if continue_session:
        cmd.append("-c")
    cmd += ["--dir", str(dossier_local)]
    if attach_files:
        for fp in attach_files:
            cmd += ["-f", str(fp)]
    cmd.append(message)
    return cmd


async def run_opencode(dossier_local, message, continue_session=True, attach_files=None):
    """Appelle `opencode run` en subprocess async. Capture stdout et le retourne
    comme texte. NE TOUCHE PAS a Telegram : l'appelant dispatche la reponse.
    """
    cmd = _opencode_cmd(dossier_local, message, continue_session, attach_files)
    log.info(f"opencode run (dir={dossier_local}, continue={continue_session}, "
             f"files={len(attach_files or [])}, msg_len={len(message)})")
    log.debug(f"cmd: {' '.join(cmd)!r}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=dossier_local,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=OPENCODE_TIMEOUT
        )
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        log.error(f"opencode timeout ({OPENCODE_TIMEOUT}s) - killed")
        return (f"⏱️ OpenCode a depasse le timeout de {OPENCODE_TIMEOUT}s. "
                f"Session probablement morte. Tape /kill puis /session pour relancer.")

    out = stdout_b.decode("utf-8", errors="replace").strip()
    err = stderr_b.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        log.error(f"opencode exit={proc.returncode} stderr={err[:500]}")
        return f"❌ OpenCode exit code {proc.returncode}\n```\n{err[-2000:]}\n```"
    if not out and err:
        return f"⚠️ stdout vide, stderr :\n```\n{err[-2000:]}\n```"
    return out or "(OpenCode n'a rien retourne)"


#  --- Voice transcription (Groq Whisper) ------------------------------------

async def transcribe_voice(ogg_path):
    """Transcrit un fichier audio .ogg via Groq Whisper API. Retourne le texte."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None, "GROQ_API_KEY manquant dans .env - transcription vocale desactivee."

    import urllib.request

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    boundary = "astropath-boundary"
    body = bytearray()
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
    body += b"whisper-large-v3\r\n"
    body += f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="file"; '
             f'filename="{Path(ogg_path).name}"\r\n').encode()
    body += b"Content-Type: audio/ogg\r\n\r\n"
    with open(ogg_path, "rb") as f:
        body += f.read()
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    try:
        # groq calls sont bloquants -> on les lance dans un executor
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=60))
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("text", "").strip(), None
    except Exception as e:
        return None, f"Transcription Groq echouee : {e}"


#  --- Telegram bot (python-telegram-bot v20) --------------------------------

async def _send(bot, chat_id, message_thread_id, text):
    """Envoie un message dans un topic. Chunks si trop long (limite Telegram 4096)."""
    if not text:
        return
    max_len = 4000  # marge avec le formatage
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                message_thread_id=message_thread_id,
                parse_mode=None,  # on garde brut pour eviter les soucis de balises
            )
        except Exception as e:
            log.error(f"envoi Telegram echoue : {e}")
            return
        if len(chunks) > 1:
            await asyncio.sleep(0.3)


def _resolve_topic(update, topics):
    """Retourne la config topic associee au message, ou None si hors scope.
    Filtre strict : on ne reagit qu'aux messages d'un topic declare dans le registre.
    """
    msg = update.effective_message
    if msg is None:
        return None
    thread_id = msg.message_thread_id
    if thread_id is None:
        # message general (hors topic) dans un groupe avec topics -> on ignore
        return None
    return topics.get(int(thread_id))


async def cmd_session(update, context, topics, sessions):
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    dossier_local = cfg.get("dossier_local")
    if not dossier_local or not Path(dossier_local).exists():
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"],
                    f"❌ dossier_local introuvable : {dossier_local}")
        return

    await update.message.reply_text(
        f"📡 Ouverture d'une session OpenCode pour *{cfg['nom']}*...",
        parse_mode=None,
    )

    instruction = (
        f"Tu es ASTROPATH-Relay. L'operateur vient de lancer la session. "
        f"Va sur le depot {cfg['repo']}, lis le fichier "
        f"{cfg['campaign_log']} (et son COLD_START.md si present), "
        f"regarde ou on en etait, et resume la situation a l'operateur en 5 lignes max. "
        f"Attends ensuite ses instructions."
    )

    # On lance en mode nouvelle session (pas -c) pour la commande /session
    response = await run_opencode(dossier_local, instruction, continue_session=False)

    sessions[str(cfg["telegram_topic_id"])] = {
        "alive": True,
        "repo": cfg["repo"],
        "nom": cfg["nom"],
        "last_pid_seen": None,
    }
    save_sessions(sessions)

    await _send(context.bot, update.effective_chat.id,
                cfg["telegram_topic_id"], response)


async def cmd_doctrine(update, context, topics):
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    dossier_local = cfg.get("dossier_local")
    if not dossier_local or not Path(dossier_local).exists():
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"],
                    f"❌ dossier_local introuvable : {dossier_local}")
        return

    instruction = (
        f"L'operateur demande doctrine. Va lire {cfg['campaign_log']} sur le depot "
        f"{cfg['repo']} (-c pour reprendre la session precedente), et reprends le travail "
        f"la ou on en etait. Resigne le campaign_log si besoin via gh/git."
    )
    response = await run_opencode(dossier_local, instruction, continue_session=True)
    await _send(context.bot, update.effective_chat.id,
                cfg["telegram_topic_id"], response)


async def cmd_kill(update, context, topics, sessions):
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    tid = str(cfg["telegram_topic_id"])
    if tid in sessions:
        sessions[tid]["alive"] = False
        save_sessions(sessions)
        await update.message.reply_text("🗡️ Session marquee morte. "
                                        "Prochain message relancera une nouvelle session.")
    else:
        await update.message.reply_text("Rien a tuer : aucune session trackee pour ce topic.")


async def cmd_statut(update, context, topics, sessions):
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    tid = str(cfg["telegram_topic_id"])
    s = sessions.get(tid)
    if not s:
        await update.message.reply_text(f"❓ Aucune session trackee pour {cfg['nom']}.")
        return
    alive = "✅ vivante" if s.get("alive") else "💀 morte"
    await update.message.reply_text(
        f"*{cfg['nom']}*\nSession : {alive}\nRepo : {s.get('repo')}\n"
        f"Last seen : {s.get('last_pid_seen', 'n/a')}",
        parse_mode=None,
    )


async def cmd_forge(update, context, topics):
    lines = [f"⚓ ASTROPATH - {len(topics)} flotte(s) declaree(s) :\n"]
    for tid, cfg in topics.items():
        lines.append(f"  • [{tid:>5}]  {cfg['nom']:<14} -> {cfg['repo']}")
    await update.message.reply_text("\n".join(lines))


async def on_text(update, context, topics, sessions):
    """Handler texte libre : forward vers OpenCode en mode continue."""
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    text = update.effective_message.text
    if not text or text.startswith("/"):
        return

    dossier_local = cfg.get("dossier_local")
    if not dossier_local or not Path(dossier_local).exists():
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"],
                    f"❌ dossier_local introuvable : {dossier_local}")
        return

    tid = str(cfg["telegram_topic_id"])
    # Si on n'a pas de session trackee, on en demarre une nouvelle
    continue_session = bool(sessions.get(tid, {}).get("alive"))
    response = await run_opencode(dossier_local, text, continue_session=continue_session)

    # Marquer vivant apres reussite
    if tid not in sessions:
        sessions[tid] = {}
    sessions[tid].update({
        "alive": True,
        "repo": cfg["repo"],
        "nom": cfg["nom"],
    })
    save_sessions(sessions)

    await _send(context.bot, update.effective_chat.id,
                cfg["telegram_topic_id"], response)


async def on_voice(update, context, topics, sessions):
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    dossier_local = cfg.get("dossier_local")
    if not dossier_local or not Path(dossier_local).exists():
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"],
                    f"❌ dossier_local introuvable : {dossier_local}")
        return

    voice = update.effective_message.voice or update.effective_message.audio
    if not voice:
        return

    await update.message.reply_text("🎙️ Reception audio, transcription en cours...")

    # Download Telegram -> tmp
    tmp_ogg = AUDIO_TMP_DIR / f"voice_{update.update_id}.ogg"
    tg_file = await voice.get_file()
    await tg_file.download_to_drive(str(tmp_ogg))
    log.info(f"audio downloaded : {tmp_ogg}")

    # Transcription
    text, err = await transcribe_voice(tmp_ogg)
    try:
        tmp_ogg.unlink()
    except Exception:
        pass

    if err:
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"], f"❌ {err}")
        return
    if not text:
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"], "❌ transcription vide")
        return

    await _send(context.bot, update.effective_chat.id,
                cfg["telegram_topic_id"], f"🎙️ *Transcrit* :\n{text}",
                )

    # Et on forward a OpenCode
    tid = str(cfg["telegram_topic_id"])
    continue_session = bool(sessions.get(tid, {}).get("alive"))
    response = await run_opencode(dossier_local, text, continue_session=continue_session)
    sessions[tid] = sessions.get(tid, {})
    sessions[tid].update({"alive": True, "repo": cfg["repo"], "nom": cfg["nom"]})
    save_sessions(sessions)
    await _send(context.bot, update.effective_chat.id,
                cfg["telegram_topic_id"], response)


async def on_document(update, context, topics):
    """Download media -> dossier_local/SHARED/IN/ puis notifie. Pas d'OpenCode."""
    cfg = _resolve_topic(update, topics)
    if not cfg:
        return
    dossier_local = cfg.get("dossier_local")
    if not dossier_local or not Path(dossier_local).exists():
        await _send(context.bot, update.effective_chat.id,
                    cfg["telegram_topic_id"],
                    f"❌ dossier_local introuvable : {dossier_local}")
        return

    doc = update.effective_message.document or update.effective_message.photo
    if not doc:
        return
    if isinstance(doc, list):  # photos = liste de sizes
        doc = doc[-1]

    in_dir = Path(dossier_local) / SHARED_IN_SUBDIR
    in_dir.mkdir(parents=True, exist_ok=True)
    tg_file = await doc.get_file()
    filename = getattr(doc, "file_name", None) or f"media_{update.update_id}"
    dest = in_dir / filename
    await tg_file.download_to_drive(str(dest))
    rel = dest.relative_to(dossier_local)
    await _send(context.bot, update.effective_chat.id,
                cfg["telegram_topic_id"],
                f"📥 Media depose : {rel}\nDispo pour OpenCode dans ce dossier.")


#  --- Dispatcher ------------------------------------------------------------

def build_app(topics, sessions):
    """Construit l'Application python-telegram-bot avec handlers wires."""
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        filters,
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN manquant dans .env")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()

    # Handlers commandes
    app.add_handler(CommandHandler("session",
        lambda u, c: _wrap(cmd_session, u, c, topics, sessions)))
    app.add_handler(CommandHandler("doctrine",
        lambda u, c: _wrap(cmd_doctrine, u, c, topics)))
    app.add_handler(CommandHandler("kill",
        lambda u, c: _wrap(cmd_kill, u, c, topics, sessions)))
    app.add_handler(CommandHandler("statut",
        lambda u, c: _wrap(cmd_statut, u, c, topics, sessions)))
    app.add_handler(CommandHandler("forge",
        lambda u, c: _wrap(cmd_forge, u, c, topics)))

    # Texte libre (hors commandes)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda u, c: _wrap(on_text, u, c, topics, sessions)))

    # Voice / audio
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO,
        lambda u, c: _wrap(on_voice, u, c, topics, sessions)))

    # Documents / photos
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO,
        lambda u, c: _wrap(on_document, u, c, topics)))

    return app


async def _wrap(coro_func, update, context, *args, **kwargs):
    """Wrappe les handlers pour avaler les exceptions sans crasher le bot."""
    try:
        await coro_func(update, context, *args, **kwargs)
    except Exception as e:
        log.exception(f"Handler {coro_func.__name__} crash : {e}")
        try:
            await update.effective_message.reply_text(
                f"💥 ASTROPATH erreur interne : {e.__class__.__name__}"
            )
        except Exception:
            pass


#  --- CLI helpers -----------------------------------------------------------

def cmd_check():
    """Verifie l'env de lancement."""
    print("\n  ASTROPATH -- check environnement\n" + "  " + "-" * 40)
    ok = True

    # Python
    print(f"  Python : {sys.version.split()[0]}")

    # Dependencies
    for mod in ("dotenv", "yaml", "telegram"):
        try:
            __import__(mod)
            print(f"  [{mod}] OK")
        except ImportError as e:
            print(f"  [{mod}] MANQUANT - pip install -r requirements.txt  ({e})")
            ok = False

    # Token
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    print(f"  TELEGRAM_BOT_TOKEN : {'set' if token else 'MANQUANT'}")
    if not token:
        ok = False

    # Groq
    groq = os.getenv("GROQ_API_KEY")
    print(f"  GROQ_API_KEY : {'set' if groq else 'MANQUANT (voix desactivee)'}")

    # opencode
    print(f"  OPENCODE_BIN : {OPENCODE_BIN}")
    # Cherche opencode.cmd sous Windows si jamais il n'est pas resolu correctement
    if not shutil.which(OPENCODE_BIN) and os.name == "nt":
        opencode_cmd = shutil.which("opencode.cmd")
        print(f"    (opencode.cmd trouve : {opencode_cmd})")

    # Registre
    if REGISTRE_PATH.exists():
        topics = load_registre()
        print(f"  Registre : {len(topics)} topic(s)")
        for tid, cfg in topics.items():
            dl = cfg.get("dossier_local")
            exists = Path(dl).exists() if dl else False
            mark = "OK" if exists else "MANQUANT"
            print(f"    [{tid}] {cfg['nom']:<12} dossier_local: {mark}")
            if not exists:
                ok = False
    else:
        print("  Registre : MANQUANT")
        ok = False

    print("  " + "-" * 40)
    print("  Statut : " + ("PRET" if ok else "INCOMPLET"))
    print()
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(
        description="ASTROPATH - Pont Vox Telegram <-> OpenCode")
    parser.add_argument("--doctrine", action="store_true",
                        help="Affiche la doctrine chargee et quitte")
    parser.add_argument("--forge", action="store_true",
                        help="Liste les topics connus et quitte")
    parser.add_argument("--check", action="store_true",
                        help="Verifie l'environnement et quitte")
    args = parser.parse_args()

    load_dotenv()

    if args.check:
        sys.exit(cmd_check())

    topics = load_registre()

    if args.forge:
        print(f"\n  ASTROPATH - {len(topics)} flotte(s) declaree(s) :\n")
        for tid, cfg in topics.items():
            print(f"  [{tid:>5}]  {cfg['nom']:<14} -> {cfg['repo']}  "
                  f"({cfg.get('branche','main')})")
        print()
        return

    if args.doctrine:
        doctrine = (REPO_ROOT / "DOCTRINE" / "COLD_START.md").read_text(encoding="utf-8")
        print(doctrine[:3000] + ("\n..." if len(doctrine) > 3000 else ""))
        return

    # Pre-flight check leger
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN manquant dans .env (lance `python bridge.py --check`)")
        sys.exit(1)

    if not topics:
        log.error("Registre vide : ajoute au moins un topic dans DOCTRINE/registre_topics.yml")
        sys.exit(1)

    # Verif que tous les dossier_local existent
    for tid, cfg in topics.items():
        dl = cfg.get("dossier_local")
        if not dl or not Path(dl).exists():
            log.warning(f"dossier_local introuvable pour {cfg['nom']} : {dl} "
                        f"(les messages sur ce topic echoueront)")

    sessions = load_sessions()
    app = build_app(topics, sessions)

    log.info(f"ASTROPATH en ecoute - {len(topics)} topic(s) - timeout={OPENCODE_TIMEOUT}s")
    print(f"\n  ASTROPATH lance. {len(topics)} topic(s) declare(s). "
          f"Timeout OpenCode : {OPENCODE_TIMEOUT}s\n  Ctrl-C pour stopper.\n")

    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
