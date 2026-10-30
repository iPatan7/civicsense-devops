"""
Text pre-processing for the complaint NLP pipeline.

Everything here is plain Python: a complaint written by a citizen is turned
into a clean list of word stems, which is the input every later stage
(classifier, duplicate detector, priority scorer) works on.

    "The Street Lights on MG Road are NOT working since 3 days!!"
        -> ['street', 'light', 'mg', 'road', 'not', 'work', 'since', '3', 'days']
"""
import re
import unicodedata

# Words that appear in almost every complaint and therefore carry no
# information for classification or duplicate detection.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "is", "am", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "doing",
    "of", "at", "by", "for", "with", "about", "into", "to", "from", "in", "on",
    "off", "over", "under", "again", "then", "once", "here", "there", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "than", "too", "s", "t", "can", "will", "just", "should", "now", "i", "me",
    "my", "we", "our", "you", "your", "he", "she", "it", "its", "they", "them",
    "their", "this", "that", "these", "those", "as", "so", "up", "out", "who",
    "whom", "which", "what", "when", "where", "why", "how", "also", "please",
    "kindly", "sir", "madam", "respected", "dear", "request", "requesting",
    "hello", "hi", "regards", "thanks", "thank", "you", "would", "could",
    "shall", "may", "might", "must", "get", "got", "one", "two", "us",
}

# "not", "no", "never" are deliberately KEPT: "water is not coming" must not
# become the same text as "water is coming".
NEGATIONS = {"not", "no", "never", "nor", "cannot", "cant", "dont", "doesnt", "isnt"}
STOPWORDS -= NEGATIONS

# Short forms citizens actually type, mapped to the word the engine knows.
NORMALISE = {
    "govt": "government", "corp": "corporation", "muncipal": "municipal",
    "municiple": "municipal", "streetlight": "street light",
    "street-light": "street light", "watersupply": "water supply",
    "sewerage": "sewer", "drainage": "drain", "garbge": "garbage",
    "garbge,": "garbage", "rubbish": "garbage", "trash": "garbage",
    "kachra": "garbage", "nala": "drain", "gaddha": "pothole",
    "bijli": "electricity", "pani": "water", "sadak": "road",
    "pls": "please", "plz": "please", "u": "you", "n": "and",
    "&": "and", "yrs": "years", "hrs": "hours", "mnth": "month",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# A tiny Porter-style suffix stripper.  It is not a full stemmer, but it makes
# "lights/lighting/lighted" collapse to one token, which is all the TF-IDF
# comparison needs.
_SUFFIXES = ("ication", "ation", "ement", "ingly", "edly", "ness",
             "ion", "ing", "er", "ed")
_MIN_STEM_LENGTH = 4   # "water" must not be cut down to "wat"


def normalise_text(text):
    """Lower-case, remove accents and collapse whitespace/punctuation."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"https?://\S+", " ", text)          # drop links
    text = re.sub(r"[^a-z0-9\s]", " ", text)           # drop punctuation
    return re.sub(r"\s+", " ", text).strip()


def stem(word):
    """Strip plural and the longest known suffix, keeping a readable base.

    "lights", "lighting", "lighted" -> "light";  "dogs" -> "dog";
    "water" stays "water" instead of being cut down to "wat".
    """
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:              # supplies -> supply
        word = word[:-3] + "y"
    elif len(word) > 4 and word.endswith(("ches", "shes", "xes", "zes", "sses")):
        word = word[:-2]                                    # boxes, wishes
    elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        word = word[:-1]                                    # dogs -> dog
    if len(word) <= _MIN_STEM_LENGTH:
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM_LENGTH:
            base = word[: -len(suffix)]
            # "running" -> "runn" -> "run" (only when a real word is left)
            if len(base) > _MIN_STEM_LENGTH and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            return base
    return word


def tokenize(text, remove_stopwords=True, apply_stem=True):
    """Full pipeline: normalise -> expand short forms -> tokens -> stems."""
    words = _TOKEN_RE.findall(normalise_text(text))
    expanded = []
    for word in words:
        expanded.extend(NORMALISE.get(word, word).split())
    tokens = []
    for word in expanded:
        if remove_stopwords and word in STOPWORDS:
            continue
        tokens.append(stem(word) if apply_stem else word)
    return tokens


def token_pairs(text):
    """[(stem, original word)] - used to show explanations in plain words."""
    words = _TOKEN_RE.findall(normalise_text(text))
    expanded = []
    for word in words:
        expanded.extend(NORMALISE.get(word, word).split())
    return [(stem(w), w) for w in expanded if w not in STOPWORDS]


def bigrams(tokens):
    """Word pairs, so that 'no water' is different from 'no light'."""
    return ["%s_%s" % (tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]


def features(text):
    """Tokens + bigrams: the feature list used by the Naive Bayes classifier."""
    tokens = tokenize(text)
    return tokens + bigrams(tokens)
