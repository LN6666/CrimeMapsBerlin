import pytest

from crimemapsberlin.geocode import category


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bilanz der polizeilichen Maßnahmen zum Jahreswechsel", ("Unklassifiziert", False)),
        ("Geldausgabeautomaten aufgebrochen", ("Eigentumsdelikt", True)),
        ("Gesprengter Geldausgabeautomat", ("Eigentumsdelikt", True)),
        ("Polizist bei Fahrzeugüberprüfung mitgeschleift – Fahrer flüchtet", ("Gewalt", True)),
        ("Kältebus eines gemeinnützigen Vereins in Brand gesetzt", ("Sachbeschädigung", True)),
        ("Zivilfahnder erkennen mutmaßlichen Kfz-Aufbrecher wieder", ("Diebstahl", True)),
    ],
)
def test_official_headline_category_candidates(title, expected):
    assert category(title) == expected
