import copy
import hashlib
import json

import pytest

from crimemapsberlin import berlin_semantic_review
from crimemapsberlin.berlin_semantic_review import validate_article


def _supplement(tmp_path):
    digest = lambda data: hashlib.sha256(data).hexdigest()
    write = lambda name, data: (tmp_path / name).write_bytes(data)
    article_url = 'https://www.berlin.de/polizei/polizeimeldungen/2026/pressemitteilung.1.php'
    document_url = 'https://www.berlin.de/polizei/fixture.pdf'
    source = {**SOURCE, 'source_url': article_url, 'source_sha256': digest(BODY.encode())}
    payload = decision()
    payload.update(source_url=article_url, source_sha256=source['source_sha256'])
    text = 'Am 16. Juni 2026 wurde eine Gruppe am Platz beobachtet.'
    html = '<p class="polizeimeldung">Nr.1</p><!-- Flex Text -->' + BODY + '<!-- /Flex Text -->'
    html += f'<a href="{document_url}">Download</a>'
    for name, data in [('article.html', html.encode()), ('doc.pdf', b'%PDF-1.0 synthetic fixture'),
                       ('doc.txt', text.encode()), ('robots.txt', b'User-agent: *\nAllow: /\n'),
                       ('map.png', b'synthetic inspected map fixture')]:
        write(name, data)
    file_hash = lambda name: digest((tmp_path / name).read_bytes())
    capture = {'schema_version': 1, 'source_id': '1', 'frozen_source_url': article_url,
        'frozen_source_sha256': source['source_sha256'], 'official_article_url': article_url,
        'official_attachment_url': document_url, 'observed_attachment_url': document_url,
        'current_extracted_body_sha256': source['source_sha256'], 'current_body_matches_frozen': True,
        'article_file': str(tmp_path / 'article.html'), 'article_file_sha256': file_hash('article.html'),
        'attachment_file': str(tmp_path / 'doc.pdf'), 'attachment_file_sha256': file_hash('doc.pdf'),
        'attachment_text_file': str(tmp_path / 'doc.txt'), 'attachment_text_file_sha256': file_hash('doc.txt'),
        'robots_file': str(tmp_path / 'robots.txt'), 'robots_sha256': file_hash('robots.txt'), 'robots_allowed': True,
        'retrieved_at': '2026-10-01T12:00:00+09:00',
        'article_redirect_chain': [{'url': article_url, 'status': 200}],
        'attachment_redirect_chain': [{'url': document_url, 'status': 200}]}
    comparison = {'source_id': '1', 'frozen_source_url': article_url,
        'frozen_source_sha256': source['source_sha256'], 'official_attachment_url': document_url,
        'official_attachment_sha256': file_hash('doc.pdf'),
        'map_inspection': {'file': str(tmp_path / 'map.png'), 'sha256': file_hash('map.png'), 'inspected': True},
        'findings': [{'evidence': {'source_url': document_url, 'source_file_sha256': file_hash('doc.pdf'),
            'extracted_text_sha256': file_hash('doc.txt'), 'verbatim_quote': text}}]}
    write('comparison.json', json.dumps(comparison).encode())
    time = {'status': 'sourced', 'date': '2026-06-16', 'display': '16. Juni 2026; Uhrzeit unbekannt',
        'precision': 'date', 'evidence_quotes': [text], 'review_note': 'Explicit historical date, unknown clock.'}
    episode = {'episode_id': '1:supplement:1', 'details': 'Historical context, not an extra counted crime.',
        'evidence_quotes': [text], 'event_time_review': time,
        'locations': [{'location_id': '1:supplement:1:location:1', 'label': 'unrefined square observation',
            'role': 'background', 'precision': 'area', 'coordinates': None, 'details': 'Position unknown.',
            'evidence_quotes': [text], 'event_time_review': copy.deepcopy(time), 'poi_contexts': [], 'transit_route': None}]}
    review = {'schema_version': 1, 'city': 'berlin', 'source_id': '1', 'source_url': article_url,
        'source_sha256': source['source_sha256'], 'reviewer': 'Codex source-backed attachment review',
        'reviewed_at': '2026-10-01T12:00:00+09:00', 'attachment_read_complete': True,
        'comparison_file': str(tmp_path / 'comparison.json'), 'comparison_sha256': file_hash('comparison.json'),
        'supplemental_context_episodes': [episode], 'count_contribution': 0, 'review_note': 'Source-bound context only.'}
    write('capture.json', json.dumps(capture).encode())
    write('review.json', json.dumps(review).encode())
    ref = {'capture_file': str(tmp_path / 'capture.json'), 'capture_sha256': file_hash('capture.json'),
        'review_file': str(tmp_path / 'review.json'), 'review_sha256': file_hash('review.json')}
    payload['source_supplement_refs'] = [ref]
    return payload, source, capture, review, comparison, file_hash


