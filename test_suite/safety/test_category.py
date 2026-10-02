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
            ("Verkehr / sonstige Meldung", True),
        ),
        ("Weitere Erkenntnisse zum Zugunfall in Hamburg-Wilhelmsburg", ("Verkehr / sonstige Meldung", False)),
        ("Kältebus eines gemeinnützigen Vereins in Brand gesetzt", ("Sachbeschädigung", True)),
        ("Zivilfahnder erkennen mutmaßlichen Kfz-Aufbrecher wieder", ("Diebstahl", True)),
        ("Durchsuchungen wegen des Verdachts des gewerbsmäßigen Waffenhandels", ("Waffendelikt", True)),
        ("Zeugenaufruf nach Verkehrsunfallflucht", ("Verkehr / sonstige Meldung", True)),
        ("Autofahrerflucht nach Unfall in Hamburg", ("Verkehr / sonstige Meldung", True)),
        ("Illegales Straßenrennen in der Innenstadt", ("Verkehr / sonstige Meldung", True)),
        ("Verbotenes Kraftfahrzeugrennen", ("Verkehr / sonstige Meldung", True)),
        ("Fahrt ohne Versicherungsschutz", ("Verkehr / sonstige Meldung", True)),
        ("Fahrer ohne Pflichtversicherung", ("Verkehr / sonstige Meldung", True)),
        ("Fahren ohne Fahrerlaubnis", ("Verkehr / sonstige Meldung", True)),
        ("Betrug und Verstoß gegen das Markengesetz", ("Betrug", True)),
        ("Verdacht auf Verstoß gegen das Markengesetz", ("Unklassifiziert", True)),
        ("Betrug bei Fahrerlaubnisprüfungen", ("Betrug", True)),
        ("Betrug beim Versicherungsschutz", ("Betrug", True)),
        ("Zeugenaufruf nach möglicher Freiheitsberaubung", ("Gewalt", True)),
        ("Zeugenaufruf nach rassistischer Beleidigung", ("Unklassifiziert", True)),
        ("Zeugenaufruf nach tödlicher Auseinandersetzung", ("Gewalt", True)),
    ],
)
def test_official_headline_category_candidates(title, expected):
    assert category(title) == expected


def test_body_can_recover_explicit_robbery_when_title_is_euphemistic():
    assert category(
        "Angeblicher Polizeibeamter entwendet Wertsachen",
        "Tatort: Hamburg-Poppenbüttel, Langenstücken. Die Frau wurde in ihrer Wohnung beraubt.",
    ) == ("Raub", True)


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        ("Zwei mutmaßliche Trickdiebinnen festgenommen", "", ("Diebstahl", True)),
        (
            "Zeugenaufruf nach Hasskriminalität",
            "Die Polizei ermittelt wegen eines Körperverletzungsdelikts.",
            ("Gewalt", True),
        ),
        (
            "Entwendete Waren sichergestellt",
            "Die Ermittlungen gegen beide wegen des Verdachts der Hehlerei dauern an.",
            ("Eigentumsdelikt", True),
        ),
        (
            "Öffentlichkeitsfahndung nach einem Verkehrsunfall",
            "Die Fahndung erfolgt wegen des Verdachts der fahrlässigen Körperverletzung durch Unterlassen.",
            ("Verkehr / sonstige Meldung", True),
        ),
        (
            "Tödlicher Arbeitsunfall",
            "Die Behörden ermitteln wegen des Verdachts der fahrlässigen Tötung.",
            ("Verkehr / sonstige Meldung", True),
        ),
        (
            "Zeugenaufruf nach Auffinden eines Leichnams",
            "Die Mordkommission prüft den Verdacht einer Gewalteinwirkung.",
            ("Unklassifiziert", True),
        ),
    ],
)
def test_reviewed_explicit_offence_and_uncertain_death_categories(title, body, expected):
    assert category(title, body) == expected


def test_explicit_unauthorized_departure_retains_traffic_category_and_crime_flag():
    for body in (
        "Der Fahrer hat sich anschließend unerlaubt vom Unfallort entfernt.",
        "Der Fahrer entfernte sich vom Unfallort, ohne seinen Pflichten als Unfallbeteiligter nachzukommen.",
    ):
        assert category("Zeugenaufruf nach Verkehrsunfall", body) == (
            "Verkehr / sonstige Meldung", True
        )


