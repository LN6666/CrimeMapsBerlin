"""Small, stable JSON representation for candidate and published map records."""


def compact(value):
    # Public display coordinates need sub-metre precision, not 16 decimal places.
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [compact(v) for v in value]
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k != "location_geometry"}
    return value
