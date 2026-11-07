# StillNote improvement plan

Prepared 8 November 2026 (Australia/Perth). This is a living implementation plan.

## Evidence and product direction

StillNote is a small, single-user, self-hosted Flask/SQLite app with a plain-JavaScript editor, local Bootstrap assets, and recent iPad landscape work. Keep that architecture: a frontend framework, vector database, cloud analytics, or background worker would add cost without evidence of benefit.

A read-only inspection of the live library found two notes (980 characters total), one tag, and no pinned or archived notes. The patterns are short idea capture and longer journaling. This is a very small sample, not proof of habitual behaviour. Personal note text and titles must stay out of source control, fixtures, screenshots, and analytics. Repository history also establishes iPad landscape as an important supported workflow.

Success means writing is trustworthy, capture is quick, retrieval stays simple, and improvements follow measured usage. Do not remove features based on this sample. Preserve the calm editor and readable text.

## Audit findings

| Priority | Finding | Consequence / approach |
| --- | --- | --- |
| P0 | Autosave reads the current editor after a delay; selecting another note does not flush it | Edits can disappear. Serialize saves, flush before navigation, preserve a local recovery draft, and test delayed/failing requests. |
| P0 | Concurrent clients overwrite each other; timestamps only have second precision | Add monotonically increasing revisions and atomic conflict checks; keep local edits on conflict. |
| P0 | Deletion is permanent; export drops metadata; no restore path | Add recoverable trash first. Follow with versioned backups, validated import and documented restore drills. |
| P1 | Every save reloads every note body and all tags; list serialization queries tags once per note | Add summary responses, batched tags and local list updates. Avoid introducing pagination until library size warrants it. |
| P1 | SQLite connection context commits but does not close connections | Explicitly close connections and exercise repeated requests. |
| P1 | JSON values are coerced or silently truncated; create accepts non-object inputs poorly | Validate types/limits, reject invalid requests without partial mutation, return useful JSON errors. |
| P1 | Tag names are interpolated into HTML attributes using text-only escaping | Use DOM construction for tag buttons; test quotes and markup as literal text. |
| P1 | Search responses may arrive out of order; navigation failures are not consistently caught | Ignore stale list responses and retain the current editor on save failure. |
| P1 | No usage evidence or user controls | Local, opt-in aggregate counters with visible controls, export, reset and retention; never collect note contents, titles, tags, queries or identifiers. |
| P2 | Browser zoom is disabled; last-used state assumes browser storage works | Restore zoom and degrade gracefully when storage is unavailable. |
| P2 | Backup endpoint exists but is not visible in the interface | Add a discoverable export control and distinguish portable Markdown from a restorable backup. |
| P2 | Tests mainly cover API happy paths and layout | Add behavioural browser tests, migration tests, conflict/failure tests and privacy tests. |

## Delivery phases and acceptance criteria

### 1. Reliable editing and efficient persistence — first implementation slice

- Add additive schema migration for revisions; check and increment revisions in a transaction. Older clients remain compatible initially; the updated client always sends revisions.
- Queue saves; never mark subsequent keystrokes saved just because an earlier request succeeded. Flush edits before note selection, creation, pin/archive/delete actions. Navigation stops on failure.
- Preserve pending drafts in browser storage and offer recovery without silently replacing a newer server version. Warn when closing with unsaved work; retry on reconnection. Browser storage can fail and is not a backup.
- Load compact previews for the library and full text only when opening a note. Batch tag reads. Update the edited row locally, refreshing tags only when tags change.
- Validate inputs, close SQLite connections, prevent attribute injection, and reject stale search results.
- Acceptance: switching immediately after typing, editing during an in-flight save, failed saves, reload recovery, concurrent tabs and out-of-order searches preserve text. Existing iPad/WebKit regressions pass.

### 2. Private usage insights — first implementation slice

- Provide a visible Usage panel. Collection starts only when enabled in that browser; make it easy to stop, export and clear.
- Store daily counts in browser storage for at most 90 days. Fixed vocabulary: app opens, notes opened/created, successful saves, save failures/conflicts, searches, pin/archive/restore/trash, exports, journal creation, theme changes. No free-form event properties.
- Count feature actions, not keystrokes or text. No third party, cookies, fingerprint, device/user IDs, raw event stream or background upload. No reading note text for analytics.
- Explain per-browser scope and loss on browser data clearing. Local recovery drafts are separate and contain pending text; explain this distinction.
- Acceptance: disabled means no events; unknown events are rejected; retention is bounded; reset/export work; broken storage never prevents editing.
- Review after 2–4 weeks of real use. Treat low counts as a prompt to investigate discoverability, not an automatic removal decision. Compare save failures with successful saves, feature shares and active days. A single user's counts are directional, not statistically representative.