def test_official_supplement_is_bound_and_does_not_add_primary_counts(tmp_path, monkeypatch):
    payload, source, *_ = _supplement(tmp_path)
    result = validate_article(payload, source, AUDIT)
    assert len(result['source_supplement_reviews']) == 1
    assert result['source_supplement_reviews'][0]['count_contribution'] == 0
    assert result['minimum_independent_events'] == 1
    assert len(result['incidents']) == 1 and len(result['formal_locations']) == 2
    monkeypatch.setattr(berlin_semantic_review, 'frozen_sources', lambda *_: ([source], {'1': AUDIT}))
    parts = tmp_path / 'parts'
    parts.mkdir()
    (parts / 'review-001.json').write_text(json.dumps({'articles': [payload]}))
    args = {'db_path': tmp_path / 'unused', 'audit_root': tmp_path / 'unused', 'reviews_dir': parts}
    inventory = berlin_semantic_review.build_geometry_inventory(**args)
    assert inventory == berlin_semantic_review.build_geometry_inventory(**args)
    assert len(inventory['geometry_requests']) == 2
    assert inventory['articles'][0]['audit']['source_supplement_reviews'] == result['source_supplement_reviews']
    (tmp_path / 'doc.pdf').unlink()
    with pytest.raises(ValueError, match='requires complete valid Berlin review'):
        berlin_semantic_review.build_geometry_inventory(**args)


@pytest.mark.parametrize('target', ['article.html', 'doc.pdf', 'doc.txt', 'robots.txt', 'map.png',
                                     'capture.json', 'review.json', 'comparison.json'])
def test_changed_supplement_files_block_review(tmp_path, target):
    payload, source, *_ = _supplement(tmp_path)
    with (tmp_path / target).open('ab') as file:
        file.write(b' changed')
    with pytest.raises(ValueError, match='source supplement.*hash mismatch'):
        validate_article(payload, source, AUDIT)


@pytest.mark.parametrize('field,value', [('count_contribution', 1), ('count_contribution', False),
    ('attachment_read_complete', False), ('source_id', '2'), ('city', 'hamburg'),
    ('source_sha256', 'b' * 64), ('reviewed_at', '2026-10-01')])
def test_invalid_supplement_review_is_rejected(tmp_path, field, value):
    payload, source, _, review, _, file_hash = _supplement(tmp_path)
    review[field] = value
    (tmp_path / 'review.json').write_text(json.dumps(review))
    payload['source_supplement_refs'][0]['review_sha256'] = file_hash('review.json')
    with pytest.raises(ValueError):
        validate_article(payload, source, AUDIT)


@pytest.mark.parametrize('field,value', [('source_id', '2'), ('current_body_matches_frozen', False),
    ('robots_allowed', False), ('official_attachment_url', 'https://example.invalid/doc.pdf'),
    ('observed_attachment_url', 'https://www.berlin.de/polizei/unlinked.pdf'),
    ('official_article_url', 'https://www.berlin.de/polizei/pressemitteilung.2.php'),
    ('attachment_redirect_chain', [None]), ('attachment_media_files_sha256', [])])
def test_invalid_capture_identity_or_link_is_rejected(tmp_path, field, value):
    payload, source, capture, _, _, file_hash = _supplement(tmp_path)
    capture[field] = value
    (tmp_path / 'capture.json').write_text(json.dumps(capture))
    payload['source_supplement_refs'][0]['capture_sha256'] = file_hash('capture.json')
    with pytest.raises((ValueError, TypeError)):
        validate_article(payload, source, AUDIT)


@pytest.mark.parametrize('field,value', [('coordinates', [13.4, 52.5]), ('poi_contexts', [{'kind': 'bar'}]),
    ('transit_route', {'line': 'U8'}), ('role', 'offence_point'), ('precision', 'exact'),
    ('evidence_quotes', ['A quotation that is not in the attachment.'])])
