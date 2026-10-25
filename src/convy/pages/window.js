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

// The steps' icons: a bulb for a thought, a wrench for a call, a stack for folded steps, a speech
// bubble for the answer.
const GLYPHS = {
  thought: "M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z",
  call: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
  steps: "M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  answer: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
};
function glyph(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({viewBox: "0 0 24 24", width: 15, height: 15, fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"})) svg.setAttribute(key, value);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", GLYPHS[name]);
  svg.append(path);
  return svg;
}

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
  return attempt.turns.flatMap((t, i) => [
    el("div", {className: "msg user"}, el("span", {className: "who"}, "USER"), el("div", {className: "bubble"}, t.user)),
    el("div", {className: "msg agent", "data-turn": i}, t.steps.length ? timeline(t) : el("div", {className: "bubble"}, answerHead(t), markdown(t.agent))),
  ]);
}
function answerHead(t, toggle = null) {
  return el("div", {className: "bhead"}, el("span", {className: "who"}, "AGENT"),
    el("span", {className: "m"}, clock(), el("strong", {}, secs(t.seconds))),
    el("span", {className: "m"}, t.tokens == null ? el("span", {className: "muted"}, "tokens not reported")
      : [el("strong", {}, count(t.tokens)), " tokens ", el("span", {className: "muted"}, `· ${tokenParts(t)}`)]), toggle);
}
// An answer with steps: a line of its thoughts and calls that ends in the answer. Folded, all the
// steps show as one node, and clicking it unfolds them. The button that unfolds or folds them stays
// at the end of the answer's head and hands its focus to the one that replaces it.
function timeline(t) {
  const box = el("div", {className: "bubble flow"});
  let calls = [];  // which calls were open, by place, so folding and unfolding keeps them
  const draw = (open, focus) => {
    const flip = () => {
      if (open) calls = [...box.querySelectorAll("details")].map(d => d.open);
      draw(!open, true);
    };
    const toggle = el("button", {className: "link steps", type: "button", "aria-expanded": String(open)}, open ? "Hide steps" : "Show steps");
    toggle.addEventListener("click", flip);
    const summary = [t.thoughts && plural(t.thoughts, "thought"), t.calls && plural(t.calls, "call"), t.calls && `calls ran ${secs(t.span)}`].filter(Boolean).join(" · ");
    const steps = open ? t.steps.map((s, i) => s.type === "thought" ? thoughtNode(s) : callNode(s, i))
      : [node("steps", el("div", {className: "card fold", onclick: flip}, el("span", {className: "kind"}, "Steps"), el("span", {}, summary)))];
    box.replaceChildren(answerHead(t, toggle),
      el("ol", {className: "line"}, steps, node("answer", el("div", {className: "card"}, el("span", {className: "kind"}, "Answer"), markdown(t.agent)))));
    box.querySelectorAll("details").forEach((d, i) => { d.open = calls[i] ?? false; });
    if (focus) toggle.focus();
  };
  draw(false, false);
  return box;
}
const node = (type, card, step = null) => el("li", {className: `node ${type}`, "data-step": step}, el("span", {className: "dot"}, glyph(type)), card);
const thoughtNode = s => node("thought", el("div", {className: "card"}, el("span", {className: "kind"}, "Thought"), el("div", {className: "said"}, s.text)));
// A call: its bar on the line of the answer's calls, where it started and how long it took; opened,
// what it sent and received.
function callNode(c, step) {
  return node("call", el("details", {className: "card"},
    el("summary", {},
      el("span", {className: "kind"}, "Call"), el("span", {className: "name"}, c.name),
      el("span", {className: "track", "aria-hidden": "true"}, el("span", {className: "bar", style: `left: min(${c.left * 100}%, 100% - 3px); width: max(3px, ${c.width * 100}%)`})),
      el("span", {className: "m"}, el("span", {className: "muted"}, `from +${secs(c.start)} `), el("strong", {}, secs(c.seconds)), " · ",
        c.tokens == null ? el("span", {className: "muted"}, "tokens not reported") : `${count(c.tokens)} tokens`)),
    el("div", {className: "io"}, said("Sent", c.sent), said("Received", c.received))), step);
}
// Opens one call of the window's dialogue, brings it into view and marks it for a moment.
function reveal(turn, step) {
  const folded = document.querySelector(`dialog [data-turn="${turn}"] .steps[aria-expanded="false"]`);
  if (folded) folded.click();
  const call = document.querySelector(`dialog [data-turn="${turn}"] [data-step="${step}"]`);
  if (!call) return;
  call.querySelector("details").open = true;
  call.scrollIntoView({block: "center"});
  call.classList.add("found");
  setTimeout(() => call.classList.remove("found"), 1600);
}
// Text the agent reported, in a box that scrolls: JSON indented, "empty" and "not reported" as words.
function said(label, text) {
  const body = text == null ? el("div", {className: "box none"}, "not reported")
    : text === "" ? el("div", {className: "box none"}, "empty")
    : el("pre", {className: "box", tabIndex: 0, role: "region", "aria-label": label}, indented(text));
  return el("div", {}, el("div", {className: "sec"}, label), body);
}
function indented(text) {
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}

// The address keeps the open window, #id=<scenario>&attempt=<n>, and the page's own settings.
function address(id, attempt) {
  writeAddress(new URLSearchParams({id, attempt: String(attempt)}));
}
function fromAddress() {
  const params = readAddress(), id = params.get("id");
  return id ? {id, attempt: Number(params.get("attempt")) || 1} : null;
}
function clearAddress() {
  writeAddress(new URLSearchParams());
}
function filtered() {
  const mask = document.getElementById("filter").value.trim() || "*";
  const pattern = new RegExp("^" + mask.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
  return {mask, keep: id => pattern.test(id)};
}
