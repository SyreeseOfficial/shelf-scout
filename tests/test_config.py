import json

import pytest

from shelf_scout import config


def test_defaults_when_file_missing(tmp_path):
    s = config.load(tmp_path / "settings.json")
    assert s["msrp_cents"] == 89999
    assert config.cap_cents(s) == 94999
    assert s["retailers"]["bestbuy"]["interval_seconds"] == 45


def test_partial_file_overlays_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"tolerance_cents": 0, "channels": {"ntfy": {"alert_topic": "abc"}}}))
    s = config.load(p)
    assert config.cap_cents(s) == 89999
    assert s["channels"]["ntfy"]["alert_topic"] == "abc"
    assert s["channels"]["ntfy"]["server"] == "https://ntfy.sh"  # untouched sibling keeps default


@pytest.mark.parametrize("bad, key", [
    ({"tolerance_cents": "abc"}, "tolerance_cents"),
    ({"tolerance_cents": True}, "tolerance_cents"),
    ({"channels": {"pc": {"enabled": "yes"}}}, "channels.pc.enabled"),
    ({"retailers": {"bestbuy": {"interval_seconds": 1}}}, "retailers.bestbuy.interval_seconds"),
    ({"tolerence_cents": 1}, "tolerence_cents"),
    ({"quiet_hours": [{"days": [0], "start": "25:00", "end": "07:00", "mode": "mute"}]}, "quiet_hours[0].start"),
    ({"quiet_hours": [{"days": [0], "start": "23:00", "end": "07:00", "mode": "silence"}]}, "quiet_hours[0].mode"),
])
def test_validation_names_the_bad_key(tmp_path, bad, key):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(config.ConfigError, match=key.replace("[", r"\[").replace("]", r"\]")):
        config.load(p)


def test_invalid_json_is_plain_english(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"msrp_cents": 1,}')
    with pytest.raises(config.ConfigError, match="isn't valid JSON"):
        config.load(p)


def test_unknown_retailer_gets_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"retailers": {"newegg": {"enabled": False}}}))
    assert config.load(p)["retailers"]["newegg"]["interval_seconds"] == 45


def test_atomic_save_roundtrip_and_no_leftovers(tmp_path):
    p = tmp_path / "settings.json"
    s = config.load(p)
    s["tolerance_cents"] = 1234
    config.save(p, s)
    assert config.load(p)["tolerance_cents"] == 1234
    assert [f.name for f in tmp_path.iterdir()] == ["settings.json"]


def test_save_rejects_invalid_and_keeps_old_file(tmp_path):
    p = tmp_path / "settings.json"
    config.save(p, config.load(p))
    before = p.read_text()
    with pytest.raises(config.ConfigError):
        config.save(p, {"msrp_cents": "x"})
    assert p.read_text() == before
    assert [f.name for f in tmp_path.iterdir()] == ["settings.json"]
