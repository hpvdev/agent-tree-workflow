## Agent Tree — project workflow

This workflow applies only inside this project. The user explicitly requests native subagents under this workflow. Main is Sol/high; worker is Sol/medium; explorer/researcher are Luna/medium; Astra is on call. Actual model IDs, effort and limits come from `.agent-tree/settings.json` and `.codex/agents/agent_tree_*.toml`. Respect higher-priority instructions and the user's current task scope.

### Main agent protocol

Run through `.agent-tree/run.py "task"` to enable the controller and observer. The launch prompt provides RUN_ID. Use `python3 .agent-tree/control.py --run-id RUN_ID ...` (substitute the actual ID).

1. **Before a plan:** call `checkpoint before_plan`, spawn native `agent_tree_astra` with the goal, constraints and relevant initial evidence; wait for its advice. Call `checkpoint before_plan --agent-id ACTUAL_ID`. If observation is still pending, wait briefly and retry completion. Never edit the journal to simulate a review. Astra advises; Sol owns the plan and writes code.
2. **Jev fork layer:** use `fork` at narrow semantic decisions about which file, which tool, or retry/stop. Known facts and deterministic lookups stay in ordinary code. Prepare the JSON described below and send it on stdin or use `fork --input FILE`. `sharp` executes the selected bounded action in Python; use its result. `split` executes nothing: Sol reasons from the evidence and calls `resolve DECISION_ID CHOICE` or `resolve DECISION_ID stop`. Do not merely mention Jev and bypass the controller. Do not invent a fork when there is no genuine choice.
3. **Spawn work:** delegate independent bounded work to worker, explorer and researcher as useful, with file ownership, constraints and acceptance criteria. Worker edits and runs assigned checks; explorer reads code; researcher reads primary docs. Respect the configured maximum (default six) and lower runtime limits. Avoid concurrent edits to the same file. Main continues independent work. Children do not recursively delegate or run main checkpoints.
4. **Error repeats:** when the same underlying failure happens, call `failure "stable non-sensitive description"` for each occurrence. On the second and every subsequent recurrence the controller requests `error_repeats`; spawn a fresh Astra with the evidence, await advice, complete that checkpoint before another retry. Use the returned failure_key in a retry fork. Retry budget is enforced by code. Astra may identify a wrong fixture/environment rather than a code bug.
5. **Back to Sol:** integrate and inspect actual changes, run the smallest relevant validation, apply justified fixes. Keep code review separate from execution approvals.
6. **Before done:** call `checkpoint before_done`, spawn a fresh Astra with relevant diff and test evidence, await review, then complete with its actual agent ID. Apply justified findings; if relevant code changes after review, request another before_done review. Finally call `finish`. Report missing checkpoints, unresolved decisions or unsupported capabilities honestly; a native turn ending is not enough to pass workflow audit.

Astra is silent outside these three checkpoint types and never edits code. Do not add a rule restricting these checkpoints to risky tasks or invent an arbitrary number of different repair attempts.

### Fork input

Example: selecting which file to read, using non-sensitive descriptions only:

```json
{
  "kind": "which_file",
  "non_sensitive": true,
  "state": "The task is to inspect a Python text normalization implementation. The candidates are the implementation and its introductory documentation.",
  "question": "Which candidate should be read to understand the implementation?",
  "options": {
    "implementation": {"description": "Python implementation", "action": {"type": "read_file", "path": "slug.py"}},
    "documentation": {"description": "Introductory documentation", "action": {"type": "read_file", "path": "README.md"}}
  }
}
```

Allowed `kind`: `which_file`, `which_tool`, `retry_or_stop`. Options are a finite map of 2–12 candidates. The controller always adds a `sol` fallback for missing evidence/candidates. `which_tool` can compare `read_file` against `search_text` (which also takes literal `text`). `retry_or_stop` adds `failure_key` returned by `failure`, and compares retrying a bounded read/search action against `{ "type": "stop" }`. Stop stops the current fork, not an unrelated task.

Only `state`, `question` and option descriptions are sent to Jev. Paths and action arguments are kept local, unless you explicitly include them in those descriptions. Never set `non_sensitive` true for secrets, private code or sensitive personal data; request explicit user authorization or use Sol directly. No automatic file upload happens. Thresholds in settings are adjustable engineering policy, not numbers established by the reference image.

Automatic actions are restricted to bounded local reads/searches/stop. Edits, shell commands, network actions, tests, deployment and purchases use native Codex tools and their existing approval policy. Jev probabilities never authorize those operations. Missing Jev, timeout, malformed output or insufficient confidence produce `split → Sol`, not a fabricated result.

### Evidence and scope

The observer reads metadata of this run and its descendants, including actual role/model/status and usage. It does not decrypt messages. If the local Codex format changes or the model/agent is unavailable, report the limitation; do not self-certify checkpoints. If not launched through run.py, say full workflow monitoring/audit is unavailable rather than running a hidden nested CLI.

Do not create branches, worktrees, commits, deployments or external messages unless separately authorized. Never edit global configuration, another project, workflow scripts/settings or the journal as part of an implementation task. Do not audit the entire repository or create broad test infrastructure without need. Give concise progress updates at actual phase transitions, using evidence rather than private reasoning.
