# Local multi-agent coordination

`ai-dev agents` provides a small local task board for coding agents sharing one repository. It
coordinates intent only: it does not spawn agents, edit source files, create branches, commit, or
merge changes.

## Workflow

Register tasks with the files or directories they may edit:

```bash
ai-dev agents add api --title "Implement API" --path src/api --path tests/api
ai-dev agents add docs --title "Update docs" --path docs --depends-on api
```

Claim and maintain a task with an agent identity:

```bash
ai-dev agents claim api --agent agent-a --lease-seconds 900
ai-dev agents heartbeat api --agent agent-a --lease-seconds 900
ai-dev agents complete api --agent agent-a
```

Use `ai-dev agents release api --agent agent-a` to return unfinished work to the queue and
`ai-dev agents status --json` for the compact machine-readable board.

## Guarantees

State is stored at `.ai/cache/agent-coordination.json` using schema `1.0`. Mutations take a
cross-process exclusive lock and replace the JSON file atomically. Claims have bounded leases;
expired claims return to `queued` automatically. A claim is blocked when dependencies are
incomplete, another agent owns the task, or an active task declares an equal, parent, or child
path. Reports expose stable reason codes for every decision.

The local MCP server exposes the same operations as `coordinate_agents`. MCP inputs are strict and
bounded, and the tool is marked mutating because it can change coordination state.

## Limits

Path declarations are advisory and cannot prevent an external process from editing a file. Agents
should still use separate Git worktrees or branches when concurrent edits are possible. Leases use
the local machine clock, and this protocol is not a distributed lock for network filesystems.
Task titles and paths must not contain secrets because the board is shared with every local agent.