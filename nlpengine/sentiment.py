"""
Lexicon based sentiment and urgency scoring.

The tone of a complaint is a genuine signal for a municipality: "the drain is
choked" and "the drain has been choked for two months, sewage is entering my
house, my child is sick" describe the same category but not the same
situation.  Two numbers are produced:

    polarity  -1.0 (very angry / distressed)  ...  +1.0 (appreciation)
    urgency    0.0 (routine)                  ...   1.0 (emergency)

Both are computed from word lists (see lexicon.py) with two linguistic rules:
an intensifier multiplies the next word ("very bad" > "bad") and a negation
flips it ("not clean" becomes negative).
"""
from .lexicon import (INTENSIFIERS, NEGATIVE_WORDS, POSITIVE_WORDS,
                      URGENCY_PHRASES, URGENCY_WORDS)
from .preprocess import NEGATIONS, normalise_text, stem

# The lexicons list base words; citizens write "cleaned", "leaking", "thanks".
# Stemmed copies are built once at import so both forms are recognised.
_NEGATIVE_STEMS = {stem(word): weight for word, weight in NEGATIVE_WORDS.items()}
_POSITIVE_STEMS = {stem(word): weight for word, weight in POSITIVE_WORDS.items()}
_URGENCY_STEMS = {stem(word): weight for word, weight in URGENCY_WORDS.items()}


def _weight_of(word, table, stem_table):
    """Look the word up directly, then by its stem."""
    if word in table:
        return table[word]
    return stem_table.get(stem(word), 0)


def analyse_sentiment(text):
    """Return {'polarity', 'label', 'negative_hits', 'positive_hits'}."""
    words = normalise_text(text).split()
    positive = negative = 0.0
    negative_hits, positive_hits = [], []
    multiplier = 1.0
    negate_for = 0          # a negation colours the next few words

    for word in words:
        if word in INTENSIFIERS:            # "very", "extremely"
            multiplier = INTENSIFIERS[word]
            continue
        if word in NEGATIONS:               # "not", "no", "never"
            negate_for = 3
            continue

        weight = 0.0
        negative_weight = _weight_of(word, NEGATIVE_WORDS, _NEGATIVE_STEMS)
        positive_weight = _weight_of(word, POSITIVE_WORDS, _POSITIVE_STEMS)
        if negative_weight:
            weight = -negative_weight * multiplier
        elif positive_weight:
            weight = positive_weight * multiplier

        if not weight:
            negate_for = max(0, negate_for - 1)
            continue

        if negate_for:                      # "not working" -> negative
            weight = -weight * 0.8
            negate_for = 0
        if weight < 0:
            negative += -weight
            negative_hits.append(word)
        else:
            positive += weight
            positive_hits.append(word)
        multiplier = 1.0

    total = positive + negative
    # The denominator never goes below 4, otherwise a single word such as
    # "problem" would give a full -1.0 and every complaint would look furious.
    polarity = 0.0 if total == 0 else (positive - negative) / max(total, 4.0)
    if polarity <= -0.4:
        label = "ANGRY"
    elif polarity < -0.05:
        label = "NEGATIVE"
    elif polarity <= 0.2:
        label = "NEUTRAL"
    else:
        label = "POSITIVE"

    return {
        "polarity": round(polarity, 3),
        "label": label,
        "negative_hits": negative_hits[:6],
        "positive_hits": positive_hits[:6],
        "intensity": round(min(total / 6.0, 1.0), 3),
    }


def analyse_urgency(text):
    """Return {'urgency', 'triggers'} - how fast this needs a crew on site."""
    normalised = normalise_text(text)
    words = normalised.split()
    triggers = []
    weights = []

    for phrase, weight in URGENCY_PHRASES.items():
        if phrase in normalised:
            weights.append(weight)
            triggers.append(phrase)

    for word in words:
        weight = _weight_of(word, URGENCY_WORDS, _URGENCY_STEMS)
        if weight:
            weights.append(weight)
            triggers.append(word)

    if not weights:
        return {"urgency": 0.0, "triggers": []}

    weights.sort(reverse=True)
    # The strongest signal decides, the rest can only add a little; three
    # medium words must not outrank one "live wire".
    urgency = weights[0] + sum(w * 0.15 for w in weights[1:4])
    ordered, seen = [], set()
    for trigger in triggers:
        if trigger not in seen:
            seen.add(trigger)
            ordered.append(trigger)
    return {"urgency": round(min(urgency, 1.0), 3), "triggers": ordered[:6]}
