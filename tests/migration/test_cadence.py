import copy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('cadence', ROOT / 'scripts/safety/cadence.py')
cadence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cadence)
POLICY = json.loads((ROOT / 'config/update-cadence.json').read_text())
CITY = json.loads((ROOT / 'city-config.json').read_text())


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def test_all_14_policy_identities_are_bound_and_direct_workers_disabled():
    for city in cadence.CITY_IDS:
        identity = {'city': city, 'repository': 'crimemaps-' + city.capitalize()}
        policy = {**POLICY, **identity}
        result = cadence.plan(policy, identity, {}, instant('2026-10-03T00:00:00Z'))
        assert result['police_check_due'] and result['map_poi_refresh_due']
        assert not result['police_check_may_run'] and not result['map_poi_refresh_may_run']
        assert result['automatic_publication'] is False


@pytest.mark.parametrize('previous,current,due', [
    ('2026-09-30T00:00:00Z', '2026-10-02T23:59:59Z', False),
    ('2026-09-30T00:00:00Z', '2026-10-03T00:00:00Z', True),
    ('2026-03-27T09:00:00+01:00', '2026-03-30T09:00:00+02:00', False),
    ('2026-03-27T09:00:00+01:00', '2026-03-30T10:00:00+02:00', True),
    ('2026-10-23T09:00:00+02:00', '2026-10-26T07:59:59+01:00', False),
    ('2026-10-23T09:00:00+02:00', '2026-10-26T08:00:00+01:00', True),
])
def test_elapsed_72_hours_survives_both_dst_transitions(previous, current, due):
    state = {'city': CITY['city'], 'last_successful_source_check': previous}
    assert cadence.plan(POLICY, CITY, state, instant(current))['police_check_due'] is due


def test_berlin_calendar_boundary_and_month_success_deduplication():
    state = {'city': CITY['city'], 'map_poi_successful_month': '2026-03'}
    before = cadence.plan(POLICY, CITY, state, instant('2026-03-31T21:59:59Z'))
    after = cadence.plan(POLICY, CITY, state, instant('2026-03-31T22:00:00Z'))
    assert before['calendar_month'] == '2026-03' and not before['map_poi_refresh_due']
    assert after['calendar_month'] == '2026-04' and after['map_poi_refresh_due']


def test_failed_checks_leave_state_and_all_three_dates_unchanged():
    state = {'city': CITY['city'], 'last_successful_source_check': '2026-10-01T00:00:00Z',
             'last_announcement_publication': '2026-09-30T00:00:00Z',
             'last_map_poi_snapshot': '2026-09-01T00:00:00Z', 'map_poi_successful_month': '2026-09'}
    prior = copy.deepcopy(state)
    with pytest.raises(ValueError, match='checked success'):
        cadence.record_success(state, 'source_check', instant('2026-10-03T00:00:00Z'),
                               checks_passed=False, acceptance_sha256='a' * 64)
    assert state == prior
    checked = cadence.record_success(state, 'source_check', instant('2026-10-03T00:00:00Z'),
                                     checks_passed=True, acceptance_sha256='a' * 64)
    assert state == prior and checked['last_successful_source_check'] == '2026-10-03T00:00:00+00:00'
    assert checked['last_announcement_publication'] == state['last_announcement_publication']
    assert checked['last_map_poi_snapshot'] == state['last_map_poi_snapshot']
    with pytest.raises(ValueError, match='separate'):
        cadence.record_success(state, 'publication', instant('2026-10-03T00:00:00Z'),
                               checks_passed=True, acceptance_sha256='a' * 64)


def test_initial_snapshot_counts_for_its_actual_month_and_requires_snapshot_date():
    state = {'city': CITY['city']}
    checked = cadence.record_success(state, 'map_poi', instant('2026-10-03T00:00:00Z'),
        checks_passed=True, acceptance_sha256='a' * 64, snapshot_at='2026-09-15T00:00:00Z')
    assert checked['map_poi_successful_month'] == '2026-09'
    assert cadence.plan(POLICY, CITY, checked, instant('2026-10-03T00:00:00Z'))['map_poi_refresh_due']
    same_month = cadence.record_success(state, 'map_poi', instant('2026-10-03T00:00:00Z'),
        checks_passed=True, acceptance_sha256='a' * 64, snapshot_at='2026-10-01T00:00:00Z')
    assert not cadence.plan(POLICY, CITY, same_month, instant('2026-10-03T00:00:00Z'))['map_poi_refresh_due']
    with pytest.raises(ValueError, match='snapshot timestamp'):
        cadence.record_success(state, 'map_poi', instant('2026-10-03T00:00:00Z'),
                               checks_passed=True, acceptance_sha256='a' * 64)


@pytest.mark.parametrize('state,bind_city', [
    ({'city': 'other'}, False), ({'last_successful_source_check': '2026-10-01T00:00:00Z'}, False),
    ({'last_successful_source_check': '2026-10-03T00:00:00'}, True),
    ({'last_successful_source_check': '2026-10-03T00:00:01Z'}, True),
    ({'map_poi_successful_month': '2026-11'}, True), ({'map_poi_successful_month': '2026-13'}, True),
])
def test_foreign_unbound_naive_future_or_invalid_success_state_rejected(state, bind_city):
    if bind_city:
        state = {**state, 'city': CITY['city']}
    with pytest.raises(ValueError):
        cadence.plan(POLICY, CITY, state, instant('2026-10-03T00:00:00Z'))


def test_policy_cannot_disable_release_requirement_or_change_city():
    for delta in ({'city': 'other'}, {'police_check_interval_hours': 24},
                  {'first_publication_refresh_required': False}, {'timezone': 'Asia/Tokyo'}):
        with pytest.raises(ValueError):
            cadence.plan({**POLICY, **delta}, CITY, {}, instant('2026-10-03T00:00:00Z'))


@pytest.mark.parametrize('script,args,success', [
    ('cadence.py', [], True), ('schedule.py', ['show'], True), ('update.py', ['--plan'], True),
    ('schedule.py', ['install'], False), ('schedule.py', ['remove'], False),
    ('update.py', [], False), ('update.py', ['--full'], False),
])
def test_command_is_read_only_and_retired_routes_cannot_modify_checkout_or_home(tmp_path, script, args, success):
    checkout = tmp_path / 'checkout'
    directory = checkout / 'scripts/safety'
    directory.mkdir(parents=True)
    (checkout / 'config').mkdir()
    for name in ('cadence.py', 'schedule.py', 'update.py'):
        shutil.copyfile(ROOT / 'scripts/safety' / name, directory / name)
    (checkout / 'config/update-cadence.json').write_text(json.dumps(POLICY))
    (checkout / 'city-config.json').write_text(json.dumps(CITY))
    home = tmp_path / 'home'
    home.mkdir()
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = subprocess.run([sys.executable, str(directory / script), *args], cwd=checkout,
        env={**os.environ, 'HOME': str(home), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
    assert (result.returncode == 0) is success, result.stderr
    if success:
        assert json.loads(result.stdout)['automatic_publication'] is False
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before
    assert not (checkout / '.runtime').exists() and list(home.iterdir()) == []
