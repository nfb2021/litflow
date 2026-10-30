// litflow: answer question tickets, then have lit-critic try to break each
// answer. A blocked review reopens the ticket; the answerer gets it back with
// the critic's note, up to `rounds` more times.
//
// subagent({ workflow: "<this file>", cwd: "<project>", args: {
//   questions: ["Q-0001", ...], role: "lit-reader", rounds: 2, reviewOnly: false } })
const QID = /^Q-\d{4,}$/;
const ROLES = ["lit-scout", "lit-reader", "lit-critic"];
const questions = (args.questions || []).filter((q) => QID.test(q));
if (!questions.length) return { error: "args.questions holds no valid id (Q-0001)" };
const role = ROLES.includes(args.role) ? args.role : "lit-reader";
const rounds = args.rounds ?? 2;
const report = {};

function answerTask(q, issues) {
  const lines = [
    `Work question ticket ${q}: \`obs q claim ${q} --by ${role}\`, \`obs show ${q}\`, answer it from the vault.`,
    "If it has a Review section, a critic blocked the last answer: fix exactly what the newest entry says.",
    `Done when \`rsx gate answer --question ${q}\` says pass.`,
  ];
  if (issues && issues.length) {
    lines.push("", "Open issues:");
    for (const i of issues) lines.push("- " + i);
  }
  return lines.join("\n");
}

function reviewTask(q) {
  return [
    `Review the answer to ${q} (your procedure "Reviewing an answered question").`,
    `Record \`rsx review ${q} --ok|--block --note "..." --by lit-critic\`.`,
    `Done when \`rsx gate review --question ${q}\` says pass.`,
  ].join("\n");
}

for (const q of questions) {
  report[q] = { rounds: [] };
  for (let round = 0; round <= rounds; round++) {
    const entry = {};
    if (!(args.reviewOnly && round === 0)) {
      const a = await runs.run(`answer-${q}-${round}`, {
        agent: role,
        task: answerTask(q, round ? report[q].issues : null),
        gate: { command: `rsx gate answer --question ${q}`, output: "json" },
      });
      const g = a.structuredOutput || {};
      entry.answer = g.verdict || "failed";
      if (entry.answer !== "pass") {
        report[q].issues = g.issues || ["the answering run failed"];
        report[q].rounds.push(entry);
        continue;
      }
    }
    const r = await runs.run(`review-${q}-${round}`, {
      agent: "lit-critic",
      task: reviewTask(q),
      gate: { command: `rsx gate review --question ${q}`, output: "json" },
    });
    const g = r.structuredOutput || {};
    const state = (g.reviews || {})[q] || "none";
    entry.review = state;
    report[q].rounds.push(entry);
    if (state === "current-ok") {
      report[q].result = "answered and reviewed ok";
      break;
    }
    report[q].issues = g.issues && g.issues.length
      ? g.issues
      : [`the critic blocked it: read the newest entry of the Review section (obs show ${q})`];
  }
  report[q].result = report[q].result || "not settled: see rounds; the lead decides";
  emit({ question: q, result: report[q].result });
}

return report;
