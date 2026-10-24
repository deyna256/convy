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

// A scale under a panel's rows: 0 at the left, its top at the right.
const scaleLine = top => el("div", {className: "scale"}, el("span"), el("span", {}, el("span", {}, "0"), el("span", {}, top)), el("span"));
const swatch = (part, word) => el("span", {}, el("i", {className: `key ${part}`}), word);

// A tile of a spread: its four statistics at the same size, each with what goes under it,
// then its lines.
function spreadTile(label, spread, unit, lines, under = () => null) {
  return el("div", {className: "tile"}, el("span", {className: "l"}, label),
    el("div", {className: "stats"}, STATS.map(k => el("div", {}, el("span", {className: "k"}, STAT[k]), el("span", {className: "v"}, spread ? unit(spread[k]) : "—"), under(k)))),
    lines.map(line => typeof line === "string" ? el("span", {className: "s"}, line) : line));
}

// Tokens by turn: per turn number a bar of the chosen statistic of its answers' input, split into
// what was read from the cache and the new input when every answer reports its cache reads, and a
// bar of their output; the share cached above, how many answers under. `top` is the shared scale's
// top.
function turnChart(title, turns, top) {
  const h = v => `${top ? v / top * 100 : 0}%`;
  const split = turns.some(t => t.cached), whole = turns.some(t => !t.cached);
  const cols = turns.map(t => {
    const input = chosen(t.input), output = chosen(t.output), cached = t.cached ? chosen(t.cached) : null;
    const said = `Turn ${t.turn}, ${STAT[stat]} per answer: ${count(input)} in${cached == null ? ", cache not reported" : `, ${count(cached)} of it from the cache`} · ${count(output)} out`;
    const parts = cached == null ? [el("span", {className: "seg input"})]
      : [el("span", {className: "seg input", style: `flex-grow: ${input - cached}`}), el("span", {className: "seg cache", style: `flex-grow: ${cached}`})];
    return el("div", {className: t.answers < 3 ? "turn few" : "turn", title: said},
      el("span", {className: "share"}, cached == null ? "cache not reported" : `${pct(input ? cached / input : null)} cached`),
      el("div", {className: "bars", "aria-hidden": "true"},
        el("span", {className: "bar", style: `height: ${h(input)}`}, parts),
        el("span", {className: "bar", style: `height: ${h(output)}`}, el("span", {className: "seg output"}))),
      el("span", {className: "tn"}, `Turn ${t.turn}`),
      el("span", {className: "sub"}, `${plural(t.answers, "answer")} · ${plural(t.scenarios, "scenario")}`));
  });
  return el("section", {className: "chart", "aria-label": title}, el("h3", {}, title),
    el("div", {className: "scroll"}, el("div", {className: "turns"}, el("span", {className: "axis"}, el("span", {}, count(top)), el("span", {}, "0")), cols)),
    el("div", {className: "legend"}, split && swatch("cache", "read from the cache"),
      swatch("input", !split ? "input" : whole ? "new input; all of it where the cache is not reported" : "new input"), swatch("output", "output")),
    el("p", {className: "caption"}, "Later turns hold only the longer dialogues."));
}
const turnTop = turns => Math.max(0, ...turns.flatMap(t => [chosen(t.input) ?? 0, chosen(t.output) ?? 0]));

// Tokens by part: a scenario's mean tokens per attempt as one bar split into the parts the agent
// reports. A sum of parts is true only for the mean, so these bars do not follow the switch.
const PARTS = ["cached", "input", "output", "thinking"];
const SEG = {cached: "cache", input: "input", output: "output", thinking: "thinking"};
const partWords = p => ({cached: "from the cache", input: p.cached == null ? "input" : "new input", output: "output", thinking: "thinking"});
const partText = p => PARTS.filter(k => p[k] != null).map(k => `${count(p[k])} ${partWords(p)[k]}`).join(" · ");
const partBar = (p, total, top, thin = false) => el("span", {className: thin ? "pbar thin" : "pbar", style: `width: ${top ? total / top * 100 : 0}%`},
  PARTS.filter(k => p[k]).map(k => el("span", {className: `seg ${SEG[k]}`, style: `flex-grow: ${p[k]}`})));
function partLegend(parts) {
  const has = k => parts.filter(p => p[k] != null);
  const split = has("input").filter(p => p.cached != null).length;
  const input = !split ? "input" : split === has("input").length ? "new input" : "new input; all of it where the cache is not reported";
  return el("div", {className: "legend"}, PARTS.filter(k => has(k).length).map(k => swatch(SEG[k], k === "cached" ? "from the cache" : k === "input" ? input : k)));
}
