"""German location names and narrative roles, without a model or remote geocoder."""

import re
import unicodedata
from collections import defaultdict

DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})
GENERIC_NAMES = {
    "aufzug",
    "balkon",
    "schulweg",
    "verbindungsweg",
    "zufahrt",
    "ausfahrt",
    "eingang",
    "ausgang",
    "parkplatz",
    "park",
    "restaurant",
    "cafe",
    "hotel",
    "friedhof",
    "treppe",
    "bahnsteig",
    "brücke",
    "fussweg",
    "radweg",
    "an der strasse",
}
DISTRICT_NAMES = {
    "mitte",
    "friedrichshain-kreuzberg",
    "pankow",
    "charlottenburg-wilmersdorf",
    "spandau",
    "steglitz-zehlendorf",
    "tempelhof-schöneberg",
    "neukölln",
    "treptow-köpenick",
    "marzahn-hellersdorf",
    "lichtenberg",
    "reinickendorf",
    "prenzlauer berg",
    "alt-hohenschönhausen",
    "nikolaiviertel",
}


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("ß", "ss").translate(DASHES)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"(?<=\w)str\.(?=\s|$|[,;/])", "strasse", text)
    text = re.sub(r"\bstr\.(?=\s|$|[,;/])", "strasse", text)
    return " ".join(text.split())


def name_aliases(name):
    """Bounded grammatical variants; collisions stay visible to the resolver."""
    base = normalize(name)
    aliases = {base}
    words = base.split()
    if len(words) > 1:
        inflected = list(words)
        for i, word in enumerate(words[:-1]):
            if word.endswith(("ische", "sche")) or word in {"alte", "neue", "grosse", "kleine"}:
                inflected[i] = word + "n"
            elif word in {"kleiner", "grosser"}:
                inflected[i] = word[:-1] + "n"
        aliases.add(" ".join(inflected))
    for alias in tuple(aliases):
        if alias.endswith(("ring", "weg", "damm", "park", "ufer", "garten")):
            aliases.add(alias + "s")
        if alias.endswith("platz"):
            aliases.add(alias + "es")
    return aliases


class NameMatcher:
    def __init__(self, aliases):
        self.aliases = defaultdict(set)
        for alias, key in aliases:
            if alias and alias not in GENERIC_NAMES:
                self.aliases[alias].add(key)
        trie = {}
        for alias in self.aliases:
            node = trie
            for char in alias:
                node = node.setdefault(char, {})
            node[""] = {}

        def pattern(node):
            branches = [re.escape(char) + pattern(child) for char, child in sorted(node.items()) if char]
            if not branches:
                return ""
            part = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
            return "(?:" + part + ")?" if "" in node else part

        # Factor common prefixes so whole-body scans do not try thousands of names per word.
        self.pattern = re.compile(r"(?<!\w)" + pattern(trie) + r"(?!\w)") if trie else None

    def matches(self, text):
        if self.pattern:
            for match in self.pattern.finditer(text):
                yield match, self.aliases[match[0]]


def narrative_sentences(body):
    # Whole narrative, including an embedded original report; never truncate at character 900.
    text = normalize(body)
    text = re.sub(r"\b(?:z\. b\.|u\. a\.|bzw\.|ca\.)", lambda m: m[0].replace(".", ""), text)
    boundaries = []
    for match in re.finditer(r"(?<=[.!?])\s+(?=[a-zäöü„“])|(?=\berstmeldung\b)", text):
        if (
            text[max(0, match.start() - 2) : match.start()].endswith(".")
            and re.search(r"\d\.$", text[: match.start()])
            and re.match(
                r"(?:januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b",
                text[match.end() :],
            )
        ):
            continue  # preserve dates and names such as Straße des 17. Juni
        boundaries.append((match.start(), match.end()))
    rows, start = [], 0
    for end, next_start in boundaries:
        if text[start:end].strip():
            rows.append(text[start:end].strip())
        start = next_start
    if text[start:].strip():
        rows.append(text[start:].strip())
    return rows


