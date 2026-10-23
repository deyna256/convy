const STOPS = {user_stop: "the user finished", max_turns: "the turns ran out", agent_failure: "the agent failed", agent_busy: "the agent's service stayed busy", model_failure: "convy's model failed"};
const clock = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("width", "14"); svg.setAttribute("height", "14"); svg.setAttribute("aria-hidden", "true");
  for (const [name, attrs] of [["circle", {cx: 8, cy: 8, r: 6.5}], ["path", {d: "M8 4.5V8l2.5 1.5", "stroke-linecap": "round"}]]) {
    const part = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries({...attrs, fill: "none", stroke: "currentColor", "stroke-width": 1.5})) part.setAttribute(key, value);
    svg.append(part);
  }
  return svg;
};

// A safe subset of Markdown, built as DOM nodes: paragraphs, line breaks, **bold**, *italic*,
// `code`, lists and #–### headings. Anything else stays text.
function inline(text) {
  const nodes = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|\*([^*\s][^*]*?)\*/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    nodes.push(text.slice(last, match.index));
    if (match[1] != null) nodes.push(el("strong", {}, inline(match[1])));
    else if (match[2] != null) nodes.push(el("code", {}, match[2]));
    else nodes.push(el("em", {}, inline(match[3])));
    last = match.index + match[0].length;
  }
  nodes.push(text.slice(last));
  return nodes;
}
function markdown(text) {
  const blocks = [];
  let list = null, lines = [];
  const flush = () => {
    if (lines.length) blocks.push(el("p", {}, lines.flatMap((line, i) => i ? [el("br"), inline(line)] : [inline(line)])));
    lines = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/), number = line.match(/^\s*(\d{1,9})[.)]\s+(.*)$/), heading = line.match(/^#{1,3}\s+(.*)$/);
    if (bullet || number) {
      flush();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) { list = el(tag); blocks.push(list); }
      list.append(el("li", number ? {value: Number(number[1])} : {}, inline(bullet ? bullet[1] : number[2])));
      continue;
    }
    list = null;
    if (heading) { flush(); blocks.push(el("p", {className: "h"}, inline(heading[1]))); }
    else if (!line.trim()) flush();
    else lines.push(line);
  }
  flush();
  return blocks;
}