def test_supplement_context_rejects_invented_attribution(tmp_path, field, value):
    payload, source, _, review, _, file_hash = _supplement(tmp_path)
    review['supplemental_context_episodes'][0]['locations'][0][field] = value
    (tmp_path / 'review.json').write_text(json.dumps(review))
    payload['source_supplement_refs'][0]['review_sha256'] = file_hash('review.json')
    with pytest.raises(ValueError):
        validate_article(payload, source, AUDIT)


def test_duplicate_supplement_is_rejected(tmp_path):
    payload, source, *_ = _supplement(tmp_path)
    payload['source_supplement_refs'] *= 2
    with pytest.raises(ValueError, match='duplicate source supplement'):
        validate_article(payload, source, AUDIT)


@pytest.mark.parametrize('field,value', [('verbatim_quote', 'Not in the captured document.'),
    ('source_url', 'https://www.berlin.de/polizei/other.pdf'),
    ('source_file_sha256', 'b' * 64), ('extracted_text_sha256', 'b' * 64)])
def test_rehashed_comparison_still_requires_actual_quote_provenance(tmp_path, field, value):
    payload, source, _, review, comparison, file_hash = _supplement(tmp_path)
    comparison['findings'][0]['evidence'][field] = value
    (tmp_path / 'comparison.json').write_text(json.dumps(comparison))
    review['comparison_sha256'] = file_hash('comparison.json')
    (tmp_path / 'review.json').write_text(json.dumps(review))
    payload['source_supplement_refs'][0]['review_sha256'] = file_hash('review.json')
    with pytest.raises(ValueError):
        validate_article(payload, source, AUDIT)


def test_rehashed_robots_denial_blocks_capture(tmp_path):
    payload, source, capture, _, _, file_hash = _supplement(tmp_path)
    (tmp_path / 'robots.txt').write_text('User-agent: *\nDisallow: /\n')
    capture['robots_sha256'] = file_hash('robots.txt')
    (tmp_path / 'capture.json').write_text(json.dumps(capture))
    payload['source_supplement_refs'][0]['capture_sha256'] = file_hash('capture.json')
    with pytest.raises(ValueError, match='robots snapshot denies'):
        validate_article(payload, source, AUDIT)

BODY = (
    "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen. "
    "Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz. "
    "Später wurde die Jacke in der Beispielstraße gefunden."
)


def decision():
    return {
        "schema_version": 1,
        "city": "berlin",
        "source_id": "1",
        "source_url": "https://example.invalid/1",
        "source_sha256": "a" * 64,
        "reviewer": "Codex source-first review",
        "reviewed_at": "2026-09-29T20:00:00+09:00",
        "source_read_complete": True,
        "six_rule_checks": {
            "discovery_role_checked": True,
            "moving_transit_checked": True,
            "all_independent_events_checked": True,
            "original_event_times_checked": True,
            "all_location_roles_checked": True,
            "poi_context_only_checked": True,
        },
        "announcement_kind": "single incident with later discovery",
        "event_relationship": "one attack and a later evidence discovery",
        "minimum_independent_events": 1,
        "incidents_complete": True,
        "formal_locations_complete": True,
        "event_times_complete": True,
        "transit_review_complete": True,
        "poi_context_review_complete": True,
        "incidents": [
            {
                "incident_id": "1:incident:1",
                "evidence_quotes": [
                    "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen."
                ],
                "formal_location_ids": ["1:location:1"],
                "details": "Attack in the moving U8 train.",
                "event_time_review": {
                    "status": "sourced",
                    "display": "Montag gegen 10 Uhr",
                    "date": None,
                    "precision": "approximate",
                    "evidence_quotes": [
                        "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen."
                    ],
                    "review_note": "The source gives weekday and approximate time only.",
                },
            }
        ],
        "formal_locations": [
            {
                "location_id": "1:location:1",
                "label": "U8 between Alexanderplatz and Hermannplatz",
                "role": "incident",
                "precision": "route",
                "city_scope": "in_city",
                "evidence_quotes": ["Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz."],
                "details": "Moving-train incident, not pinned to either station.",
                "event_time_review": {
                    "status": "sourced",
                    "display": "Montag gegen 10 Uhr",
                    "date": None,
                    "precision": "approximate",
                    "evidence_quotes": [
                        "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen."
                    ],
                    "review_note": "The source gives weekday and approximate time only.",
                },
                "transit_review": {
                    "status": "reviewed_route",
                    "mode": "subway",
                    "line": "U8",
                    "extent": "source_segment",
                    "evidence_quotes": ["Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz."],
                    "review_note": "Both segment endpoints are explicit.",
                },
                "poi_contexts": [
                    {
                        "kind": "station",
                        "scope": "near_geometry",
                        "radius_m": 100,
                        "evidence_quotes": ["Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz."],
                        "review_note": "Stations are context, not offence venues.",
                    }
                ],
            },
            {
                "location_id": "1:location:2",
                "label": "Beispielstraße",
                "role": "discovery",
                "precision": "street",
                "city_scope": "in_city",
                "evidence_quotes": ["Später wurde die Jacke in der Beispielstraße gefunden."],
                "details": "Later discovery only, not the attack location.",
                "event_time_review": {
                    "status": "reviewed_unknown",
                    "display": "",
                    "date": None,
                    "precision": "unknown",
                    "evidence_quotes": ["Später wurde die Jacke in der Beispielstraße gefunden."],
                    "review_note": "Only the relative word later is present.",
                },
                "transit_review": {
                    "status": "not_applicable",
                    "mode": None,
                    "line": "",
                    "extent": None,
                    "evidence_quotes": ["Später wurde die Jacke in der Beispielstraße gefunden."],
                    "review_note": "No moving public transport at this location.",
                },
                "poi_contexts": [],
            },
        ],
        "linked_source_ids": [],
        "uncertainty": ["Calendar date is not present in the excerpt."],
    }


