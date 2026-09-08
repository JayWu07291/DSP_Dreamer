# Issue 13 validation

Status on 2026-09-08: implementation and synthetic integration checks pass. Fresh live acceptance remains pending. Issue #13 must remain open until that evidence is verified.

## Automated checks

- Full public-interface suite: 13 passed in 20.47 seconds.
- Python type checking: no issues in seven source files.
- Release net472 build: zero warnings and zero errors.
- Deployed DLL SHA-256: `7f705deb9624457036cefba8f4717ff574bbbafe0412a322c8439058cb5d73f9`.

The suite exercises request identity under reversed callbacks, adjacent RGB and actual-action readback, a 205-frame recording with a five-frame tail, nonconstant alpha, both sides of the segment boundary, missing files, corrupted evidence and tables, unknown fingerprints/events, same-tick sequence ordering, half-open boundary events, and scheduler-gap attribution.

## Standards review

The independent standards reviewer found no documented-standard violations. A duplicated observation-layout definition was extracted into `observation_contract`. The reviewer also identified scheduler-gap attribution to the wrong interval; explicit affected-time ranges and a regression test resolve it. Follow-up review confirmed both fixes.

## Spec review

The independent spec reviewer identified duplicate or stale startup input sampling and missing stable event sorting. The plugin now records input only once per completed `VFInput.OnUpdate` frame and waits for that sample before capture. The compiler stably sorts ticks and sequence numbers while preserving evidence bytes. Follow-up review confirmed the fixes and reported no additional actionable findings in those changes.

Remaining spec finding: no new live recording has yet exercised this C# plugin. Synthetic passing results do not establish full UI/cursor capture, actual game-input correspondence or successful Unity stop-to-worker integration.

## Live handoff

The reviewed Release DLL and config are deployed under the installed game's BepInEx directory. The deployment backup directory is `runs/deployment-20260908-090825`. The config starts with no approved runtime fingerprint, so F8 first emits a candidate and refuses recording.

Next, start DSP, load the baseline and press F8 once. Inspect `runs/live/runtime-candidate.json` against the installed binaries and settings, approve only the matching fingerprint, then record at least 15 seconds with UI, cursor motion and Digit1. Verify the new four-file evidence, dataset readback, output checksums and game log. Save that run's results here before claiming issue completion.

Full episode lifecycle, terminal observations, recovery and cleanup remain for later tickets. The current compiler preserves recording events and actual actions; task/reward labels and the 10 Hz model view are not implemented by this first integration slice.
