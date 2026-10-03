export type AnalyticsLanguage = 'de' | 'en' | 'zh';
export const analyticsCopy = {
 en: {
  'analytics.notes':'About these statistics', 'analytics.title':'Map visits', 'analytics.countries':'Page views by country or region',
  'analytics.notConnected':'No visit origin data yet.',
  'analytics.loading':'Loading country statistics…', 'analytics.unavailable':'Country statistics are temporarily unavailable.',
  'analytics.total':'Page views', 'analytics.small':'Too few page views to publish a total.',
  'analytics.collection':'GoatCounter counts page loads and reloads, excluding language changes and map operations. These are not unique visitors.',
  'analytics.off':'Visit collection is not enabled on this page.',
  'analytics.privacy':'Country totals only. The connection IP is processed to estimate the country; individual pageviews, referrers and sessions are disabled.',
  'analytics.updated':'Snapshot updated', 'analytics.range':'Statistics period', 'analytics.source':'Source: GoatCounter website aggregate. README images may be cached.',
 },
 de: {
  'analytics.notes':'Über diese Statistik', 'analytics.title':'Kartenbesuche', 'analytics.countries':'Seitenaufrufe nach Ländern und Regionen',
  'analytics.notConnected':'Noch keine Daten zur Herkunft der Aufrufe.',
  'analytics.loading':'Länderstatistik wird geladen…', 'analytics.unavailable':'Die Länderstatistik ist vorübergehend nicht verfügbar.',
  'analytics.total':'Seitenaufrufe', 'analytics.small':'Zu wenige Seitenaufrufe, um eine Summe zu veröffentlichen.',
  'analytics.collection':'GoatCounter zählt Seitenaufrufe und Neuladen; Sprachwechsel und Kartenaktionen zählen nicht zusätzlich. Das sind keine eindeutigen Besucher.',
  'analytics.off':'Auf dieser Seite ist die Besuchserfassung nicht aktiviert.',
  'analytics.privacy':'Nur Länderaggregate. Die Verbindungs-IP wird zur Schätzung des Landes verarbeitet; Einzelaufrufe, Verweise und Sitzungen sind deaktiviert.',
  'analytics.updated':'Snapshot aktualisiert', 'analytics.range':'Statistikzeitraum', 'analytics.source':'Quelle: GoatCounter-Website-Aggregat. README-Bilder können zwischengespeichert sein.',
 },
 zh: {
  'analytics.notes':'统计说明与隐私', 'analytics.title':'地图访问', 'analytics.countries':'页面浏览国家／地区分布',
  'analytics.notConnected':'暂无访问来源数据',
  'analytics.loading':'正在读取国家统计…', 'analytics.unavailable':'国家统计暂时不可用。',
  'analytics.total':'浏览量', 'analytics.small':'浏览次数较少，暂不公布总数。',
  'analytics.collection':'GoatCounter 统计页面加载及刷新，语言切换和地图操作不另计；这些次数不是独立访客。',
  'analytics.off':'此页面尚未启用访问采集。',
  'analytics.privacy':'仅保留国家汇总。连接 IP 用于估计国家；已关闭单次访问记录、来路和会话。',
  'analytics.updated':'快照更新时间', 'analytics.range':'统计期间', 'analytics.source':'来源：GoatCounter 网站访问汇总。README 图片可能有缓存。',
 },
} as const;
export type AnalyticsKey = keyof typeof analyticsCopy.en;