SOURCE = {
    "source_id": "1",
    "source_url": "https://example.invalid/1",
    "source_sha256": "a" * 64,
    "source_body": BODY,
}
AUDIT = {"minimum_independent_events": 1}


def corrected_minimum(tmp_path):
    previous = decision()
    previous['minimum_independent_events'] = 2
    previous['incidents'].append(copy.deepcopy(previous['incidents'][0]))
    previous['incidents'][1]['incident_id'] = '1:incident:2'
    audit = {'minimum_independent_events': 2}
    path = tmp_path / 'superseded-review.json'
    path.write_text(json.dumps(previous))
    payload = decision()
    payload['minimum_event_count_correction'] = {
        'prior_audit_sha256': berlin_semantic_review._digest(audit),
        'prior_minimum': 2, 'corrected_minimum': 1,
        'superseded_review_file': str(path),
        'superseded_review_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'removed_incident_ids': ['1:incident:2'],
        'evidence_quotes': [BODY.split(' Später')[0]],
        'review_note': 'The same source-reported attack was duplicated; retain one event, every location and all original evidence.',
        'reviewer': payload['reviewer'], 'reviewed_at': payload['reviewed_at'],
    }
    return payload, audit, path


def test_source_bound_minimum_correction_preserves_original_review_and_locations(tmp_path, monkeypatch):
    payload, audit, path = corrected_minimum(tmp_path)
    original = path.read_bytes()
    result = validate_article(payload, SOURCE, audit)
    assert result['minimum_independent_events'] == 1 and len(result['incidents']) == 1
    assert len(result['formal_locations']) == 2 and path.read_bytes() == original
    assert result['minimum_event_count_correction']['prior_minimum'] == 2
    monkeypatch.setattr(berlin_semantic_review, 'frozen_sources', lambda *_: ([SOURCE], {'1': audit}))
    parts = tmp_path / 'reviews'
    parts.mkdir()
    (parts / 'review-001.json').write_text(json.dumps({'articles': [payload]}))
    inventory = berlin_semantic_review.build_geometry_inventory(
        db_path=tmp_path / 'unused', audit_root=tmp_path / 'unused', reviews_dir=parts)
    assert inventory['articles'][0]['audit']['minimum_event_count_correction'] == result['minimum_event_count_correction']
    assert len(inventory['geometry_requests']) == 2
    assert not inventory['owner_approved'] and not inventory['publication_ready']


@pytest.mark.parametrize('field,value', [
    ('prior_audit_sha256', '0' * 64), ('prior_minimum', 3), ('prior_minimum', True),
    ('corrected_minimum', 0), ('corrected_minimum', True), ('superseded_review_sha256', '0' * 64),
    ('removed_incident_ids', []), ('removed_incident_ids', ['1:incident:1']),
    ('removed_incident_ids', ['1:incident:2', '1:incident:2']),
    ('evidence_quotes', ['This evidence does not occur in the source body.']),
    ('reviewer', 'another reviewer'), ('reviewed_at', '2026-10-01'), ('review_note', ''),
])
def test_minimum_correction_rejects_unbound_or_incomplete_override(tmp_path, field, value):
    payload, audit, _ = corrected_minimum(tmp_path)
    payload['minimum_event_count_correction'][field] = value
    with pytest.raises((ValueError, TypeError)):
        validate_article(payload, SOURCE, audit)


