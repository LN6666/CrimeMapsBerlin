import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {transform} from 'esbuild';

const source = readFileSync(new URL('../src/safety/appearance.ts', import.meta.url), 'utf8');
const {code} = await transform(source, {loader: 'ts', format: 'esm', target: 'es2022'});
const {appearanceValue, appearanceStorageKey, readAppearance, saveAppearance} =
  await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('a first visit and invalid saved preference select blue', () => {
  assert.equal(readAppearance(), 'blue');
  for (const value of [null, '', 'night', 'dark', 'unexpected', {}, 1]) assert.equal(appearanceValue(value), 'blue');
  assert.equal(appearanceValue('light'), 'light');
});
test('the same small preference is available across city paths on one origin', () => {
  const values = new Map();
  const storage = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
  saveAppearance('light', storage);
  assert.equal(readAppearance(storage), 'light');
  assert.deepEqual([...values.entries()], [[appearanceStorageKey, 'light']]);
  saveAppearance('blue', storage);
  assert.equal(readAppearance(storage), 'blue');
  assert.equal(values.size, 1);
});
test('blocked storage and quota errors leave the page usable', () => {
  const storage = {getItem() {throw new Error('blocked');}, setItem() {throw new Error('quota');}};
  assert.equal(readAppearance(storage), 'blue');
  assert.doesNotThrow(() => saveAppearance('light', storage));
});
test('reading an existing preference does not write anything', () => {
  const storage = {getItem: () => 'light', setItem() {throw new Error('unexpected write');}};
  assert.equal(readAppearance(storage), 'light');
});
