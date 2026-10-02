"""Plan city-bound update eligibility. This module never fetches or publishes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BERLIN = ZoneInfo('Europe/Berlin')
CITY_IDS = {'berlin','hamburg','munich','cologne','frankfurt','dusseldorf','stuttgart',
            'leipzig','dortmund','bremen','essen','dresden','hannover','nuremberg'}

def utc(value: datetime | str) -> datetime:
    if not isinstance(value,(datetime,str)):
        raise ValueError('A timezone-aware timestamp is required')
    instant = datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('A timezone-aware timestamp is required')
    return instant.astimezone(timezone.utc)

def validate(policy: dict, city_config: dict) -> None:
    city = city_config['city']
    if (city not in CITY_IDS or policy.get('schema_version') != 1 or policy.get('city') != city
            or policy.get('repository') != city_config['repository']
            or city_config['repository'] != 'crimemaps-' + city.capitalize()
            or policy.get('police_check_interval_hours') != 72
            or policy.get('map_poi_cadence') != 'calendar_month'
            or policy.get('timezone') != 'Europe/Berlin'
            or policy.get('first_publication_refresh_required') is not True
            or policy.get('prelaunch_source_check_max_age_hours') != 72
            or policy.get('publication_requires_existing_checked_release_gates') is not True
            or not isinstance(policy.get('operational_timers_enabled'),bool)
            or not isinstance(policy.get('operational_adapters_ready'),bool)):
        raise ValueError('Invalid or foreign-city cadence policy')

def plan(policy: dict, city_config: dict, state: dict, now: datetime) -> dict:
    validate(policy,city_config)
    if not isinstance(state,dict) or (state and state.get('city') != city_config['city']):
        raise ValueError('Update state belongs to another city')
    current = utc(now)
    prior = state.get('last_successful_source_check')
    previous = utc(prior) if prior is not None else None
    if previous and previous > current:
        raise ValueError('Success timestamp is in the future')
    source_due = previous is None or (current-previous).total_seconds() >= 72*3600
    month = current.astimezone(BERLIN).strftime('%Y-%m')
    successful_month = state.get('map_poi_successful_month')
    if successful_month is not None and (not isinstance(successful_month,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',successful_month)):
        raise ValueError('Invalid successful map/POI month')
    if successful_month and successful_month > month:
        raise ValueError('Successful map/POI month is in the future')
    enabled = policy['operational_timers_enabled'] and policy['operational_adapters_ready']
    return {'city':city_config['city'],'repository':city_config['repository'],
            'checked_at':current.isoformat(),'calendar_month':month,'timezone':'Europe/Berlin',
            'police_check_due':source_due,'map_poi_refresh_due':successful_month != month,
            'police_check_may_run':enabled and source_due,'map_poi_refresh_may_run':enabled and successful_month != month,
            'operational_timers_enabled':policy['operational_timers_enabled'],
            'operational_adapters_ready':policy['operational_adapters_ready'],
            'last_successful_source_check':prior,
            'last_announcement_publication':state.get('last_announcement_publication'),
            'last_map_poi_snapshot':state.get('last_map_poi_snapshot'),
            'map_poi_successful_month':successful_month,'automatic_publication':False}

def record_success(state: dict, stage: str, completed_at: datetime, *, checks_passed: bool,
                   acceptance_sha256: str, snapshot_at: datetime | str | None = None) -> dict:
    if (checks_passed is not True or not isinstance(acceptance_sha256,str)
            or not re.fullmatch(r'[a-f0-9]{64}',acceptance_sha256)):
        raise ValueError('Only a hash-bound checked success advances cadence state')
    current = utc(completed_at)
    result = dict(state)
    if stage == 'source_check':
        if state.get('last_successful_source_check') and utc(state['last_successful_source_check']) > current:
            raise ValueError('A success record cannot move backwards')
        result['last_successful_source_check'] = current.isoformat()
        result['source_check_acceptance_sha256'] = acceptance_sha256
    elif stage == 'map_poi':
        if snapshot_at is None:
            raise ValueError('The actual accepted snapshot timestamp is required')
        snapshot = utc(snapshot_at)
        month = snapshot.astimezone(BERLIN).strftime('%Y-%m')
        if snapshot > current or state.get('map_poi_successful_month','') > month:
            raise ValueError('Future or superseded snapshot cannot advance the successful month')
        result['map_poi_successful_month'] = month
        result['last_map_poi_snapshot'] = snapshot.isoformat()
        result['map_poi_acceptance_sha256'] = acceptance_sha256
    else:
        raise ValueError('Publication and source/snapshot dates use separate checked records')
    return result

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--now',help='Aware ISO timestamp for deterministic inspection')
    args = parser.parse_args(argv)
    state = json.loads(args.state.read_text()) if args.state else {}
    policy = json.loads((ROOT/'config/update-cadence.json').read_text())
    city = json.loads((ROOT/'city-config.json').read_text())
    print(json.dumps(plan(policy,city,state,utc(args.now) if args.now else datetime.now(timezone.utc)),indent=2))

if __name__ == '__main__':
    main()
