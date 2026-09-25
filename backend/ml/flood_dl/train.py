"""Train and honestly evaluate the flood lead-time model (LEHAR Phase 2.5).

    .venv\\Scripts\\python backend\\ml\\flood_dl\\train.py
    .venv\\Scripts\\python backend\\ml\\flood_dl\\train.py --epochs 3 --register

** imports torch ** — training only. The API never imports this module.

What "honestly evaluate" means here, because it is the whole point of the
phase (CLAUDE.md rule 4):

1. Every number written to metrics.json is computed on the held-out TEST
   split (issue day in 2024 or later), which the model never saw and whose
   days did not contribute to the normalisation statistics either.

2. Every number is reported side by side with a PERSISTENCE baseline -
   "tomorrow's discharge equals today's". Persistence is not a strawman: on
   a daily river series it is genuinely hard to beat at D+1, and if this
   model does not beat it, metrics.json will say so in plain numbers and so
   will docs/FLOOD_DL.md. A model that loses to persistence is a finding,
   not a failure to hide.

3. Accuracy is reported twice, in two spaces, because one alone would
   mislead:
     - log space (what the model optimises): scale-free, so a Karakoram
       torrent and a desert wadi contribute comparably.
     - m3/s (what a hydrologist reads): dominated by the biggest rivers,
       which is sometimes exactly what you want to know.

4. The number that actually matters for an EARLY-WARNING system is not MAE.
   It is: of the days that really were flood-level days, how many did the
   model flag at least 24 hours ahead - and how often did it cry wolf? That
   is the level-hit-rate block, computed through the SAME
   forecast_flood_index() and evaluate_flood_forecast() the API and the
   alert engine use, so the offline claim and the online behaviour cannot
   drift apart.
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import torch  # noqa: E402
from torch import nn  # noqa: E402

from ml.districts import DISTRICTS  # noqa: E402
from ml.flood_dl import registry as flood_dl_registry  # noqa: E402
from ml.flood_dl.dataset import (  # noqa: E402
    DEFAULT_HISTORY_DIR,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
    TEST_START_YEAR,
    TRAIN_END_YEAR,
    VAL_YEAR,
    build_dataset,
)
from ml.flood_dl.features import HORIZONS, WINDOW_DAYS, predictions_to_m3s  # noqa: E402
from ml.flood_dl.model import FloodLeadTimeGRU  # noqa: E402

DEFAULT_SEED = 20260924
DEFAULT_EPOCHS = 30
DEFAULT_BATCH_SIZE = 512
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_PATIENCE = 4

# The alert level at or above which a day counts as a "flood-level day" for
# the hit-rate measurement. 3 = the Flood Risk Index's HIGH band = LEHAR's
# red Warning level (docs/ALERT_LEVELS.md).
EVENT_LEVEL = 3


def set_seeds(seed: int) -> None:
    """Fixed seeds everywhere, so a rerun reproduces these numbers."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


# --- metrics ------------------------------------------------------------


