"""Smart matching: scores a lost item against found items (and vice versa)."""
import re
from difflib import SequenceMatcher

STOP = {"a", "an", "the", "of", "and", "in", "on", "with", "my", "is", "near", "at"}

def tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP}

def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0

def score(x, y):
    """Return a 0-100 match score between two item dicts."""
    title = SequenceMatcher(None, x["title"].lower(), y["title"].lower()).ratio()
    desc = jaccard(tokens(x["title"] + " " + x["description"]),
                   tokens(y["title"] + " " + y["description"]))
    cat = 1.0 if x["category"] == y["category"] else 0.0
    loc = jaccard(tokens(x["location"]), tokens(y["location"]))
    return round(100 * (0.30 * title + 0.35 * desc + 0.20 * cat + 0.15 * loc))

def best_matches(item, candidates, threshold=35, limit=5):
    scored = [(score(item, c), c) for c in candidates]
    scored = [s for s in scored if s[0] >= threshold]
    return sorted(scored, key=lambda s: s[0], reverse=True)[:limit]
  