def test_body_only_explicit_uninsured_use_is_a_traffic_crime_candidate():
    assert category(
        "Autofahrer bei Kontrolle gestoppt",
        "Die Beamten stellten fest, dass der Pkw ohne Versicherungsschutz gefahren wurde.",
    ) == ("Verkehr / sonstige Meldung", True)


@pytest.mark.parametrize(
    "wording",
    [
        "nicht im Besitz einer Fahrerlaubnis",
        "nicht im Besitz einer gültigen Fahrerlaubnis",
        "nicht im Besitz der erforderlichen Fahrerlaubnis",
    ],
)
def test_body_only_explicit_unlicensed_driving_is_a_traffic_crime_candidate(wording):
    assert category(
        "Schwerer Verkehrsunfall",
        f"Der Fahrer ist nach den bisherigen Erkenntnissen {wording}.",
    ) == ("Verkehr / sonstige Meldung", True)


def test_multiple_official_scenes_with_explicit_threat_are_a_crime_candidate():
    assert category(
        "Zeugenaufruf nach zwei Fällen von Hasskriminalität",
        "Tatorte: I.) Hamburg-Barmbek II.) Hamburg-Ohlsdorf. "
        "Ein Mann bedrohte den Geschädigten; später bedrohte ein anderer ihn mit einem Messer.",
    ) == ("Unklassifiziert", True)


def test_generic_plagiarism_sale_headline_uses_explicit_fraud_and_trademark_investigation():
    assert category(
        "Fünf vorläufige Festnahmen nach mutmaßlichem Plagiatsverkauf",
        "Das LKA übernimmt die Ermittlungen wegen des Verdachts des Betrugs und des "
        "Verstoßes gegen das Markengesetz.",
    ) == ("Betrug", True)
    assert category(
        "Verdächtige Produkte sichergestellt",
        "Das LKA ermittelt wegen des Verdachts eines Verstoßes gegen das Markengesetz.",
    ) == ("Unklassifiziert", True)


def test_explicit_body_offences_recover_generic_titles():
    assert category(
        "Metallspäne auf einer Radstrecke",
        "Mehrere Rennräder wurden durch Metallspäne beschädigt.",
    ) == ("Sachbeschädigung", True)
    assert category(
        "Polizei beschlagnahmt Vermögenswerte",
        "Sie soll sich mittels gefälschter Gehaltsnachweise einen Kredit rechtswidrig verschafft haben.",
    ) == ("Betrug", True)
    assert category(
        "Zeugenaufruf nach Hasskriminalität",
        "Der Unbekannte soll den Geschädigten homophob motiviert geschlagen haben.",
    ) == ("Gewalt", True)
    assert category(
        "Öffentlichkeitsfahndung nach Hasskriminalität",
        "Die Unbekannten attackierten und verletzten einen einschreitenden Zeugen.",
    ) == ("Gewalt", True)
    assert category(
        "Metallspäne auf einer Radstrecke",
        "Mehrere Räder wurden durch Metallspäne beschädigt; zwei Fahrer wurden verletzt.",
    ) == ("Sachbeschädigung", True)


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        (
            "Haftbefehle nach Durchsuchungen",
            "Die Beschuldigten stehen im Verdacht, mit Waffen gehandelt zu haben. "
            "Ermittelt wird wegen Verstößen gegen das Waffengesetz.",
            ("Waffendelikt", True),
        ),
        (
            "Medizinischer Notfall nach mutmaßlichem Drogenkonsum: Mann verstirbt",
            "Die Staatsanwaltschaft führt ein Todesermittlungsverfahren zur Todesursache.",
            ("Unklassifiziert", False),
        ),
        (
            "Pkw kollidiert mit Radfahrer und verletzt diesen",
            "Dem Fahrer wird Fahren ohne Fahrerlaubnis vorgeworfen.",
            ("Verkehr / sonstige Meldung", True),
        ),
        (
            "Bilanz der Drogenerkennung im Straßenverkehr",
            "Bei der Kontrollaktion überprüften Beamte 200 Fahrzeuge und 210 Personen. "
            "Strafverfahren wurden eingeleitet.",
            ("Unklassifiziert", False),
        ),
        (
            "Tödlicher Bahnunfall",
            "Gegen den Mann leiteten Beamte ein Verfahren wegen des Verdachts des "
            "gefährlichen Eingriffes in den Bahnverkehr ein.",
            ("Verkehr / sonstige Meldung", True),
        ),
        (
            "Geldabholer festgenommen",
            "Er soll als Teil einer Betrügerbande versucht haben, Schmuck abzuholen.",
            ("Betrug", True),
        ),
        (
            "Schussabgabe auf Fenster eines Wohnhauses",
            "Die Fenster wurden durch Schüsse beschädigt. In den Räumen wurde niemand verletzt.",
            ("Sachbeschädigung", True),
        ),
    ],
)
def test_source_detail_corrects_generic_hamburg_headline(title, body, expected):
    assert category(title, body) == expected


