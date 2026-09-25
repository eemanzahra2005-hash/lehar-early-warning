"""Export the trained GRU to ONNX and register it (LEHAR Phase 2.5).

** imports torch ** — this is the last point in the pipeline that does.
Everything downstream (app/services/flood_forecast.py, the alert engine, the
endpoint, the tests) reads only what this module writes:

    <version>/model.onnx     the graph, runnable by onnxruntime alone
    <version>/norm.json      per-district normalisation + the feature
                             contract the graph was built against
    <version>/metrics.json   the REAL measured evaluation

Why ONNX rather than a .pt state dict: loading a .pt needs PyTorch in the
API process, and PyTorch is roughly 200 MB against a 512 MB ceiling
(CLAUDE.md rule 11). The exported graph is ~180 KB and onnxruntime loads it
with a fraction of the footprint. It also means the serving path cannot
accidentally drift from the trained architecture — there is no architecture
to re-declare, only a graph to run.

The export is verified before it is registered: the ONNX graph is run
through onnxruntime and its output compared against the PyTorch model's on
the same input. An export that silently changed the numbers would be worse
than no export at all, so a mismatch raises instead of registering.
"""

import json
from pathlib import Path

import numpy as np
import torch

from ml.flood_dl import registry as flood_dl_registry
from ml.flood_dl.dataset import write_norm_json
from ml.flood_dl.features import HORIZONS, N_FEATURES, WINDOW_DAYS

# Opset 14 covers GRU, Gather (the embedding) and the shape ops the concat
# needs, and is old enough that any onnxruntime this project could plausibly
# pin will load it.
ONNX_OPSET = 14

INPUT_WINDOW = "window"
INPUT_DISTRICT = "district_id"
OUTPUT_PREDICTION = "prediction"

# How closely the ONNX graph has to reproduce the PyTorch model. Tight
# enough to catch a real export bug (a transposed weight, a dropped layer),
# loose enough not to trip on float32 kernel differences between the two
# runtimes.
EXPORT_TOLERANCE = 1e-4


def export_onnx(model, path: Path, batch_example: int = 1) -> Path:
    """Write model.onnx with a dynamic batch axis.

    Traced at batch size 1. torch's TorchScript RNN exporter emits a warning
    here about GRUs traced at one batch size being run at another; it fires
    unconditionally for any GRU export, and the case it describes is
    VARIABLE-LENGTH sequences, which these are not (every window is exactly
    WINDOW_DAYS long). Rather than reason about it, verify_onnx() below
    checks the exported graph against PyTorch at four different batch sizes
    and refuses to register a mismatch."""
    model.eval()
    path.parent.mkdir(parents=True, exist_ok=True)

    example_window = torch.zeros(batch_example, WINDOW_DAYS, N_FEATURES, dtype=torch.float32)
    example_district = torch.zeros(batch_example, dtype=torch.int64)

    torch.onnx.export(
        model,
        (example_window, example_district),
        str(path),
        input_names=[INPUT_WINDOW, INPUT_DISTRICT],
        output_names=[OUTPUT_PREDICTION],
        # Batch is dynamic so one session serves a single district forecast
        # and a whole 107-district sweep alike; the window length and channel
        # count are fixed on purpose — they are the contract.
        dynamic_axes={
            INPUT_WINDOW: {0: "batch"},
            INPUT_DISTRICT: {0: "batch"},
            OUTPUT_PREDICTION: {0: "batch"},
        },
        opset_version=ONNX_OPSET,
        dynamo=False,
    )
    return path


