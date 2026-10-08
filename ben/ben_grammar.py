"""Quick Dutch grammar rules: is "ben" in a chat message the name Ben or the verb (ik ben)?

guess() returns True (name, talking to/about Ben), False (verb) or None (can't tell).
"""

from __future__ import annotations

import re

PRONOUNS = {"ik", "je", "jij", "u", "we", "wij", "ze", "zij", "hij", "jullie"}
GREETINGS = {"hey", "hi", "hoi", "hallo", "hello", "yo", "he", "hé", "heey", "hee", "ey", "oi", "goeiemorgen",
             "goedemorgen", "morgen", "dag", "doei", "dankjewel", "dankje", "bedankt", "thanks", "thx", "sorry",
             "oke", "ok", "okay", "oké", "zeg", "toch", "wacht", "kom", "joh", "nou", "ah", "oh", "lieve", "beste"}
# words right before "ben" that make it a name: "vraag het aan ben", "dat vindt ben ook"
NAME_BEFORE = {"aan", "vraag", "vragen", "vraagt", "vindt", "zegt", "denkt", "weet", "wil", "kan", "moet", "zou",
               "mag", "gaat", "heeft", "is", "was", "met", "van", "voor", "tegen", "hoor", "zei"}
# verbs/question words that follow a name: "ben is...", "ben heeft...", "ben gaat robin winnen"
FOLLOWS_NAME = {"is", "heeft", "gaat", "kan", "moet", "wil", "zou", "mag", "wordt", "weet", "vindt", "denkt",
                "zegt", "zal", "kun", "kunt", "hoe", "waarom", "wie", "wanneer", "welke", "zeg", "vertel", "kom",
                "help", "luister", "check", "kijk"}
ENGLISH = {"do", "does", "did", "what", "can", "could", "are", "will", "would", "should", "how", "why", "where",
           "who", "tell", "say", "please", "yes", "you", "is", "have", "has", "answer"}
# first word after a subject-less "ben" (= ik ben): "ben zo terug", "ben op school", "ben net wakker"
AFTER_DROPPED_IK = {"zo", "er", "al", "nu", "net", "even", "eventjes", "ff", "effe", "efkes", "bijna", "op", "aan",
                    "om", "in", "thuis", "moe", "echt", "wel", "niet", "nooit", "heel", "super", "te", "gewoon",
                    "nog", "best", "klaar", "terug", "weg", "back", "afk", "online", "offline", "benieuwd",
                    "gisteren", "vandaag", "vanavond", "morgen", "druk", "bezig", "ziek", "kapot", "blij", "boos",
                    "bang", "met", "bij", "naar", "van", "uit", "binnen", "buiten", "onderweg", "wakker", "brak",
                    "dood", "beter", "slecht", "goed", "verdrietig", "jarig", "het", "een", "de", "geen", "altijd",
                    "ook", "zelf", "pas", "zeker", "toch", "eigenlijk", "helemaal", "zwaar", "lekker", "erg",
                    "kwijt", "vrij", "stuk", "weer", "hard", "fan", "zat", "gaming", "aan't"}
PUNCT = set(",.?!:;")

_TOKEN = re.compile(r"[\w'éèëïöü]+|[,.?!:;]")


def tokens(message: str) -> list[str]:
    return _TOKEN.findall(message.lower())


def _occurrence(t: list[str], i: int) -> bool | None:
    prev = t[i - 1] if i > 0 and t[i - 1] not in PUNCT else None
    nxt = t[i + 1] if i + 1 < len(t) else None
    nxt2 = t[i + 2] if i + 2 < len(t) else None

    # verb: "ik ben", "als ik thuis ben", "of ik er ben"
    if prev == "ik":
        return False
    clause_before = []
    for w in reversed(t[:i]):
        if w in PUNCT:
            break
        clause_before.append(w)
    if "ik" in clause_before[:3] and prev not in NAME_BEFORE:
        return False

    if prev == "big":  # Big Ben
        return False
    # name: "hey ben", "ok ben"
    if prev in GREETINGS:
        return True
    # name: "ben, ...", "ben?", "klopt dat ben"
    if nxt is None or nxt in PUNCT:
        return True
    if nxt == "ben":  # "ben ben je wakker"
        return True

    # verb: "ben je thuis", "ben jij gek", "ben ik de enige" ...
    if nxt in PRONOUNS:
        if nxt == "ik" and nxt2 is not None and nxt2 not in PUNCT and nxt2 not in AFTER_DROPPED_IK \
                and nxt2 not in PRONOUNS and nxt2 not in {"de", "het", "een", "nou", "nu", "dan", "echt", "zo"}:
            return True  # "ben ik heb een vraag" = "Ben, ik heb..."
        if nxt2 in {"bent", "bent?"}:
            return True  # "ben jij bent de beste"
        return False

    # name: "vraag het aan ben", "dat vindt ben ook"
    if prev in NAME_BEFORE:
        return True
    # name: "ben is pizza lekker", "ben do you like bones"
    if nxt in FOLLOWS_NAME or nxt in ENGLISH:
        return True
    # name: "ben vind jij...", "ben hou je van...", "ben wat vind jij ervan": verb + pronoun right after
    for j in range(i + 1, min(i + 4, len(t) - 1)):
        if t[j] in PUNCT:
            break
        if t[j + 1] in PRONOUNS - {"ik"} and t[j] not in PRONOUNS and t[j] not in AFTER_DROPPED_IK:
            return True

    # name: "ben pizza of patat", "ben goed of slecht": a choice for Ben to make
    if i == 0 and "of" in t[i + 1:i + 5]:
        return True
    # verb: "ben zo terug", "ben net wakker", "ben gestopt"
    participle = len(nxt) > 4 and nxt.startswith(("ge", "ver", "be", "ont", "her"))
    if i == 0 and (nxt in AFTER_DROPPED_IK or participle or nxt.isdigit()):
        return False
    # name: "wat ben ervan vindt", "ben mijn moeder vindt dat...": Ben is the one who thinks/says
    if any(w in {"vindt", "denkt", "zegt"} for w in t[i + 1:i + 5]):
        return True
    return None


def guess(message: str) -> bool | None:
    """True: Ben is meant. False: "ben" is just the verb. None: not sure."""
    t = tokens(message)
    results = [_occurrence(t, i) for i, w in enumerate(t) if w == "ben"]
    if not results:
        return False
    if True in results:
        return True
    if None in results:
        return None
    return False