def test_secondary_traffic_offence_does_not_hide_fraud_or_make_a_bilanz_one_crime():
    body = "Auch ein Fahrer fuhr ohne die erforderliche Fahrerlaubnis."
    assert category("Einsatz wegen Sozialleistungsbetrug", body) == ("Betrug", True)
    assert category("Bilanz einer hamburgweiten Verkehrskontrolle", body) == (
        "Unklassifiziert", False
    )


def test_specific_drug_flight_and_bias_reports_keep_their_offence_flags():
    assert category(
        "Drei Zuführungen nach Sicherstellung mehrerer Kilogramm Heroin",
        "Die Beamten beobachteten eine mutmaßliche Übergabe von Betäubungsmitteln.",
    ) == ("Betäubungsmittel", True)
    assert category(
        "Zwei Festnahmen nach Verdacht des Handels mit Rauschmitteln",
        "Zivile Einsatzkräfte sahen einen mutmaßlichen Verkauf.",
    ) == ("Betäubungsmittel", True)
    assert category(
        "Eine Festnahme nach mehreren Verkehrsunfällen mit Flucht",
        "Der Fahrer flüchtete von den Unfallorten.",
    ) == ("Verkehr / sonstige Meldung", True)
    assert category(
        "Zeugenaufruf nach mutmaßlicher Hasskriminalität",
        "Ein Mann beleidigte ein Kind mutmaßlich aufgrund seiner Behinderung.",
    ) == ("Unklassifiziert", True)


def test_specific_illegal_cannabis_trade_is_a_drug_crime_candidate():
    assert category(
        "Durchsuchungen wegen des Verdachts des illegalen Handels mit Cannabis",
        "Die Betreiber sollen Cannabis verkauft haben; ermittelt wird wegen Verstößen "
        "gegen das Konsumcannabisgesetz (KCanG).",
    ) == ("Betäubungsmittel", True)
    assert category(
        "Informationstag zum Cannabisgesetz",
        "Fachleute informieren über die geltenden Regeln.",
    ) == ("Unklassifiziert", False)
    assert category(
        "Kriminalstatistik 2025",
        "Illegaler Handel mit Cannabis floriert weiterhin. Die Statistik weist "
        "1.230 Fälle nach dem Konsumcannabisgesetz aus.",
    ) == ("Unklassifiziert", False)


def test_traffic_chase_with_explicit_criminal_proceedings_has_crime_flag():
    assert category(
        "Fahrzeugführer flüchtet vor der Polizei und verursacht einen Verkehrsunfall",
        "Die Polizei leitete gegen den Fahrer ein Strafverfahren wegen des Verdachts "
        "mehrerer Verkehrsdelikte ein.",
    ) == ("Verkehr / sonstige Meldung", True)


def test_medical_episode_causing_a_road_collision_remains_noncriminal_traffic():
    assert category(
        "Fahrer erleidet Erkrankung und verstirbt im Straßenverkehr",
        "Aufgrund der Erkrankung kam es zu einem Auffahrunfall zwischen zwei Pkw. "
        "Es liegen keine Hinweise auf ein strafbares Verhalten vor.",
    ) == ("Verkehr / sonstige Meldung", False)


def test_annual_traffic_statistics_is_not_a_violent_crime_report():
    assert category(
        "Verkehrssicherheitsbilanz 2025: Zahl der Verkehrstoten fast halbiert - "
        "Risiko im Straßenverkehr verletzt zu werden sinkt",
        "Die Polizei stellte die Jahresbilanz vor; darin stehen mehrere Unfälle und Straftaten.",
    ) == ("Unklassifiziert", False)


def test_independent_online_hate_offence_investigations_have_crime_flag():
    assert category(
        "Hasskriminalität im Internet - Staatsschutz durchsucht Wohnungen",
        "Die Maßnahmen erfolgten in voneinander unabhängig geführten "
        "Ermittlungsverfahren wegen des Verdachts der Volksverhetzung.",
    ) == ("Unklassifiziert", True)
    assert category(
        "Hasskriminalität im Internet - Präventionstipps",
        "Die Polizei gibt allgemeine Hinweise zum Melden von Beiträgen.",
    ) == ("Unklassifiziert", False)