def test_minimum_correction_cannot_drop_a_formal_location(tmp_path):
    payload, audit, _ = corrected_minimum(tmp_path)
    payload['formal_locations'].pop()
    with pytest.raises(ValueError, match='retain all locations'):
        validate_article(payload, SOURCE, audit)


def retired_synthetic_location(tmp_path):
    payload, audit, path = corrected_minimum(tmp_path)
    previous = json.loads(path.read_text())
    location = copy.deepcopy(previous['formal_locations'][1])
    location.update(location_id='1:location:3', role='unknown', precision='unknown',
                    label='unsupported synthetic aggregate slot', poi_contexts=[])
    previous['formal_locations'].append(location)
    previous['incidents'][1]['formal_location_ids'].append('1:location:3')
    path.write_text(json.dumps(previous))
    proof = payload['minimum_event_count_correction']
    proof['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    proof['retired_formal_location_ids'] = ['1:location:3']
    proof['evidence_quotes'].extend(location['evidence_quotes'])
    return payload, audit, path


def test_explicit_synthetic_retirement_keeps_recoverable_original_and_quotes(tmp_path, monkeypatch):
    payload, audit, path = retired_synthetic_location(tmp_path)
    before = path.read_bytes()
    result = validate_article(payload, SOURCE, audit)
    assert len(result['formal_locations']) == 2
    assert result['minimum_event_count_correction']['retired_formal_location_ids'] == ['1:location:3']
    assert path.read_bytes() == before
    monkeypatch.setattr(berlin_semantic_review, 'frozen_sources', lambda *_: ([SOURCE], {'1': audit}))
    parts = tmp_path / 'reviews'
    parts.mkdir()
    (parts / 'review-001.json').write_text(json.dumps({'articles': [payload]}))
    inventory = berlin_semantic_review.build_geometry_inventory(
        db_path=tmp_path / 'unused', audit_root=tmp_path / 'unused', reviews_dir=parts)
    assert len(inventory['geometry_requests']) == 2
    assert inventory['articles'][0]['audit']['minimum_event_count_correction']['retired_formal_location_ids'] == ['1:location:3']


@pytest.mark.parametrize('retired', [[], '1:location:3', ['1:location:1'],
                                   ['1:location:3', '1:location:3'], [True]])
def test_synthetic_retirement_rejects_unlisted_or_mismatched_locations(tmp_path, retired):
    payload, audit, _ = retired_synthetic_location(tmp_path)
    payload['minimum_event_count_correction']['retired_formal_location_ids'] = retired
    with pytest.raises((ValueError, TypeError)):
        validate_article(payload, SOURCE, audit)


@pytest.mark.parametrize('field,value', [('role', 'incident'), ('precision', 'street'),
                                      ('poi_contexts', [{'kind': 'bar'}])])
def test_synthetic_retirement_cannot_remove_real_or_poi_location(tmp_path, field, value):
    payload, audit, path = retired_synthetic_location(tmp_path)
    previous = json.loads(path.read_text())
    previous['formal_locations'][2][field] = value
    path.write_text(json.dumps(previous))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises((ValueError, TypeError)):
        validate_article(payload, SOURCE, audit)


def test_synthetic_retirement_cannot_remove_a_retained_incident_location(tmp_path):
    payload, audit, path = retired_synthetic_location(tmp_path)
    previous = json.loads(path.read_text())
    previous['incidents'][0]['formal_location_ids'].append('1:location:3')
    path.write_text(json.dumps(previous))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='synthetic slot'):
        validate_article(payload, SOURCE, audit)


def test_synthetic_retirement_cannot_remove_transit_context(tmp_path):
    payload, audit, path = retired_synthetic_location(tmp_path)
    previous = json.loads(path.read_text())
    previous['formal_locations'][2] = copy.deepcopy(previous['formal_locations'][0])
    previous['formal_locations'][2].update(location_id='1:location:3', role='unknown', poi_contexts=[])
    path.write_text(json.dumps(previous))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises((ValueError, TypeError)):
        validate_article(payload, SOURCE, audit)


