# CLAUDE.md — Permanent Project Rules

This file defines the **permanent rules** for working on **LEHAR — Level-based
Early-warning for Hydrological & Agricultural Risk**. These rules apply to every
future session and every phase of the project. Read this file before making
changes.

## Project summary

LEHAR is an early-warning and irrigation advisory system for Pakistan's 107
districts: a research-grade web application that issues five-level, rule-based
hydrological and agricultural risk alerts, provides daily irrigation decision
support, and doubles as an MLOps learning/demo platform.

LEHAR is a research project by Syeda Eeman Zahra. Alongside irrigation
decision support it provides a five-level, multi-channel early-warning system,
a separate console, and a zero-cost split cloud deployment.

- Backend: Python FastAPI
- ML: scikit-learn (RandomForest to start)
- Database: SQLite locally, PostgreSQL (Neon) in the deployed stack
- Frontend: vanilla HTML/CSS/JS (no React, no build step) in `frontend/`; the
  Next.js Early-Warning Console lives in this repo under `console/`
- Containerization: Docker / docker compose
- Alerts: rule-based, deterministic, auditable — never LLM-generated

## Permanent rules (do not violate)

1. **Extend, never rewrite working code.** Never delete working features or
   passing tests. Additive changes are preferred over rewrites. If something
   must be replaced, confirm with the user first.

2. **Tests must pass before a phase is considered done.** After every change
   set, run:

   ```
   .venv\Scripts\python -m pytest backend\tests -q
   ```

   A phase is not complete until all tests pass.

3. **All configuration via environment variables.** Use a `.env` file (never
   committed) loaded through `backend/app/config.py`. Never hard-code secrets,
   API keys, or environment-specific values. Keep `backend/.env.example` up to
   date with every new variable that is introduced.

4. **All data is SYNTHETIC.** Every dataset in this project is
   synthetic/research data generated for demonstration purposes. It must be
   clearly labeled as synthetic in the UI and in documentation. Never fabricate
   ML metrics, evaluation results, or monitoring data — real computed numbers
   only, even on synthetic data.

5. **Everything runs locally first.** The full stack must always be runnable
   end-to-end on the local machine via Docker Compose or the no-Docker
   fallback, with no cloud service required. The deployed stack in rule 11 is
   an addition to local-first operation, never a replacement for it. If a
   change makes the app unrunnable offline, it violates this rule.

6. **ML model versioning.** Trained models are saved under
   `backend/ml/model/<version>/` with a `registry.json` file that tracks a
   `"latest"` pointer. Never overwrite an existing version directory — always
   create a new version.

7. **Frontend stays vanilla HTML/CSS/JS.** No React, Vue, or any framework
   requiring a build step. Any third-party JS/CSS libraries must be vendored
   locally into `frontend/vendor/` — no CDN dependency, so the app works fully
   offline. This rule governs everything in `frontend/`; the Next.js
   Early-Warning Console in `console/` (LEHAR Phase 5, deployed on Vercel with
   Root Directory = `console`) is explicitly out of its scope.

8. **Pin exact dependency versions.** `backend/requirements.txt` and
   `backend/requirements-dev.txt` must pin exact versions (`==`), compatible
   with Python 3.14.

9. **Keep code simple, commented, and understandable.** This is a student
   research project. Prefer clarity over cleverness. Add comments explaining
   *why*, not *what*.

10. **Alerts are rule-based, deterministic and auditable — never
    LLM-generated.** Every alert level, threshold, escalation, dedupe decision
    and all-clear must come from explicit rules in code that a reader can trace
    from input to output, and that produce the same alert every time for the
    same inputs. An LLM may help a user *read* an alert (summarise, translate,
    answer questions about it), but must never decide whether one fires, what
    level it is, or what it says. No alert text is ever model-generated.

11. **Target deployment is a split, free stack.** Next.js console on Vercel,
    this FastAPI backend on Render free (512 MB RAM), PostgreSQL on Neon. Keep
    memory low — every dependency, eager import, cache and worker count is
    weighed against the 512 MB ceiling before it is added. **Never add a paid
    service.** If a feature can only be built on a paid tier, stop and raise it
    with the user instead of adding the dependency.

12. **Every alert and flood view carries the disclaimer** "Research advisory —
    NDMA/PMD/PDMA official warnings are authoritative". This applies to every
    surface a user can see an alert or flood state on: API responses, the
    console, the local frontend, Telegram and email messages, and exported
    reports. LEHAR is a research advisory, never an official warning, and must
    never present itself as one.

13. **Synthetic training data stays labelled as synthetic.** Every dataset,
    model card, report, evaluation output, API response and UI surface derived
    from synthetic data must say so, in the shipped artifact itself and not
    only in the documentation. Reinforces rule 4: labelling travels with the
    data wherever it goes.

## Environment

- OS: Windows, shell: cmd / PowerShell
- Python: 3.14
- Virtual environment: `.venv` at the project root
- Run tests: `.venv\Scripts\python -m pytest backend\tests -q`
- Run dev server: `.venv\Scripts\uvicorn app.main:app --reload --app-dir backend`
- One-click local start: `START.bat` (Docker, with automatic no-Docker fallback)

## Project structure

```
LEHAR/
├── CLAUDE.md
├── PROGRESS.md              # LEHAR's live phase checklist
├── README.md
├── ARCHITECTURE.md
├── START.bat / STOP.bat / STARTUP-NO-DOCKER.bat / start.sh
├── docker-compose.yml
├── render.yaml              # lehar-api + lehar-db
├── backend/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── .env.example
│   ├── app/                 # config, db, auth, middleware, routers/, services/
│   ├── ml/                  # districts, generate_data, pipeline, model/<version>/
│   └── tests/
├── frontend/                # vanilla HTML/CSS/JS + vendor/ (no CDN)
├── console/                 # Next.js Early-Warning Console (Vercel Root Directory)
├── docs/                    # feature, deployment and MLOps documentation
├── monitoring/              # Prometheus + provisioned Grafana
├── scripts/
└── data/
```

## Phase tracking

See `PROGRESS.md` for the LEHAR phase checklist and current status. Update it
as phases complete.