def verify_onnx(model, path: Path, n_districts: int, batch_sizes=(1, 2, 8, 64), seed: int = 0) -> float:
    """Run both the PyTorch model and the exported graph on the same random
    inputs and return the largest absolute difference seen. Raises if that
    exceeds EXPORT_TOLERANCE.

    Several batch sizes, including the traced one and much larger, because
    the dynamic batch axis is the one part of this export that could plausibly
    be wrong: a GRU whose exported graph baked in a fixed batch would still
    load, still run, and still return numbers — just the wrong ones for every
    request whose batch differed from the traced one."""
    import onnxruntime

    model.eval()
    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(seed)
    worst = 0.0

    for samples in batch_sizes:
        window = rng.normal(size=(samples, WINDOW_DAYS, N_FEATURES)).astype(np.float32)
        district = rng.integers(0, n_districts, size=samples).astype(np.int64)

        with torch.no_grad():
            expected = model(torch.from_numpy(window), torch.from_numpy(district)).numpy()
        actual = session.run(None, {INPUT_WINDOW: window, INPUT_DISTRICT: district})[0]

        difference = float(np.max(np.abs(expected - actual)))
        if not np.isfinite(difference) or difference > EXPORT_TOLERANCE:
            raise RuntimeError(
                f"ONNX export does not reproduce the PyTorch model at batch size {samples}: "
                f"max |difference| = {difference:.3e} (tolerance {EXPORT_TOLERANCE:.1e}). "
                "Refusing to register it."
            )
        worst = max(worst, difference)

    return worst


def export_and_register(
    model,
    dataset,
    metrics: dict,
    model_root: Path = flood_dl_registry.FLOOD_DL_MODEL_ROOT,
    version: str | None = None,
    set_latest: bool = True,
) -> str:
    """Write a complete, verified version directory and record it.

    A NEW version directory every time, never an overwrite (CLAUDE.md
    rule 6): the artifacts are written first, verified, and only then does
    registry.json learn the version exists — so a crashed export leaves an
    orphan directory rather than a registry pointing at a broken model.
    """
    version = version or flood_dl_registry.new_version_id()
    model_root = Path(model_root)
    directory = flood_dl_registry.version_dir(version, model_root)
    if directory.exists():
        raise FileExistsError(f"{directory} already exists — versions are never overwritten.")
    directory.mkdir(parents=True)

    onnx_path = export_onnx(model, directory / flood_dl_registry.MODEL_FILENAME)
    difference = verify_onnx(model, onnx_path, n_districts=len(dataset.districts))

    write_norm_json(dataset, directory / flood_dl_registry.NORM_FILENAME)

    metrics = {
        **metrics,
        "version": version,
        "export": {
            "format": "onnx",
            "opset": ONNX_OPSET,
            "max_abs_difference_vs_pytorch": difference,
            "onnx_bytes": onnx_path.stat().st_size,
            "input_names": [INPUT_WINDOW, INPUT_DISTRICT],
            "output_names": [OUTPUT_PREDICTION],
        },
    }
    (directory / flood_dl_registry.METRICS_FILENAME).write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )

    flood_dl_registry.register(
        version=version,
        metrics=_registry_summary(metrics),
        model_root=model_root,
        extra={
            "source": "ml/flood_dl/train.py",
            "training_data": "real (GloFAS + ERA5 via Open-Meteo)",
            "parameters": metrics["model"]["parameters"],
            "districts": metrics["model"]["districts"],
        },
        set_latest=set_latest,
    )
    return version


def _registry_summary(metrics: dict) -> dict:
    """The short form registry.json carries — enough to compare versions at
    a glance without opening each metrics.json."""
    evaluation = metrics.get("evaluation", {})
    verdict = metrics.get("verdict_vs_persistence", {})
    horizon = f"D+{HORIZONS[0]}"
    block = evaluation.get("model", {}).get(horizon, {})
    hit = evaluation.get("level_hit_rate", {}).get("model", {})
    return {
        "test_samples": evaluation.get("test_samples"),
        f"mae_log_{horizon}": block.get("log", {}).get("mae"),
        f"nse_m3s_{horizon}": block.get("m3s", {}).get("nse"),
        "beats_persistence": {key: value["beats_persistence"] for key, value in verdict.items()},
        "level_hit_rate": hit.get("hit_rate"),
        "level_false_alarm_ratio": hit.get("false_alarm_ratio"),
    }
