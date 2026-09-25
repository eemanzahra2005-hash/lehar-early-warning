"""Write the measured metrics of a registered flood lead-time model into
docs/FLOOD_DL.md (LEHAR Phase 2.5).

    .venv\\Scripts\\python scripts\\write_flood_dl_metrics_doc.py

Reads `backend/ml/flood_dl/model/<version>/metrics.json` — the artifact the
training run actually wrote — and replaces the block between the
`<!-- METRICS:BEGIN -->` and `<!-- METRICS:END -->` markers in the document.

Why this is a script rather than something typed by hand: CLAUDE.md rule 4
forbids fabricated metrics, and a number copied by hand from a console into
a Markdown table is a number that can be copied wrong. This way the
documented figures are provably the ones in the artifact, and regenerating
the page after a retrain is one command. No torch, no network.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml.flood_dl import registry as flood_dl_registry  # noqa: E402

DOC_PATH = PROJECT_ROOT / "docs" / "FLOOD_DL.md"
BEGIN = "<!-- METRICS:BEGIN -->"
END = "<!-- METRICS:END -->"


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "**no**"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _pair(model_value, baseline_value, digits: int = 4, lower_is_better: bool = True) -> tuple[str, str]:
    """Format a model/baseline pair, bolding whichever actually won.

    Bolding the model's number unconditionally would read as a claim that it
    is the better one — which, on a metric it lost, would be a small lie told
    by formatting (CLAUDE.md rule 4). The winner gets the emphasis, whoever
    it is."""
    model_text, baseline_text = _fmt(model_value, digits), _fmt(baseline_value, digits)
    if model_value is None or baseline_value is None:
        return model_text, baseline_text
    model_wins = model_value < baseline_value if lower_is_better else model_value > baseline_value
    if model_wins:
        return f"**{model_text}**", baseline_text
    return model_text, f"**{baseline_text}**"


def render(metrics: dict, version: str) -> str:
    model = metrics["model"]
    data = metrics["data"]
    training = metrics["training"]
    evaluation = metrics["evaluation"]
    verdict = metrics["verdict_vs_persistence"]
    hit = evaluation["level_hit_rate"]
    samples = data["samples"]

    lines: list[str] = []
    lines.append("### The trained model")
    lines.append("")
    lines.append(f"Registered version **`{version}`** — every number below is measured on the")
    lines.append("held-out test split and reproduced verbatim from that version's")
    lines.append("`metrics.json` by `scripts/write_flood_dl_metrics_doc.py`.")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Districts | {model['districts']} |")
    lines.append(f"| Parameters | {model['parameters']:,} |")
    lines.append(f"| Total district-days | {data['total_days']:,} |")
    lines.append(f"| Date range | {data['date_range']['first']} → {data['date_range']['last']} |")
    lines.append(
        f"| Training / validation / test windows | {samples['train']:,} / {samples['val']:,} / {samples['test']:,} |"
    )
    lines.append(f"| Epochs run (best) | {training['epochs_run']} ({training['best_epoch']}) |")
    lines.append(f"| Training time | {training['train_seconds']} s |")
    lines.append(f"| Seed | {training['seed']} |")
    if "export" in metrics:
        lines.append(f"| Exported ONNX | {metrics['export']['onnx_bytes']:,} bytes, opset {metrics['export']['opset']} |")
        lines.append(
            f"| Max abs. difference ONNX vs PyTorch | {metrics['export']['max_abs_difference_vs_pytorch']:.2e} |"
        )
    lines.append("")

    lines.append("### Accuracy vs the persistence baseline")
    lines.append("")
    lines.append("Persistence is *\"the river tomorrow is the river today\"*. On a daily")
    lines.append("discharge series that is a genuinely strong baseline, especially at D+1.")
    lines.append("")
    lines.append("**log1p space** (scale-free — what the model optimises, and the fair")
    lines.append("comparison across districts spanning four orders of magnitude):")
    lines.append("")
    lines.append("| Horizon | Model MAE | Persistence MAE | Model RMSE | Persistence RMSE | Beats persistence |")
    lines.append("|---|---:|---:|---:|---:|:---:|")
    for horizon in model["horizons_days"]:
        key = f"D+{horizon}"
        m = evaluation["model"][key]["log"]
        p = evaluation["persistence"][key]["log"]
        v = verdict[key]
        improvement = f" ({v['improvement_pct']:+.1f}%)" if v["improvement_pct"] is not None else ""
        mae_model, mae_base = _pair(m["mae"], p["mae"])
        rmse_model, rmse_base = _pair(m["rmse"], p["rmse"])
        lines.append(
            f"| {key} | {mae_model}{improvement} | {mae_base} | "
            f"{rmse_model} | {rmse_base} | {_fmt(v['beats_persistence'])} |"
        )
    lines.append("")
    lines.append("**m³/s** (physical units — dominated by the largest rivers, which is")
    lines.append("what a hydrologist reads), with Nash-Sutcliffe efficiency:")
    lines.append("")
    lines.append("| Horizon | Model MAE | Persistence MAE | Model NSE | Persistence NSE |")
    lines.append("|---|---:|---:|---:|---:|")
    for horizon in model["horizons_days"]:
        key = f"D+{horizon}"
        m = evaluation["model"][key]["m3s"]
        p = evaluation["persistence"][key]["m3s"]
        mae_model, mae_base = _pair(m["mae"], p["mae"], digits=3)
        # NSE is a skill score: higher is better, unlike every other column.
        nse_model, nse_base = _pair(m["nse"], p["nse"], lower_is_better=False)
        lines.append(f"| {key} | {mae_model} | {mae_base} | {nse_model} | {nse_base} |")
    lines.append("")

    lines.append("### The number that actually matters: lead time on real events")
    lines.append("")
    lines.append("MAE is not what an early-warning system is for. This is: **of the days")
    lines.append(f"that really were level ≥ {hit['event_level']} flood days, how many did the model flag at")
    lines.append("least 24 hours ahead — and how often did it cry wolf?**")
    lines.append("")
    lines.append(f"Measured over **{hit['samples']:,}** test issue-days, of which")
    lines.append(f"**{hit['model']['event_days']:,}** were real level-≥{hit['event_level']} days:")
    lines.append("")
    lines.append("| | Model | Persistence |")
    lines.append("|---|---:|---:|")
    for label, field, digits in (
        ("**Hit rate** (flagged ≥24 h early)", "hit_rate", 4),
        ("False-alarm ratio (FP / flagged)", "false_alarm_ratio", 4),
        ("False-alarm rate (FP / calm days)", "false_alarm_rate", 4),
        ("True positives", "true_positives", 0),
        ("False positives", "false_positives", 0),
        ("False negatives", "false_negatives", 0),
        ("True negatives", "true_negatives", 0),
    ):
        lines.append(
            f"| {label} | {_fmt(hit['model'][field], digits)} | {_fmt(hit['persistence'][field], digits)} |"
        )
    lines.append("")
    lines.append(f"> {hit['definition']}")
    lines.append(">")
    lines.append(f"> {hit['rainfall_assumption']}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default="latest")
    parser.add_argument("--model-root", default=None)
    parser.add_argument("--doc", default=str(DOC_PATH))
    args = parser.parse_args()

    model_root = Path(args.model_root) if args.model_root else flood_dl_registry.FLOOD_DL_MODEL_ROOT
    version = flood_dl_registry.resolve_version(args.version, model_root)
    if version is None:
        print(f"No registered flood lead-time model found under {model_root}. Train one first.")
        return 1

    metrics = flood_dl_registry.read_metrics(version, model_root)
    doc = Path(args.doc)
    text = doc.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print(f"{doc} has no {BEGIN} / {END} markers.")
        return 1

    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    doc.write_text(f"{head}{BEGIN}\n\n{render(metrics, version)}\n{END}{tail}", encoding="utf-8")
    print(f"Wrote {version}'s measured metrics into {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