def _nse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Nash-Sutcliffe efficiency: 1.0 is perfect, 0.0 is "no better than
    always predicting the mean", negative is worse than that. The standard
    hydrological skill score, which is why it is here alongside MAE."""
    denominator = float(np.sum((actual - np.mean(actual)) ** 2))
    if denominator <= 0.0:
        return float("nan")
    return float(1.0 - np.sum((actual - predicted) ** 2) / denominator)


def _error_block(actual: np.ndarray, predicted: np.ndarray) -> dict:
    residual = predicted - actual
    return {
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "nse": _nse(actual, predicted),
    }


def horizon_metrics(actual_m3s: np.ndarray, predicted_m3s: np.ndarray) -> dict:
    """Per-horizon errors in both spaces. Arrays are (N, len(HORIZONS))."""
    out = {}
    for index, horizon in enumerate(HORIZONS):
        actual = actual_m3s[:, index]
        predicted = predicted_m3s[:, index]
        out[f"D+{horizon}"] = {
            "m3s": _error_block(actual, predicted),
            "log": _error_block(np.log1p(actual), np.log1p(np.maximum(predicted, 0.0))),
        }
    return out


# --- the run ------------------------------------------------------------


def iterate_batches(starts: np.ndarray, batch_size: int, generator: np.random.Generator | None = None):
    order = np.arange(len(starts))
    if generator is not None:
        generator.shuffle(order)
    for begin in range(0, len(order), batch_size):
        yield starts[order[begin : begin + batch_size]]


def predict_all(model, dataset, starts: np.ndarray, batch_size: int, device) -> np.ndarray:
    """Model output (normalised log discharge) for every window in `starts`."""
    model.eval()
    chunks = []
    with torch.no_grad():
        for batch in iterate_batches(starts, batch_size):
            windows, district_ids, _ = dataset.batch(batch)
            chunks.append(
                model(
                    torch.from_numpy(windows).to(device),
                    torch.from_numpy(district_ids).to(device),
                ).cpu().numpy()
            )
    return np.concatenate(chunks) if chunks else np.zeros((0, len(HORIZONS)), dtype=np.float32)


def denormalise_per_row(normalised: np.ndarray, dataset, starts: np.ndarray) -> np.ndarray:
    """Each row's predictions are in ITS OWN district's normalised space, so
    the inverse has to be applied per district rather than once globally."""
    issue_rows = dataset.issue_rows(starts)
    district_ids = dataset.district_ids[issue_rows]
    out = np.empty_like(normalised, dtype=np.float64)
    for index, name in enumerate(dataset.districts):
        mask = district_ids == index
        if mask.any():
            out[mask] = predictions_to_m3s(normalised[mask], dataset.norm[name])
    return out


def train(
    dataset,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    patience: int,
    seed: int,
    device: str = "cpu",
) -> tuple[FloodLeadTimeGRU, dict]:
    set_seeds(seed)
    generator = np.random.default_rng(seed)
    torch_device = torch.device(device)

    model = FloodLeadTimeGRU(n_districts=len(dataset.districts)).to(torch_device)
    optimiser = torch.optim.Adam(model.parameters(), lr=learning_rate)
    # Huber rather than plain MSE: river series are spiky by nature, and a
    # single monsoon peak should inform the model without dominating the
    # gradient of an entire epoch.
    criterion = nn.HuberLoss(delta=1.0)

    train_starts = dataset.starts[SPLIT_TRAIN]
    val_starts = dataset.starts[SPLIT_VAL]

    history = []
    best_val = float("inf")
    best_state = None
    best_epoch = 0
    epochs_without_improvement = 0
    started = time.monotonic()

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss, seen = 0.0, 0
        for batch in iterate_batches(train_starts, batch_size, generator):
            windows, district_ids, targets = dataset.batch(batch)
            predicted = model(
                torch.from_numpy(windows).to(torch_device),
                torch.from_numpy(district_ids).to(torch_device),
            )
            loss = criterion(predicted, torch.from_numpy(targets).to(torch_device))
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            total_loss += float(loss.item()) * len(batch)
            seen += len(batch)

        train_loss = total_loss / max(seen, 1)

        model.eval()
        val_loss, val_seen = 0.0, 0
        with torch.no_grad():
            for batch in iterate_batches(val_starts, batch_size):
                windows, district_ids, targets = dataset.batch(batch)
                predicted = model(
                    torch.from_numpy(windows).to(torch_device),
                    torch.from_numpy(district_ids).to(torch_device),
                )
                val_loss += float(
                    criterion(predicted, torch.from_numpy(targets).to(torch_device)).item()
                ) * len(batch)
                val_seen += len(batch)
        val_loss = val_loss / max(val_seen, 1)

        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})
        print(f"  epoch {epoch:>3}  train {train_loss:.6f}  val {val_loss:.6f}", flush=True)

        if val_loss < best_val - 1e-6:
            best_val, best_epoch = val_loss, epoch
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                print(f"  early stopping at epoch {epoch} (best was {best_epoch})", flush=True)
                break

    if best_state is not None:
        # Always serve the best-validation weights, never merely the last
        # ones — otherwise early stopping accomplishes nothing.
        model.load_state_dict(best_state)

    return model, {
        "epochs_run": len(history),
        "best_epoch": best_epoch,
        "best_val_loss": best_val,
        "history": history,
        "train_seconds": round(time.monotonic() - started, 1),
    }


# --- the early-warning evaluation ---------------------------------------


def _district_start_rows(dataset) -> np.ndarray:
    """For every row, the first row index of the district it belongs to.

    The dataset lays all 107 districts end to end in one array, so any
    backward lookback (the 30-day baseline below) has to know where its own
    district starts or it will quietly read the previous one's river."""
    district_ids = dataset.district_ids
    boundaries = np.concatenate([[0], np.flatnonzero(np.diff(district_ids)) + 1, [len(district_ids)]])
    starts = np.empty(len(district_ids), dtype=np.int64)
    for begin, end in zip(boundaries[:-1], boundaries[1:]):
        starts[begin:end] = begin
    return starts