def mention_role(sentence, start, end):
    before = sentence[max(0, start - 100) : start]
    if re.search(
        r"hinweise\s+(?:nimmt|nehmen|erbitt|bitte)|(?:rufnummer|telefonnummer)|"
        r"(?:telefonisch|telefon)\s+unter|(?:kontakt|erreichbar)\s+unter",
        sentence,
    ):
        return "contact"
    if re.search(r"polizeidirektion\s+\d|kommissariat|polizeigewahrsam", sentence) and re.search(
        r"gebracht|brachten|überstellt|eingeliefert|hinweise", sentence
    ):
        return "destination"
    if re.search(r"gebracht|brachten|überstellt|eingeliefert|transportiert", before) and re.search(
        r"krankenhaus|gewahrsam|polizeidienststelle", sentence
    ):
        return "destination"
    if re.search(r"\b(?:richtung|fahrtrichtung)\s+(?:der\s+|des\s+)?$", before):
        return "direction"
    if re.search(r"(?:anschliessend|danach|daraufhin).*?(?:flücht|floh|fuhr|fuhren)", before):
        return "followup"
    if re.search(r"(?:zwischen|bis\s+zur|bis\s+zum)\s*$", before) and re.search(
        r"sperr|verkehr|umleit", sentence
    ):
        return "restriction_endpoint"
    return "primary"


def locative(sentence, start):
    return bool(
        re.search(
            r"(?:\b(?:in|im|am|an|auf|beim|vor|nahe|gegenüber|hinter|unter|über|zur|zum|zu|entlang|"
            r"befuhr|befuhren|überquerte|überquerten|passierte|erreichte)|"
            r"\b(?:bereich|höhe|kreuzung|kreuzungsbereich|ecke|einmündung|hinterhof|hausflur|gebäude|wohnung|"
            r"wohnanschrift|anschrift|adresse|strasse))\s+(?:der\s+|dem\s+|des\s+|die\s+|den\s+|einem\s+|einer\s+)?(?:"
            r"bahnhof\s+|[us]-bahnhof\s+|s\+u-bahnhof\s+|haltestelle\s+|bushaltestelle\s+|"
            r"einkaufscenter\s+|einkaufszentrum\s+|restaurant\s+|cafe\s+|bar\s+|hotel\s+)?[„“\"‚'»]*$",
            sentence[max(0, start - 65) : start],
        )
    )


def contextual_locality(sentence, start):
    return bool(
        re.search(
            r"(?:\bin|\bortsteil|\bbezirk|\bstadtteil|\bstadtteilen|\bortsteilen)\s+(?:berlin-)?$",
            sentence[:start],
        )
    )


def station_context(sentence, start, end, name):
    return "bahnhof" in name or bool(
        re.search(
            r"\b(?:[us](?:\+u)?[- ](?:bahnhof|bhf\.?|station)?|bahnhof|haltestelle)\s*$",
            sentence[max(0, start - 45) : start],
        )
    )


def venue_context(sentence, start):
    return bool(
        re.search(
            r"\b(?:bar|kneipe|club|nachtclub|restaurant|cafe|hotel|einkaufscenter|einkaufszentrum|"
            r"geschäft|supermarkt|museum|park|grünanlage)\s+(?:namens\s+)?[„“\"‚'»]*$",
            sentence[max(0, start - 65) : start],
        )
    ) or bool(re.search(r"[„“\"‚'»]$", sentence[:start]))


INCIDENT_WORDS = re.compile(
    r"raub|beraub|überfall|angegriff|angriff|geschlagen|schlug|besprüht|reizstoff|"
    r"schuss|schüsse|schoss|gestohlen|entwend|brand|brannte|zusammenstoss|kollid|"
    r"angefahren|fuhr.*?an,|prall|beschädig|stach|verletz|beleidig|bedroht|bedrohung|unfall"
)


def preparatory_location(sentence):
    return bool(
        re.search(
            r"befuhr|befuhren|stiegen|eingestiegen|einsteigen|anhalten|überprüfung|verkehrskontrolle",
            sentence,
        )
    ) and not INCIDENT_WORDS.search(sentence)
