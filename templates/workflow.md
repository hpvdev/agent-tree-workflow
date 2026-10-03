## Agent Tree — project workflow

This workflow applies only inside this project. The user explicitly requests native subagents under this workflow. Main is Sol/high; worker is Sol/medium; explorer/researcher are Luna/medium; Astra is on call. Actual model IDs, effort and limits come from `.agent-tree/settings.json` and `.codex/agents/agent_tree_*.toml`. Respect higher-priority instructions and the user's current task scope.

### Main agent protocol

After native project hooks are reviewed/trusted through `/hooks`, UserPromptSubmit supplies a fresh RUN_ID for each turn, including sessions opened directly in Codex. The optional `.agent-tree/run.py "task"` launcher supplies the same context. Never start a nested CLI to activate this workflow. Use `python3 .agent-tree/control.py --run-id RUN_ID ...` (substitute the actual ID).

1. **Before a plan:** first identify the exact feature and task scope. If the request could mean different flows, make a narrow read-only lookup or ask one concise clarification before requesting the checkpoint; do not ask Astra to review a guessed flow. Then call `checkpoint before_plan`, spawn native `agent_tree_astra` with the concrete goal, constraints and relevant initial evidence; wait for its advice. Call `checkpoint before_plan --agent-id ACTUAL_ID`. If observation is still pending, wait briefly and retry completion. Never edit the journal to simulate a review. Astra advises; Sol owns the plan and writes code.
2. **Jev fork layer:** use `fork` at narrow semantic decisions about which file, which tool, which agent, or retry/stop. This is the decision layer between Sol and execution, not optional telemetry. Known facts and deterministic lookups stay in ordinary code. Prepare the JSON described below and call `fork --json 'JSON'` with canonical shell quoting (Python `shlex.join` format), as a standalone command from the project root. This lets bookkeeping run while a branch is pending. The CLI also accepts stdin and `--input FILE` outside the guarded native flow. `sharp` dispatches the selected action in code: local read/search executes immediately; native tool/agent actions return an exact call for the native runtime. Invoke that call without choosing a different branch. Native hooks bind its tool/input and observe completion. The Python controller cannot invoke a Codex session tool itself; Sol relays the selected native call without making another routing decision. `split` executes nothing: Sol reasons from the evidence and calls `resolve DECISION_ID CHOICE` or `resolve DECISION_ID stop`. Do not merely mention Jev and bypass the controller. Do not invent a fork when there is no genuine choice.
3. **Spawn work:** use `which_agent` to choose worker/explorer/researcher before spawning native work agents. Supply the real available `spawn_agent` tool schema; use `agent_type` to select the installed role. Astra is selected by the fixed checkpoint rules, not a Jev competition. Delegate independent bounded work to worker, explorer and researcher as useful, with file ownership, constraints and acceptance criteria. Worker edits and runs assigned checks; explorer reads code; researcher reads primary docs. Respect the configured maximum (default six) and lower runtime limits. Avoid concurrent edits to the same file. Main continues independent work. Children do not recursively delegate or run main checkpoints.
4. **Error repeats:** hooks record failed calls when the runtime supplies structured error/exit status; do not double-count those occurrences. For unobserved errors or equivalent failures with different commands, call `failure "stable non-sensitive description"` for each occurrence. On the second and every subsequent recurrence the controller requests `error_repeats`; spawn a fresh Astra with the evidence, await advice, complete that checkpoint before another retry. Use the returned failure_key in a retry fork. Retry budget is enforced by code. Astra may identify a wrong fixture/environment rather than a code bug.
5. **Back to Sol:** integrate and inspect actual changes, run the smallest relevant validation, apply justified fixes. Keep code review separate from execution approvals.
6. **Before done:** call `checkpoint before_done`, spawn a fresh Astra with relevant diff and test evidence, await review, then complete with its actual agent ID. Apply justified findings; if relevant code changes or a new decision arise after review, request another before_done review. Read-only inspection after review does not require a duplicate Astra call. Call `finish` once the answer is ready; do not start a second audit of unchanged evidence. Report missing checkpoints, unresolved decisions or unsupported capabilities honestly; a native turn ending is not enough to pass workflow audit.

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

Allowed `kind`: `which_file`, `which_tool`, `which_agent`, `retry_or_stop`. Options are a finite map of 2–12 candidates. The controller always adds a `sol` fallback for missing evidence/candidates. `which_tool` can compare `read_file` against `search_text` (which also takes literal `text`). `retry_or_stop` adds `failure_key` returned by `failure`, and compares retrying an allowed local or native action against `{ "type": "stop" }`. Stop stops the current fork, not an unrelated task.

Only `state`, `question` and option descriptions are sent to Jev. Paths and action arguments are kept local, unless you explicitly include them in those descriptions. Never set `non_sensitive` true for secrets, private code or sensitive personal data; request explicit user authorization or use Sol directly. No automatic file upload happens. Thresholds in settings are adjustable engineering policy, not numbers established by the reference image.

Native action examples (inside an option's `action`):

```json
{"type":"native_tool","tool":"Bash","input":{"command":"python3 -m unittest"}}
```

```json
{"type":"spawn_agent","role":"explorer","tool":"spawn_agent","input":{"agent_type":"agent_tree_explorer","message":"Read the assigned implementation and report relevant callsites. Do not edit."}}
```

Use the actual canonical hook tool name/input for the installed runtime, not a guessed alias. Codex shell hooks use `Bash` and `input.command`; MCP tools use their canonical name and arguments. Keep the returned call unchanged. A mismatch stays pending; cancel with `resolve ID stop` and make a new fork if circumstances changed. An unavailable hook/tool must be reported, never manually marked executed.

Native hooks block unrelated execution while a fork awaits a decision or dispatch, and require a routed decision before a worker/explorer/researcher spawn. Controller commands, waits and fixed Astra checkpoints remain available. Already-determined ordinary work does not require a fabricated Jev question. Children execute their bounded assignment; main owns routing and checkpoints. This is a cooperative workflow, not a security boundary against agents rewriting their own scripts. Hooks can only check events the host actually exposes.

Automatic in-process actions are bounded local reads/searches/stop. Edits, shell commands, network actions, tests, deployment and purchases use native Codex tools and their existing approval policy. Jev probabilities never authorize those operations. Missing Jev, timeout, malformed output or insufficient confidence produce `split → Sol`, not a fabricated result.

### Evidence and scope

The observer reads metadata of this run and its descendants, including actual role/model/status and usage. It does not decrypt messages. If the local Codex format changes or the model/agent is unavailable, report the limitation; do not self-certify checkpoints. Hooks provide session/agent/tool evidence; the optional launcher observer is a fallback when hooks are inactive. Native routed actions require trusted Pre/PostToolUse hooks. If hooks are unavailable, report incomplete execution evidence. Main model/effort and approval mode in the Codex app remain the user-selected settings; project role files define child models. The launcher applies configured main settings. Never claim settings.json changed the app model automatically.

Do not create branches, worktrees, commits, deployments or external messages unless separately authorized. Never edit global configuration, another project, workflow scripts/settings or the journal as part of an implementation task. Do not audit the entire repository or create broad test infrastructure without need. Give concise progress updates at actual phase transitions, using evidence rather than private reasoning.
