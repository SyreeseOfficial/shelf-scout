"""Load, validate and save settings.json.

Every key is optional; anything missing falls back to DEFAULTS. Bad values raise
ConfigError with a plain-English message that names the key.
"""
import copy
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

RETAILERS = ["sony", "bestbuy", "amazon", "walmart", "target", "gamestop", "costco"]

# api_key is only used by retailers that have an official API (Best Buy); the rest ignore it.
RETAILER_DEFAULT = {"enabled": True, "interval_seconds": 45, "urls": [], "skus": [], "api_key": ""}

DEFAULTS = {
    "msrp_cents": 89999,
    "tolerance_cents": 5000,
    "repeat_seconds": 60,
    "no_poll_alert_minutes": 10,
    "quiet_hours_loud_override": False,
    "zip": "98036",
    "radius_miles": 10,
    "quiet_hours": [],
    "retailers": {name: copy.deepcopy(RETAILER_DEFAULT) for name in RETAILERS},
    "channels": {
        "ntfy": {"enabled": True, "server": "https://ntfy.sh", "alert_topic": "", "ack_topic": ""},
        "discord": {"enabled": False, "webhook_url": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "sms": {"enabled": False, "gateway_address": "", "smtp_host": "smtp.gmail.com",
                "smtp_user": "", "smtp_password": ""},
        "pc": {"enabled": True},
    },
    "feeds": [],
    "dashboard": {"host": "127.0.0.1", "port": 8765},
}
# Sony's PS5 Pro 2TB (found via direct.playstation.com; see pollers/sony.py for how to re-find it).
# Set "urls"/"skus" in settings.json to replace these. urls[i] is the link shown for skus[i].
DEFAULTS["retailers"]["sony"].update(
    urls=["https://direct.playstation.com/en-us/buy-consoles/playstation5-pro-console-2-tb"], skus=["1000050928"])

# Smallest allowed value for numeric keys (stops a typo from hammering a retailer or spamming the phone).
MINIMUMS = {"repeat_seconds": 10, "interval_seconds": 10, "no_poll_alert_minutes": 1, "port": 1}
_TYPE_NAMES = {bool: "true or false", int: "a whole number", str: "text", list: "a list"}


class ConfigError(Exception):
    pass


def _fail(key, problem, default=None):
    hint = f" Fix it in settings.json, or delete the key to use the default ({default!r})." if default is not None else ""
    raise ConfigError(f'settings.json: "{key}" {problem}.{hint}')


def _merge(default, user, path):
    """Overlay `user` on `default`, checking each value's type against the default's."""
    if isinstance(default, dict):
        if not isinstance(user, dict):
            _fail(path, f"must be an object {{...}} (got {user!r})")
        out = copy.deepcopy(default)
        for k, v in user.items():
            key = f"{path}.{k}" if path else k
            if k in default:
                out[k] = _merge(default[k], v, key)
            elif path == "retailers":  # any retailer name is allowed; it gets the retailer defaults
                out[k] = _merge(RETAILER_DEFAULT, v, key)
            else:
                _fail(key, "is not a known setting (typo?)")
        return out
    # bool is a subclass of int, so check it explicitly in both directions.
    want = type(default)
    ok = isinstance(user, want) and (want is bool or not isinstance(user, bool))
    if not ok:
        _fail(path, f"must be {_TYPE_NAMES[want]} (got {user!r})", default)
    leaf = path.rsplit(".", 1)[-1]
    if leaf in MINIMUMS and user < MINIMUMS[leaf]:
        _fail(path, f"must be at least {MINIMUMS[leaf]} (got {user})", default)
    return user


def _check_quiet_hours(items):
    for i, q in enumerate(items):
        key = f"quiet_hours[{i}]"
        if not isinstance(q, dict):
            _fail(key, 'must look like {"days": [0,1,2], "start": "23:00", "end": "07:00", "mode": "mute"}')
        days = q.get("days")
        if not (isinstance(days, list) and days and all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days)):
            _fail(f"{key}.days", "must be a list of day numbers 0-6 (0 = Monday)")
        for field in ("start", "end"):
            v = q.get(field)
            if not (isinstance(v, str) and re.fullmatch(r"\d\d:\d\d", v)):
                _fail(f"{key}.{field}", f'must be a 24-hour time like "23:00" (got {v!r})')
            try:
                datetime.strptime(v, "%H:%M")
            except ValueError:
                _fail(f"{key}.{field}", f'is not a real time (got {v!r})')
        if q.get("mode") not in ("mute", "downgrade"):
            _fail(f"{key}.mode", f'must be "mute" or "downgrade" (got {q.get("mode")!r})')


def validate(user: dict) -> dict:
    """Return DEFAULTS overlaid with `user`, or raise ConfigError."""
    settings = _merge(DEFAULTS, user, "")
    _check_quiet_hours(settings["quiet_hours"])
    return settings


def load(path: Path) -> dict:
    """Missing file = all defaults. Unreadable or invalid file = ConfigError."""
    if not path.exists():
        return validate({})
    try:
        user = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"settings.json isn't valid JSON: {e.msg} at line {e.lineno}, column {e.colno}. "
                          "Check for a missing comma or quote near there.") from e
    return validate(user)


def save(path: Path, settings: dict) -> None:
    """Validate, then write to a temp file and rename so a crash can't leave half a file."""
    validate(settings)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def cap_cents(settings: dict) -> int:
    """Highest price that still counts as a loud (at-or-near MSRP) alert."""
    return settings["msrp_cents"] + settings["tolerance_cents"]
