// Runs stay in the workspace's order. Every group uses all recorded attempts and answers.
const answersIn = row => row.numbers.seconds?.n ?? 0;
const fraction = (n, total) => `${n} / ${total}`;
const percent = new Intl.NumberFormat("en", {style: "percent", maximumFractionDigits: 2});
function portion(rate, detail) {
  if (rate == null) return detail == null ? "—" : ["—", el("small", {}, detail)];
  return [percent.format(rate), el("meter", {value: rate, min: 0, max: 1, "aria-hidden": "true"}),
    detail != null && el("small", {}, detail)];
}
function distribution(add, lookup) {
  for (const [key, label] of [["min", "Minimum"], ["p50", "Median"], ["mean", "Mean"],
    ["p90", "90th percentile (P90)"], ["max", "Maximum"]]) {
    add(label, row => lookup(row)?.[key]);
  }
}

function outcomes(add) {
  add("Recorded / planned attempts", r => fraction(r.numbers.attempts, planned(r)));
  add("Counted / recorded attempts", r => fraction(r.judged, r.numbers.attempts));
  add("Passed / counted attempts", r => portion(r.rate, fraction(r.passed, r.judged)));
  for (const [key, label] of [["open", "Attempts without a verdict"], ["errors", "Attempts with errors"],
    ["agent_errors", "Agent failures"], ["busy", "Agent stayed busy"], ["model_errors", "Model failures"]]) {
    add(label, r => fraction(r[key], r.numbers.attempts));
  }
  add("Unreadable records", r => r.run.unreadable);
  add("Stable scenarios", r => fraction(r.stable, r.run.scenarios));
  add("Flaky scenarios", r => fraction(r.flaky, r.run.scenarios));
  return "Errors and missing verdicts use recorded attempts as their denominator. Stable scenarios passed every planned attempt. Flaky scenarios have both passed and failed attempts.";
}

function scenarioRates(add, list) {
  const rates = [...new Set(list.flatMap(r => r.results.map(bucket => bucket.rate)))];
  rates.sort((a, b) => (a ?? 2) - (b ?? 2));
  for (const rate of rates) {
    add(rate == null ? "No verdict" : el("span", {title: String(rate)}, `${percent.format(rate)} passed`), r => {
      const bucket = r.results.find(b => b.rate === rate);
      return portion(bucket?.part ?? (r.run.scenarios ? 0 : null), fraction(bucket?.count ?? 0, r.run.scenarios));
    });
  }
  return "Each row groups scenarios by the fraction of counted attempts that passed. Cells show the share and count of all planned scenarios in that group.";
}

function resources(add) {
  const field = $("resourcefield").value;
  const task = field.startsWith("attempt_") || field === "tool_calls";
  add(`Measured / recorded ${task ? "tasks" : "answers"}`, r =>
    fraction(r.numbers[field]?.n ?? 0, task ? r.numbers.attempts : answersIn(r)));
  distribution(add, r => r.numbers[field]);
  return {
    attempt_seconds: "Seconds summed across each task’s recorded answers. A task needs at least one answer to contribute.",
    seconds: "Seconds per recorded answer, including answers from failed attempts and attempts without verdicts.",
    attempt_tokens: "Input and output tokens summed across a task. Every answer in the task must report usage.",
    tokens: "Input and output tokens per answer with reported usage.",
    tool_calls: "Tool calls per task with a complete trace for every answer. Repeated and failed calls count. An explicitly empty trace contributes zero.",
  }[field];
}

function tokenComposition(add) {
  add("Answers reporting usage", r => fraction(r.numbers.tokens?.n ?? 0, answersIn(r)));
  add("Answers reporting cache reads", r => fraction(r.cache_answers, answersIn(r)));
  add("Answers reporting thinking tokens", r => fraction(r.thinking_answers, answersIn(r)));
  for (const [key, label] of [["cached", "Cache reads"], ["input", "Other input"],
    ["output", "Other output"], ["thinking", "Thinking"]]) {
    add(label, r => {
      const mean = r.parts?.[key];
      return portion(r.shares?.[key], mean == null ? null : `${number.format(mean)} tokens / answer`);
    });
  }
  add("Cache reads / all reported input", r => portion(r.shares?.read));
  add("Cache reads / input on cache-reporting answers", r => portion(r.cached));
  return "Parts show the share of reported tokens and the mean per answer reporting usage. Input and output include any cache reads or thinking the agent did not itemize.";
}

function namedCalls(add, list) {
  const select = $("callname"), previous = select.value;
  const names = [...new Set(list.flatMap(r => r.time.map(c => c.name)))].sort();
  select.replaceChildren(...names.map(name => el("option", {value: name}, name)));
  if (names.includes(previous)) select.value = previous;
  select.parentElement.hidden = !names.length;
  add("Answers with complete traces", r => fraction(r.traced_answers, answersIn(r)));
  if (!names.length) return "No named calls were recorded in the runs in scope.";

  const calls = new Map(list.map(r => {
    const call = r.time.find(c => c.name === select.value);
    if (call || !answersIn(r) || r.traced_answers !== answersIn(r)) return [r, call];
    // Every answer supplied its complete trace, so the absent call contributed zero.
    return [r, {calls: 0, token_calls: 0, answers: 0, total: 0, average: 0, tokens: 0,
      share: r.time.some(c => c.total > 0) ? 0 : null}];
  }));
  add("Recorded calls", r => calls.get(r)?.calls);
  add("Calls reporting tokens", r => {
    const c = calls.get(r);
    return c && fraction(c.token_calls, c.calls);
  });
  add("Answers with this call / all answers", r => {
    const c = calls.get(r);
    return c && fraction(c.answers, answersIn(r));
  });
  add("Total call time (s)", r => calls.get(r)?.total);
  add("Share of all recorded call time", r => portion(calls.get(r)?.share));
  add("Call seconds / all answers", r => calls.get(r)?.average);
  add("Reported call tokens / all answers", r => calls.get(r)?.tokens);
  distribution(add, r => calls.get(r)?.spread);
  return "Averages include all answers. Minimum through maximum use seconds per answer containing this call. Overlapping calls each contribute their own duration. An absent name counts as zero when all answer traces are complete. A dash marks an unavailable measurement.";
}

function runMetrics(list) {
  const group = $("metricgroup").value, body = el("tbody");
  $("resourcefield").parentElement.hidden = group !== "resources";
  $("callname").parentElement.hidden = group !== "calls";
  const add = (label, read) => body.append(el("tr", {}, el("th", {scope: "row"}, label), list.map(r => {
    const result = read(r);
    return el("td", typeof result === "number" ? {title: String(result)} : {},
      typeof result === "number" ? number.format(result) : result ?? "—");
  })));
  let note = "";
  if (list.length) {
    note = {outcomes, rates: scenarioRates, resources, parts: tokenComposition, calls: namedCalls}[group](add, list);
  } else {
    $("callname").parentElement.hidden = true;
  }
  if (!body.rows.length) body.append(el("tr", {}, el("td", {className: "empty", colSpan: list.length + 1},
    list.length ? "No scenarios in scope." : "No runs in scope.")));
  $("metricnote").textContent = note;
  $("metrics").replaceChildren(comparisonHead(list, "Metric"), body);
}
