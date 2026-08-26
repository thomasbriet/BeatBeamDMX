# Protected Worktree Checkpoint Plan

Status: `EXECUTED_SAFE_CHECKPOINT` — generated from a read-only audit and
executed on 2026-08-26 after every current diff was reclassified. No files were
amended, rebased, reset, restored, checked out, stashed, cleaned, fetched,
pulled, or pushed.

## Repository baselines

- BeatBeam: branch `beta/1.2`, HEAD `5be144b5646195874c2a1081921013df401757a2`,
  staged files `0`.
- SongAnalyzer: branch `main`, HEAD
  `d8bc313733d668a9c1be642f5d278506dc169ac2`, staged files `0`, configured
  remotes `0`.

## BeatBeam classification

### SAFE_ISOLATED_CANDIDATE

- `dynamic_composer.py`
- `live_intensity.py`
- `musical_event_envelope.py`
- `production_show_selector.py`
- `rme_preview.py`
- `tools/dynamic_composer_shadow_soak.py`
- `tests/test_dynamic_composer.py`
- `tests/test_live_intensity.py`
- `tests/test_musical_event_envelope.py`
- `tests/test_production_show_selector.py`
- `tests/test_production_show_selector_fault_matrix.py`
- `tests/test_rme_preview.py`

These are new, logically bounded modules or direct tests, but they still need a
dependency-aware review before any future staging because `beatbeam_app.py`
contains their runtime wiring.

### MIXED_PROTECTED

- `beatbeam_app.py`
- `beatbeam_config.json`
- `build_native_app.sh`
- `native/BeatBeamDMXApp.swift`
- `tests/test_beta_backend_packaging.py`
- `tests/test_preview_only_authoritative_show_frame.py`
- `tests/test_song_analyzer_structure_handoff.py`
- `tests/test_structure_source_ui.py`
- `tests/test_virtualdj_live_sync.py`

These tracked files contain large or cross-milestone changes. They must be
reviewed hunk by hunk against the baseline before any staging.

### ROADMAP_ONLY

- `CHANGELOG.md`
- `CURRENT_ROADMAP.md`
- `MASTER_ROADMAP.md`
- `DYNAMIC_COMPOSER_PRODUCTION_PROMOTION_DESIGN.md`
- `PROTECTED_WORKTREE_CHECKPOINT_PLAN.md`

### GENERATED/BUILD

- `artifacts/`

Runtime-soak JSON and local review evidence are reproducibility artifacts, not
default source checkpoints. Decide an artifact-retention policy before adding
any of them to Git.

### UNKNOWN

- `BeatBeam.code-workspace`

Treat as user-owned until its intended repository status is explicitly known.

## SongAnalyzer classification

### SAFE_ISOLATED_CANDIDATE

- `analysis-worker/music_analyzer_worker/short_accent_evidence.py`
- `analysis-worker/tests/test_short_accent_evidence.py`
- `analysis-worker/tools/fill_micro_evidence_diagnostic.py`
- `analysis-worker/tools/fill_human_review_package.py`
- `src/MusicAnalyzer.Core/PhraseAnalysis/Shadow/ShortAccentObservations.cs`
- `tests/MusicAnalyzer.Core.Tests/ShortAccentObservationTests.cs`

These new files are logically bounded, but their integration dependencies in
tracked files must be checkpointed coherently.

### MIXED_PROTECTED

