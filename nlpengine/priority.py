"""
Priority scoring.

A ward office receives far more complaints than it can attend to in a day, so
the queue order decides who suffers.  Instead of a clerk's guess, every
complaint gets a transparent score out of 100 built from five parts:

    severity      35  how serious this type of problem is (set per category)
    urgency       30  emergency wording found in the text
    corroboration 15  how many other citizens reported the same thing
    distress      10  how negative the tone of the complaint is
    ageing        10  how much of its SLA time has already been used

    LOW  < 35 <= MEDIUM < 55 <= HIGH < 75 <= CRITICAL

Because the parts are added, the dashboard can show a citizen exactly why a
complaint is CRITICAL - which is impossible with a black-box model.
"""
from .corpus import CRITICAL_PATTERNS
from .preprocess import normalise_text
from .sentiment import analyse_sentiment, analyse_urgency

WEIGHTS = {
    "severity": 35.0,
    "urgency": 30.0,
    "corroboration": 15.0,
    "distress": 10.0,
    "ageing": 10.0,
}

BANDS = ((75, "CRITICAL"), (55, "HIGH"), (35, "MEDIUM"), (0, "LOW"))

# How long a crew may take, in hours, before the complaint breaches its SLA.
SLA_HOURS = {"CRITICAL": 6, "HIGH": 24, "MEDIUM": 72, "LOW": 168}


def band_for(score):
    for minimum, label in BANDS:
        if score >= minimum:
            return label
    return "LOW"


def has_critical_pattern(text):
    """Some phrases are an emergency whatever the arithmetic says."""
    normalised = normalise_text(text)
    return [p for p in CRITICAL_PATTERNS if p in normalised]


def score_complaint(text, category_severity=0.5, supporters=0,
                    sla_fraction_used=0.0, sentiment=None, urgency=None):
    """Return the full priority breakdown for one complaint.

    category_severity : 0.0 - 1.0, configured per category by the municipality
    supporters        : number of other citizens who reported / upvoted it
    sla_fraction_used : 0.0 at the moment of filing, 1.0 when the SLA is over
    """
    sentiment = sentiment or analyse_sentiment(text)
    urgency = urgency or analyse_urgency(text)

    distress = max(0.0, -sentiment["polarity"])          # only anger counts
    corroboration = min(supporters / 5.0, 1.0)           # 5 reports = full mark
    ageing = min(max(sla_fraction_used, 0.0), 1.0)

    parts = {
        "severity": WEIGHTS["severity"] * max(0.0, min(category_severity, 1.0)),
        "urgency": WEIGHTS["urgency"] * urgency["urgency"],
        "corroboration": WEIGHTS["corroboration"] * corroboration,
        "distress": WEIGHTS["distress"] * distress,
        "ageing": WEIGHTS["ageing"] * ageing,
    }
    score = sum(parts.values())

    critical_matches = has_critical_pattern(text)
    if critical_matches:
        score = max(score, 80.0)     # never let an emergency sit in the queue

    score = round(min(score, 100.0), 1)
    priority = band_for(score)
    return {
        "score": score,
        "priority": priority,
        "sla_hours": SLA_HOURS[priority],
        "parts": {k: round(v, 1) for k, v in parts.items()},
        "critical_patterns": critical_matches,
        "urgency_triggers": urgency["triggers"],
        "sentiment": sentiment["label"],
        "polarity": sentiment["polarity"],
        "reasons": build_reasons(parts, critical_matches, urgency, sentiment,
                                 supporters, ageing),
    }


def build_reasons(parts, critical_matches, urgency, sentiment, supporters, ageing):
    """Short human sentences shown next to the priority badge."""
    reasons = []
    if critical_matches:
        reasons.append("Emergency wording detected: %s" % ", ".join(critical_matches[:2]))
    if urgency["triggers"]:
        reasons.append("Urgency words: %s" % ", ".join(urgency["triggers"][:3]))
    if parts["severity"] >= 24:
        reasons.append("This category is a high-severity civic service")
    if supporters:
        reasons.append("%d other citizen(s) reported the same problem" % supporters)
    if sentiment["label"] in ("ANGRY", "NEGATIVE"):
        reasons.append("Tone of the complaint is %s" % sentiment["label"].lower())
    if ageing >= 0.75:
        reasons.append("Most of the SLA time has already been used")
    return reasons or ["Routine request, no urgency indicators found"]
