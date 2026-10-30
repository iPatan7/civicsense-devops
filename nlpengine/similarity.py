"""
Duplicate detection: TF-IDF vectors + cosine similarity + geo distance.

Ten citizens of the same street reporting the same overflowing drain must
become ONE work order with ten supporters, not ten work orders.  Comparing the
raw sentences does not work, because people describe the same thing in
different words, so each complaint is turned into a weighted vector:

    tf(w, d)  = count of w in d / number of words in d
    idf(w)    = log((1 + N) / (1 + df(w))) + 1        (smoothed)
    weight    = tf * idf,  then the vector is L2-normalised

Rare, meaningful words ("manhole") therefore weigh much more than words that
appear in every complaint ("road").  Two complaints are compared with the
cosine of the angle between their vectors, which is 1.0 for identical text and
0.0 when they share nothing.

Text alone is not enough: "pothole near the bus stop" is a different pothole in
a different ward.  The final decision therefore mixes three explainable parts -
how similar the words are, how close the two locations are, and how recent the
older complaint is.
"""
import math
from collections import Counter

from .preprocess import tokenize

EARTH_RADIUS_M = 6_371_000.0


# --------------------------------------------------------------------------
# TF-IDF
# --------------------------------------------------------------------------
class TfidfIndex:
    """A small in-memory TF-IDF index over the currently open complaints."""

    def __init__(self, documents=None):
        self.doc_ids = []
        self.doc_tokens = {}
        self.idf = {}
        self.vectors = {}
        if documents:
            self.build(documents)

    def build(self, documents):
        """documents: iterable of (doc_id, text)."""
        self.doc_ids, self.doc_tokens = [], {}
        for doc_id, text in documents:
            self.doc_ids.append(doc_id)
            self.doc_tokens[doc_id] = tokenize(text)

        n_docs = len(self.doc_ids)
        document_frequency = Counter()
        for tokens in self.doc_tokens.values():
            document_frequency.update(set(tokens))

        self.idf = {
            word: math.log((1 + n_docs) / (1 + df)) + 1.0
            for word, df in document_frequency.items()
        }
        self.vectors = {
            doc_id: self._vectorise(tokens) for doc_id, tokens in self.doc_tokens.items()
        }
        return self

    def _vectorise(self, tokens):
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = len(tokens)
        vector = {
            word: (count / length) * self.idf.get(word, math.log(1 + len(self.doc_ids)) + 1.0)
            for word, count in counts.items()
        }
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        return {word: value / norm for word, value in vector.items()}

    def vector_for(self, text):
        return self._vectorise(tokenize(text))

    def similarities(self, text):
        """Cosine similarity of `text` against every indexed document."""
        query = self.vector_for(text)
        results = {}
        for doc_id, vector in self.vectors.items():
            # both vectors are unit length, so the dot product IS the cosine
            shared = set(query) & set(vector)
            results[doc_id] = sum(query[w] * vector[w] for w in shared)
        return results


def cosine_similarity(text_a, text_b):
    """Similarity of two free-standing texts (used by the unit tests)."""
    index = TfidfIndex([(0, text_a), (1, text_b)])
    return index.similarities(text_a).get(1, 0.0)


def overlap_coefficient(text_a, text_b):
    """|A n B| / min(|A|, |B|) on the word stems.

    Complaints are short - two or three sentences - and TF-IDF alone becomes
    unstable at that length, so plain word overlap is measured as well and the
    two are averaged.  Overlap answers the simple question a clerk would ask:
    "how much of the shorter complaint also appears in the longer one?"
    """
    a, b = set(tokenize(text_a)), set(tokenize(text_b))
    if not a or not b:
        return 0.0
    return len(a & b) / float(min(len(a), len(b)))


def text_similarity(text_a, text_b):
    """The blended textual score used for duplicate detection."""
    return 0.5 * cosine_similarity(text_a, text_b) + 0.5 * overlap_coefficient(text_a, text_b)


# --------------------------------------------------------------------------
# Geography
# --------------------------------------------------------------------------
def haversine_metres(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points, in metres."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# The duplicate decision
# --------------------------------------------------------------------------
TEXT_WEIGHT = 0.70
PLACE_WEIGHT = 0.20
TIME_WEIGHT = 0.10
MIN_TEXT_SIMILARITY = 0.35      # below this the words are simply different
MIN_PLACE_SCORE = 0.35          # the same problem must be at the same place


def _place_score(candidate, latitude, longitude, ward, radius_m):
    """1.0 = same spot, 0.0 = far away.  Falls back to the ward when the
    citizen did not share GPS coordinates."""
    distance = haversine_metres(
        latitude, longitude, candidate.get("latitude"), candidate.get("longitude")
    )
    if distance is None:
        same_ward = ward is not None and ward == candidate.get("ward")
        return (0.75 if same_ward else 0.15), None
    return max(0.0, 1.0 - min(distance / radius_m, 1.0)), distance


def find_similar(text, candidates, latitude=None, longitude=None, ward=None,
                 category=None, threshold=0.62, radius_m=300, window_days=30,
                 limit=5):
    """Rank existing complaints against a new one.

    `candidates` is a list of dicts with the keys: id, text, latitude,
    longitude, ward, age_days, category.  The function is pure - the Django
    layer decides what to do with the ranking.
    """
    candidates = [c for c in candidates if c.get("text")]
    if not candidates:
        return []

    # complaints older than the window describe a different event, even when
    # the words match, so they are not candidates at all
    candidates = [c for c in candidates if (c.get("age_days") or 0) <= window_days]
    if not candidates:
        return []

    index = TfidfIndex([(c["id"], c["text"]) for c in candidates])
    cosine_scores = index.similarities(text)

    results = []
    for candidate in candidates:
        cosine = cosine_scores.get(candidate["id"], 0.0)
        overlap = overlap_coefficient(text, candidate["text"])
        similarity = 0.5 * cosine + 0.5 * overlap
        if similarity < MIN_TEXT_SIMILARITY:
            continue

        place, distance = _place_score(candidate, latitude, longitude, ward, radius_m)
        age_days = candidate.get("age_days") or 0
        recency = max(0.0, 1.0 - min(age_days / float(window_days), 1.0))

        score = TEXT_WEIGHT * similarity + PLACE_WEIGHT * place + TIME_WEIGHT * recency

        # A different service category is a strong signal of a different issue.
        if category and candidate.get("category") and candidate["category"] != category:
            score *= 0.75

        results.append({
            "id": candidate["id"],
            "text_similarity": round(similarity, 4),
            "cosine": round(cosine, 4),
            "word_overlap": round(overlap, 4),
            "place_score": round(place, 4),
            "recency_score": round(recency, 4),
            "distance_m": None if distance is None else round(distance),
            "score": round(score, 4),
            # Identical words are not enough: two wards can report the very
            # same sentence about two different potholes, so a complaint is
            # only merged when the location agrees as well.
            "is_duplicate": (score >= threshold and similarity >= 0.45
                             and place >= MIN_PLACE_SCORE),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]
