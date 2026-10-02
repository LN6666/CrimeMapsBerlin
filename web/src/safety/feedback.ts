import { ufText, type UFLocale, type UFKey } from "./uncertainty-copy";
export interface FeedbackConfig { endpoint: string; siteKey: string; operatorName: string; privacyURL: string }
interface Turnstile {
  render(el: HTMLElement, options: Record<string, unknown>): string;
  remove(id: string): void;
  reset(id: string): void;
}
declare global { interface Window { turnstile?: Turnstile } }
let turnstilePromise: Promise<Turnstile> | undefined;
function turnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (turnstilePromise) return turnstilePromise;
  turnstilePromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true; script.defer = true;
    const timeout = window.setTimeout(() => {script.remove(); turnstilePromise = undefined; reject(Error("challenge timeout"));}, 15000);
    script.onload = () => {window.clearTimeout(timeout); window.turnstile ? resolve(window.turnstile) : reject(Error("challenge unavailable"));};
    script.onerror = () => {window.clearTimeout(timeout); script.remove(); turnstilePromise = undefined; reject(Error("challenge unavailable"));};
    document.head.append(script);
  });
  return turnstilePromise;
}
export function validatedFeedbackConfig(config: FeedbackConfig | undefined): FeedbackConfig | null {
  if (!config || !/^[A-Za-z0-9_-]{20,100}$/.test(config.siteKey) || /^[123]x0{10}/.test(config.siteKey) ||
      !config.operatorName.trim()) return null;
  try {
    const endpoint = new URL(config.endpoint), policy = new URL(config.privacyURL);
    if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash ||
        policy.protocol !== "https:" || policy.username || policy.password) return null;
    return {...config, endpoint: endpoint.href.replace(/\/$/, "")};
  } catch {return null;}
}
export function mountFeedbackPanel(container: HTMLElement, options: {city: string; locale: UFLocale; translate?: (key: UFKey, params?: Record<string, string | number>) => string; config?: FeedbackConfig}) {
  const t = (key: UFKey, params = {}) => options.translate?.(key, params) ?? ufText(options.locale, key, params);
  const section = document.createElement("details"); section.className = "feedback-panel"; section.id = "private-feedback";
  const summary = document.createElement("summary"); summary.textContent = t("feedback.title"); section.append(summary);
  const content = document.createElement("div"); content.className = "feedback-body"; section.append(content);
  const add = (tag: string, value: string, parent: HTMLElement = content) => {
    const node = document.createElement(tag); node.textContent = value; parent.append(node); return node;
  };
  add("p", t("feedback.policy")).className = "feedback-policy";
  const privacy = add("details", ""); privacy.className = "feedback-privacy";
  add("summary", t("feedback.details"), privacy);
  add("p", t("feedback.processing"), privacy); add("p", t("feedback.retention"), privacy);
  const status = add("p", t("feedback.disabled")); status.className = "feedback-status";
  status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
  const config = validatedFeedbackConfig(options.config); let alive = true, widget: string | undefined, token = "";
  let sending = false; const activeRequests = new Set<AbortController>();
  const request = async (path: string, body?: object): Promise<Response> => {
    const controller = new AbortController(); activeRequests.add(controller);
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {return await fetch(`${config!.endpoint}${path}`, {
      method: body ? "POST" : "GET", mode: "cors", credentials: "omit", cache: "no-store", redirect: "error",
      referrerPolicy: "no-referrer", signal: controller.signal,
      headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined,
    });} finally {window.clearTimeout(timer); activeRequests.delete(controller);}
  };
  const input = (form: HTMLElement, caption: string, name: string, max: number) => {
    const label = add("label", caption, form), node = document.createElement("input");
    node.name = name; node.maxLength = max; node.autocomplete = "off"; label.append(node); return node;
  };
  const ready = (async () => {
    if (!config) return false;
    try {
      const r = await request(`/health?city=${encodeURIComponent(options.city)}`);
      const health = await r.json();
      if (!alive || !r.ok || health.enabled !== true || health.policyVersion !== "private-feedback-v1" || health.city !== options.city) return false;
    } catch {return false;}
    if (!alive) return false;
    status.textContent = "";
    section.classList.add("feedback-ready");
    add("p", config.operatorName, privacy).className = "feedback-operator";
    const policy = add("a", t("feedback.policyLink"), privacy) as HTMLAnchorElement;
    policy.href = config.privacyURL; policy.rel = "noopener noreferrer"; policy.target = "_blank"; policy.referrerPolicy = "no-referrer";
    const form = document.createElement("form"); form.className = "feedback-form"; form.noValidate = true; content.append(form);
    const kindLabel = add("label", t("feedback.kind"), form), kind = document.createElement("select"); kind.name = "kind";
    for (const k of ["correction", "accessibility", "privacy", "other"] as const) kind.append(new Option(t(`feedback.${k}`), k)); kindLabel.append(kind);
    const source = input(form, t("feedback.sourceId"), "source_id", 120);
    const messageLabel = add("label", t("feedback.message"), form), message = document.createElement("textarea");
    message.name = "message"; message.minLength = 10; message.maxLength = 2000; message.autocomplete = "off"; message.required = true; messageLabel.append(message);
    const consentLabel = add("label", "", form); consentLabel.className = "feedback-consent";
    const consent = document.createElement("input"); consent.type = "checkbox"; consent.required = true; consentLabel.append(consent, document.createTextNode(t("feedback.consent")));
    add("p", t("feedback.challengeNotice"), form).className = "feedback-challenge-notice";
    const challenge = add("button", t("feedback.challenge"), form) as HTMLButtonElement; challenge.type = "button";
    challenge.className = "feedback-challenge";
    const challengeBox = add("div", "", form); challengeBox.className = "feedback-challenge-box";
    const send = add("button", t("feedback.send"), form) as HTMLButtonElement; send.type = "submit"; send.disabled = true; send.className = "feedback-send";
    challenge.onclick = async () => {
      challenge.disabled = true;
      try {
        const ts = await turnstile(); if (!alive) return;
        if (widget) ts.remove(widget);
        widget = ts.render(challengeBox, {sitekey: config.siteKey, action: "feedback", size: "compact", language: options.locale === "zh" ? "zh-cn" : options.locale,
          callback: (value: string) => {token = value; send.disabled = false;},
          "expired-callback": () => {token = ""; send.disabled = true; challenge.disabled = false;},
          "error-callback": () => {token = ""; send.disabled = true; challenge.disabled = false; status.textContent = t("feedback.challengeFailed");},
        });
      } catch {if (alive) {status.textContent = t("feedback.challengeFailed"); challenge.disabled = false;}}
    };
    form.onsubmit = async e => {
      e.preventDefault(); if (sending) return; const body = message.value.trim();
      if (body.length < 10 || body.length > 2000 || !consent.checked) {status.textContent = t("feedback.validation"); return;}
      if (!token) {status.textContent = t("feedback.challengeFailed"); return;}
      sending = true; send.disabled = true; status.textContent = t("feedback.sending");
      try {
        const r = await request("/feedback", {city: options.city, kind: kind.value, message: body, source_id: source.value.trim() || null, challenge_token: token});
        if (!alive) return;
        if (!r.ok) {status.textContent = t(r.status === 429 ? "feedback.rate" : "feedback.error"); return;}
        const result = await r.json();
        if (!/^[0-9a-f-]{36}$/.test(result.id) || !/^[0-9a-f]{64}$/.test(result.deletionToken)) throw Error("bad receipt");
        status.textContent = t("feedback.success"); message.value = ""; source.value = ""; consent.checked = false;
        const receipt = add("div", ""); receipt.className = "feedback-receipt";
        add("p", t("feedback.receipt", {id: result.id, expires: result.expiresAt}), receipt);
        const secret = input(receipt, t("feedback.token"), "deletion_token", 64); secret.value = result.deletionToken; secret.readOnly = true;
        const remove = add("button", t("feedback.delete"), receipt) as HTMLButtonElement; remove.type = "button";
        remove.onclick = async () => {
          remove.disabled = true;
          try {
            const response = await request("/retract", {id: result.id, deletion_token: secret.value});
            if (response.ok) {secret.value = ""; receipt.remove(); status.textContent = t("feedback.deleted");}
            else {status.textContent = t(response.status === 429 ? "feedback.rate" : "feedback.error"); remove.disabled = false;}
          } catch {status.textContent = t("feedback.error"); remove.disabled = false;}
        };
        const clear = add("button", t("feedback.clear"), receipt) as HTMLButtonElement; clear.type = "button";
        clear.onclick = () => {secret.value = ""; receipt.remove();};
      } catch {if (alive) status.textContent = t("feedback.error");}
      finally {sending = false; token = ""; send.disabled = true; challenge.disabled = false; if (widget) window.turnstile?.reset(widget);}
    };
    const retractDetails = add("details", ""); retractDetails.className = "feedback-retract";
    add("summary", t("feedback.deleteTitle"), retractDetails);
    const retract = document.createElement("form"); retractDetails.append(retract);
    const id = input(retract, t("feedback.receiptId"), "receipt_id", 36), deletion = input(retract, t("feedback.token"), "deletion_token", 64);
    deletion.type = "password";
    const remove = add("button", t("feedback.delete"), retract) as HTMLButtonElement; remove.type = "submit";
    retract.onsubmit = async e => {
      e.preventDefault(); remove.disabled = true;
      try {
        const r = await request("/retract", {id: id.value.trim(), deletion_token: deletion.value.trim()});
        status.textContent = t(r.ok ? "feedback.deleted" : r.status === 429 ? "feedback.rate" : "feedback.error");
        if (r.ok) {id.value = ""; deletion.value = "";}
      } catch {status.textContent = t("feedback.error");}
      finally {remove.disabled = false;}
    };
    return true;
  })();
  container.append(section);
  return {ready, destroy() {alive = false; for (const controller of activeRequests) controller.abort(); if (widget) window.turnstile?.remove(widget); section.replaceChildren(); section.remove();}};
}