def level_hit_rate(dataset, starts: np.ndarray, predicted_m3s: np.ndarray, actual_m3s: np.ndarray) -> dict:
    """Did the model flag the real flood-level days, a day or more early?

    For every test issue day D0 this computes three Flood Risk Index levels
    through the production code path:

      ACTUAL      what the index says using the discharge that really
                  occurred at D0+1..D0+3
      FORECAST    the same, with the model's predicted discharge substituted
      PERSISTENCE the same, assuming the river simply stays at its D0 value

    Everything else feeding the index - rainfall over the horizon, the
    district's static river exposure, the month, the 30-day baseline median -
    is identical across all three, so the comparison isolates exactly one
    thing: the discharge forecast. The rainfall used is the OBSERVED rainfall
    of those days, i.e. a perfect rain forecast, for all three alike. That is
    a deliberate simplification and it is stated in docs/FLOOD_DL.md: this
    measures the DISCHARGE model's lead-time skill, not the skill of an
    end-to-end operational forecast that would also have to predict the rain.
    """
    from app.config import get_settings
    from app.services.alerts.rules import AlertThresholds, evaluate_flood_forecast
    from app.services.flood_forecast import forecast_flood_index

    settings = get_settings()
    thresholds = AlertThresholds.from_settings(settings)
    weights = {
        "discharge": settings.flood_w_discharge,
        "rain_3day": settings.flood_w_rain_3day,
        "rain_intensity": settings.flood_w_rain_intensity,
        "exposure": settings.flood_w_exposure,
        "monsoon": settings.flood_w_monsoon,
    }

    issue_rows = dataset.issue_rows(starts)
    target_rows = dataset.target_rows(starts)
    district_ids = dataset.district_ids[issue_rows]

    # 30-day baseline median ending at D0, exactly as app/services/flood.py
    # computes it from its own 30 past days — clamped so the lookback can
    # never run off the front of a district's record and silently average in
    # the PREVIOUS district's river (the districts are laid end to end in one
    # array). In practice the test split sits years into every record, but a
    # metric that is only correct by luck is not a metric.
    baselines = np.median(
        dataset.discharge_m3s[
            np.maximum(issue_rows[:, None] - np.arange(30)[None, :], _district_start_rows(dataset)[issue_rows][:, None])
        ],
        axis=1,
    )
    horizon_rain = dataset.precipitation_mm[target_rows]
    persistence_m3s = dataset.discharge_m3s[issue_rows]

    # The month of the first day being forecast, matching what
    # app/services/flood_forecast.py passes at serving time.
    months = (dataset.dates[target_rows[:, 0]].astype("datetime64[M]").astype(int) % 12) + 1
    exposures = np.array(
        [DISTRICTS[dataset.districts[i]]["river_exposure"] for i in range(len(dataset.districts))]
    )

    def level_for(series: list[float], row: int) -> int:
        index = forecast_flood_index(
            baseline_median=float(baselines[row]),
            forecast_discharge_m3s=series,
            daily_rain_mm=[float(v) for v in horizon_rain[row]],
            river_exposure=float(exposures[district_ids[row]]),
            month=int(months[row]),
            weights=weights,
        )
        outcome = evaluate_flood_forecast(
            band=index["band"],
            score=index["score"],
            predicted_discharge=series,
            anomaly_ratio=index["anomaly_ratio"],
            # Today's observed discharge, so the inherited rising-48 h test
            # sees exactly what it sees at serving time. The level-3 ceiling
            # is irrelevant at the >= 3 boundary this metric is measured at,
            # but passing the configured thresholds keeps the offline path
            # identical to the served one either way.
            thresholds=thresholds,
            current_discharge=float(persistence_m3s[row]),
        )
        return outcome.level if outcome is not None else 1

    counts = {"model": [0, 0, 0, 0], "persistence": [0, 0, 0, 0]}  # TP, FP, FN, TN
    for row in range(len(starts)):
        actual = level_for([float(v) for v in actual_m3s[row]], row) >= EVENT_LEVEL
        for name, series in (
            ("model", [float(v) for v in predicted_m3s[row]]),
            ("persistence", [float(persistence_m3s[row])] * len(HORIZONS)),
        ):
            flagged = level_for(series, row) >= EVENT_LEVEL
            slot = 0 if (actual and flagged) else 1 if (flagged and not actual) else 2 if actual else 3
            counts[name][slot] += 1

    def summarise(values: list[int]) -> dict:
        true_positive, false_positive, false_negative, true_negative = values
        events = true_positive + false_negative
        flagged = true_positive + false_positive
        quiet = false_positive + true_negative
        return {
            "true_positives": true_positive,
            "false_positives": false_positive,
            "false_negatives": false_negative,
            "true_negatives": true_negative,
            "event_days": events,
            "flagged_days": flagged,
            # "Of the days that really were level >= 3, how many did we flag
            # at least 24 h ahead?" — the early-warning question.
            "hit_rate": (true_positive / events) if events else None,
            # "Of the days we flagged, how many were wrong?" — the
            # meteorological false-alarm RATIO.
            "false_alarm_ratio": (false_positive / flagged) if flagged else None,
            # "Of the calm days, how many did we wrongly flag?" — the
            # classic false-positive RATE. Reported alongside because with
            # rare events the two say very different things.
            "false_alarm_rate": (false_positive / quiet) if quiet else None,
        }

    return {
        "event_level": EVENT_LEVEL,
        "definition": (
            "An 'event day' is a test issue day D0 whose Flood Risk Index, computed from the discharge that "
            "actually occurred at D0+1..D0+3, maps to alert level >= 3 (band HIGH). A 'hit' is the same index "
            "computed from the model's prediction, issued at D0, reaching level >= 3 as well - i.e. at least "
            "24 h of lead time. Rainfall, exposure, month and the 30-day baseline are held identical across "
            "model, persistence and actual, so only the discharge forecast differs."
        ),
        "rainfall_assumption": (
            "Observed rainfall over D0+1..D0+3 is used for all three series alike (a perfect rain forecast). "
            "This isolates the discharge model's lead-time skill; it is NOT an end-to-end operational score."
        ),
        "samples": int(len(starts)),
        "model": summarise(counts["model"]),
        "persistence": summarise(counts["persistence"]),
    }


