# Project skills

Claude Code loads skills from this folder automatically when working in SoledadWX.

## rust-best-practices, rust-review (from BeautifulRust)

Vendored from https://github.com/morganlinton/BeautifulRust at commit
`c6f56d27a01739d404da2a554daaea023d7ddcca` (2026-10-26), MIT licensed. See `BeautifulRust-LICENSE`.
The reference digests summarise five public guides, each under its own license (listed in the upstream README).

- **Taken:** each skill's `SKILL.md`, plus `rust-best-practices/references/`. Every file was read in full before it was committed.
- **Left upstream:** `rust-port` (we don't port anything to Rust), every `evals/` folder (test fixtures and shell scripts), the installers,
  `scripts/`, and the `lints/` config. If we adopt a `[lints]` table, write it into `soledadwx-ui/src-tauri/Cargo.toml` by hand.
- **Pinned on purpose.** Don't refresh from upstream silently. To update, read the diff and record the new commit here.

### How these rules apply to SoledadWX

- **SoledadWX is application code, not a library.** Per the skill's own §1, favour simplicity: concrete types, `Vec` returns, no speculative
  generality. The strict API-design rules (semver, `#[non_exhaustive]`, sealed traits, `Send` assertions on public types) mostly don't apply.
- **Deliberate exception: the tray tooltip recovers from a poisoned `LIVE` lock (`into_inner`).** The skill says lock poisoning should be fatal.
  For the Monitor, a tooltip read must never take down the Recorder, so the recovery is intentional. A review should list it under
  *Consider*, not *Must fix*.