def test_synthetic_retirement_cannot_remove_unlinked_unknown_location(tmp_path):
    payload, audit, path = retired_synthetic_location(tmp_path)
    previous = json.loads(path.read_text())
    previous['incidents'][1]['formal_location_ids'].remove('1:location:3')
    path.write_text(json.dumps(previous))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='synthetic slot'):
        validate_article(payload, SOURCE, audit)


def test_synthetic_retirement_must_preserve_its_source_quotes(tmp_path):
    payload, audit, path = retired_synthetic_location(tmp_path)
    quote = 'Rund zwanzig Fälle sind nur eine unaufgeschlüsselte Gesamtzahl.'
    source = {**SOURCE, 'source_body': BODY + ' ' + quote}
    previous = json.loads(path.read_text())
    previous['formal_locations'][2]['evidence_quotes'] = [quote]
    path.write_text(json.dumps(previous))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='retired synthetic-location evidence'):
        validate_article(payload, source, audit)


def test_minimum_correction_rejects_changed_or_nested_original(tmp_path):
    payload, audit, path = corrected_minimum(tmp_path)
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='hash mismatch'):
        validate_article(payload, SOURCE, audit)
    original = json.loads(path.read_text())
    original['minimum_event_count_correction'] = payload['minimum_event_count_correction']
    path.write_text(json.dumps(original))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='nested correction'):
        validate_article(payload, SOURCE, audit)


def test_bare_lowered_minimum_still_rejected(tmp_path):
    payload, audit, _ = corrected_minimum(tmp_path)
    payload.pop('minimum_event_count_correction')
    with pytest.raises(ValueError, match='source-first audit minimum'):
        validate_article(payload, SOURCE, audit)


def explicit_additions_with_lowered_minimum(tmp_path):
    payload, audit, path = corrected_minimum(tmp_path)
    quote = 'Später wurde die Jacke in der Beispielstraße gefunden.'
    location = copy.deepcopy(payload['formal_locations'][1])
    location.update(location_id='1:location:3', precision='unknown',
                    label='Undisclosed exact position of the source jacket discovery')
    incident = {'incident_id': '1:incident:3', 'evidence_quotes': [quote],
                'formal_location_ids': ['1:location:3'],
                'details': 'Separately reported later jacket discovery, not another crime.',
                'event_time_review': copy.deepcopy(location['event_time_review'])}
    payload['formal_locations'].append(location)
    payload['incidents'].append(incident)
    payload['minimum_event_count_correction']['source_explicit_additions'] = [
        {'kind': 'incident', 'record_id': '1:incident:3', 'evidence_quotes': [quote],
         'review_note': 'Retain the explicit later discovery without undoing the attack duplicate correction.'},
        {'kind': 'formal_location', 'record_id': '1:location:3', 'evidence_quotes': [quote],
         'review_note': 'The added context has no claimed exact position, selected POI or coordinate.'},
    ]
    return payload, audit, path


def test_lowered_minimum_retains_separately_sourced_new_phases_and_unknown_contexts(tmp_path, monkeypatch):
    payload, audit, path = explicit_additions_with_lowered_minimum(tmp_path)
    original = path.read_bytes()
    result = validate_article(payload, SOURCE, audit)
    assert result['minimum_independent_events'] == 1
    assert {i['incident_id'] for i in result['incidents']} == {'1:incident:1', '1:incident:3'}
    assert len(result['formal_locations']) == 3 and path.read_bytes() == original
    assert len(result['minimum_event_count_correction']['source_explicit_additions']) == 2
    monkeypatch.setattr(berlin_semantic_review, 'frozen_sources', lambda *_: ([SOURCE], {'1': audit}))
    parts = tmp_path / 'explicit-additions'
    parts.mkdir()
    (parts / 'review-001.json').write_text(json.dumps({'articles': [payload]}))
    args = dict(db_path=tmp_path / 'unused', audit_root=tmp_path / 'unused', reviews_dir=parts)
    inventory = berlin_semantic_review.build_geometry_inventory(**args)
    assert inventory == berlin_semantic_review.build_geometry_inventory(**args)
    added = next(r for r in inventory['geometry_requests'] if r['location_id'] == '1:location:3')
    assert added['precision'] == 'unknown' and added['coordinates'] is None
    assert not inventory['owner_approved'] and not inventory['publication_ready']


