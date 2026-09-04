# BeatBeamDMX — Repository Instructions

Before substantial work, Codex **MUST** read `../BeatBeamProject/PROJECT_AGENTS.md` and `CURRENT_ROADMAP.md`. Do not assume the external shared file is discovered automatically. When lasting architecture or backlog direction is relevant, also read `MASTER_ROADMAP.md` and `MASTER_BACKLOG.md`.

The shared file contains the permanent product, Git, acceptance, runtime, movement and show-quality rules. This file adds BeatBeam-specific requirements.

## Beta identity

- Beta app: `/Applications/BeatBeam DMX Beta.app`
- Bundle: `com.local.beatbeamdmx.beta`
- Version: `1.2.0-beta`
- Backend port: `8781`

## Historical Release protection

Historical Release: `/Applications/BeatBeam DMX.app`, bundle `com.local.beatbeamdmx.native`, version `1.1.0`, known executable SHA-256 `19ee79a62ade75601f88a25efe3407a3655c25f768d026a97dcdc99cb0ac1a1a`.

During Beta work, **NEVER** build, replace or modify the historical Release. For relevant Beta deployment, verify Release identity/hash before and after. If it unexpectedly changes, declare FAIL and stop.

## Runtime verification

After relevant Beta runtime changes, verify: backend port 8781 responds; renderer is active/healthy; `renderer_error = null`; frame sequence advances; source and installed backend hashes match; and the installed Beta signature verifies. Source-only completion is insufficient for a runtime milestone.

## Worktree and testing safety

Preserve `BeatBeam.code-workspace` and `artifacts/`. The worktree may contain substantial coherent dirty/untracked feature work; never destroy it.

After code changes, run relevant targeted tests first. For substantial runtime/backend changes, run the full repository suite before deployment. Automated PASS never equals user show-quality PASS.

Automated tests must never modify real user/workspace BeatBeam configuration. Tests needing configuration use isolated unique temporary paths/directories; parallel/background tests must not share a racing temporary config filename. Where configuration plumbing is tested, verify the real workspace/user config is unchanged afterward. Never restore user config from guessed/default values: it is user-owned state.

## UI and production routes

Do not add UI or settings without explicit product approval; developer/manual-test controls are also UI/product changes. Movement Lab/test tools must remain connected to the real production movement route.
