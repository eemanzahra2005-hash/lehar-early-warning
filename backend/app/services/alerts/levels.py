"""LEHAR alert levels — the single source of truth for the scheme.

Five farmer-facing levels plus one admin-only OPS level, adapted for
farmers from Japan's five-level disaster alert system (the JMA / Cabinet
Office "warning levels": 1 White early advisory, 2 Yellow advisory,
3 Red warning, 4 Purple urgent warning, 5 Black emergency). The colours and
the "the number IS the urgency" idea are taken from that scheme; the
thresholds behind them are this project's own (see rules.py and
docs/ALERT_LEVELS.md).

Everything the API, the templates and the docs say about a level is read
from LEVELS below — nothing re-declares a colour, a channel list or an
action anywhere else. GET /api/v1/alerts/levels serves this verbatim.

CLAUDE.md rule 12: DISCLAIMER_EN is appended to every message this system
produces, in both languages, by templates.py. It lives here rather than in
templates.py so there is exactly one copy of the mandated wording.
"""

from dataclasses import dataclass, field

# The exact wording CLAUDE.md rule 12 requires on every surface that can
# show an alert or a flood state. Never reworded, never abbreviated.
DISCLAIMER_EN = "Research advisory — NDMA/PMD/PDMA official warnings are authoritative."
DISCLAIMER_UR = "تحقیقی مشورہ — این ڈی ایم اے/پی ایم ڈی/پی ڈی ایم اے کی سرکاری وارننگ ہی مستند ہے۔"

# Delivery channel identifiers. Only IN_APP actually delivers in Phase 2 —
# TELEGRAM and EMAIL are declared here (and matched against subscriptions)
# so the level metadata is complete and the console can render it, but
# their transports arrive in Phase 3. See channels.py.
CHANNEL_IN_APP = "in_app"
CHANNEL_TELEGRAM = "telegram"
CHANNEL_EMAIL = "email"

# The OPS level is deliberately number 0, not 6: it sits OUTSIDE the
# farmer-facing 1-5 urgency ladder rather than above level 5. A grey
# operations notice must never sort as "worse than an emergency".
OPS_LEVEL = 0

FARMER_LEVELS = (1, 2, 3, 4, 5)

AUDIENCE_FARMER = "farmer"
AUDIENCE_ADMIN = "admin"


@dataclass(frozen=True)
class AlertLevel:
    """One level's complete, immutable metadata."""

    number: int
    key: str
    color_hex: str
    # Foreground colour with sufficient contrast on color_hex — carried here
    # so the console and the local frontend can't each guess differently.
    text_color_hex: str
    name_en: str
    name_ur: str
    audience: str  # AUDIENCE_FARMER | AUDIENCE_ADMIN
    summary_en: str
    summary_ur: str
    channels: tuple[str, ...]
    # True for levels 4 and 5 only: the console/frontend interrupts whatever
    # the user is doing with a full-screen takeover instead of a banner.
    full_screen_takeover: bool
    actions_en: tuple[str, ...] = field(default_factory=tuple)
    actions_ur: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        """Plain-JSON form served by GET /api/v1/alerts/levels."""
        return {
            "number": self.number,
            "key": self.key,
            "color_hex": self.color_hex,
            "text_color_hex": self.text_color_hex,
            "name_en": self.name_en,
            "name_ur": self.name_ur,
            "audience": self.audience,
            "summary_en": self.summary_en,
            "summary_ur": self.summary_ur,
            "channels": list(self.channels),
            "full_screen_takeover": self.full_screen_takeover,
            "actions_en": list(self.actions_en),
            "actions_ur": list(self.actions_ur),
            "disclaimer_en": DISCLAIMER_EN,
            "disclaimer_ur": DISCLAIMER_UR,
        }


