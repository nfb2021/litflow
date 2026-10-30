// litflow: extract the claims of papers (one lit-reader per paper), then have a
// different agent verify them (one lit-verifier per paper). Every step ends at
// its `rsx gate`; a blocked gate sends the agent back with the gate's issues,
// up to `rounds` more times.
//
// subagent({ workflow: "<this file>", cwd: "<project>", args: {
//   papers: ["citekey", ...], rounds: 2, parallel: 3, skipExtract: false } })
const KEY = /^[A-Za-z0-9_][A-Za-z0-9_.:-]*$/;
const papers = (args.papers || []).filter((k) => KEY.test(k));
if (!papers.length) return { error: "args.papers holds no valid citekey" };
const rounds = args.rounds ?? 2;
const parallel = args.parallel ?? 3;
const report = { extract: {}, verify: {} };

function readerTask(key, issues) {
  const lines = [
    `Extract the claims of paper ${key} for the map's questions.`,
    "Follow your procedure for a paper. Finish with `rsx extracted " + key + " --by lit-reader`.",
    `Done when \`rsx gate extract --paper ${key}\` says pass.`,
  ];
  if (issues && issues.length) {
    lines.push("", "The gate blocked your last attempt. Fix exactly these:");
    for (const i of issues) lines.push("- " + i);
  }
  return lines.join("\n");
}

function verifierTask(key, issues) {
  const lines = [
    `Verify every unverified claim of paper ${key} against its page.`,
    `List them with \`obs ls claim paper=${key} verification=unverified\`.`,
    `Done when \`rsx gate verify --paper ${key}\` says pass.`,
  ];
  if (issues && issues.length) {
    lines.push("", "The gate blocked your last attempt. Fix exactly these:");
    for (const i of issues) lines.push("- " + i);
  }
  return lines.join("\n");
}

function record(into, key, r) {
  const g = r.structuredOutput || {};
  into[key] = {
    verdict: g.verdict || "failed",
    issues: g.issues || ["the agent run failed before its gate ran"],
    runId: r.runId,
  };
  return into[key].verdict === "pass";
}

if (!args.skipExtract) {
  let todo = papers.slice();
  for (let round = 0; round <= rounds && todo.length; round++) {
    const failed = [];
    for (let i = 0; i < todo.length; i += parallel) {
      const batch = todo.slice(i, i + parallel);
      const results = await runs.all(
        batch.map((key) => ({
          key: `extract-${key}-${round}`,
          agent: "lit-reader",
          task: readerTask(key, round ? report.extract[key].issues : null),
          gate: { command: `rsx gate extract --paper ${key}`, output: "json" },
        })),
      );
      results.forEach((r, j) => {
        if (!record(report.extract, batch[j], r)) failed.push(batch[j]);
      });
    }
    todo = failed;
    emit({ stage: "extract", round, blocked: todo });
  }
}

const toVerify = args.skipExtract
  ? papers
  : papers.filter((k) => report.extract[k].verdict === "pass");
let todo = toVerify.slice();
for (let round = 0; round <= rounds && todo.length; round++) {
  const failed = [];
  for (let i = 0; i < todo.length; i += parallel) {
    const batch = todo.slice(i, i + parallel);
    const results = await runs.all(
      batch.map((key) => ({
        key: `verify-${key}-${round}`,
        agent: "lit-verifier",
        task: verifierTask(key, round ? report.verify[key].issues : null),
        gate: { command: `rsx gate verify --paper ${key}`, output: "json" },
      })),
    );
    results.forEach((r, j) => {
      if (!record(report.verify, batch[j], r)) failed.push(batch[j]);
    });
  }
  todo = failed;
  emit({ stage: "verify", round, blocked: todo });
}

report.next = "run `rsx next` for the next step";
return report;
