---
title: Local Server operations
description: Use the independent Ops tool to configure and manage an existing personal Server runtime.
---

# Local Server operations

The Ops tool provides a non-interactive boundary for configuring and managing a personal Server. It reuses the
current-user service controller used by `powercontext service`; it does not need a running Server HTTP session.
Its own Python and dependencies must be distributed separately from the Server runtime it manages. A missing Server
interpreter therefore does not prevent the tool itself from starting or inspecting the registered service.

This service boundary supports prepared Server runtimes. For fixed managed resources and the install/repair policy,
see [Managed local Server installation](managed-local-server.md). The Desktop native bridge and installation UI are
separate capabilities. Existing human-facing CLI commands remain available.
Ops is not an HTTP API and does not add a daemon.
Managed registrations carrying `isolated_runtime=true` require the bundled Ops or a matching-version service tool;
an older CLI that does not support this definition field rejects it instead of managing the registration.

## Operator binding and invocation

The trusted operator supplies `--target-file` and `--state-dir` when launching Ops. JSON requests cannot substitute
arbitrary executable, configuration, or state paths. The target file binds the intended Server interpreter and package
version; these are not inferred from Ops' own interpreter or package version.

The target file has this shape, with absolute paths appropriate to the installation:

```json
{
  "format_version": 1,
  "target_id": "personal-server",
  "python_executable": "/absolute/server/bin/python3",
  "package_version": "1.2.3",
  "env_file": "/absolute/config/server.env",
  "configuration_owned": false
}
```

`package_version` must be the actual version in the prepared Server resource. Protect the target file, configuration,
and state directory against other users' writes. Set `configuration_owned` only when the trusted installer owns the
configuration; it is not a request to take over an independently managed file.
Keep the binding stable for its operation-state directory. Cross-binding upgrades and migration of existing operation
records are not supported here; changing the target file cannot authorize bypassing unresolved records.

For source-development environments containing the `ops` extra, use:

```bash
python -m powercontext.ops --target-file /absolute/target.json --state-dir /absolute/ops-state
```

For the independent bundle described below, use the exact bundled interpreter and entry:

```powershell
& 'C:\absolute\ops\runtime\python.exe' -I -S -B 'C:\absolute\ops\entry.py' --target-file 'C:\absolute\target.json' --state-dir 'C:\absolute\ops-state'
```

```bash
/absolute/ops/runtime/bin/python3 -I -S -B /absolute/ops/entry.py --target-file /absolute/target.json --state-dir /absolute/ops-state
```

Send one UTF-8 JSON request on stdin. Stdout contains JSON Lines messages, each with `protocol_version`, `request_id`,
and a `type` of `accepted`, `progress`, or `result`. Keep stdout separate from stderr and drain both streams.
Never treat process exit alone as evidence that an operation had no side effects.

## Requests and confirmation

Every request supplies `protocol_version: 1`, a `request_id`, and an `action`.

| Action | Additional input | Behavior |
| --- | --- | --- |
| `inspect` | None | Observe the bound service without mutating it or actively probing readiness. |
| `config_validate` | None | Validate the bound configuration without applying it. |
| `preflight` | `operation`, `options` | Return a plan, including its `plan_id`, without performing the mutation. |
| `apply` | `operation_id`, complete `plan`, `authorization` | Recheck and execute the exact approved plan, or return the existing operation for a repeated request. |
| `operation_status` | `operation_id` | Read the persisted attempt and result without resuming it. |
| `cancel` | `operation_id`, `attempt` | Request cancellation of that attempt at a safe boundary. |
| `resume` | `operation_id`, `expected_attempt`, complete recovery `plan`, `authorization` | Continue supported remaining work after checking the previous attempt and current facts. |

Supported operations are `register`, `start`, `stop`, `restart`, `remove_registration`, and `config_apply`.
Registration includes startup; display the plan's startup effect before approval. Removal unregisters the service and
preserves configuration and user data. It does not remove Desktop or delete the Server environment.

For example, request a stop plan:

```json
{"protocol_version":1,"request_id":"plan-stop","action":"preflight","operation":"stop","options":{}}
```

After displaying the returned plan and obtaining approval, pass that complete plan unchanged to `apply`.
Its `authorization` is `{"plan_id":"<returned plan_id>","approved":true}`. Allocate and retain `operation_id` before
invoking the tool so that a lost response can be resolved with `operation_status`. The authorization field represents
the trusted caller's confirmation; it is not an authentication token and must not become an unrestricted renderer API.
The complete plan includes a safe `target_summary` with the target interpreter, package version, configuration path,
endpoint, data directory, and login-start setting. Display this summary for review; do not construct or alter it yourself.
When omitted, `start_on_login` preserves an existing registration's setting; a new Windows registration defaults to `false`.

