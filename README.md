# shelf-scout

Free, local PS5 Pro stock alerts. See `PRD.md` (what/why) and `BUILD_PLAN.md` (how/order).

## Setup

```
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp settings.example.json settings.json   # optional: defaults work without it
```

## Run

```
.venv/bin/python -m shelf_scout     # Ctrl+C to stop
.venv/bin/pytest
```

(Full setup, troubleshooting and the retailer table arrive in later phases.)