LEVELS: dict[int, AlertLevel] = {
    OPS_LEVEL: AlertLevel(
        number=OPS_LEVEL,
        key="OPS",
        color_hex="#6B7280",
        text_color_hex="#FFFFFF",
        name_en="Operations Notice",
        name_ur="آپریشنز اطلاع",
        audience=AUDIENCE_ADMIN,
        summary_en="Platform health only — model drift, quality gate or rollback. Never shown to farmers.",
        summary_ur="صرف نظام کی کارکردگی — ماڈل ڈرفٹ، کوالٹی گیٹ یا رول بیک۔ کسانوں کو کبھی نہیں دکھایا جاتا۔",
        channels=(CHANNEL_IN_APP,),
        full_screen_takeover=False,
        actions_en=(
            "Admin only — no farmer action.",
            "Open the Monitoring page and review drift, the quality gate and the served model version.",
        ),
        actions_ur=(
            "صرف منتظم کے لیے — کسان کے لیے کوئی کارروائی نہیں۔",
            "مانیٹرنگ صفحہ کھولیں اور ڈرفٹ، کوالٹی گیٹ اور زیرِ استعمال ماڈل ورژن کا جائزہ لیں۔",
        ),
    ),
    1: AlertLevel(
        number=1,
        key="L1",
        color_hex="#FFFFFF",
        text_color_hex="#111827",
        name_en="Early Advisory",
        name_ur="ابتدائی اطلاع",
        audience=AUDIENCE_FARMER,
        # Level 1 is the CALM BASELINE, not an event. It is what
        # GET /api/v1/alerts/active computes for any district with no
        # active alert (nothing is stored for a calm district — see
        # engine.py's highest_active_by_district and rules.py's
        # FLOOD_CALM_BANDS). The only level-1 rows the engine writes are
        # IRRIGATION_DUE, which is about one saved field rather than a
        # district-wide state, and ALL_CLEAR.
        summary_en="The normal state: nothing is happening here. No danger — plan normally.",
        summary_ur="معمول کی حالت: یہاں کچھ نہیں ہو رہا۔ کوئی خطرہ نہیں — معمول کے مطابق منصوبہ بندی کریں۔",
        channels=(CHANNEL_IN_APP,),
        full_screen_takeover=False,
        actions_en=(
            "Check today's forecast and your field's soil moisture.",
            "No protective action needed yet — plan your next irrigation normally.",
            "Keep watching LEHAR for updates.",
        ),
        actions_ur=(
            "آج کی پیش گوئی اور اپنے کھیت کی نمی دیکھیں۔",
            "ابھی حفاظتی کارروائی ضروری نہیں — اگلی آبپاشی معمول کے مطابق کریں۔",
            "تازہ معلومات کے لیے لہر دیکھتے رہیں۔",
        ),
    ),
    2: AlertLevel(
        number=2,
        key="L2",
        color_hex="#FFD400",
        text_color_hex="#111827",
        name_en="Advisory",
        name_ur="انتباہ",
        audience=AUDIENCE_FARMER,
        summary_en="Conditions are turning bad. Prepare the field and delay irrigation.",
        summary_ur="حالات خراب ہو رہے ہیں۔ کھیت تیار کریں اور آبپاشی مؤخر کریں۔",
        channels=(CHANNEL_IN_APP, CHANNEL_TELEGRAM, CHANNEL_EMAIL),
        full_screen_takeover=False,
        actions_en=(
            "Delay any planned irrigation until this advisory clears.",
            "Clear field drains and check tubewell and canal outlets.",
            "Move portable equipment and stored fertiliser to higher ground.",
        ),
        actions_ur=(
            "یہ انتباہ ختم ہونے تک منصوبہ بند آبپاشی مؤخر کریں۔",
            "کھیت کی نالیاں صاف کریں اور ٹیوب ویل و نہری موگھے چیک کریں۔",
            "قابلِ منتقلی سامان اور ذخیرہ شدہ کھاد اونچی جگہ منتقل کریں۔",
        ),
    ),
    3: AlertLevel(
        number=3,
        key="L3",
        color_hex="#E03131",
        text_color_hex="#FFFFFF",
        name_en="Warning",
        name_ur="وارننگ",
        audience=AUDIENCE_FARMER,
        summary_en="Damaging conditions are expected. Protect the crop, the livestock and the household.",
        summary_ur="نقصان دہ حالات متوقع ہیں۔ فصل، مویشی اور گھرانے کو محفوظ بنائیں۔",
        channels=(CHANNEL_IN_APP, CHANNEL_TELEGRAM, CHANNEL_EMAIL),
        full_screen_takeover=False,
        actions_en=(
            "Stop irrigation now and protect the crop that can still be saved.",
            "Move livestock, machinery and stored grain to higher ground.",
            "Keep documents, cash and medicines ready in one bag.",
        ),
        actions_ur=(
            "آبپاشی فوراً بند کریں اور جو فصل بچ سکتی ہے اسے محفوظ کریں۔",
            "مویشی، مشینری اور ذخیرہ شدہ اناج اونچی جگہ منتقل کریں۔",
            "کاغذات، نقدی اور ادویات ایک بیگ میں تیار رکھیں۔",
        ),
    ),
    4: AlertLevel(
        number=4,
        key="L4",
        color_hex="#7B2FBF",
        text_color_hex="#FFFFFF",
        name_en="Urgent Warning",
        name_ur="فوری وارننگ",
        audience=AUDIENCE_FARMER,
        summary_en="Move people and animals now. Do not wait for the water to arrive.",
        summary_ur="لوگوں اور جانوروں کو ابھی منتقل کریں۔ پانی آنے کا انتظار نہ کریں۔",
        channels=(CHANNEL_IN_APP, CHANNEL_TELEGRAM, CHANNEL_EMAIL),
        full_screen_takeover=True,
        actions_en=(
            "Prepare to evacuate now — do not wait for water to reach the field.",
            "Move all livestock and everyone at home to the nearest safe high ground or shelter.",
            "Follow NDMA/PDMA instructions and local announcements.",
        ),
        actions_ur=(
            "ابھی نقل مکانی کی تیاری کریں — پانی کے کھیت تک پہنچنے کا انتظار نہ کریں۔",
            "تمام مویشی اور گھر کے سب افراد کو قریبی محفوظ بلند جگہ یا پناہ گاہ منتقل کریں۔",
            "این ڈی ایم اے/پی ڈی ایم اے کی ہدایات اور مقامی اعلانات پر عمل کریں۔",
        ),
    ),
    5: AlertLevel(
        number=5,
        key="L5",
        color_hex="#0B0B0B",
        text_color_hex="#FFFFFF",
        name_en="Emergency",
        name_ur="ہنگامی حالت",
        audience=AUDIENCE_FARMER,
        summary_en="Life-threatening situation. Leave everything and get to safety.",
        summary_ur="جان لیوا صورتحال۔ سب کچھ چھوڑ کر محفوظ جگہ پہنچیں۔",
        channels=(CHANNEL_IN_APP, CHANNEL_TELEGRAM, CHANNEL_EMAIL),
        full_screen_takeover=True,
        actions_en=(
            "Evacuate immediately to the nearest safe high ground or relief camp.",
            "Leave crops, machinery and belongings behind — life first.",
            "Call 1122 or your local rescue service if you cannot move safely.",
        ),
        actions_ur=(
            "فوراً قریبی محفوظ بلند جگہ یا ریلیف کیمپ کی طرف نقل مکانی کریں۔",
            "فصل، مشینری اور سامان چھوڑ دیں — پہلے جان بچائیں۔",
            "اگر محفوظ طریقے سے نہ نکل سکیں تو 1122 یا مقامی ریسکیو کو کال کریں۔",
        ),
    ),
}


def get_level(number: int) -> AlertLevel:
    """The AlertLevel for `number`. Raises KeyError for an unknown level —
    deliberately loud: every level a rule can produce is declared above, so
    an unknown number means a rule and this table have gone out of sync."""
    return LEVELS[number]


def is_valid_level(number: int) -> bool:
    return number in LEVELS


def channels_for(number: int) -> tuple[str, ...]:
    return LEVELS[number].channels


def all_levels() -> list[dict]:
    """Every level as plain JSON, OPS (0) first, then 1-5 ascending."""
    return [LEVELS[number].as_dict() for number in sorted(LEVELS)]
