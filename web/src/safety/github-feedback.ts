import {cityIds, repositoryName, type CityId} from './deployment';
export type GitHubLocale = 'de' | 'en' | 'zh';
export type GitHubTranslate = (key: string, params?: Record<string, string | number>, fallback?: string) => string;
export const GITHUB_FEEDBACK_COPY = {
  en: {
    'project.discuss': 'Discuss this map',
    'project.issues': 'Report a problem',
    'project.contribute': 'Share how the map works for you, suggest improvements, or report an error with a link to a public source. Code and wording contributions are welcome too.',
    'project.contributionPrivacy': 'To leave a message, sign in to GitHub. Your account and message are public. Do not include personal or sensitive information.',
    'project.githubRepository': 'Open the {city} project on GitHub',
  },
  de: {
    'project.discuss': 'Über die Karte sprechen',
    'project.issues': 'Problem melden',
    'project.contribute': 'Teile deine Erfahrungen mit der Karte, schlage Verbesserungen vor oder melde einen Fehler mit einer öffentlich zugänglichen Quelle. Auch Beiträge zu Code und Texten sind willkommen.',
    'project.contributionPrivacy': 'Für einen Beitrag musst du dich bei GitHub anmelden. Dein Konto und dein Text sind öffentlich. Bitte keine persönlichen oder sensiblen Angaben veröffentlichen.',
    'project.githubRepository': 'Das Projekt {city} auf GitHub öffnen',
  },
  zh: {
    'project.discuss': '留言讨论',
    'project.issues': '报告问题',
    'project.contribute': '欢迎分享使用感受和改进建议；纠错时请附上公开来源。也欢迎帮助改进代码和文案。',
    'project.contributionPrivacy': '留言需要登录 GitHub，账号和内容都会公开。请勿发布个人信息或敏感资料。',
    'project.githubRepository': '在 GitHub 查看{city}项目',
  },
} as const;
export function githubFeedbackLinks(city: string) {
  if (!cityIds.includes(city as CityId)) return null;
  const repository = `https://github.com/LN6666/${repositoryName(city as CityId)}`;
  return {repository, discussions: `${repository}/discussions`, issues: `${repository}/issues/new/choose`};
}
interface Options {city: string; locale: GitHubLocale; translate?: GitHubTranslate}
function copy(options: Options, key: keyof typeof GITHUB_FEEDBACK_COPY.en, params: Record<string, string | number> = {}) {
  const fallback = GITHUB_FEEDBACK_COPY[options.locale][key].replace(/\{(\w+)\}/g, (match, name) => String(params[name] ?? match));
  return options.translate?.(key, params, fallback) ?? fallback;
}
function externalLink(label: string, href: string) {
  const link = document.createElement('a'); link.textContent = label; link.href = href;
  link.target = '_blank'; link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
  return link;
}
/** Plain links within the existing project introduction; no intake, scripts or requests. */
export function mountGitHubFeedback(parent: HTMLElement, options: Options) {
  const links = githubFeedbackLinks(options.city); if (!links) return {destroy() {}};
  const section = document.createElement('div'); section.className = 'project-feedback';
  const invitation = document.createElement('p'); invitation.textContent = copy(options, 'project.contribute');
  const actions = document.createElement('nav'); actions.className = 'project-feedback-links'; actions.setAttribute('aria-label', 'GitHub');
  actions.append(externalLink(copy(options, 'project.discuss'), links.discussions), externalLink(copy(options, 'project.issues'), links.issues));
  const notice = document.createElement('p'); notice.className = 'project-feedback-privacy'; notice.textContent = copy(options, 'project.contributionPrivacy');
  section.append(invitation, actions, notice); parent.append(section);
  return {destroy() {section.remove();}};
}
const blackMark = new URL('../../../assets/brand/github-mark-black.svg', import.meta.url).href;
const whiteMark = new URL('../../../assets/brand/github-mark-white.svg', import.meta.url).href;
export function mountGitHubFooter(parent: HTMLElement, options: Options) {
  const links = githubFeedbackLinks(options.city); if (!links) return {destroy() {}};
  const fallbackName = options.city[0].toUpperCase() + options.city.slice(1);
  const city = options.translate?.(`city.${options.city}`, {}, fallbackName) ?? fallbackName;
  const label = copy(options, 'project.githubRepository', {city});
  const footer = document.createElement('footer'); footer.className = 'github-repository-footer';
  const anchor = externalLink('', links.repository); anchor.className = 'github-repository-link'; anchor.setAttribute('aria-label', label); anchor.title = label;
  for (const [tone, src] of [['black', blackMark], ['white', whiteMark]]) {
    const image = document.createElement('img'); image.src = src; image.className = `github-mark-${tone}`;
    image.alt = ''; image.setAttribute('aria-hidden', 'true'); image.width = 98; image.height = 96; anchor.append(image);
  }
  footer.append(anchor); parent.append(footer);
  return {destroy() {footer.remove();}};
}
