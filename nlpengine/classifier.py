"""
Multinomial Naive Bayes classifier for civic complaints, written from scratch.

Why Naive Bayes and not a deep model?
  * a municipality starts with a few hundred labelled complaints, which is
    exactly the size where Naive Bayes is strongest,
  * training takes milliseconds, so the model can be retrained the moment an
    officer corrects a category,
  * every prediction can be explained by listing the words that pushed it,
    which matters for a government system.

Bayes rule for a complaint d and a category c:

    P(c | d)  is proportional to  P(c) * product over words w in d of P(w | c)

Probabilities are multiplied as logs to avoid floating point underflow, and
Laplace (add-one) smoothing keeps an unseen word from zeroing a whole class.
"""
import math
from collections import Counter, defaultdict

from .corpus import CATEGORY_CORPUS
from .preprocess import features, normalise_text, token_pairs


class NaiveBayesClassifier:
    """A tiny multinomial Naive Bayes text classifier."""

    def __init__(self, alpha=1.0):
        self.alpha = alpha                 # Laplace smoothing constant
        self.log_prior = {}                # category -> log P(c)
        self.word_counts = defaultdict(Counter)   # category -> Counter(word)
        self.category_totals = {}          # category -> total words in class
        self.vocabulary = set()
        self.n_samples = 0
        self.trained = False

    # -- training ---------------------------------------------------------
    def fit(self, samples):
        """samples: iterable of (text, category_code)."""
        docs_per_class = Counter()
        self.word_counts = defaultdict(Counter)
        self.vocabulary = set()

        for text, category in samples:
            tokens = features(text)
            if not tokens:
                continue
            docs_per_class[category] += 1
            self.word_counts[category].update(tokens)
            self.vocabulary.update(tokens)

        self.n_samples = sum(docs_per_class.values())
        if not self.n_samples:
            self.trained = False
            return self

        self.log_prior = {
            c: math.log(n / self.n_samples) for c, n in docs_per_class.items()
        }
        self.category_totals = {
            c: sum(counter.values()) for c, counter in self.word_counts.items()
        }
        self.trained = True
        return self

    # -- prediction -------------------------------------------------------
    def _log_likelihood(self, category, token):
        count = self.word_counts[category][token]
        denominator = self.category_totals[category] + self.alpha * len(self.vocabulary)
        return math.log((count + self.alpha) / denominator)

    def score(self, text):
        """Return {category: posterior probability} for one complaint."""
        if not self.trained:
            return {}
        tokens = [t for t in features(text) if t in self.vocabulary]
        log_scores = {}
        for category in self.log_prior:
            total = self.log_prior[category]
            for token in tokens:
                total += self._log_likelihood(category, token)
            log_scores[category] = total

        # softmax over log-probabilities -> comparable confidence values
        best = max(log_scores.values())
        exponentials = {c: math.exp(s - best) for c, s in log_scores.items()}
        normaliser = sum(exponentials.values()) or 1.0
        return {c: v / normaliser for c, v in exponentials.items()}

    def predict(self, text, top_n=3):
        """Return (category, confidence, ranked list of (category, prob))."""
        probabilities = self.score(text)
        if not probabilities:
            return None, 0.0, []
        ranked = sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[0][0], ranked[0][1], ranked[:top_n]

    def explain(self, text, category, top_n=5):
        """The words that contributed most to choosing this category.

        For each word we compare its likelihood inside the category with its
        likelihood outside it; the biggest positive gaps are the evidence.
        """
        if not self.trained or category not in self.log_prior:
            return []
        others = [c for c in self.log_prior if c != category]
        # stem -> the word the citizen actually typed, so the explanation
        # shown on the dashboard reads "water supply" and not "water suppl".
        spelling = dict(token_pairs(text))
        contributions = []
        for token in set(features(text)):
            if token not in self.vocabulary:
                continue
            inside = self._log_likelihood(category, token)
            outside = max(self._log_likelihood(c, token) for c in others) if others else 0.0
            phrase = " ".join(spelling.get(part, part) for part in token.split("_"))
            contributions.append((phrase, inside - outside))
        contributions.sort(key=lambda kv: kv[1], reverse=True)
        seen, words = set(), []
        for phrase, gain in contributions:
            if gain > 0 and phrase not in seen:
                seen.add(phrase)
                words.append(phrase)
            if len(words) >= top_n:
                break
        return words


# --------------------------------------------------------------------------
# Module level model, so a request does not retrain on every complaint.
# --------------------------------------------------------------------------
_MODEL = None
_MODEL_KEY = None
_MODEL_VERSION = 0


def seed_samples():
    """The built-in corpus as (text, category) pairs."""
    return [(text, code) for code, texts in CATEGORY_CORPUS.items() for text in texts]


def get_model(extra_samples=None, force_reload=False):
    """Return the shared classifier, training it on first use.

    `extra_samples` are the officer-corrected complaints coming from the
    database; passing them in keeps this package free of any Django import.
    """
    global _MODEL, _MODEL_KEY, _MODEL_VERSION
    extra = list(extra_samples or [])
    # Retrain when the officer-corrected samples have changed, otherwise the
    # cached model would keep making the mistake that was just corrected.
    key = (len(extra), hash(tuple(extra)))
    if _MODEL is None or force_reload or key != _MODEL_KEY:
        model = NaiveBayesClassifier()
        model.fit(seed_samples() + extra)
        _MODEL, _MODEL_KEY = model, key
        _MODEL_VERSION += 1
    return _MODEL


def invalidate():
    """Called after an officer re-labels a complaint."""
    global _MODEL, _MODEL_KEY
    _MODEL, _MODEL_KEY = None, None


def classify(text, extra_samples=None):
    """Convenience wrapper -> dict with the decision and its explanation."""
    model = get_model(extra_samples)
    category, confidence, ranked = model.predict(text)
    return {
        "category": category,
        "confidence": round(confidence, 4),
        "ranked": [(c, round(p, 4)) for c, p in ranked],
        "keywords": model.explain(text, category) if category else [],
        "text_length": len(normalise_text(text).split()),
    }
