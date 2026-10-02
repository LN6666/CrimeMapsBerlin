import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {transform} from 'esbuild';

const source = readFileSync(new URL('../src/safety/deployment.ts', import.meta.url), 'utf8');
const {code} = await transform(source, {loader: 'ts', format: 'esm', target: 'es2022'});
const {cityIds, cityDestination, portalDestination, assetPath, requestedMonth} =
  await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('all 14 production city destinations use independent pages and preserve language/month', () => {
  const paths = new Set();
  for (const city of cityIds) {
    const url = new URL(cityDestination(city, '?lang=zh&month=2026-05&city=wrong&private=discard'));
    assert.equal(url.origin, 'https://ln6666.github.io');
    assert.equal(url.pathname, `/crimemaps-${city[0].toUpperCase()}${city.slice(1)}/${city === 'berlin' ? 'map/' : ''}`);
    assert.equal(url.search, '?lang=zh&month=2026-05');
    paths.add(url.pathname);
  }
  assert.equal(paths.size, 14);
});

test('portal return preserves each language without forwarding map or private state', () => {
  for (const lang of ['de', 'en', 'zh']) {
    assert.equal(portalDestination(`?lang=${lang}&month=2026-01&city=essen&private=discard`),
      `https://ln6666.github.io/crimemaps-Berlin/?lang=${lang}`);
  }
});

test('local preview navigation uses its own origin and keeps repository data paths', () => {
  const targets = {origin: 'http://127.0.0.1:8814', portalPath: '/', berlinMapPath: '/crimemaps-Berlin/'};
  assert.equal(portalDestination('?lang=en', targets), 'http://127.0.0.1:8814/?lang=en');
  assert.equal(cityDestination('berlin', '?lang=de', '2026-09', targets),
    'http://127.0.0.1:8814/crimemaps-Berlin/?lang=de&month=2026-09');
  assert.equal(cityDestination('frankfurt', '?lang=zh', '2026-09', targets),
    'http://127.0.0.1:8814/crimemaps-Frankfurt/?lang=zh&month=2026-09');
  assert.equal(assetPath('/safety/manifest.json', '/crimemaps-Berlin/'), '/crimemaps-Berlin/safety/manifest.json');
});

test('available-month fallback stays within the destination city', () => {
  assert.equal(requestedMonth('?month=2026-05', ['2026-06', '2026-09'], '2026-09'), '2026-09');
  assert.equal(requestedMonth('?month=2026-06', ['2026-06', '2026-09'], '2026-09'), '2026-06');
  assert.equal(new URL(cityDestination('essen', '?lang=en&month=2026-01', '2026-09')).search,
    '?lang=en&month=2026-09');
  assert.equal(new URL(cityDestination('essen', '?month=2026-13')).search, '');
  assert.equal(new URL(cityDestination('hamburg', '?lang=en&month=2026-05', 'undefined-undefined')).search,
    '?lang=en&month=2026-05');
});

test('Chinese language alias becomes the actual supported page locale', () => {
  assert.equal(new URL(cityDestination('berlin', '?lang=zh-CN')).search, '?lang=zh');
  assert.equal(new URL(portalDestination('?lang=zh-CN')).search, '?lang=zh');
  assert.equal(new URL(portalDestination('?lang=unknown')).search, '');
});

test('navigation rejects a foreign path, protocol, credentials, and unknown city', () => {
  for (const portalPath of ['//evil.example/', '/../private/', '/encoded%2Fpath/', '/map/?next=evil']) {
    assert.throws(() => portalDestination('', {origin: 'https://ln6666.github.io', portalPath, berlinMapPath: '/map/'}));
  }
  for (const origin of ['javascript:alert(1)', 'https://user:password@example.org', 'https://example.org/path/', 'https://example.org/?next=evil']) {
    assert.throws(() => portalDestination('', {origin, portalPath: '/', berlinMapPath: '/map/'}));
  }
  assert.throws(() => cityDestination('../private', '?lang=en'));
});
