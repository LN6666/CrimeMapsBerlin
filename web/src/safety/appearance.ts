export type Appearance = 'blue' | 'light';
export const appearanceStorageKey = 'crimemaps:appearance:v1';
type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;
export interface AppearanceLabels {label: string; blue: string; light: string}

export function appearanceValue(value: unknown): Appearance {
  return value === 'light' ? 'light' : 'blue';
}
export function readAppearance(storage?: PreferenceStorage): Appearance {
  try { return appearanceValue(storage?.getItem(appearanceStorageKey)); }
  catch { return 'blue'; }
}
export function saveAppearance(value: Appearance, storage?: PreferenceStorage) {
  try { storage?.setItem(appearanceStorageKey, value); }
  catch { /* The selection still works when browser storage is unavailable. */ }
}
function browserStorage() {
  try { return window.localStorage; }
  catch { return undefined; }
}
export function initializeAppearance() {
  const value = readAppearance(browserStorage());
  document.documentElement.dataset.theme = value;
  return value;
}
export function mountAppearance(parent: HTMLElement, labels: AppearanceLabels) {
  const label = document.createElement('label');
  label.className = 'appearance-switch';
  label.append(document.createTextNode(labels.label));
  const select = document.createElement('select');
  select.id = 'appearance';
  select.setAttribute('aria-label', labels.label);
  select.append(new Option(labels.blue, 'blue'), new Option(labels.light, 'light'));
  select.value = appearanceValue(document.documentElement.dataset.theme);
  label.append(select);
  parent.append(label);
  select.addEventListener('change', () => {
    const value = appearanceValue(select.value);
    document.documentElement.dataset.theme = value;
    saveAppearance(value, browserStorage());
  });
  const synchronize = () => { select.value = initializeAppearance(); };
  window.addEventListener('pageshow', synchronize);
  window.addEventListener('storage', event => {
    if (event.key === appearanceStorageKey || event.key === null) synchronize();
  });
}
