"""Bilingual (English / Urdu) alert message templates.

Deterministic string templates ONLY — no LLM, ever (CLAUDE.md rule 10).
Given the same alert type, level and values, render() returns byte-identical
text every time. An LLM may later help a farmer *read* one of these messages
(translate it further, answer a question about it), but it never writes one.

Every rendered body ends with the level's farmer actions (from levels.py)
and then the mandated disclaimer (CLAUDE.md rule 12). The Urdu body carries
the Urdu disclaimer AND the exact English sentence the rule specifies, so
the mandated wording is literally present on every message in either
language.
"""

from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR, get_level
from app.services.alerts.rules import (
    TYPE_ALL_CLEAR,
    TYPE_FLOOD,
    TYPE_FLOOD_FORECAST,
    TYPE_HEAT_STRESS,
    TYPE_HEAVY_RAIN,
    TYPE_IRRIGATION_DUE,
    TYPE_OPS,
)

ACTIONS_HEADING_EN = "What to do:"
ACTIONS_HEADING_UR = "کیا کریں:"


class _SafeDict(dict):
    """format_map() backing dict that renders a missing or None value as
    "n/a" instead of raising. An alert must never fail to render because one
    optional number was unavailable — a partially-populated message that
    still reaches the farmer beats no message at all."""

    def __missing__(self, key: str) -> str:
        return "n/a"


def _fmt(template: str, values: dict) -> str:
    cleaned = _SafeDict({k: ("n/a" if v is None else v) for k, v in values.items()})
    return template.format_map(cleaned)


# Titles, per type and level. {district} is always available.
TITLES: dict[str, dict[int, tuple[str, str]]] = {
    TYPE_FLOOD: {
        1: ("Flood watch: {district}", "سیلاب کی نگرانی: {district}"),
        2: ("Flood advisory: {district}", "سیلاب کا انتباہ: {district}"),
        3: ("Flood warning: {district}", "سیلاب کی وارننگ: {district}"),
        4: ("URGENT flood warning: {district}", "فوری سیلابی وارننگ: {district}"),
        5: ("FLOOD EMERGENCY: {district}", "سیلابی ہنگامی حالت: {district}"),
    },
    # LEHAR Phase 2.5. Every title says FORECAST in both languages, at the
    # front, because the one thing a farmer must not do is read a prediction
    # as a measurement. Levels 4 and 5 are unreachable with the default
    # ALERT_FLOOD_FORECAST_MAX_LEVEL of 3 (see rules.py) and are declared
    # here so that raising that ceiling never produces an untranslated alert.
    TYPE_FLOOD_FORECAST: {
        2: ("Flood forecast advisory: {district}", "سیلاب کی پیش گوئی — انتباہ: {district}"),
        3: ("Flood forecast warning: {district}", "سیلاب کی پیش گوئی — وارننگ: {district}"),
        4: ("URGENT flood forecast: {district}", "سیلاب کی پیش گوئی — فوری وارننگ: {district}"),
        5: ("FLOOD FORECAST EMERGENCY: {district}", "سیلاب کی پیش گوئی — ہنگامی حالت: {district}"),
    },
    TYPE_HEAVY_RAIN: {
        2: ("Heavy rain advisory: {district}", "شدید بارش کا انتباہ: {district}"),
        3: ("Heavy rain warning: {district}", "شدید بارش کی وارننگ: {district}"),
    },
    TYPE_HEAT_STRESS: {
        2: ("Heat stress advisory: {district}", "گرمی کے دباؤ کا انتباہ: {district}"),
        3: ("Extreme heat warning: {district}", "شدید گرمی کی وارننگ: {district}"),
    },
    TYPE_IRRIGATION_DUE: {
        1: ("Irrigation due: {district}", "آبپاشی کا وقت: {district}"),
    },
    TYPE_ALL_CLEAR: {
        1: ("All clear: {district}", "خطرہ ٹل گیا: {district}"),
    },
    TYPE_OPS: {
        0: ("Operations notice: LEHAR platform", "آپریشنز اطلاع: لہر پلیٹ فارم"),
    },
}

