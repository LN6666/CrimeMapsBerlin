"""Build the Berlin entrance from checked, repository-local portal resources."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil

CITY_IDS = ('berlin', 'hamburg', 'munich', 'cologne', 'frankfurt', 'dusseldorf',
            'stuttgart', 'leipzig', 'dortmund', 'bremen', 'essen', 'dresden', 'hannover', 'nuremberg')
COPY_KEYS = {'title', 'home', 'caption', 'grid', 'open', 'about', 'note', 'details', 'images', 'repo', 'alt'}
PUBLIC_CODE = ('portal.js', 'portal.css', 'portal-time.mjs', 'portal-appearance.mjs')

def checked_source(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
        raise ValueError('Symlink in portal source')
    if not path.is_file():
        raise ValueError('Missing portal resource: ' + relative)
    return path

def build(output: Path, root: Path | None = None) -> dict:
    root = root or Path(__file__).resolve().parent
    if output.exists():
        raise ValueError('Output exists; preserve prior good portal')
    cities = json.loads(checked_source(root, 'cities.json').read_bytes())
    if [c.get('city') for c in cities] != list(CITY_IDS):
        raise ValueError('Expected all fourteen ordered cities')
    for c in cities:
        repository = 'crimemaps-' + c['city'].capitalize()
        expected_path = '/' + repository + ('/map/' if c['city'] == 'berlin' else '/')
        if (set(c) != {'city', 'names', 'landmark', 'map_path', 'month', 'officialPoliceUrl'}
                or c['map_path'] != expected_path
                or any(set(c[key]) != {'de', 'en', 'zh'} for key in ('names', 'landmark'))
                or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for key in ('names', 'landmark') for v in c[key].values())
                or c['month'] is not None and not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', c['month'])):
            raise ValueError('Invalid public city metadata')
    locales = {lang: json.loads(checked_source(root, 'locales/' + lang + '.json').read_bytes()) for lang in ('de', 'en', 'zh')}
    for resource in locales.values():
        if set(resource) != {'copy', 'appearanceCopy'} or set(resource['copy']) != COPY_KEYS or set(resource['appearanceCopy']) != {'label', 'blue', 'light'}:
            raise ValueError('Unexpected portal locale keys')
        if any(not isinstance(v, str) or not v.strip() or len(v) > 4000 for group in resource.values() for v in group.values()):
            raise ValueError('Invalid portal copy')
    copy = locales['de']['copy']
    appearance = locales['de']['appearanceCopy']
    assets = json.loads(checked_source(root, 'assets.json').read_bytes())
    expected_assets = {f'portal-assets/cityscapes/{c}{suffix}.jpg' for c in CITY_IDS for suffix in ('', '-night')}
    expected_assets |= {f'portal-assets/icons/{c}.png' for c in CITY_IDS}
    expected_assets |= {f'portal-assets/brand/{p}.png' for p in ('crime-map-de', 'crime-map-en', 'police-eagle')}
    if len(assets) != 45 or {a.get('path') for a in assets} != expected_assets:
        raise ValueError('Portal visual allowlist differs')
    for a in assets:
        p = checked_source(root, a['path'])
        if len(p.read_bytes()) != a['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest() != a['sha256']:
            raise ValueError('Portal image hash changed')
    if sum(a['bytes'] for a in assets) > 15_000_000:
        raise ValueError('Portal images exceed bounded budget')
    e = html.escape
    cards = []
    for index, c in enumerate(cities):
        city = c['city']
        name = c['names']['de']
        query = '?lang=de' + ('&month=' + c['month'] if c['month'] else '')
        label = copy['open'].replace('{city}', name)
        alt = copy['alt'].replace('{city}', name).replace('{landmark}', c['landmark']['de'])
        cards.append(f'''<a class="city-tile" data-city="{city}" href="{e(c['map_path'] + query)}" aria-label="{e(label)}"><div class="city-photo"><img data-day-src="portal-assets/cityscapes/{city}.jpg" data-night-src="portal-assets/cityscapes/{city}-night.jpg" width="960" height="600" loading="{'eager' if index < 4 else 'lazy'}" decoding="async" {'fetchpriority="high"' if index == 0 else ''} alt="{e(alt)}"><span class="city-icon" aria-hidden="true"><img src="portal-assets/icons/{city}.png" width="64" height="64" alt=""></span></div><span class="city-label"><span class="city-name">{e(name)}</span><span class="city-arrow" aria-hidden="true">↗</span></span></a>''')
    page = f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#111b29"><title>{e(copy['title'])}</title><link rel="icon" type="image/png" href="portal-assets/brand/police-eagle.png"><link rel="stylesheet" href="portal.css"></head><body><header class="masthead"><a class="home-mark" href="./?lang=de" aria-label="{e(copy['home'])}"><img class="police-symbol" src="portal-assets/brand/police-eagle.png" width="78" height="78" alt="" aria-hidden="true"><span class="wordmark-crop"><img class="brand-art" src="portal-assets/brand/crime-map-de.png" width="1120" height="160" alt="{e(copy['title'])}"></span></a><div class="header-tools"><nav class="language-switch" aria-label="Sprache"><button data-language="de" lang="de" aria-pressed="true">Deutsch</button><button data-language="en" lang="en" aria-pressed="false">English</button><button data-language="zh" lang="zh-CN" aria-pressed="false">中文</button></nav><label class="appearance-switch"><span data-appearance-label>{e(appearance['label'])}</span><select id="appearance" aria-label="{e(appearance['label'])}"><option value="blue">{e(appearance['blue'])}</option><option value="light">{e(appearance['light'])}</option></select></label><p class="header-caption" data-copy="caption">{e(copy['caption'])}</p></div></header><main><h1 class="sr-only" data-copy="title">{e(copy['title'])}</h1><div class="city-grid" aria-label="{e(copy['grid'])}">{''.join(cards)}</div></main><footer class="portal-footer"><details><summary data-copy="about">{e(copy['about'])}</summary><div class="footer-body"><p data-copy="note">{e(copy['note'])}</p><p data-copy="details">{e(copy['details'])}</p><p data-copy="images">{e(copy['images'])}</p></div></details><a class="repo-link" href="https://github.com/LN6666/crimemaps-Berlin" target="_blank" rel="noopener noreferrer" data-copy="repo">{e(copy['repo'])}</a></footer><script src="portal-cities.js"></script><script src="portal.js" type="module"></script></body></html>'''
    output.mkdir(parents=True)
    (output / 'index.html').write_text(page, encoding='utf-8')
    (output / 'portal-cities.js').write_text('const cities=' + json.dumps(cities, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    values = {'portalCopy': {k: v['copy'] for k, v in locales.items()}, 'portalAppearanceCopy': {k: v['appearanceCopy'] for k, v in locales.items()}}
    (output / 'portal-locales.js').write_text(''.join('export const ' + k + '=' + json.dumps(v, ensure_ascii=False, separators=(',', ':')) + ';\n' for k, v in values.items()), encoding='utf-8')
    for relative in PUBLIC_CODE + tuple(sorted(expected_assets)):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_source(root, relative), destination)
    expected = {'index.html', 'portal-cities.js', 'portal-locales.js', *PUBLIC_CODE, *expected_assets}
    if {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} != expected:
        raise ValueError('Unexpected public portal file')
    return {'files': 52, 'cities': 14, 'day_images': 14, 'night_images': 14, 'default_locale': 'de', 'map_path': '/crimemaps-Berlin/map/', 'scientific_city_data_in_portal': False}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output)))