### 3. Recoverable actions and easier capture — next implementation slice

- Replace immediate deletion with trash; restore via a dedicated view. Permanent deletion stays explicit, and deleted notes are excluded from normal searches and export. No automatic purge initially.
- Add a one-tap dated journal note using the browser's local date; retain unrestricted plain-text editing and ordinary tags. Do not infer mood or analyse diary content.
- Surface Markdown export in navigation. Preserve pin/archive state when restoring from trash.
- Acceptance: trash persists across restart, restore recovers exact text/tags/state, stale clients cannot modify trashed notes, exports omit trash, and migrations preserve existing notes.

### 4. Backups and revision history — follow-up

- Versioned JSON archive with content, tags, timestamps, pin/archive/trash state and stable format version. Restore into a temporary database first, validate before committing, and define duplicate handling explicitly.
- SQLite online backup command, scheduled host backups outside the Docker volume, retention policy and a verified restore procedure. Never copy only a live WAL database file.
- Revision history with coalesced snapshots (for example once per editing session or every few minutes), bounded retention, diff preview and restore-as-new-revision. Measure storage growth before retaining every autosave.
- Acceptance: round-trip metadata and Unicode, malformed/oversized imports leave data unchanged, backup restore works into an empty volume, and snapshot retention is tested.

### 5. Retrieval and writing improvements — evidence driven

- First: contextual library heading, sort controls, clear filters, result count, useful empty states, tag suggestions and tag rename/merge.
- If searches or library growth justify it: SQLite FTS5 with migration/backfill and rebuild command; preserve literal substring search semantics or clearly label changes. Benchmark 1,000 and 10,000 generated notes before deciding.
- If journaling becomes frequent: daily note reuse, lightweight templates, previous/next entry navigation and an optional calendar. Avoid mandatory structured forms.
- If idea notes become task lists: plain-text checklist helpers and optional safe Markdown preview. No raw HTML execution. Keep editing plain text and export portable.
- If long sessions justify it: optional word count, focus mode, font controls and editor position restoration. Measure value before expanding the toolbar.

### 6. Platform, accessibility and operations

- Keep loopback binding and deployment behind the user's trusted access boundary. If exposed to other users/networks, add authentication, per-user ownership and explicit CSRF/origin protections before claiming multi-user support.
- Add manifest/home-screen icons if installation is useful. Full offline sync is a separate project requiring a conflict model, durable queue and clear pending states; a service worker alone is insufficient.
- Test keyboard focus, zoom, contrast, screen-reader announcements and narrow-screen navigation. Preserve iPad virtual-keyboard checks and perform an actual iPad check before release.
- Consolidate duplicated CSS after behavioural work; avoid a large visual redesign. Add CI with Python tests and WebKit, dependency update review, structured error reporting without note/query content, and database-backed readiness checks.
- Measure startup bytes, list response size, request counts per edit, p50/p95 save latency and memory using synthetic libraries. Set budgets from measurements, not arbitrary targets.

## Commit and verification strategy

Use separate commits for the plan, persistence/editor reliability, usage insights, and recovery/capture features. Run focused tests per change and a full suite at the end. Test against temporary databases, never the live library. Document actual results and remaining limitations below. Deployment is separate from implementation; back up the live database before any later release. Do not push personal data or commit credentials.

