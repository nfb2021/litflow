// litflow: lit-writer writes or revises the draft until `rsx gate write`
// passes (cite-check, typst compile, submitted); lit-critic reviews it
// (`rsx gate draft`). A blocked review goes back to the writer, up to
// `rounds` more times.
//
// subagent({ workflow: "<this file>", cwd: "<project>", args: {
//   rounds: 2, reviewOnly: false } })
const rounds = args.rounds ?? 2;
const report = { rounds: [] };
let issues = null;

for (let round = 0; round <= rounds; round++) {
  const entry = {};
  if (!(args.reviewOnly && round === 0)) {
    const task = [
      "Write or revise the draft (your procedure). Start with `rsx next --role lit-writer`.",
      "Done when `rsx gate write` says pass (it checks citations, compiles, and needs `rsx draft submit --by lit-writer`).",
    ];
    if (issues && issues.length) {
      task.push("", "Open issues:");
      for (const i of issues) task.push("- " + i);
    }
    const w = await runs.run(`write-${round}`, {
      agent: "lit-writer",
      task: task.join("\n"),
      gate: { command: "rsx gate write", output: "json" },
    });
    const g = w.structuredOutput || {};
    entry.write = g.verdict || "failed";
    if (entry.write !== "pass") {
      issues = g.issues || ["the writing run failed"];
      report.rounds.push(entry);
      continue;
    }
  }
  const r = await runs.run(`draft-review-${round}`, {
    agent: "lit-critic",
    task: [
      "Review the submitted draft (your procedure \"Reviewing the draft\").",
      "Done when `rsx gate draft` says pass.",
    ].join("\n"),
    gate: { command: "rsx gate draft", output: "json" },
  });
  const g = r.structuredOutput || {};
  entry.review = g.review || "none";
  entry.reviewFile = g.review_file;
  report.rounds.push(entry);
  if (g.review === "ok") {
    report.result = `draft reviewed ok (${g.review_file})`;
    break;
  }
  issues = g.review === "blocked"
    ? [`lit-critic blocked the draft: fix every finding in ${g.review_file}`]
    : g.issues || ["the review run failed"];
}

report.result = report.result || "not settled: see rounds; the lead decides";
return report;