// The scenario window's parts, and the filter of its table.
function claimTally(c) {
  const grades = c.grades.filter(([, n]) => n).reverse().map(([grade, n]) => ` · ${grade} ${n}`).join("");  // best first
  return (!c.judged ? "no trusted verdict on this claim" : c.held === 0 ? `failed in ${c.judged} of ${c.judged}` : `held in ${c.held} of ${c.judged}`) + grades + notTrusted(c.cut);
}
function attemptTiles(attempt) {
  const answers = attempt.turns.length;
  const result = kind(attempt.passed);
  return el("div", {className: "mini"},
    el("div", {}, el("span", {className: "l"}, "Result"), el("span", {className: `v ${result}`}, icon(result), attempt.cut ? "Not trusted" : ATTEMPT[result]), el("span", {className: "s"}, STOPS[attempt.stop] ?? attempt.stop)),
    el("div", {}, el("span", {className: "l"}, "Total answer time"), el("span", {className: "v"}, secs(attempt.seconds)), el("span", {className: "s"}, attempt.slowest == null ? "no answers" : `${plural(answers, "answer")} · slowest ${secs(attempt.slowest)}`)),
    el("div", {}, el("span", {className: "l"}, "Tokens"), el("span", {className: "v"}, count(attempt.tokens)),
      el("span", {className: "s"}, attempt.input == null ? "not reported" : tokenParts(attempt))));
}
// In and out, each with the parts that were reported, a reported 0 too.
function tokenParts(v) {
  const part = (n, what) => n == null ? "" : `, ${count(n)} ${what}`;
  return `${count(v.input)} in${part(v.cache_read, "from cache")}${part(v.cache_write, "to cache")} · ${count(v.output)} out${part(v.thinking_tokens, "thinking")}`;
}
// How sure the judge was of a decision, at the run's trust; nothing when the run's judge never says.
function sure(claim, run) {
  if (claim.confidence == null) return run.confident ? "sure: not given" : null;
  const said = `${Math.floor(claim.confidence * 100)}% sure`;
  return claim.trusted ? said : `not trusted: ${said}, needs ${Math.round(run.trust * 100)}%`;
}
function judgeLines(attempt, run) {
  if (attempt.error) return el("div", {className: "error"}, attempt.error);  // the agent or convy's model failed
  return el("div", {className: "judge"}, attempt.claims.map((claim, i) => {
    const note = sure(claim, run);
    return el("div", {}, el("span", {className: "no"}, String(i + 1)), icon(kind(claim.passed)),
      el("span", {className: "why"}, claim.grade != null && [el("strong", {}, claim.grade), " · "], claim.reason || "No reason given.", note && el("small", {className: "muted"}, ` · ${note}`)));
  }));
}
function dialogue(attempt) {
  return attempt.turns.flatMap(t => [
    el("div", {className: "msg user"}, el("span", {className: "who"}, "USER"), el("div", {className: "bubble"}, t.user)),
    el("div", {className: "msg agent"}, el("div", {className: "bubble"},
      el("div", {className: "bhead"}, el("span", {className: "who"}, "AGENT"),
        el("span", {className: "m"}, clock(), el("strong", {}, secs(t.seconds))),
        el("span", {className: "m"}, t.tokens == null ? el("span", {className: "muted"}, "tokens not reported")
          : [el("strong", {}, count(t.tokens)), " tokens ", el("span", {className: "muted"}, `· ${tokenParts(t)}`)])),
      steps(t),
      markdown(t.agent))),
  ]);
}
// An answer's steps, in their order: thoughts as text, calls on a time line of their own.
function steps(t) {
  if (!t.steps.length) return null;
  const counts = [t.thoughts && plural(t.thoughts, "thought"), t.calls && plural(t.calls, "call")].filter(Boolean).join(", ");
  return el("details", {className: "steps"}, el("summary", {}, `Steps · ${counts}`),
    t.steps.map(s => s.type === "thought" ? el("div", {className: "thought"}, s.text) : callRow(s)));
}
function callRow(c) {
  return el("div", {className: "call"},
    el("span", {className: "name"}, c.name),
    el("span", {className: "track"}, el("span", {className: "bar", style: `left: min(${c.left * 100}%, 100% - 3px); width: ${c.width * 100}%`})),
    el("span", {className: "m"}, secs(c.seconds), " · ", c.tokens == null ? el("span", {className: "muted"}, "tokens not reported") : `${count(c.tokens)} tokens`),
    el("details", {className: "io"}, el("summary", {}, "Sent and received"),
      el("div", {className: "sec"}, "Sent"), reported(c.sent),
      el("div", {className: "sec"}, "Received"), reported(c.received)));
}
// Text the agent reported: "not reported" when it did not say, "empty" when it was empty.
const reported = text => text == null ? el("div", {className: "muted"}, "not reported")
  : text === "" ? el("div", {className: "muted"}, "empty") : el("div", {className: "said"}, text);

// The address keeps the open window: #<scenario>&attempt=<n>.
function address(id, attempt) {
  history.replaceState(null, "", `#${encodeURIComponent(id)}&attempt=${attempt}`);
}
function fromAddress() {
  const hash = location.hash.slice(1);
  const at = hash.lastIndexOf("&attempt=");
  if (at < 0) return null;
  try { return {id: decodeURIComponent(hash.slice(0, at)), attempt: Number(hash.slice(at + 9)) || 1}; }
  catch { return null; }
}
function clearAddress() {
  history.replaceState(null, "", location.pathname + location.search);
}
function filtered() {
  const mask = document.getElementById("filter").value.trim() || "*";
  const pattern = new RegExp("^" + mask.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
  return {mask, keep: id => pattern.test(id)};
}