References: [Flask SQLite connection lifecycle](https://flask.palletsprojects.com/en/stable/patterns/sqlite3/) and [SQLite transaction semantics](https://sqlite.org/lang_transaction.html).

## Execution record

- Initial inspection complete; working tree was clean. Live notes were accessed read-only.
- Implementation and measured verification results will be recorded as each slice completes.

### Paused checkpoint — 8 November 2026

Paused at the user's request after the first implementation slice; phases 2 onward have not started.

Implemented: serialized saves and save-before-navigation; browser-local pending drafts with reload recovery, explicit conflict recovery as a new note and a Save now control; additive revision migration and atomic stale-write rejection; compact library previews, batched tag queries and row updates without full-library reloads on ordinary saves; strict input validation; explicit connection closure; no-store API/export responses; safe DOM construction for tag names; stale list-response suppression; graceful storage errors; restored browser zoom.

Verification: **27 tests passed**, including the existing WebKit/iPad layout checks and new behavioural tests for immediate switching, typing during an in-flight save, no library/tag refetch on body-only saves, failed-save navigation blocking, reload recovery, concurrent-version recovery, literal tag rendering, storage failure, legacy migration, invalid payloads and literal search. `git diff --check` passed. Tests ran in a disposable Playwright Python container with read-only source and temporary databases because the host lacks pip/venv support. No live database mutations or deployment occurred.

Remaining before release: real iPad verification; broader stale-search and navigation-failure coverage; performance benchmarks on synthetic larger libraries. Revision checks are optional for older API clients, and pending drafts share storage between tabs, so this is not full offline synchronization. Permanent deletion still exists until phase 3. No analytics have been implemented or enabled. No personal note text or titles were added to the repository.

Resume with a review of this checkpoint, then phase 2 (opt-in private usage insights), followed by recoverable trash and journal capture. Backups and restore remain the next data-safety milestone.

### Private usage insights — 8 November 2026

Implemented a native Usage dialog with explicit opt-in, daily counters retained for 90 local calendar days, stop/clear/export controls and a fixed event vocabulary. The collector accepts no event properties and performs no network requests. Counts are per browser and must be exported for later review. Storage errors do not interrupt note editing. Browser tests cover opt-in, rejection of unknown events, retention, export, reset and unavailable storage.


### Recoverable actions and capture — 8 November 2026

Implemented additive trash migration, a dedicated Trash view, read-only trashed notes, restoration preserving content/tags/pin/archive state, and explicit permanent deletion requiring a current revision. Normal lists, tag counts and Markdown exports omit trash. Stale clients cannot edit a trashed note. Added browser-local-date journal capture, contextual library headings and a visible Markdown export action that flushes pending edits first.

Verification: **33 tests passed**, including exact restoration, stale-revision and permanent-deletion safeguards, export/tag/search exclusion, the browser trash/restore/journal flow and all earlier layout/recovery/privacy tests. No live data changed; deployment remains pending.

### Database recovery and measured performance — 8 November 2026

Added `manage.py backup` and `manage.py restore`, packaged in the Docker image. They use SQLite's online backup API, verify database integrity and expected tables, create private destination files exclusively, and refuse overwrites. Restore writes a new database for verification before switching the running app. The tested recovery preserves committed WAL changes, Unicode text, tags, trash and revisions. README includes local and Docker procedures, external storage guidance and restore verification. Host scheduling and off-host replication remain deployment work.

The full suite passed **35 tests**, followed by focused checks for backup/restore and an additional regression proving a delayed older search response cannot replace newer results. All tests used synthetic data and temporary databases.

Five in-process Flask test-client trials per case, median elapsed time; synthetic notes contain 4,250 characters each. These measure serialization/database work, not network transfer or browser rendering:

| Notes | Full response | Summary response | Full median | Summary median |
| --- | --- | --- | --- | --- |
| 1,000 | 4,422,785 bytes | 412,785 bytes | 51.2 ms | 13.8 ms |
| 10,000 | 44,247,786 bytes | 4,147,786 bytes | 654.7 ms | 147.4 ms |

Summary responses are approximately 91% smaller in this benchmark. Body-only saves also have a browser assertion that no full-library or tag refresh occurs. At 10,000 notes, a 4 MB summary still justifies pagination or incremental loading; this is unnecessary for the current small library and should be introduced with a real retrieval need. FTS remains evidence driven.

Current delivery: phases 1–3 implemented, plus SQLite backup/restore from phase 4. Still planned: versioned portable JSON import/export, coalesced revision history, scheduled external backups, evidence-driven retrieval enhancements and CI/accessibility/platform follow-ups. Actual iPad hardware verification is still required before release. No deployment, live database mutation or analytics opt-in occurred during implementation.

### Portable backups and note history — 8 November 2026

Implemented version 1 JSON export and validated, atomic append-only import with fresh IDs (repeated imports deliberately create copies). Timestamps, tags, pin/archive state and trash round-trip. Import is limited to 16 MiB/10,000 notes; SQLite backup/restore handles larger libraries and also includes history. JSON backups intentionally contain current notes, not history or browser-only data.

Implemented 20 checkpoints per note, capturing the previous version at most once per five-minute window. Explicit restores force a checkpoint of the current note, check its revision and restore as a new revision. History preview is plain text, details load on demand, and permanent note deletion cascades to its history. Database readiness now reads the notes table. Full suite: 39 passed, followed by focused browser/import/history/retention checks.