# Situation sentences, per type and level. Placeholders are filled from the
# rule outcome's `values` plus {district}; anything missing renders "n/a".
SITUATIONS: dict[str, dict[int, tuple[str, str]]] = {
    TYPE_FLOOD: {
        1: (
            "River and rainfall conditions around {district} are normal today. "
            "The LEHAR Flood Risk Index is {score} (band LOW).",
            "{district} کے گرد دریا اور بارش کے حالات آج معمول کے مطابق ہیں۔ "
            "لہر فلڈ رسک انڈیکس {score} ہے (درجہ: کم)۔",
        ),
        2: (
            "Flood risk is building around {district}. The LEHAR Flood Risk Index is {score} "
            "and forecast river discharge is {anomaly_ratio}x the 30-day baseline.",
            "{district} کے گرد سیلاب کا خطرہ بڑھ رہا ہے۔ لہر فلڈ رسک انڈیکس {score} ہے "
            "اور متوقع دریائی بہاؤ 30 دن کی بنیاد سے {anomaly_ratio} گنا ہے۔",
        ),
        3: (
            "Flooding is likely around {district}. The LEHAR Flood Risk Index is {score} (band HIGH), "
            "with forecast river discharge {anomaly_ratio}x the 30-day baseline.",
            "{district} کے گرد سیلاب کا امکان ہے۔ لہر فلڈ رسک انڈیکس {score} ہے (درجہ: زیادہ)، "
            "متوقع دریائی بہاؤ 30 دن کی بنیاد سے {anomaly_ratio} گنا ہے۔",
        ),
        4: (
            "Flood risk around {district} is HIGH and river discharge is still RISING over the next 48 hours. "
            "The LEHAR Flood Risk Index is {score}.",
            "{district} کے گرد سیلابی خطرہ زیادہ ہے اور اگلے 48 گھنٹوں میں دریائی بہاؤ مزید بڑھ رہا ہے۔ "
            "لہر فلڈ رسک انڈیکس {score} ہے۔",
        ),
        5: (
            "EXTREME flood conditions around {district}. The LEHAR Flood Risk Index is {score} and forecast "
            "river discharge is {anomaly_ratio}x the 30-day baseline — a rare, dangerous event.",
            "{district} کے گرد انتہائی شدید سیلابی حالات۔ لہر فلڈ رسک انڈیکس {score} ہے اور متوقع دریائی بہاؤ "
            "30 دن کی بنیاد سے {anomaly_ratio} گنا ہے — ایک نادر اور خطرناک صورتحال۔",
        ),
    },
    # LEHAR Phase 2.5. The word FORECAST/PREDICTED leads every sentence, and
    # the model version is named in the body: a farmer who is told to act on
    # a prediction is entitled to know it was one, and which model made it.
    TYPE_FLOOD_FORECAST: {
        2: (
            "FORECAST, not a measurement: LEHAR's flood lead-time model expects river conditions around "
            "{district} to build over the next 1 to 3 days. Predicted river discharge peaks at "
            "{predicted_peak_m3s} m3/s ({anomaly_ratio}x the 30-day baseline), a predicted Flood Risk Index "
            "of {score} (band {band}). Issued {lead_time_hours} hours ahead by model {model_version}.",
            "یہ پیش گوئی ہے، پیمائش نہیں: لہر کا ابتدائی اطلاع ماڈل {district} کے گرد اگلے 1 تا 3 دن میں "
            "دریائی حالات بگڑنے کی توقع رکھتا ہے۔ متوقع دریائی بہاؤ زیادہ سے زیادہ {predicted_peak_m3s} "
            "کیوبک میٹر فی سیکنڈ (30 دن کی بنیاد سے {anomaly_ratio} گنا)، متوقع فلڈ رسک انڈیکس {score} "
            "(درجہ {band})۔ {lead_time_hours} گھنٹے پہلے ماڈل {model_version} نے جاری کی۔",
        ),
        3: (
            "FORECAST, not a measurement: LEHAR's flood lead-time model expects FLOODING conditions around "
            "{district} within the next 1 to 3 days. Predicted river discharge peaks at "
            "{predicted_peak_m3s} m3/s ({anomaly_ratio}x the 30-day baseline), a predicted Flood Risk Index "
            "of {score} (band {band}). Issued {lead_time_hours} hours ahead by model {model_version}. "
            "Act now, while there is still time.",
            "یہ پیش گوئی ہے، پیمائش نہیں: لہر کا ابتدائی اطلاع ماڈل {district} کے گرد اگلے 1 تا 3 دن میں "
            "سیلابی حالات کی توقع رکھتا ہے۔ متوقع دریائی بہاؤ زیادہ سے زیادہ {predicted_peak_m3s} "
            "کیوبک میٹر فی سیکنڈ (30 دن کی بنیاد سے {anomaly_ratio} گنا)، متوقع فلڈ رسک انڈیکس {score} "
            "(درجہ {band})۔ {lead_time_hours} گھنٹے پہلے ماڈل {model_version} نے جاری کی۔ "
            "وقت رہتے ابھی کارروائی کریں۔",
        ),
        4: (
            "FORECAST, not a measurement: LEHAR's flood lead-time model expects SEVERE flooding around "
            "{district} within the next 1 to 3 days. Predicted river discharge peaks at "
            "{predicted_peak_m3s} m3/s ({anomaly_ratio}x the 30-day baseline), a predicted Flood Risk Index "
            "of {score}. Issued {lead_time_hours} hours ahead by model {model_version}.",
            "یہ پیش گوئی ہے، پیمائش نہیں: لہر کا ابتدائی اطلاع ماڈل {district} کے گرد اگلے 1 تا 3 دن میں "
            "شدید سیلاب کی توقع رکھتا ہے۔ متوقع دریائی بہاؤ زیادہ سے زیادہ {predicted_peak_m3s} "
            "کیوبک میٹر فی سیکنڈ (30 دن کی بنیاد سے {anomaly_ratio} گنا)، متوقع فلڈ رسک انڈیکس {score}۔ "
            "{lead_time_hours} گھنٹے پہلے ماڈل {model_version} نے جاری کی۔",
        ),
        5: (
            "FORECAST, not a measurement: LEHAR's flood lead-time model expects EXTREME flooding around "
            "{district} within the next 1 to 3 days. Predicted river discharge peaks at "
            "{predicted_peak_m3s} m3/s ({anomaly_ratio}x the 30-day baseline), a predicted Flood Risk Index "
            "of {score}. Issued {lead_time_hours} hours ahead by model {model_version}.",
            "یہ پیش گوئی ہے، پیمائش نہیں: لہر کا ابتدائی اطلاع ماڈل {district} کے گرد اگلے 1 تا 3 دن میں "
            "انتہائی شدید سیلاب کی توقع رکھتا ہے۔ متوقع دریائی بہاؤ زیادہ سے زیادہ {predicted_peak_m3s} "
            "کیوبک میٹر فی سیکنڈ (30 دن کی بنیاد سے {anomaly_ratio} گنا)، متوقع فلڈ رسک انڈیکس {score}۔ "
            "{lead_time_hours} گھنٹے پہلے ماڈل {model_version} نے جاری کی۔",
        ),
    },
    TYPE_HEAVY_RAIN: {
        2: (
            "Heavy rain is forecast for {district}: up to {peak_daily_rain_mm} mm in one day "
            "(on {peak_date}), {total_rain_mm} mm over the forecast window.",
            "{district} میں شدید بارش متوقع ہے: ایک دن میں {peak_daily_rain_mm} ملی میٹر تک "
            "({peak_date} کو)، پیش گوئی کی مدت میں کل {total_rain_mm} ملی میٹر۔",
        ),
        3: (
            "Very heavy rain is forecast for {district}: up to {peak_daily_rain_mm} mm in one day "
            "(on {peak_date}). Standing water and field damage are likely.",
            "{district} میں بہت شدید بارش متوقع ہے: ایک دن میں {peak_daily_rain_mm} ملی میٹر تک "
            "({peak_date} کو)۔ کھیتوں میں پانی کھڑا ہونے اور نقصان کا امکان ہے۔",
        ),
    },
    TYPE_HEAT_STRESS: {
        2: (
            "Sustained heat is forecast for {district}: {consecutive_days_at_or_above_l2} consecutive days at or "
            "above {l2_c} C, peaking at {peak_tmax_c} C on {peak_date}. Crop water demand will rise sharply.",
            "{district} میں مسلسل گرمی متوقع ہے: {consecutive_days_at_or_above_l2} دن مسلسل {l2_c} ڈگری یا اس سے "
            "زیادہ، {peak_date} کو زیادہ سے زیادہ {peak_tmax_c} ڈگری۔ فصل کی پانی کی ضرورت تیزی سے بڑھے گی۔",
        ),
        3: (
            "Extreme heat is forecast for {district}: {peak_tmax_c} C on {peak_date}. "
            "Heat damage to crops, livestock and people is likely.",
            "{district} میں شدید گرمی متوقع ہے: {peak_date} کو {peak_tmax_c} ڈگری۔ "
            "فصل، مویشی اور انسانوں کو گرمی سے نقصان کا امکان ہے۔",
        ),
    },
    TYPE_IRRIGATION_DUE: {
        1: (
            "Your field \"{field_name}\" ({crop_type}) in {district} is due for irrigation: the model recommends "
            "{predicted_mm} mm, and only {rain_next_days_mm} mm of rain is forecast over the next {dry_days} days.",
            "{district} میں آپ کے کھیت \"{field_name}\" ({crop_type}) کو آبپاشی درکار ہے: ماڈل کے مطابق "
            "{predicted_mm} ملی میٹر، اور اگلے {dry_days} دنوں میں صرف {rain_next_days_mm} ملی میٹر بارش متوقع ہے۔",
        ),
    },
    TYPE_ALL_CLEAR: {
        1: (
            "The {cleared_type} alert for {district} has ended. Conditions have been clear for "
            "{clear_runs} consecutive checks.",
            "{district} کے لیے {cleared_type} الرٹ ختم ہو گیا ہے۔ مسلسل {clear_runs} جانچوں میں حالات معمول پر ہیں۔",
        ),
    },
    TYPE_OPS: {
        0: (
            "LEHAR platform operations notice. {reason}",
            "لہر پلیٹ فارم آپریشنز اطلاع۔ {reason}",
        ),
    },
}

