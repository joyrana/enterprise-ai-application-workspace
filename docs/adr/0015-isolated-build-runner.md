# ADR-0015: Isolated build runner for generated projects

- Status: Accepted · Date: 2026-10-10

## Context

ADR-0014 keeps generated code out of the workspace: the API generates text only, and CI builds
example apps. Users still need "does *my* project build?" on demand. Building is executing code:
`vite.config.ts` is a program, and the TypeScript compiler and Vite plugins run with whatever
the process can reach. A generated project can also be modified after download and uploaded
again (Milestone 5), so the input must be treated as hostile.

## Decision

A separate, standard-library-only package, `services/build-runner`, builds a project archive in
two stages.

1. **Verify before anything runs** (`build_runner.verify`):
   - The archive must be a plain, bounded zip: limits on file count, file size, total size and
     compression ratio; no links, special files, encryption, absolute or `..` paths, or
     duplicate entries; exactly one top-level folder.
   - Every file must match `workspace-manifest.json`.
   - `package.json` must pin exactly the toolchain the image provides (no extra dependencies,
     overrides or workspaces).
   - The manifest is an integrity check, not authentication, so passing it never replaces the
     sandbox.
2. **Build in a locked-down container** (`build_runner.sandbox`):
   - **Network and secrets:** `--network none`; no host environment or credentials.
   - **Filesystems:** read-only root filesystem; the project is mounted read-only at `/src`;
     work happens on size-limited, `noexec` tmpfs.
   - **No writable host mount:** built files leave as a tar stream on stdout. The host caps
     its size and unpacks only regular files inside the output folder.
   - **Privileges:** uid 1000, all capabilities dropped, `no-new-privileges`.
   - **Resources:** memory (no swap), CPU, process-count and open-file limits.
   - **Deadline:** a wall-clock limit enforced from the host, which kills the container (not
     just the client).
   - **Toolchain:** the image installs the workspace's web lockfile once, with
     `--ignore-scripts`. Generated projects pin exactly those versions (tested), so builds
     need no network and never run package install scripts.
   - **Report:** status (`succeeded`, `failed`, `timed_out`, `output_too_large`, `rejected`,
     `runner_error`), per-step exit codes and durations, a log tail, SHA-256 of each built
     file, and the isolation flags actually used.
3. **Placement.** The runner is invoked by a worker process, never by the API process. CI
   proves it on every PR (`scripts/ci/sandbox_e2e.py`):
   - the example app builds;
   - a hostile project with a valid manifest probes the sandbox from `vite.config.ts` and
     finds no network, a read-only toolchain, project mount and root filesystem, no secrets
     in the environment, and a non-root uid;
   - a tampered archive is rejected before any container starts.

## Alternatives considered

- **Building in the API process or a plain subprocess:** rejected. The API's credentials,
  database and network would be reachable.
- **gVisor or Firecracker microVMs:** stronger kernel isolation. They are the right next step
  for multi-tenant production, but are not available on hosted CI runners. The runner keeps
  the container invocation in one function (`docker_argv`), so the runtime can be swapped,
  for example to `--runtime=runsc`.
- **Installing dependencies per build:** rejected. It needs network access and runs install
  scripts.

## Consequences

- On-demand builds are possible without giving project code any reach.
- This is container isolation: a kernel exploit could escape it. Production multi-tenant use
  should add a stronger runtime (gVisor or a microVM) and a dedicated host. This is recorded
  in the threat model.
- The base image is pinned by tag, not digest. Digest pinning and image signing are follow-ups.
