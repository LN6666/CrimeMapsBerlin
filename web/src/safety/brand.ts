import {locale, t} from './i18n';
import {portalDestination} from './deployment';

const wordmarks = {
  en: new URL('../../../assets/brand/crime-map-en.png', import.meta.url).href,
  de: new URL('../../../assets/brand/crime-map-de.png', import.meta.url).href,
};
const policeEagle = new URL('../../../assets/brand/police-eagle.png', import.meta.url).href;

export function mountBrand(placeholder: HTMLElement) {
  const anchor = document.createElement('a');
  anchor.className = 'brand site-brand';
  anchor.href = portalDestination(`?lang=${locale}`);
  anchor.setAttribute('aria-label', t('nav.home'));
  const symbol = document.createElement('img');
  symbol.className = 'brand-police';
  symbol.src = policeEagle;
  symbol.alt = '';
  symbol.setAttribute('aria-hidden', 'true');
  symbol.width = 192;
  symbol.height = 192;
  const lettering = document.createElement('span');
  lettering.className = 'brand-wordmark';
  const image = document.createElement('img');
  image.className = 'brand-title';
  image.src = locale === 'de' ? wordmarks.de : wordmarks.en;
  image.alt = t('app.brandName');
  const crop = document.createElement('span');
  crop.className = 'brand-title-crop';
  crop.append(image);
  lettering.append(crop);
  if (locale === 'zh') {
    const caption = document.createElement('span');
    caption.className = 'brand-caption';
    caption.textContent = t('app.brandName');
    lettering.append(caption);
  }
  anchor.append(symbol, lettering);
  placeholder.replaceWith(anchor);
}
