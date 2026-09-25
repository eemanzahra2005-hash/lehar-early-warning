"""LEHAR Phase 2.5 — the flood LEAD-TIME model.

The idea, in one sentence: like a tsunami early warning, predict the river
discharge 1-3 days AHEAD per district, so an alert can fire BEFORE the water
arrives rather than while it is arriving.

This package is deliberately split so that the SERVING path never needs
PyTorch (CLAUDE.md rule 11 — the deployed API lives inside a 512 MB ceiling):

    features.py   pure numpy feature construction + the window/horizon
                  constants. Imported by BOTH training and the API.
    dataset.py    builds the training/validation/test windows out of the
                  real Parquet history, with per-district normalisation.
                  numpy/pandas only — no torch.
    registry.py   the versioned model registry for this model family.
                  Plain JSON — no torch.
    model.py      the GRU itself.                     ** imports torch **
    train.py      the training run + the real metrics.** imports torch **
    export.py     ONNX + normalisation JSON export.   ** imports torch **

Nothing in this package's __init__ imports anything, so
`from ml.flood_dl.features import ...` on the API path costs a module import
and nothing else. `backend/tests/test_no_heavy_imports.py` asserts that a
served request never pulls `torch` into sys.modules, and torch is installed
in the local venv precisely so that assertion is a real test rather than a
vacuous one.

Training data is REAL (GloFAS river discharge + ERA5 weather via Open-Meteo,
downloaded by scripts/data/fetch_flood_history.py) — unlike the irrigation
RandomForest, which stays synthetic. See docs/FLOOD_DL.md.
"""
