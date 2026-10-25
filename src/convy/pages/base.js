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
const notTrusted = cut => cut ? ` · ${cut} not trusted` : "";
const secs = s => s == null ? "—" : s > 0 && s < 0.1 ? `${Math.round(s * 1000)} ms` : s < 10 ? `${s.toFixed(1)} s` : `${Math.round(s)} s`;
const count = n => n == null ? "—" : n < 1000 ? String(Math.round(n)) : n < 1e6 ? `${(n / 1e3).toFixed(n < 1e4 ? 1 : 0)}k` : `${(n / 1e6).toFixed(1)}M`;
const when = iso => new Date(iso).toLocaleString("en-GB", {dateStyle: "medium", timeStyle: "short"});
const STATUS = {running: "not finished", interrupted: "interrupted", finished: null};

// Squares, one per attempt: ✓, ✕ or – with its word in the title, the open attempt outlined, a
// click opening one. Not tab stops: the row's Open button and the window's tabs are the keyboard's.
function squares(marks, what, open, go) {
  return el("span", {className: "squares", role: "img", "aria-label": `${what}: ${marks.map(m => m.word).join(", ")}`},
    marks.map(m => {
      const square = el("span", {className: `sq ${m.result}${m.attempt === open ? " at" : ""}${go ? " go" : ""}`, title: `Attempt ${m.attempt}: ${m.word}`}, GLYPH[m.result]);
      if (go) square.addEventListener("click", event => { event.stopPropagation(); go(m.attempt); });
      return square;
    }));
}
const attemptMarks = attempts => attempts.map(a => ({attempt: a.attempt, result: kind(a.passed),
  word: a.cut ? "not trusted" : a.passed == null ? "no verdict" : a.passed ? "passed" : "failed"}));

function readAddress() {
  const hash = location.hash.slice(1), first = hash.split("&")[0];
  return new URLSearchParams(first && !first.includes("=") ? `id=${hash}` : hash);  // part 1's #<id>&attempt=<n>
}
const kept = {};  // the settings the address keeps, each unwritten at its default; a page adds its own
function writeAddress(params) {
  for (const [key, value] of Object.entries(kept)) { params.delete(key); if (value()) params.set(key, value()); }
  const hash = params.toString();
  history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
}

// A panel with nothing to show, and the button that shows all of a panel's rows or fewer; `every`
// holds the panels showing all, by a key of the page's choice.
const every = new Set();
const emptyPanel = (title, text) => el("section", {className: "chart", "aria-label": title}, el("h3", {}, title), el("p", {className: "empty"}, text));
function moreButton(key, rows, redraw) {
  const all = every.has(key), button = el("button", {className: "more", type: "button"}, all ? "Show fewer" : `Show all ${rows}`);
  button.addEventListener("click", () => { all ? every.delete(key) : every.add(key); redraw(); });
  return button;
}

// A panel's message, in a line under its title.
function lede(section, text) {
  if (text) section.querySelector("h3").after(el("p", {className: "lede"}, text));
  return section;
}

// A scale from 0 that ends on a round value past `most`: its ticks are 1, 2 or 5 times a power of
// ten, four or five of them. Its panel's tracks draw a faint line at each tick.
function axis(most) {
  if (!(most > 0)) return {top: 0, step: 0, ticks: [0]};
  const rough = most / 4, power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map(m => m * power).find(s => s >= rough);
  const top = Math.ceil(most / step - 1e-9) * step;
  return {top, step, ticks: Array.from({length: Math.round(top / step) + 1}, (_, i) => i * step)};
}
const gridStyle = a => a.step ? `--grid: ${a.step / a.top * 100}%` : null;
// The scale under a panel's rows: a label at each tick.
const scaleLine = (a, unit) => el("div", {className: "scale"}, el("span"),
  el("span", {className: "ticks"}, a.ticks.map(v => el("span", {style: `left: ${a.top ? v / a.top * 100 : 0}%`}, v ? unit(v) : "0"))), el("span"));

// The parts of tokens, their colours and their words.
const PARTS = ["cached", "input", "output", "thinking"];
const SEG = {cached: "cache", input: "input", output: "output", thinking: "thinking"};
const partWords = p => ({cached: "from the cache", input: p.cached == null ? "input" : "new input", output: "output", thinking: "thinking"});

// One tooltip for the page: what the mark under the pointer holds, as its data-tip says. The other
// parts of its bar fade while it is pointed at.
const tip = el("div", {className: "tip", role: "tooltip", hidden: true});
document.addEventListener("DOMContentLoaded", () => document.body.append(tip));
document.addEventListener("pointerover", event => {
  const mark = event.target instanceof Element ? event.target.closest("[data-tip]") : null;
  tip.hidden = !mark;
  if (mark) tip.textContent = mark.dataset.tip;
});
document.addEventListener("pointermove", event => {
  if (tip.hidden) return;
  tip.style.left = `${Math.max(8, Math.min(event.clientX + 14, innerWidth - tip.offsetWidth - 8))}px`;
  tip.style.top = `${event.clientY + 18 + tip.offsetHeight > innerHeight ? event.clientY - tip.offsetHeight - 10 : event.clientY + 18}px`;
});
