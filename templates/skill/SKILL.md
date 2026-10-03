---
name: agent-tree
description: Run the optional Agent Tree workflow only when the user explicitly invokes $agent-tree for a project task.
---

Use this skill only for the current requested task. Do not apply it to later turns unless the user invokes it again. Work inside the current project and respect the user's scope and permissions.

1. From the project root, run `python3 .agent-tree/control.py begin` and retain the returned `run_id`. If Codex does not expose the thread ID or the native agents are unavailable, report the limitation instead of pretending the workflow ran.
2. Request `checkpoint before_plan` with `python3 .agent-tree/control.py --run-id RUN_ID checkpoint before_plan`. Spawn the configured Astra agent with the concrete task and relevant evidence, wait for its response, then complete the checkpoint using its real ID. Astra advises and never edits.
3. Before implementation or delegation, call Jev through `fork` with `kind=which_agent`. Include a `main` option with `{"type":"main"}` and at least one feasible worker, explorer or researcher option. Jev chooses who performs the first work package. If Jev chooses main, Sol may implement; otherwise invoke the exact native spawn call returned and confirm the observed agent with `confirm-agent DECISION_ID AGENT_ID`. For a split or unavailable Jev, gather narrow evidence, cancel the unresolved choice with `resolve DECISION_ID stop`, and ask Jev again. Sol must not select the agent in Jev's place.
4. Use further Jev forks for real file, tool, agent, or retry decisions, as explained in [workflow reference](references/workflow.md). Do not invent choices for deterministic work. Coordinate bounded agents, integrate results and run relevant checks. Ask a fresh Astra on repeated errors.
5. Request and complete `checkpoint before_done` with a fresh Astra after the final changes and checks. If work changes afterward, repeat that review. Run `python3 .agent-tree/control.py --run-id RUN_ID finish`; report any incomplete audit honestly.

The skill does not install or activate project hooks. Native actions inside the Codex app remain subject to its ordinary permissions. The controller verifies observed agent metadata where available; without hooks it cannot prove every tool input/output, so do not claim otherwise.