# Shown on every farmer-facing message so the reader knows what the numbers
# behind it are (CLAUDE.md rules 4 and 13 — the labelling travels with the
# data). OPS messages get their own line instead.
SYNTHETIC_NOTE_EN = (
    "LEHAR's irrigation model is trained on SYNTHETIC research data; weather and river-discharge "
    "values are live Open-Meteo/GloFAS readings."
)
SYNTHETIC_NOTE_UR = (
    "لہر کا آبپاشی ماڈل مصنوعی (synthetic) تحقیقی ڈیٹا پر تربیت یافتہ ہے؛ موسم اور دریائی بہاؤ کی "
    "قدریں Open-Meteo/GloFAS سے حاصل کردہ زندہ ریڈنگز ہیں۔"
)

# LEHAR Phase 2.5. The flood lead-time model is the one model in this project
# trained on REAL measurements rather than synthetic data, and it is also the
# one that asks a farmer to act on a PREDICTION. Both facts are stated on the
# message itself, not left to the documentation (CLAUDE.md rule 13) — added
# as an EXTRA note for this type only, so every other type's message is
# byte-for-byte what it was before this phase (CLAUDE.md rule 1).
EXTRA_NOTES: dict[str, tuple[str, str]] = {
    TYPE_FLOOD_FORECAST: (
        "This is a forecast from a research model trained on REAL data (GloFAS river discharge and ERA5 "
        "weather via Open-Meteo), not an observation and not an official forecast. It may be wrong in "
        "either direction: a flood it did not predict is still possible, and a predicted flood may not "
        "arrive.",
        "یہ ایک تحقیقی ماڈل کی پیش گوئی ہے جو اصل (real) ڈیٹا — Open-Meteo کے ذریعے GloFAS دریائی بہاؤ "
        "اور ERA5 موسمی ڈیٹا — پر تربیت یافتہ ہے؛ یہ مشاہدہ نہیں اور سرکاری پیش گوئی بھی نہیں۔ یہ دونوں "
        "طرف غلط ہو سکتی ہے: جس سیلاب کی پیش گوئی نہ ہو وہ بھی آ سکتا ہے، اور پیش گوئی شدہ سیلاب نہ بھی آئے۔",
    ),
}