- `README.md`
- `analysis-worker/music_analyzer_worker/phrase_analysis.py`
- `native/VirtualDJ/SongAnalyzerVirtualDJ/src/BridgeProtocol.cpp`
- `native/VirtualDJ/SongAnalyzerVirtualDJ/src/BridgeProtocol.h`
- `native/VirtualDJ/SongAnalyzerVirtualDJ/src/DeckResolver.cpp`
- `native/VirtualDJ/SongAnalyzerVirtualDJ/src/DeckResolver.h`
- `native/VirtualDJ/SongAnalyzerVirtualDJ/src/SongAnalyzerVirtualDJ.cpp`
- `native/VirtualDJ/SongAnalyzerVirtualDJ/tests/ProbeStatusTests.cpp`
- `src/MusicAnalyzer.App/ViewModels/MainViewModel.PhraseAndRekordbox.cs`
- `src/MusicAnalyzer.App/ViewModels/MainViewModel.cs`
- `src/MusicAnalyzer.Core/BeatBeam/StructureHandoff.cs`
- `src/MusicAnalyzer.Core/PhraseAnalysis/Services/PhraseAnalysisService.cs`
- `src/MusicAnalyzer.Core/PhraseAnalysis/Shadow/ArrangementProfileShadow.cs`
- `src/MusicAnalyzer.Core/PhraseAnalysis/Shadow/ArrangementProfileShadowProjector.cs`
- `tests/MusicAnalyzer.Core.Tests/ArrangementProfileShadowProjectorTests.cs`
- `tests/MusicAnalyzer.Core.Tests/StructureHandoffTests.cs`
- `tests/MusicAnalyzer.Core.Tests/VirtualDjBridgeTests.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/BridgeActivationService.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/BridgeDiagnostics.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/BridgeJobs.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/BridgeProtocol.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/PlaylistWatcher.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/Program.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/SongAnalyzerBridgeAnalysisRunner.cs`
- `tools/MusicAnalyzer.VirtualDjBridge/UnixBridgeServer.cs`
- `tools/MusicAnalyzer.VirtualDjHarness/Program.cs`
- `tools/MusicAnalyzer.VirtualDjHarness/README.md`

These tracked files span short-accent handoff, analysis lifecycle, app UI,
VirtualDJ master/prewarm and bridge diagnostics. They are protected mixed work.

### ROADMAP_ONLY

- None in the current SongAnalyzer dirty set.

### GENERATED/BUILD

- `artifacts/fill-human-review/`

The 36 local AAC review snippets and manifests contain local review data and
must not be committed by default.

### UNKNOWN

- None identified. Reclassify any newly discovered untracked file before use.

## Proposed future checkpoint order

1. **Checkpoint A — FILL evidence foundation.** Review and checkpoint the new
   Python/C# short-accent models and their direct tests together with only the
   exact required integration hunks. Keep review artifacts excluded.
2. **Checkpoint B — Dynamic Composer pure foundation.** Review and checkpoint
   the new composer, envelope, intensity, selector and RME modules plus their
   direct tests. Keep the soak JSON excluded unless an explicit artifact policy
   is chosen.
3. **Checkpoint C — BeatBeam mixed runtime wiring.** Audit
   `beatbeam_app.py`, native UI, config, packaging and cross-cutting tests hunk
   by hunk. Split only with positive ownership evidence; never infer ownership
   from file names alone.
4. **Checkpoint D — VirtualDJ lifecycle work.** Audit plugin, bridge, harness
   and related SongAnalyzer tests as one dependency graph. This milestone did
   not modify or restart that stack.
5. **Checkpoint E — documentation.** Reconcile changelog, promotion design and
   both roadmaps after code checkpoint boundaries are proven.

## Execution result — 2026-08-26

- SongAnalyzer `397e071` — `Add short-accent evidence foundation`.
- BeatBeam `84c1779` — `Add dynamic show composition foundations`.
- BeatBeam `c499a0c` — `Integrate preview composer runtime and diagnostics`.
- SongAnalyzer `d3fd28f` — `Persist shadow analysis in BeatBeam handoff`.
- SongAnalyzer `b982211` — `Improve VirtualDJ deck lifecycle and handoff`.
- Checkpoint E contains only the current roadmap, master roadmap, changelog,
  production-promotion design and this audit/result document.

Every checkpoint was staged with explicit paths, inspected with
`git diff --cached --stat`, `git diff --cached` and `git diff --cached --check`,
then committed normally. SongAnalyzer remains without a remote. BeatBeam was
not pushed because protected local-only assets remain and the safe policy is
therefore `LOCAL_COMMITS_ONLY`.

The following were deliberately excluded: BeatBeam `artifacts/`,
`BeatBeam.code-workspace`, SongAnalyzer `artifacts/fill-human-review/`, native
`build/`, .NET `bin/obj` and all runtime cache/socket/log/install output. The
generated FILL review manifests stay with their generated audio package rather
than being split into Git without an explicit artifact-retention policy.

Before every future checkpoint: repeat `git status --short`, inspect both
unstaged and staged diffs, run the relevant tests, stage only explicit paths or
reviewed hunks, and verify the staged diff. Do not use clean/reset/restore/
checkout/stash to manufacture a clean tree.
