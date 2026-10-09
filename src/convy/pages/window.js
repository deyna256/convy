const STOPS = {user_stop: "the user finished", max_turns: "the turns ran out", agent_failure: "the agent failed", model_failure: "convy's model failed"};
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
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/), number = line.match(/^\s*\d+[.)]\s+(.*)$/), heading = line.match(/^#{1,3}\s+(.*)$/);
    if (bullet || number) {
      flush();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) { list = el(tag); blocks.push(list); }
      list.append(el("li", {}, inline((bullet || number)[1])));
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
  const cut = c.cut ? ` · ${c.cut} not trusted` : "";
  return (!c.judged ? "no trusted verdict on this claim" : c.held === 0 ? `failed in ${c.judged} of ${c.judged}` : `held in ${c.held} of ${c.judged}`) + cut;
}
function attemptTiles(attempt) {
  const answers = attempt.turns.length;
  const result = kind(attempt.passed);
  return el("div", {className: "mini"},
    el("div", {}, el("span", {className: "l"}, "Result"), el("span", {className: `v ${result}`}, icon(result), attempt.cut ? "Not trusted" : ATTEMPT[result]), el("span", {className: "s"}, STOPS[attempt.stop] ?? attempt.stop)),
    el("div", {}, el("span", {className: "l"}, "Answer time"), el("span", {className: "v"}, secs(attempt.seconds)), el("span", {className: "s"}, attempt.slowest == null ? "no answers" : `${plural(answers, "answer")} · slowest ${secs(attempt.slowest)}`)),
    el("div", {}, el("span", {className: "l"}, "Tokens"), el("span", {className: "v"}, count(attempt.tokens)),
      el("span", {className: "s"}, attempt.input == null ? "not reported" : `${count(attempt.input)} in · ${count(attempt.output)} out`)));
}
// How sure the judge was of a decision, at the run's trust.
function sure(claim, trust) {
  if (claim.confidence == null) return "sure: not given";
  const said = `${Math.round(claim.confidence * 100)}% sure`;
  return claim.trusted ? said : `not trusted: ${said}, needs ${Math.round(trust * 100)}%`;
}
function judgeLines(attempt, trust) {
  if (attempt.error) return el("div", {className: "error"}, attempt.error);  // the agent or convy's model failed
  return el("div", {className: "judge"}, attempt.claims.map((claim, i) =>
    el("div", {}, el("span", {className: "no"}, String(i + 1)), icon(kind(claim.passed)),
      el("span", {className: "why"}, claim.reason || "No reason given.", el("small", {className: "muted"}, ` · ${sure(claim, trust)}`)))));
}
function dialogue(attempt) {
  return attempt.turns.flatMap(t => [
    el("div", {className: "msg user"}, el("span", {className: "who"}, "USER"), el("div", {className: "bubble"}, t.user)),
    el("div", {className: "msg agent"}, el("div", {className: "bubble"},
      el("div", {className: "bhead"}, el("span", {className: "who"}, "AGENT"),
        el("span", {className: "m"}, clock(), el("strong", {}, secs(t.seconds))),
        el("span", {className: "m"}, t.tokens == null ? el("span", {className: "muted"}, "tokens not reported")
          : [el("strong", {}, count(t.tokens)), " tokens ", el("span", {className: "muted"}, `· ${count(t.input)} in · ${count(t.output)} out`)])),
      markdown(t.agent))),
  ]);
}

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
