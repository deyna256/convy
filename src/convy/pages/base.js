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
const atTrust = trust => trust > 0 ? ` · trust ${trust}` : "";
const secs = s => s == null ? "—" : s < 10 ? `${s.toFixed(1)} s` : `${Math.round(s)} s`;
const count = n => n == null ? "—" : n < 1000 ? String(Math.round(n)) : n < 1e6 ? `${(n / 1e3).toFixed(n < 1e4 ? 1 : 0)}k` : `${(n / 1e6).toFixed(1)}M`;
const when = iso => new Date(iso).toLocaleString("en-GB", {dateStyle: "medium", timeStyle: "short"});
const STATUS = {running: "not finished", interrupted: "interrupted", finished: null};

// Squares, one per attempt: ✓, ✕ or – with its word in the title, the open attempt outlined, a
// click opening one. Not tab stops: the row's Open button and the window's tabs are the keyboard's.
const MARK = {passing: "✓", failing: "✕", none: "–"};
function squares(marks, what, open, go) {
  return el("span", {className: "squares", role: "img", "aria-label": `${what}: ${marks.map(m => m.word).join(", ")}`},
    marks.map(m => {
      const square = el("span", {className: `sq ${m.result}${m.attempt === open ? " at" : ""}${go ? " go" : ""}`, title: `Attempt ${m.attempt}: ${m.word}`}, MARK[m.result]);
      if (go) square.addEventListener("click", event => { event.stopPropagation(); go(m.attempt); });
      return square;
    }));
}
const attemptMarks = attempts => attempts.map(a => ({attempt: a.attempt, result: kind(a.passed),
  word: a.cut ? "not trusted" : a.passed == null ? "no verdict" : a.passed ? "passed" : "failed"}));
const claimMarks = (attempts, i) => attempts.map(a => {
  const d = a.claims[i], shown = d.passed != null && d.trusted;
  return {attempt: a.attempt, result: shown ? kind(d.passed) : "none",
    word: d.passed == null ? "not decided" : !d.trusted ? "not trusted" : d.passed ? "held" : "failed"};
});

// A panel of the spread or change block: its title, its rows, its scale, and "Show all" past ten.
const ROWS = 10;
let every = false;
function chart(title, rows, scale, redraw) {
  if (!rows.length) return el("section", {className: "chart", "aria-label": title}, el("h3", {}, title), el("p", {className: "empty"}, "No scenario to show"));
  const more = rows.length > ROWS && el("button", {className: "more", type: "button"}, every ? "Show fewer" : `Show all ${rows.length}`);
  if (more) more.addEventListener("click", () => { every = !every; redraw(); });
  return el("section", {className: "chart", "aria-label": title}, el("h3", {}, title), rows.slice(0, every ? rows.length : ROWS), scale, more);
}

// The statistic of each time and token spread that the charts and tables after the switch show,
// one per page, P50 by default. The address keeps it as stat=, beside the open scenario's id and
// attempt; P50 is not written.
const STATS = ["p50", "p90", "max", "mean"];
const STAT = {p50: "P50", p90: "P90", max: "Max", mean: "Mean"};
const MEANING = {p50: "P50: half the values are at or under it", p90: "P90: 9 in 10 values are at or under it",
  max: "Max: the largest value", mean: "Mean: the sum of the values over their count"};
function readAddress() {
  const hash = location.hash.slice(1), first = hash.split("&")[0];
  return new URLSearchParams(first && !first.includes("=") ? `id=${hash}` : hash);  // part 1's #<id>&attempt=<n>
}
function writeAddress(params) {
  params.delete("stat");
  if (stat !== "p50") params.set("stat", stat);
  const hash = params.toString();
  history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
}
let stat = STATS.includes(readAddress().get("stat")) ? readAddress().get("stat") : "p50";
const chosen = spread => spread == null ? null : spread[stat];
function statSwitch(redraw) {
  const buttons = STATS.map(s => el("button", {type: "button", "aria-pressed": String(s === stat), title: MEANING[s]}, STAT[s]));
  buttons.forEach((button, i) => button.addEventListener("click", () => {
    stat = STATS[i];
    buttons.forEach((other, j) => other.setAttribute("aria-pressed", String(i === j)));
    writeAddress(readAddress());
    redraw();
  }));
  return el("div", {className: "switch"}, el("span", {"aria-hidden": "true"}, "Charts show:"), el("div", {role: "group", "aria-label": "Charts show"}, buttons));
}
