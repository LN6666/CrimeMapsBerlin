import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {transform} from 'esbuild';

const source = readFileSync(new URL('../src/safety/statistics-binding.ts', import.meta.url), 'utf8');
const {code} = await transform(source, {loader:'ts', format:'esm', target:'es2022'});
const {statisticsBinding} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const generation = '0123456789abcdef-20261003T000000';
const binding = {schema_version:1, city:'berlin', map_generation:generation,
  map_announcements:1100, mapping_sha256:'a'.repeat(64), static_reports_checked:false};

test('saved counts bind to the exact loaded city, generation and announcement denominator', () => {
  assert.deepEqual(statisticsBinding(binding, 'berlin', generation, 1100), binding);
  assert.throws(() => statisticsBinding(binding, 'essen', generation, 1100));
  assert.throws(() => statisticsBinding(binding, 'berlin', 'fedcba9876543210-20261003T000000', 1100));
  assert.throws(() => statisticsBinding(binding, 'berlin', generation, 1101));
});

test('missing, invalid, unsafe counts and unconfirmed report availability are rejected', () => {
  for (const value of [null, [], {}, {...binding, schema_version:2},
    {...binding, map_announcements:-1}, {...binding, map_announcements:1100.5},
    {...binding, map_announcements:'1100'}, {...binding, mapping_sha256:'invalid'},
    {...binding, static_reports_checked:undefined}, {...binding, static_reports_checked:'true'}])
    assert.throws(() => statisticsBinding(value, 'berlin', generation, 1100));
});

test('statistics can be read while links to unchecked static reports stay disabled', () => {
  assert.equal(statisticsBinding(binding, 'berlin', generation, 1100).static_reports_checked, false);
  assert.equal(statisticsBinding({...binding, static_reports_checked:true}, 'berlin', generation, 1100).static_reports_checked, true);
});