def test_unlicensed_homemade_pyrotechnics_is_a_suspected_offence_without_new_category():
    title = "Sicherstellung von Chemikalien und pyrotechnischen Gegenständen"
    assert category(
        title,
        "Der Mann war nicht im Besitz einer sprengstoffrechtlichen Erlaubnis. "
        "Bei der Durchsuchung wurden selbstgefertigte pyrotechnische Effektsätze gefunden.",
    ) == ("Unklassifiziert", True)
    assert category(
        title,
        "Der Mann hatte erlaubnisfreie Grundstoffe gekauft; eine mögliche Herstellung "
        "wird noch geprüft.",
    ) == ("Unklassifiziert", False)


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        (
            "Nach Hinweisen zu unerlaubtem Glücksspiel: mehrere Verstöße festgestellt",
            "Es wurden mehrere Ermittlungsverfahren eingeleitet, unter anderem wegen des "
            "Verdachts der Geldwäsche und eines Verstoßes gegen das Cannabisgesetz.",
            ("Unklassifiziert", True),
        ),
        (
            "Tatverdächtige zu mehreren Gewalt- und Eigentumsdelikten ermittelt",
            "Die Gruppe soll mehrere unabhängige Taten begangen haben.",
            ("Unklassifiziert", True),
        ),
        (
            "Zeugenaufruf nach sexuellem Übergriff",
            "Der Unbekannte nahm sexuelle Handlungen an der Frau vor.",
            ("Sexualdelikt", True),
        ),
        (
            "Zeugenaufruf nach Schüssen",
            "Die ersten Ermittlungen zu der Sachbeschädigung führte der Kriminaldauerdienst.",
            ("Sachbeschädigung", True),
        ),
        (
            "Fahrrad mit mutmaßlich gestohlener Bankkarte erlangt",
            "Die Personen stehen im Verdacht, Waren mit fremden Bankkarten betrügerisch "
            "erworben zu haben.",
            ("Betrug", True),
        ),
        (
            "Eine Person bei Wohnungsbrand lebensgefährlich verletzt",
            "Eine Wohnung geriet aus noch ungeklärter Ursache in Brand.",
            ("Unklassifiziert", False),
        ),
        (
            "Zeugenaufruf nach Überfällen auf zwei Frauen",
            "Zwei voneinander unabhängige Fälle werden geprüft.",
            ("Raub", True),
        ),
        (
            "Festnahmen nach mehreren Geschäftseinbrüchen",
            "Die Ermittlungen dauern an.",
            ("Diebstahl", True),
        ),
        (
            "Sicherstellung von mehreren Kilogramm Cannabis",
            "Zwei Personen stehen im Verdacht, mit Betäubungsmitteln gehandelt zu haben.",
            ("Betäubungsmittel", True),
        ),
        (
            "Frühjahrstagung der Arbeitsgemeinschaft der Polizeipräsidentinnen und "
            "Polizeipräsidenten - Hybride Bedrohungen im Fokus",
            "Die Fachleute erörterten Bedrohungen für kritische Infrastruktur.",
            ("Unklassifiziert", False),
        ),
        (
            '"sicher.mobil.leben" - Ergebnisse einer bundesweiten Verkehrssicherheitsaktion',
            "Bei Kontrollen wurden Verfahren wegen Fahrens ohne Fahrerlaubnis eingeleitet.",
            ("Unklassifiziert", False),
        ),
        (
            '"sicher.mobil.leben" - Ergebnisse einer bundesweiten Verkehrssicherheitsaktion',
            "Bei stationären und mobilen Kontrollen wurden 33 Strafverfahren unter anderem "
            "wegen Fahrens ohne Fahrerlaubnis und Trunkenheit im Straßenverkehr eingeleitet.",
            ("Verkehr / sonstige Meldung", True),
        ),
        (
            "Verbundeinsatz zur Überprüfung von Sozialleistungsbetrug",
            "Einsatzkräfte führten stationäre und mobile Verkehrskontrollen durch.",
            ("Unklassifiziert", False),
        ),
    ],
)
def test_source_explicit_categories_and_aggregate_guards(title, body, expected):
    assert category(title, body) == expected
