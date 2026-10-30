"""
Word lists used by the sentiment analyser and the priority scorer.

A municipal corpus is small and very domain specific, so a hand-built lexicon
beats a generic pre-trained model here and, more importantly, every decision it
makes can be explained to a citizen who asks "why was my complaint marked
low priority?".
"""

# --- Sentiment ------------------------------------------------------------
NEGATIVE_WORDS = {
    "bad": 1, "worst": 2, "terrible": 2, "horrible": 2, "pathetic": 2,
    "awful": 2, "disgusting": 2, "filthy": 2, "stink": 2, "stench": 2,
    "unbearable": 2, "useless": 2, "careless": 1, "negligence": 2,
    "negligent": 2, "ignored": 2, "ignoring": 2, "harassed": 2, "suffering": 2,
    "suffer": 2, "trouble": 1, "problem": 1, "issue": 1, "broken": 1,
    "damaged": 1, "leaking": 1, "overflowing": 2, "blocked": 1, "dirty": 1,
    "dangerous": 2, "unsafe": 2, "risk": 1, "hazard": 2, "accident": 2,
    "injury": 2, "injured": 2, "died": 3, "death": 3, "fear": 1, "angry": 2,
    "frustrated": 2, "disappointed": 1, "complaint": 1, "repeated": 1,
    "again": 1, "still": 1, "delay": 1, "delayed": 1, "pending": 1,
    "nobody": 1, "nothing": 1, "shame": 2, "worse": 2, "stuck": 1,
}

POSITIVE_WORDS = {
    "good": 1, "great": 1, "clean": 1, "resolved": 2, "fixed": 2, "quick": 1,
    "fast": 1, "thanks": 1, "appreciate": 2, "happy": 2, "satisfied": 2,
    "excellent": 2, "helpful": 1, "prompt": 1, "working": 1, "better": 1,
}

INTENSIFIERS = {"very": 1.5, "extremely": 1.8, "highly": 1.5, "totally": 1.4,
                "completely": 1.5, "absolutely": 1.6, "really": 1.3,
                "too": 1.3, "so": 1.2, "utterly": 1.7}

# --- Urgency --------------------------------------------------------------
# Weight = how much the phrase pushes the complaint up the queue (0-1 scale
# before normalisation).
URGENCY_WORDS = {
    # life-threatening
    "emergency": 1.0, "urgent": 0.8, "immediately": 0.7, "immediate": 0.7,
    "danger": 0.9, "dangerous": 0.9, "fire": 1.0, "electrocution": 1.0,
    "shock": 0.8, "live wire": 1.0, "gas leak": 1.0, "collapse": 1.0,
    "collapsed": 1.0, "accident": 0.9, "injured": 0.9, "injury": 0.9,
    "death": 1.0, "died": 1.0, "fatal": 1.0, "bleeding": 0.9, "trapped": 1.0,
    "drowning": 1.0, "electric shock": 1.0, "short circuit": 0.9,
    # health hazard
    "disease": 0.7, "dengue": 0.8, "malaria": 0.8, "cholera": 0.9,
    "epidemic": 0.9, "infection": 0.7, "contaminated": 0.8, "poison": 0.9,
    "sewage": 0.6, "overflow": 0.6, "overflowing": 0.6, "stagnant": 0.6,
    "mosquito": 0.5, "rats": 0.4, "stray dog": 0.6, "snake": 0.7,
    # vulnerable people / public places
    "school": 0.5, "hospital": 0.7, "children": 0.5, "child": 0.5,
    "elderly": 0.5, "pregnant": 0.6, "ambulance": 0.8, "patient": 0.6,
    "handicapped": 0.5, "blind": 0.5,
    # scale
    "entire": 0.4, "whole": 0.4, "colony": 0.3, "society": 0.3,
    "residents": 0.3, "everyone": 0.3, "many": 0.2, "several": 0.2,
    # persistence
    "weeks": 0.4, "week": 0.3, "months": 0.5, "month": 0.4, "days": 0.2,
    "years": 0.6, "year": 0.5, "repeatedly": 0.4,
    "again": 0.2, "still": 0.2, "third time": 0.5, "no response": 0.5,
}

# Multi-word urgency phrases are checked on the raw (normalised) text.
URGENCY_PHRASES = {
    "live wire": 1.0, "gas leak": 1.0, "electric shock": 1.0,
    "short circuit": 0.9, "no water": 0.6, "no electricity": 0.6,
    "wall collapse": 1.0, "tree fallen": 0.8, "manhole open": 0.9,
    "open manhole": 0.9, "school children": 0.7, "no response": 0.5,
    "third time": 0.5, "since months": 0.6, "since weeks": 0.4,
}
