"""Deterministic extraction from original Polizei Berlin article narratives."""

import html
import re

TERMS = {
    "bar": r"\b(?:Bar|Bars|Kneipe|Kneipen|Gaststätte|Gaststätten)\b",
    "nightclub": r"\b(?:Diskothek|Diskotheken|Nachtclub|Nachtclubs|Tanzlokal)\b",
    "station": r"\b(?:(?:U|S|U- und S)-)?Bahnhof\b|\b(?:Bahnhöfe|Bahnsteig|Bahnsteigen)\b",
    "restaurant": r"\b(?:Restaurant|Restaurants)\b",
    "cafe": r"\b(?:Café|Cafés|Cafe|Cafes)\b",
    "fast_food": r"\b(?:Imbiss|Schnellrestaurant|Fastfoodrestaurant)\b",
    "shop": r"\b(?:Supermarkt|Supermärkte|Geschäft|Geschäfte|Einkaufszentrum|Kaufhaus|Spätkauf|Laden)\b",
    "park": r"\b(?:Park|Parkanlage|Parkanlagen)\b",
    "parking": r"\b(?:Parkplatz|Parkhaus|Tiefgarage)\b",
    "hotel": r"\b(?:Hotel|Hotels|Hotellobby)\b",
    "airport": r"\b(?:Flughafen|Flughäfen|Flughafenterminal)\b",
    "marketplace": r"\b(?:Wochenmarkt|Weihnachtsmarkt|Marktplatz)\b",
    "attraction": r"\b(?:Sehenswürdigkeit|Museum|Museen)\b",
}


def mentions(text):
    return sorted(kind for kind, pattern in TERMS.items() if re.search(pattern, text, re.I))


def article_text(page):
    # Discard navigation/contact footer: police HQ is not an incident location.
    marker = re.search(r'<p class="polizeimeldung"[^>]*>', page)
    if marker:
        section = re.search(r"<!-- Flex Text -->(.*?)<!-- /Flex Text -->", page[marker.end() :], re.S)
        if section:
            return html.unescape(re.sub("<[^>]+>", " ", section[1]))
    match = re.search(r"Nr\.?\s*\d+.*?<!-- /Flex Text -->", page, re.S)
    return html.unescape(re.sub("<[^>]+>", " ", match.group(0))) if match else ""
