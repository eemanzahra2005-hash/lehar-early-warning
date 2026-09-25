"""LEHAR's five-level early-warning alert engine (Phase 2).

Module map — each file has one job, so a reader can follow an alert from
threshold to farmer without holding the whole system in their head:

    levels.py     the 5 farmer levels + the admin OPS level: colours, names
                  (EN/UR), farmer actions, channels. Single source of truth.
    rules.py      pure threshold functions. Numbers in, level out. No I/O.
    templates.py  deterministic bilingual message templates. No LLM, ever.
    channels.py   the delivery interface + the in-app channel. Phase 3 adds
                  Telegram and email behind the same interface.
    ops_events.py cross-process breadcrumbs for the OPS rule.
    engine.py     the run: fetch -> evaluate -> dedupe/escalate -> resolve
                  -> deliver -> record.

Nothing here is ever LLM-generated (CLAUDE.md rule 10) and every message
ends with the mandated research-advisory disclaimer (rule 12). See
docs/ALERT_LEVELS.md for the farmer-facing description of the scheme.
"""