@pytest.mark.parametrize('missing', ['all', 'incident', 'formal_location'])
def test_minimum_correction_rejects_undeclared_new_records(tmp_path, missing):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    proof = payload['minimum_event_count_correction']
    if missing == 'all':
        proof.pop('source_explicit_additions')
    else:
        proof['source_explicit_additions'] = [r for r in proof['source_explicit_additions'] if r['kind'] != missing]
    with pytest.raises(ValueError):
        validate_article(payload, SOURCE, audit)


@pytest.mark.parametrize('field,value', [
    ('kind', 'offence_point'), ('record_id', True), ('record_id', '2:incident:3'),
    ('record_id', '1:incident:1'), ('evidence_quotes', []),
    ('evidence_quotes', ['An invented event unsupported by the official source.']),
    ('evidence_quotes', ['Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen.']),
    ('review_note', ''),
])
def test_minimum_addition_rejects_unbound_or_mismatched_declaration(tmp_path, field, value):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    payload['minimum_event_count_correction']['source_explicit_additions'][0][field] = value
    with pytest.raises((ValueError, TypeError)):
        validate_article(payload, SOURCE, audit)


@pytest.mark.parametrize('declarations', [[], True, 'new phase'])
def test_minimum_addition_requires_nonempty_individual_proof(tmp_path, declarations):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    payload['minimum_event_count_correction']['source_explicit_additions'] = declarations
    with pytest.raises(ValueError):
        validate_article(payload, SOURCE, audit)


def test_minimum_addition_rejects_duplicate_proofs(tmp_path):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    additions = payload['minimum_event_count_correction']['source_explicit_additions']
    additions.append(copy.deepcopy(additions[0]))
    with pytest.raises(ValueError, match='duplicate'):
        validate_article(payload, SOURCE, audit)


@pytest.mark.parametrize('field,value', [
    ('precision', 'street'), ('poi_contexts', [{'kind': 'bar'}]),
    ('transit_review', None),
])
def test_minimum_addition_rejects_new_geocoded_or_poi_context(tmp_path, field, value):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    payload['formal_locations'][2][field] = value
    with pytest.raises(ValueError, match='unlocated linked context'):
        validate_article(payload, SOURCE, audit)


def test_minimum_addition_rejects_unlinked_location(tmp_path):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    payload['incidents'][1]['formal_location_ids'] = ['1:location:2']
    with pytest.raises(ValueError, match='unlocated linked context'):
        validate_article(payload, SOURCE, audit)


def test_minimum_addition_does_not_allow_unlisted_removed_evidence(tmp_path):
    payload, audit, path = explicit_additions_with_lowered_minimum(tmp_path)
    previous = json.loads(path.read_text())
    quote = 'The additional removed-row evidence must still remain in the corrected review.'
    source = {**SOURCE, 'source_body': BODY + ' ' + quote}
    previous['incidents'][1]['evidence_quotes'] = [quote]
    path.write_text(json.dumps(previous))
    payload['minimum_event_count_correction']['superseded_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='loses previously reviewed incident evidence'):
        validate_article(payload, source, audit)


def test_minimum_addition_still_requires_exact_removed_incidents(tmp_path):
    payload, audit, _ = explicit_additions_with_lowered_minimum(tmp_path)
    payload['minimum_event_count_correction']['removed_incident_ids'] = ['1:incident:1']
    with pytest.raises(ValueError, match='exactly the removed incidents'):
        validate_article(payload, SOURCE, audit)


def test_validates_explicit_six_rule_review():
    result = validate_article(decision(), SOURCE, AUDIT)
    assert result["formal_locations"][0]["transit_review"]["line"] == "U8"
    assert result["formal_locations"][0]["poi_contexts"][0]["association"] == ("source_reviewed_context_only")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("event_times_complete",), False),
        (("incidents", 0, "event_time_review"), None),
        (("formal_locations", 0, "transit_review", "status"), "not_applicable"),
        (("formal_locations", 0, "event_time_review"), None),
        (("formal_locations", 0, "poi_contexts"), None),
        (("six_rule_checks", "discovery_role_checked"), False),
    ],
)
def test_rejects_shortcuts(path, value):
    payload = decision()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((TypeError, ValueError)):
        validate_article(payload, SOURCE, AUDIT)