`config_apply` accepts `http_port`, `dashboard_enabled`, `start_on_login`, and an explicit `restart` option (default
`false`). It requires an
existing, valid, tool-owned configuration and preserves other settings. Configuration creation belongs to the managed
installer. Configuration and service definitions must switch together under service protection; a failed or interrupted
switch must be reconciled before a later start. Windows login startup is an explicit option; do not assume that the
same disabled-login option exists on macOS.
A configuration switch can stop an active service. It leaves the service stopped unless the plan explicitly permits
an applicable restart; an explicitly stopped service remains stopped, and recovery does not implicitly authorize startup.
When service status reports an interrupted `config_apply`, use the owning Ops caller to query `operation_status`,
obtain and confirm a fresh `preflight` plan, and `resume` the recorded operation. The human-facing `service install`
and `service start` commands cannot finish an Ops configuration switch.

## Failure, cancellation, and recovery

Registration, process state, and readiness are separate facts. A registered process is not proof of a ready Server.
Startup failure cleanup applies only to the owned target started by the operation. An uncertain stop must remain
uncertain rather than being reported as stopped.

Cancellation requests do not immediately terminate a service-management critical section and do not promise rollback.
An already persisted success or failure is not replaced by a late cancellation. After a lost response or forced exit,
query the saved operation first; do not automatically repeat the mutation. Read-only status and cancellation remain
available while another operation holds the mutation lock.

An interrupted operation can leave a native service-manager command running. Recovery must confirm that the recorded
command process has exited before performing another mutation. If interruption occurs between spawning the command
and recording its process identity, the evidence is incomplete: report an uncertain outcome and do not blindly replay
the command. Read-only status and cancellation requests remain available, but unknown command evidence does not promise
automatic repair.
While the prior command is alive or its identity cannot be confirmed, new mutations—including stop and removal—remain
blocked. Acquiring an operation lock alone is not proof that an orphaned native command has stopped. Status reports the
saved result separately from current observation; a later observation failure does not erase a persisted result.

Each new attempt records its executor PID. Status returns a separate executor observation and an `execution_state`:
`finished` when a final result is saved, `interrupted` when an unfinished attempt's executor is confirmed to have exited,
and `unknown` otherwise. A present or inaccessible PID is not proof that the original executor is still running,
because process identifiers can be reused. Older version 1 records without an executor remain readable with an unknown
observation. These observations never replace the service lock and native-command evidence required before a mutation.

A published configuration revision alone does not prove completion. If a stop guard remains but the process is active,
configuration recovery reports an uncertain outcome; an explicit stop must first establish a verified stopped state.
For an unguarded running target, a recovery plan that permits startup also permits the required readiness verification.
Recovery verifies that existing process without restarting it; a plan narrowed to exclude startup cannot silently probe
readiness instead.

Service ownership and configuration checks still apply. A missing or changed Server runtime does not authorize
replacing its configuration, taking over an unknown registration, or deleting data. Supported inspection, stop, and
unregistration use the existing ownership rules. Keep incomplete-operation evidence when manual recovery is required.

## Produce an independent bundle

`scripts/build_ops_bundle.py` is a release-producer tool. It accepts a trusted, complete, redistributable Python tree,
a directory of compatible wheels including `powercontext[ops]` and its full dependency closure, and a requirements file
with exact versions and SHA-256 hashes. Build on the target OS and architecture; this is not a cross-compilation tool.
The build host needs Python and `uv`; users of the completed bundle need neither installed globally.

```powershell
uv run python scripts/build_ops_bundle.py --runtime C:\inputs\python --python-relative python.exe --wheelhouse C:\inputs\wheels --requirements C:\inputs\ops-requirements.txt --output C:\artifacts\ops
```

On macOS, provide the corresponding runtime tree and use `--python-relative bin/python3`. The builder rejects virtual
environments and links that escape the runtime. It copies the full interpreter, installs only supplied hashed wheels
with offline mode, and verifies the copied entry from its bundle with an empty executable search path. Runtime imports
use isolated Python, its standard library, and the bundle's `packages` directory; they do not use the managed Server's
environment or the source checkout.

Run `uv run python scripts/ci_ops_bundle_smoke.py --bundle C:\artifacts\ops` against the completed artifact (use the
corresponding absolute directory on macOS). This launches real subprocesses outside the checkout, with poisoned Python
environment variables and a missing Server interpreter. Entry/protocol checks use an empty `PATH`; read-only inspection
uses only OS utility directories for native service and ACL commands. Loaded module paths must remain inside the bundle.
The check does not register, start, stop, or remove any service. It is not a native lifecycle test.

The output contains `runtime/`, `packages/`, `entry.py`, and `bundle.json`. The manifest records the runtime identity,
launch arguments, requirements digest, installed file bytes, and file digests. It is inventory, not a trust anchor or signature. It does not
make an untrusted runtime or wheel trustworthy. Existing output trees are never overwritten; inspect a partial build
before removing it or building at a new location.

The [candidate resource producer](../../development/managed-resource-production.md) supplies fixed input versions,
hashes, platform/architecture identity, retained license notices, and provenance for all three Windows/macOS targets.
Its output is always unqualified. Windows/macOS packaging (#2108/#2109) must publish Ops to a stable,
user-protected location independent of both the Desktop installation and the managed Server. Desktop removal must not
silently remove the maintenance tool or user data. Signing, macOS notarization, clean-machine execution, and native
service/login/reboot acceptance are separate release checks; a successful bundle build does not establish them.

See [Deploy the Server](deploy-server.md) for the existing service behavior and platform restrictions.
