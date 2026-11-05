# Platform UX Uplift Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent tasks; preserve the current shared worktree and its existing changes. Do not commit unrelated work.

**Goal:** Implement the remaining approved UX improvements: actionable requirement review, real evidence preview, honest waiting feedback, useful project directory, accurate leave prompts, compact mobile shell, and model settings summary. The user subsequently cancelled the assistant business-control avoidance and business-activity quieting from area A.

**Architecture:** Extend existing React/Ant Design owners and authorized evidence APIs. Keep navigation state in the established URL/history contract, retain source versions and draft protections, and reuse the existing tokens, dialogs and model tests.

**Tech Stack:** React, TypeScript, Ant Design, Vite; Python service; scoped Playwright and pytest verification.

**Spec:** User initially approved the complete eight-row UX review plus model-settings summary, then explicitly cancelled area A's new avoidance and quieting after trying it. This later instruction supersedes the original area A approval. Existing DESIGN.md and UX-CONTRACT.md remain authoritative for unchanged behavior.

## Global Constraints

- No unscreened full suite. Reproduce a failing case first, fix it, then run its affected file; preserve existing assertions/timeouts.
- No synthetic progress, silent business approval, automatic model probes, or real-project mutations during browser tests.
- Preserve manual mascot location, existing aerospace motion, full-screen/search/draft/navigation behavior, and authorization/version checks.
- Reuse the existing worktree; no branch reset, clean, publishing, or committing unrelated changes.
- Existing APIs that lack identity display names must not invent identities; local ownership may be described as 本地用户, with original ID available in details.

## Work and Ownership

### A. Assistant awareness — cancelled by the user
- Remove the uplift's active business-control avoidance and its business-focus/modal/busy quieting, including the 15-second business-idle recovery timer and business-activity triggers.
- Preserve the original manual drag position, edge docking/reveal, chat-open behavior, background-page and reduced-motion rules. Keep the existing greeting cadence of 6 seconds visible / 24 seconds hidden and existing weather interactions and automatic-nudge conditions.
- Do not undo areas B–E or treat the previous awareness test receipt as verification of this removal. Record the removal's actual scoped checks separately in the verification report.

### B. Requirement review and analysis feedback
- Own RequirementDecisionTable, SourceRequirementList, SourceAnalysisPanel and their CSS.
- Add search and counted filters for pending decisions, drafts, clarification and stale-source review, plus next pending item.
- Preserve exact drafts and row IDs while filtering. Fullscreen reuses selection and adoption permissions; stale or adopted data cannot be silently re-adopted.
- Display elapsed analysis time and only real known phases (saving model vs waiting for analysis); clear recovery guidance on failure, no invented percentage.
- Verify filtered saves, full-screen selection/adoption and failure/retry using affected fixture files.

### C. Authorized evidence preview
- Own RequirementEvidence, EvidenceLocations, evidence preview components; source-preview backend endpoint/service, API types, evidence tests.
- Use the same checked source and version/hash identity as existing locators. Render normalized document blocks as text, highlight the chosen quote and scroll to the requested location.
- Support formats already parsed by the service; unsupported/unavailable formats explicitly offer original download and location guidance.
- Preserve deleted/historical markers, exact authorization checks, cancellation and error retry; never return arbitrary file paths or unsafe HTML.
- Verify source/version mismatch, multiple matches, denied access, unsupported content, and browser open/close/anchor recovery.

### D. Project directory, mobile shell, leave wording (root)
- Own RdPlatformPage, platformNavigation, ProjectOverviewCard and new directory helper/component styles.
- Add card/list view, status filter and recent-update sorting with URL/history restoration. Keep stable page membership and pending edits when changing controls.
- Show friendly owner names when provided; hide raw internal IDs behind optional details.
- Remove empty project context on project directory, compact repeated mobile subtitle while keeping account/navigation reachable.
- Correct misleading leave title to 未保存的填写; retain safe discard/continue behavior where no single save exists.
- Verify query/filter/sort/view restore, no-results/empty state, owner presentation, and mobile layout.

### E. Settings summary and visual consistency (root)
- Own model-settings summary component and settings/probe callbacks.
- Show current default model, active environment, and last completed probe with timestamp; distinguish unsaved-draft tests and unavailable readings, never infer live availability from a prior success.
- Refresh summary after credential/default-model save or probe using existing APIs; no credentials persisted in browser storage.
- Reuse spacing/control/typography tokens and existing layout. Verify read failures, changed model/environment, and no automatic probe.

## Review Focus
- Filtering or full-screen close must not lose pending row drafts/selected suggestions.
- Evidence preview must authorize and validate the exact source revision rather than exposing a filesystem path.
- Removing area A must preserve the user's saved drag preference and the original mascot, chat, greeting and weather behavior; business controls must no longer cause automatic displacement or business-idle quieting.
- Settings cannot label an unsaved test or previous-environment result as current health.
- Directory URL changes and browser back must retain old search/paging/case return semantics.

## Progress
- A assistant awareness: originally delivered, subsequently cancelled and removed; original companion browser regression, direct interaction checks and production build passed after removal.
- [x] B requirement review and analysis feedback
- [x] C evidence preview
- [x] D directory/mobile/leave wording
- [x] E settings summary
- [x] Integrated visual review, scoped verification, build, design/UX documentation

## Original uplift completion (historical)

The originally approved areas were delivered before the user cancelled area A. Independent review's preview navigation finding was fixed and checked again. Targeted browser files, evidence backend tests, navigation unit tests and the production build passed at that point; no unfiltered full suite was run. The local backend was refreshed and the new preview route verified. These are historical results, not a repeat verification after the cancellation. Current removal scope, completed scoped checks and historical limitations are separated in `docs/rd-platform/verification/2026-11-05-platform-ux-uplift.md`.
