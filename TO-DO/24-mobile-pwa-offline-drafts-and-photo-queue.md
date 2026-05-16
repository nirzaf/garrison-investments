# Mobile PWA, Offline Drafts, and Photo Queue

## Title
Mobile PWA, Offline Drafts, and Photo Queue

## User Story
As a field user,
I want mobile-friendly offline draft saving and photo upload retry,
so that weak construction-site internet does not cause report data loss.

## Description
Implement Phase 3 PWA behavior for installability, offline app shell, IndexedDB report drafts, background sync, offline photo queue, sync status, and mobile UX polish.

## Acceptance Criteria
1. Given I am filling a report on mobile,
   When the network drops,
   Then my draft continues saving locally.

2. Given I capture photos while offline,
   When connectivity returns,
   Then queued uploads retry automatically and show sync status.

3. Given the app is installable,
   When I open it from a mobile device,
   Then the app shell loads quickly and works like a PWA.

4. Given a draft sync conflict occurs,
   When the user returns online,
   Then the system shows a clear resolution path without silent data loss.

## Business Rules
- Offline draft saving can wait until Phase 3.
- Offline behavior is limited to saving draft reports offline, not full offline operation.
- Photo uploads should work offline.
- Material transactions do not need offline support.
- Forms autosave every 30 seconds and on field blur/change.
- Supported browsers include Chrome, Edge, iOS Safari, Android Chrome, and Opera if feasible.

## UI/UX Notes
- Mobile flows prioritize supervisor updates, engineer reports, photo upload, document view, approvals if confirmed, and notifications.
- Show offline, queued, syncing, failed, and synced states clearly.
- Touch targets must be comfortable for field use.
- The app must tolerate weak H+ network conditions.

## Technical Notes
- Add Web App Manifest and service worker.
- Use IndexedDB for report drafts and upload queue metadata.
- Implement background sync where browser support allows and foreground retry fallback otherwise.
- Keep offline queue scoped to reports and photos.
- Test browser differences, especially iOS Safari limitations.
- Follow `ARCHITECTURE.md` offline strategy: client-generated UUIDs, `Idempotency-Key` headers, Redis-backed 24-hour idempotency cache, and explicit sync status fields.
- Conflict handling must surface `server_newer` conflicts instead of silently overwriting approved or updated server records.
- Use TanStack Query optimistic updates only where the server can safely reconcile them.

## Priority
Low

## Dependencies
- Report flow.
- Photo upload management.
- App shell and offline indicator.
- Confirmation whether mobile approvals are MVP or desktop-only.
- Confirmation that Edge replaces Internet Explorer.

## Definition of Done
- PWA install metadata exists.
- Offline draft saving works.
- Offline photo queue retries.
- Sync status is visible.
- Mobile regression tests cover supported browsers and weak network scenarios.