def test_rejects_missing_independent_event():
    payload = decision()
    payload["incidents"] = []
    with pytest.raises(ValueError, match="omits independent events"):
        validate_article(payload, SOURCE, AUDIT)


def test_reviewed_unknown_time_is_explicit_and_noninvented():
    payload = decision()
    time = payload["incidents"][0]["event_time_review"]
    time.update(
        {
            "status": "reviewed_unknown",
            "display": "",
            "date": None,
            "precision": "unknown",
            "review_note": "The current source body contains no calendar date.",
        }
    )
    assert (
        validate_article(payload, SOURCE, AUDIT)["incidents"][0]["event_time_review"]["status"]
        == "reviewed_unknown"
    )


def test_stale_source_hash_is_rejected():
    payload = copy.deepcopy(decision())
    payload["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="stale or mismatched"):
        validate_article(payload, SOURCE, AUDIT)


def test_non_transit_route_is_explicitly_distinguished():
    payload = decision()
    location = payload["formal_locations"][0]
    location["transit_review"].update(
        {
            "status": "reviewed_non_transit_route",
            "mode": None,
            "line": "",
            "extent": None,
            "review_note": "This is a march route, not public transport.",
        }
    )
    assert (
        validate_article(payload, SOURCE, AUDIT)["formal_locations"][0]["transit_review"]["status"]
        == "reviewed_non_transit_route"
    )


def _inventory(tmp_path, monkeypatch, payload=None):
    monkeypatch.setattr(berlin_semantic_review, "frozen_sources", lambda *_: ([SOURCE], {"1": AUDIT}))
    parts = tmp_path / "reviews"
    parts.mkdir()
    if payload is not None:
        (parts / "review-0001.json").write_text(json.dumps({"articles": [payload]}))
    return berlin_semantic_review.build_geometry_inventory(
        db_path=tmp_path / "readonly.sqlite", audit_root=tmp_path, reviews_dir=parts,
    )


def test_inventory_requires_complete_valid_review(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="1 pending"):
        _inventory(tmp_path, monkeypatch)


def test_inventory_preserves_unknown_times_roles_and_context(tmp_path, monkeypatch):
    result = _inventory(tmp_path, monkeypatch, decision())
    article = result["articles"][0]
    assert len(article["formal_locations"]) == 2
    discovery = article["formal_locations"][1]
    assert discovery["role"] == "discovery"
    assert discovery["event_time_review"]["status"] == "reviewed_unknown"
    assert discovery["event_time"]["date"] is None
    assert discovery["event_time"]["precision"] == "unknown"
    assert "geprüft" in discovery["event_time"]["display"]
    assert all(row["coordinates"] is None for row in article["formal_locations"])
    assert result["geometry_requests"][0]["transit_route"]["line"] == "U8"
    assert result["geometry_requests"][0]["poi_contexts"][0]["association"] == "source_reviewed_context_only"
    assert result["owner_approved"] is result["publication_ready"] is False
    assert "not_independent_offence_total" in result["incident_count_basis"]


def test_inventory_distinguishes_non_transit_routes(tmp_path, monkeypatch):
    payload = decision()
    payload["formal_locations"][0]["transit_review"].update(
        {"status": "reviewed_non_transit_route", "mode": None, "line": "", "extent": None}
    )
    result = _inventory(tmp_path, monkeypatch, payload)
    request = result["geometry_requests"][0]
    assert request["geometry_task"] == "checked_non_transit_route_geometry_required"
    assert "transit_route" not in request


def test_inventory_is_deterministic_and_binds_explicit_decisions(tmp_path, monkeypatch):
    first = _inventory(tmp_path, monkeypatch, decision())
    parts = tmp_path / "reviews"
    second = berlin_semantic_review.build_geometry_inventory(
        db_path=tmp_path / "readonly.sqlite", audit_root=tmp_path, reviews_dir=parts,
    )
    assert first == second
    payload = decision()
    payload["formal_locations"][1]["details"] += " Explicit discovery context."
    (parts / "review-0001.json").write_text(json.dumps({"articles": [payload]}))
    third = berlin_semantic_review.build_geometry_inventory(
        db_path=tmp_path / "readonly.sqlite", audit_root=tmp_path, reviews_dir=parts,
    )
    assert third["inventory_digest"] != first["inventory_digest"]
    assert third["geometry_requests"][1]["geometry_request_sha256"] != first["geometry_requests"][1]["geometry_request_sha256"]