def evaluate(dataset, model, batch_size: int, device: str) -> dict:
    """Everything metrics.json reports, on the held-out test split."""
    starts = dataset.starts[SPLIT_TEST]
    if not len(starts):
        raise RuntimeError("The test split is empty — there is nothing to evaluate honestly.")

    normalised = predict_all(model, dataset, starts, batch_size, torch.device(device))
    predicted_m3s = denormalise_per_row(normalised, dataset, starts)

    target_rows = dataset.target_rows(starts)
    actual_m3s = dataset.discharge_m3s[target_rows]
    # Persistence: "tomorrow, and the day after, and the day after that, all
    # look like today". The baseline every number below is measured against.
    issue_rows = dataset.issue_rows(starts)
    persistence_m3s = np.repeat(dataset.discharge_m3s[issue_rows][:, None], len(HORIZONS), axis=1)

    return {
        "test_samples": int(len(starts)),
        "model": horizon_metrics(actual_m3s, predicted_m3s),
        "persistence": horizon_metrics(actual_m3s, persistence_m3s),
        "level_hit_rate": level_hit_rate(dataset, starts, predicted_m3s, actual_m3s),
    }


def beats_persistence(metrics: dict) -> dict:
    """Per horizon: did the model actually beat persistence, in log space?

    Reported as an explicit boolean rather than left for a reader to work out
    from two tables — if the answer is "no", the artifact should say "no"."""
    verdict = {}
    for horizon in HORIZONS:
        key = f"D+{horizon}"
        model_mae = metrics["model"][key]["log"]["mae"]
        baseline_mae = metrics["persistence"][key]["log"]["mae"]
        verdict[key] = {
            "model_mae_log": model_mae,
            "persistence_mae_log": baseline_mae,
            "beats_persistence": bool(model_mae < baseline_mae),
            "improvement_pct": float(100.0 * (baseline_mae - model_mae) / baseline_mae) if baseline_mae else None,
        }
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--patience", type=int, default=DEFAULT_PATIENCE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--register", action="store_true", help="export and register the trained model")
    parser.add_argument("--model-root", default=None, help="override the flood_dl model registry root")
    args = parser.parse_args()

    print("LEHAR Phase 2.5 — flood lead-time model training")
    print(f"  history: {args.history_dir}")
    dataset = build_dataset(args.history_dir)
    summary = dataset.summary()
    print(json.dumps(summary, indent=2))

    if not len(dataset.starts[SPLIT_TRAIN]):
        raise RuntimeError("No training windows were built — check the downloaded history.")

    model, training = train(
        dataset,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        patience=args.patience,
        seed=args.seed,
        device=args.device,
    )
    print(f"  trained in {training['train_seconds']}s, best epoch {training['best_epoch']}")

    evaluation = evaluate(dataset, model, args.batch_size, args.device)
    verdict = beats_persistence(evaluation)

    metrics = {
        "model": {
            "architecture": "GRU(2 layers, hidden 64) + per-district embedding(16) -> Linear(3)",
            "parameters": model.parameter_count(),
            "window_days": WINDOW_DAYS,
            "horizons_days": list(HORIZONS),
            "districts": len(dataset.districts),
        },
        "data": {
            "source": (
                "REAL data: GloFAS river discharge (Open-Meteo Flood API) + ERA5 precipitation and maximum "
                "temperature (Open-Meteo Historical Weather API). NOT synthetic — unlike LEHAR's irrigation "
                "model, which remains trained on synthetic research data."
            ),
            "attribution": (
                "Weather data by Open-Meteo.com (CC BY 4.0). River discharge from GloFAS / Copernicus "
                "Emergency Management Service, served via Open-Meteo."
            ),
            **summary,
        },
        "split": {
            "train": f"issue day <= {TRAIN_END_YEAR}-12-31",
            "val": f"issue day in {VAL_YEAR}",
            "test": f"issue day >= {TEST_START_YEAR}-01-01",
            "note": (
                "Split by time, never at random, and per-district normalisation statistics are computed on "
                "the training rows only — a random split on a series this autocorrelated scores near-perfectly "
                "and means nothing."
            ),
        },
        "training": {
            **training,
            "seed": args.seed,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "loss": "HuberLoss(delta=1.0) on normalised log discharge",
        },
        "evaluation": evaluation,
        "verdict_vs_persistence": verdict,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    print("\n--- test metrics (held out, real data) ---")
    for horizon in HORIZONS:
        key = f"D+{horizon}"
        model_block = evaluation["model"][key]
        base_block = evaluation["persistence"][key]
        print(
            f"  {key}: model  MAE(log) {model_block['log']['mae']:.4f}  NSE(m3/s) {model_block['m3s']['nse']:.4f}"
            f"   |  persistence MAE(log) {base_block['log']['mae']:.4f}  NSE(m3/s) {base_block['m3s']['nse']:.4f}"
            f"   |  beats persistence: {verdict[key]['beats_persistence']}"
        )
    hit = evaluation["level_hit_rate"]
    print(
        f"  level >= {EVENT_LEVEL} events: {hit['model']['event_days']} — "
        f"model hit rate {hit['model']['hit_rate']}, false-alarm ratio {hit['model']['false_alarm_ratio']}"
    )

    if args.register:
        from ml.flood_dl.export import export_and_register  # noqa: PLC0415

        model_root = Path(args.model_root) if args.model_root else flood_dl_registry.FLOOD_DL_MODEL_ROOT
        version = export_and_register(model, dataset, metrics, model_root=model_root)
        print(f"\nRegistered flood lead-time model {version} under {model_root}")
    else:
        print("\n(not registered — rerun with --register to export and register)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
