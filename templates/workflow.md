# Agent Tree workflow reference

This reference is used only after the user explicitly invokes `$agent-tree`. It does not apply to ordinary project turns. Sol coordinates and integrates; Astra advises at fixed checkpoints; Jev chooses the first executor and later genuine semantic branches. Respect higher-priority project and user instructions.

## Controller calls

Run `python3 .agent-tree/control.py begin` once in the current project. Use its `run_id` with subsequent commands. The controller reads the current Codex thread ID and stores its journal only under `.agent-tree/logs/RUN_ID`.

Before planning, request `checkpoint before_plan`, spawn native `agent_tree_astra` with the concrete objective, wait for advice, and complete the checkpoint with the actual agent ID. Repeat Astra only after a repeated failure (`error_repeats`) and before the final answer (`before_done`). Astra never writes code. The observer checks the role, model, timing and completion from local Codex metadata. If this evidence is unavailable, report that the checkpoint cannot be verified.

## Jev chooses the executor

The first `fork` after `before_plan` must be `which_agent`. Sol supplies feasible options, including Sol/main and at least one bounded child agent. Example JSON:

```json
{
  "kind": "which_agent",
  "non_sensitive": true,
  "state": "A small project task needs one implementation owner. A worker can edit the assigned files; Sol can implement directly.",
  "question": "Who should perform the first work package?",
  "options": {
    "main": {"description": "Sol implements directly", "action": {"type": "main"}},
    "worker": {"description": "Worker implements the bounded change", "action": {"type": "spawn_agent", "role": "worker", "tool": "spawn_agent", "input": {"agent_type": "agent_tree_worker", "message": "Implement the assigned change and report checks."}}
  }
}
```

Call `python3 .agent-tree/control.py --run-id RUN_ID fork --json 'JSON'` with normal shell quoting. Replace the example with the real task and the native tool's actual canonical schema. The agent role files define models and scope. Jev sees only the short state, question and option descriptions; native arguments stay local. Do not send sensitive data or private code to Jev without the user's authorization.

For `which_agent`, Jev's highest ranked non-fallback choice selects the executor, even if it is below the generic confidence threshold. If Jev chooses main, the controller records that Sol may work directly. If Jev selects a child, invoke the returned native spawn call, then run `confirm-agent DECISION_ID AGENT_ID`. This command checks the observed child role, model, parent and creation time. Until confirmation, the agent branch remains unresolved. If Jev chooses its insufficient-evidence fallback, ties, fails or times out, the result is `split`: gather narrow evidence, `resolve DECISION_ID stop`, and ask Jev again. Sol must not resolve a `which_agent` split to its own preferred agent.

Jev can also choose among actual file reads, text searches and retry/stop branches. Use `which_file`, `which_tool`, or `retry_or_stop` only when there are real alternatives. Known facts and deterministic coordination do not need a fabricated fork. Generic forks use configured confidence, probability and margin thresholds. `sharp` dispatches the selected local action; `split` requires Sol to resolve from evidence. Without native hooks, a native tool action cannot be proven from its exact input/output, so do not claim that such a branch passed audit in skill mode.

## Completion

Sol integrates agent work, inspects changes and runs relevant validation. Record repeated failures with `failure` using a stable non-sensitive description, then complete a fresh Astra `error_repeats` checkpoint before retrying. Request and complete `before_done` after final evidence is ready. A new fork or relevant change invalidates that review. `finish` checks checkpoints, the initial Jev agent route and unresolved decisions, then writes `retro.json`. If any check fails, report the missing evidence instead of marking the workflow complete.

The skill has no project hook and does not run in ordinary sessions. It does not grant tool permissions, enforce every unreported semantic decision, or prove code quality. Codex's native approvals and normal project instructions still apply.
