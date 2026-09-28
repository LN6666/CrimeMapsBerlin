import pytest

from crimemapsberlin.geocode import category


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bilanz der polizeilichen Maßnahmen zum Jahreswechsel", ("Unklassifiziert", False)),
        ("Geldausgabeautomaten aufgebrochen", ("Eigentumsdelikt", True)),
        ("Gesprengter Geldausgabeautomat", ("Eigentumsdelikt", True)),
        ("Polizist bei Fahrzeugüberprüfung mitgeschleift – Fahrer flüchtet", ("Gewalt", True)),
        (
            "Autofahrerin fährt Fußgängerin in Hamburg-Neugraben-Fischbek an und flüchtet",
            ("Verkehr / sonstige Meldung", False),
        ),
        ("Weitere Erkenntnisse zum Zugunfall in Hamburg-Wilhelmsburg", ("Verkehr / sonstige Meldung", False)),
        ("Kältebus eines gemeinnützigen Vereins in Brand gesetzt", ("Sachbeschädigung", True)),
        ("Zivilfahnder erkennen mutmaßlichen Kfz-Aufbrecher wieder", ("Diebstahl", True)),
    ],
)
def test_official_headline_category_candidates(title, expected):
    assert category(title) == expected


def test_body_can_recover_explicit_robbery_when_title_is_euphemistic():
    assert category(
        "Angeblicher Polizeibeamter entwendet Wertsachen",
        "Tatort: Hamburg-Poppenbüttel, Langenstücken. Die Frau wurde in ihrer Wohnung beraubt.",
    ) == ("Raub", True)
