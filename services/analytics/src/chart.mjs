import { buildWorldCardModel, buildPlaceholderModel, isPublicStats, renderWorldCardSvg } from './world-card.mjs';
export { escapeXml, countryName } from './world-card.mjs';
export function validateStats(stats) {
  return isPublicStats(stats) && (stats.collection_start_date===null || /^\d{4}-\d{2}-\d{2}$/.test(stats.collection_start_date));
}
export function renderChart(stats,lang='en',layout='wide') {
  if (!validateStats(stats)) throw new Error('invalid_chart_data');
  return renderWorldCardSvg(buildWorldCardModel(stats,lang),layout);
}
export function renderPlaceholder(city,lang='en',layout='wide') {
  return renderWorldCardSvg(buildPlaceholderModel(city,lang),layout);
}
