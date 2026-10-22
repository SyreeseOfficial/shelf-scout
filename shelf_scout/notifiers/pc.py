"""Local alarm: desktop popup, plus a sound for loud alerts."""
import asyncio
import logging
import shutil
from pathlib import Path

from ..models import Alert
from . import body, title

log = logging.getLogger("shelf_scout.pc")

ALARM = Path(__file__).with_name("alarm.wav")
# First player found wins. Each entry is the command prefix; the sound file is appended.
PLAYERS = [["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]]


async def _run(*cmd: str) -> None:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"{cmd[0]} failed (exit {proc.returncode}): {err.decode().strip()}")


class Pc:
    name = "pc"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def send(self, alert: Alert) -> None:
        jobs = [self._popup(alert)]
        if alert.loud:
            jobs.append(self._sound())
        errors = [r for r in await asyncio.gather(*jobs, return_exceptions=True) if isinstance(r, Exception)]
        if errors:
            raise errors[0]

    async def _popup(self, alert: Alert) -> None:
        if not shutil.which("notify-send"):
            raise RuntimeError("notify-send not found, so no desktop popup. Install libnotify (Arch: sudo pacman -S libnotify)")
        await _run("notify-send", "-u", "critical" if alert.loud else "low", "-a", "shelf-scout",
                   title(alert), body(alert))

    async def _sound(self) -> None:
        for player in PLAYERS:
            if shutil.which(player[0]):
                await _run(*player, str(ALARM))
                return
        raise RuntimeError("no sound player found (looked for paplay, aplay, ffplay), so no alarm sound. Install pipewire-pulse or alsa-utils")
