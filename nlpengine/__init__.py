"""
CivicSense NLP engine.

A deliberately dependency-free package (standard library only) that performs
the four language tasks of the platform:

    classifier.py  - which department does this complaint belong to?
    similarity.py  - has somebody already reported this?
    sentiment.py   - how distressed / how urgent does it sound?
    priority.py    - which complaint should the crew attend first?

Nothing here imports Django, so the whole engine can be unit-tested on its own
and could be lifted into a separate micro-service without any change.
"""
from .classifier import classify, get_model, invalidate, seed_samples
from .priority import SLA_HOURS, band_for, score_complaint
from .sentiment import analyse_sentiment, analyse_urgency
from .similarity import (TfidfIndex, cosine_similarity, find_similar,
                         haversine_metres, overlap_coefficient, text_similarity)

__all__ = [
    "analyse_complaint", "classify", "get_model", "invalidate", "seed_samples",
    "score_complaint", "band_for", "SLA_HOURS", "analyse_sentiment",
    "analyse_urgency", "find_similar", "cosine_similarity", "text_similarity",
    "overlap_coefficient", "haversine_metres", "TfidfIndex",
]


def analyse_complaint(text, category_severity=0.5, supporters=0,
                      sla_fraction_used=0.0, extra_samples=None):
    """One call that runs the whole pipeline on a piece of complaint text."""
    classification = classify(text, extra_samples=extra_samples)
    sentiment = analyse_sentiment(text)
    urgency = analyse_urgency(text)
    priority = score_complaint(
        text,
        category_severity=category_severity,
        supporters=supporters,
        sla_fraction_used=sla_fraction_used,
        sentiment=sentiment,
        urgency=urgency,
    )
    return {"classification": classification, "sentiment": sentiment,
            "urgency": urgency, "priority": priority}