class AlertMessage:
    """The four rendered strings stored on an alert row."""

    __slots__ = ("title_en", "title_ur", "body_en", "body_ur")

    def __init__(self, title_en: str, title_ur: str, body_en: str, body_ur: str):
        self.title_en = title_en
        self.title_ur = title_ur
        self.body_en = body_en
        self.body_ur = body_ur

    def as_dict(self) -> dict:
        return {
            "title_en": self.title_en,
            "title_ur": self.title_ur,
            "body_en": self.body_en,
            "body_ur": self.body_ur,
        }


def _fallback_situation(alert_type: str, level: int) -> tuple[str, str]:
    """Used only if a type/level pair has no situation text yet — states
    plainly what fired rather than inventing a description."""
    return (
        f"A level-{level} {alert_type} alert is active for {{district}}. {{reason}}",
        f"{{district}} کے لیے درجہ {level} کا {alert_type} الرٹ فعال ہے۔ {{reason}}",
    )


def render(alert_type: str, level: int, context: dict) -> AlertMessage:
    """Render one alert's bilingual title and body.

    `context` is the rule outcome's `values` merged with its `thresholds`
    and at least {"district": ..., "reason": ...} — engine.py builds it.
    Unknown placeholders render as "n/a"; they never raise."""
    meta = get_level(level)

    title_en_tpl, title_ur_tpl = TITLES.get(alert_type, {}).get(
        level, ("{district}: level {level} alert", "{district}: درجہ {level} الرٹ")
    )
    situation_en_tpl, situation_ur_tpl = SITUATIONS.get(alert_type, {}).get(
        level, _fallback_situation(alert_type, level)
    )

    values = {**context, "level": level}
    title_en = _fmt(title_en_tpl, values)
    title_ur = _fmt(title_ur_tpl, values)

    actions_en = "\n".join(f"- {action}" for action in meta.actions_en)
    actions_ur = "\n".join(f"- {action}" for action in meta.actions_ur)

    body_en_parts = [
        f"[{meta.name_en} — level {meta.number}]",
        _fmt(situation_en_tpl, values),
        f"{ACTIONS_HEADING_EN}\n{actions_en}",
    ]
    body_ur_parts = [
        f"[{meta.name_ur} — درجہ {meta.number}]",
        _fmt(situation_ur_tpl, values),
        f"{ACTIONS_HEADING_UR}\n{actions_ur}",
    ]

    if alert_type != TYPE_OPS:
        body_en_parts.append(SYNTHETIC_NOTE_EN)
        body_ur_parts.append(SYNTHETIC_NOTE_UR)

    extra = EXTRA_NOTES.get(alert_type)
    if extra is not None:
        body_en_parts.append(extra[0])
        body_ur_parts.append(extra[1])

    # CLAUDE.md rule 12 — last line of every message, both languages. The
    # Urdu body repeats the exact English sentence so the mandated wording
    # is verbatim present regardless of the reader's language setting.
    body_en_parts.append(DISCLAIMER_EN)
    body_ur_parts.append(f"{DISCLAIMER_UR}\n{DISCLAIMER_EN}")

    return AlertMessage(
        title_en=title_en,
        title_ur=title_ur,
        body_en="\n\n".join(body_en_parts),
        body_ur="\n\n".join(body_ur_parts),
    )
