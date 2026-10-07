// Every number and decision comes from the data; this script only draws it.
// Everything from the data is added as text, never as HTML.

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key.startsWith("aria-") || key.startsWith("data-") || key === "role" || key === "style") node.setAttribute(key, value);
    else node[key] = value;
  }
  node.append(...children.flat(Infinity).filter(child => child != null && child !== false && child !== ""));
  return node;
}

// The theme: Auto follows the system; the choice is kept where the browser allows it.
const THEMES = ["auto", "light", "dark"];
const NAMES = {auto: "Auto", light: "Light", dark: "Dark"};
function storedTheme() {
  try { return THEMES.includes(localStorage.getItem("convy-theme")) ? localStorage.getItem("convy-theme") : "auto"; }
  catch { return "auto"; }
}
let theme = storedTheme();
function applyTheme(button) {
  if (theme === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  if (button) {
    button.textContent = `Theme: ${NAMES[theme]}`;
    button.setAttribute("aria-label", `Theme: ${NAMES[theme]}. Switch theme`);
  }
}
function themeButton() {
  const button = el("button", {className: "theme", type: "button"});
  button.addEventListener("click", () => {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    try { localStorage.setItem("convy-theme", theme); } catch { /* not kept: the next page opens in Auto */ }
    applyTheme(button);
  });
  applyTheme(button);
  return button;
}
applyTheme(null);

const SCENARIO = {passing: "Passing", failing: "Failing", flaky: "Flaky", none: "No verdict"};
const ATTEMPT = {passing: "Passed", failing: "Failed", none: "No verdict"};
const GLYPH = {passing: "✓", failing: "✕", flaky: "◐", none: "–"};

const kind = passed => passed == null ? "none" : passed ? "passing" : "failing";
const icon = result => el("span", {className: `si ${result}`, "aria-hidden": "true"}, GLYPH[result]);
const badge = (result, words = SCENARIO) => el("span", {className: `badge ${result}`}, icon(result), words[result]);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const pct = rate => rate == null ? "—" : `${Math.round(rate * 100)}%`;
const secs = s => s == null ? "—" : s < 10 ? `${s.toFixed(1)} s` : `${Math.round(s)} s`;
const count = n => n == null ? "—" : n < 1000 ? String(Math.round(n)) : n < 1e6 ? `${(n / 1e3).toFixed(n < 1e4 ? 1 : 0)}k` : `${(n / 1e6).toFixed(1)}M`;
const when = iso => new Date(iso).toLocaleString("en-GB", {dateStyle: "medium", timeStyle: "short"});
const STATUS = {running: "not finished", interrupted: "interrupted", finished: null};
