# 08 — Roadmap and Task Checklist

Work top to bottom. A phase is done when all its boxes are ticked, tests pass, and docs are updated. Each task should fit in one focused commit or PR.

## Phase 0 — Foundation

**Pre-check**
- [ ] Verify the Moodle mobile web service works: log in to `egylms.arabou.edu.kw` from the official Moodle app (blocker R1)
- [ ] Reserve Telegram bot `@ZakerniBot` via BotFather
- [ ] Create Firebase project, add Android + iOS apps, download `google-services.json`, `GoogleService-Info.plist`, service-account JSON

**Repo and infra**
- [x] Monorepo: `backend/`, `mobile/`, `docs/`, `brand/`, `CLAUDE.md`, `.gitignore`, `.editorconfig`
- [x] `docker compose up -d` brings up Postgres 16 + Redis 7 with healthchecks (verified 2026-09-28: migrate + full test suite pass on Postgres; host port 5433 via `POSTGRES_PORT` when a native Postgres holds 5432)
- [x] `.env.example` complete; `.env` git-ignored

**Backend**
- [x] Django project `config/` with split settings (base/dev/test/prod) and `django-environ`
- [x] Apps skeleton: `core, accounts, moodle, schedule, reminders, notifications, support, broadcasts`
- [x] Custom `User` model (before first migration)
- [x] `core`: `UUIDModel`, `TimeStampedModel`, `ApplicationError`, exception handler (error envelope), cursor pagination, Fernet `crypto`
- [x] i18n: `LANGUAGES = ar, en`, `LocaleMiddleware`, `locale/` folders
- [x] DRF + simplejwt + drf-spectacular wired; `/api/schema/` works
- [x] Celery app + beat schedule placeholder; `celery -A config worker` runs
- [x] Unfold admin installed with Zakerni branding
- [x] Tooling: ruff, mypy, pytest-django, factory_boy; one passing smoke test

**Mobile**
- [ ] Expo app (TypeScript strict), Expo Router, dev build runs on Android (app scaffolded on SDK 57 with `expo-dev-client`; `expo export --platform android` and `expo-doctor` pass, but `npx expo run:android` has not been run on a device/emulator yet)
- [x] `shared/theme` tokens from `07-design-system.md`, light/dark + system mode
- [x] `shared/i18n` with `ar.json` / `en.json`, RTL switching + reload
- [x] IBM Plex Sans Arabic loaded
- [x] `shared/lib/http` (interface + axios impl), `shared/lib/storage` (interface + secure store impl)
- [x] `shared/ui` base: `Screen, Text, Button, TextField, Card, Chip, Switch, EmptyState, ErrorState, Skeleton`
- [x] ESLint, Prettier, Jest configured; `npm run typecheck` passes

## Phase 1 — Auth and onboarding

**Backend**
- [x] `MoodleAuthClient` / `MoodleDataClient` protocols, `HttpMoodleClient`, `FakeMoodleClient`
- [x] `MoodleAccount` model (encrypted token)
- [x] `login_with_lms` service: token -> site info -> get_or_create user -> default rules -> enqueue sync
- [x] `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET/PATCH/DELETE /me`
- [x] Login rate limit; password scrubbed from logs
- [x] Tests: success, wrong credentials, LMS down, existing user re-login

**Mobile**
- [x] Native static splash (`expo-splash-screen`) + animated splash screen (timeline in design doc)
- [x] Language screen
- [x] Intro slides (3) with swipe, dots, skip
- [x] Login screen + session store + token refresh interceptor
- [x] Route guard in `app/index.tsx` (session / onboarding state)

## Phase 2 — Calendar data

**Backend**
- [x] Models: `Course`, `Enrollment`, `Item`, `LectureSchedule`, `SyncLog` + constraints from ERD
- [x] `sync_moodle_account` service (courses, quizzes, assignments, diff, soft delete, token expiry)
- [x] Celery: `enqueue_moodle_syncs` (30 min), `sync_moodle_account` task
- [x] Manual exam CRUD service; lecture schedule service + `expand_lecture_schedules` task
- [x] Endpoints: `/items`, `/lectures`, `/courses`, `/me/lms`, `/me/lms/sync`
- [x] Tests with `FakeMoodleClient` (new, changed, removed items; expired token)

**Mobile**
- [x] `itemTypeMeta` registry (icon, colour, label)
- [x] Calendar screen: month grid with dots, day list, Today, pull to refresh
- [x] Item bottom sheet
- [x] Add/edit form (exam | quiz | lecture) with zod validation; manual quizzes (close time, optional opens-at) for quiz dates published outside Moodle
- [x] Courses screen with mute
- [x] Sync status and token-expired banners
- [x] Upcoming tab limited to the next 7 calendar days (today to today + 6, user timezone) with an "All" segment; past items dimmed
- [x] Reminder text includes the location (push and Telegram) and, on Telegram, the tutor name and the Teams join link
- [x] Course detail screen: tutor and group, mute, next 30 days by type, lecture times
- [x] Backend: group and tutor per enrollment from the Moodle sync (best effort); `GET /courses/{id}`
- [x] SIS connection (Settings -> SIS): exam schedule and lecture timetable imported every 6 hours; `/me/sis`, `/me/sis/sync` (docs/01 section 9)

## Phase 3 — Reminders and FCM

**Backend**
- [x] Models: `ReminderRule`, `ItemReminderOverride`, `ScheduledReminder`, `Device`, `Notification`
- [x] `defaults.py` registry; rules created on sign-up
- [x] `schedule_reminders_for_item` + hooks from item/rule/override/mute changes
- [x] `NotificationChannel` protocol, `FcmChannel`, channel registry
- [x] `dispatch_due_reminders` (every minute, skip_locked, retry, skip late) + history rows
- [x] Localised message rendering (`messages.py`) in user language and timezone
- [x] Endpoints: `/reminder-rules`, `/items/{id}/reminders`, `/devices`, `/notifications*`
- [x] Tests: offsets, overrides, mutes, reschedule, concurrency (no double send), invalid FCM token (the multi-thread lock test runs on PostgreSQL only; see Implementation notes)

**Mobile**
- [x] Notification permission screen, FCM token registration + refresh (implemented and unit-tested over native mocks; not run on a device yet, and needs `google-services.json` / `GoogleService-Info.plist`)
- [x] Foreground display (Notifee), tap handling and deep links to item sheet (same caveat: Notifee display and tap events are untested on a device)
- [x] Default reminders onboarding screen
- [x] Reminders tab (`RuleCard`, `OffsetChips`, `ChannelToggles`, optimistic updates)
- [x] Item reminder override screen
- [x] Notification history + unread badge on bell

## Phase 4 — Telegram

**Backend**
- [x] `TelegramLink`, `TelegramLinkToken` models
- [x] `create_link_token`, webhook handler (`/start <token>`, secret header), unlink
- [x] `TelegramChannel` registered in channel registry; 403 -> auto unlink
- [x] Bot texts in AR/EN (no emoji)
- [x] Endpoints: `/telegram`, `/telegram/link`, `/telegram/webhook`
- [x] Tests: valid, expired, reused token; blocked bot

**Mobile**
- [x] Telegram screen (onboarding + settings): connect, linked state, unlink; refresh on app focus (the round trip through the Telegram app is not verified on a device)
- [x] Telegram toggle enabled only when linked

## Phase 5 — Support and admin

**Backend**
- [x] `Report`, `ReportAttachment`, `ReportReply` models; image validation (3 files, 5 MB)
- [x] Endpoints: `/reports*`, `/reports/categories`
- [x] Admin: reports list/detail, inline reply -> push to user, status changes
- [x] `Broadcast` model + admin "Send now" action + `send_broadcast` task (per-user language)
- [x] Unfold dashboard: KPI cards, reminders-per-day chart, failed syncs table
- [x] Admin translated (AR/EN, RTL)
- [x] Admin redesign: brand-indigo Unfold theme, IBM Plex Sans Arabic, branded login, KPI-card dashboard with quick actions, grouped sidebar
- [x] Moodle sync limited to current-term courses (`inprogress` classification, date-filter fallback); old enrollments deactivated and their items soft-deleted
- [x] Moodle calendar events (online Teams lectures) synced as `lecture` items with the Teams link
- [x] Sync skips quizzes, TMAs and calendar events dated before their course's `startdate` (reused course pages from earlier terms)
- [x] `/courses` and `/items` exclude inactive enrollments
- [x] Lecture schedules generate every occurrence up to `ends_on` on create/edit (daily job fills gaps); `LECTURE_EXPANSION_DAYS` removed
- [x] `GET /items`: `from=now`, optional `to`, `type` filter documented in Swagger
- [x] Real-time report chat: Django Channels WebSocket `ws/v1/reports/<id>/` (JWT `?token=` or admin session), broadcast on commit from the reply service
- [x] Admin report page: live conversation with a send box over the same socket

**Mobile**
- [x] Report a problem (category, description, screenshots, auto device info)
- [x] My reports list + report details with replies
- [x] Settings screen complete (theme, language, account, delete account)
- [x] About & privacy screen
- [x] Upcoming tab (Quizzes / TMA / Exams / Lectures top tabs, nearest first, grouped by day, pull to refresh syncs)
- [x] Item sheet: "Join on Teams" for Teams meeting links (Moodle calendar lectures)
- [x] `shared/lib/realtime` (native WebSocket, reconnect/backoff, 4401 refresh once, 4403 stop) + live report details (`useReportChat`, POST fallback)

## Phase 6 — Release

- [ ] Empty / loading / error / offline states reviewed on every screen
- [ ] RTL and dark mode QA pass on all 18 screens
- [ ] Accessibility: labels on icon buttons, font scaling 1.3x, contrast check
- [ ] Sentry (backend + app), structured logging
- [ ] Production deploy: web, worker, beat, managed Postgres/Redis, HTTPS, Telegram webhook set
  - [x] Config ready for Railway: Dockerfile, `railway*.json`, prod settings (hosts, CSRF, proxy SSL, HSTS, WhiteNoise, stdout logging), `FIREBASE_CREDENTIALS_JSON`, Cloudinary media storage, `telegram_set_webhook` command
  - [ ] Actually deployed and webhook set (not done yet)
- [ ] Daily DB backup + restore test
- [ ] Privacy policy published; store listings AR/EN, screenshots, icon
- [ ] Internal testing track (Android) / TestFlight (iOS)

## Phase 7 — Per-item status & notes

**Backend**
- [x] `Item.status` (`ItemStatus` registry) + `Item.note`, migration `0005_item_status_note`
- [x] `set_item_status_note` service (any type/source, never reschedules), `PATCH /items/{id}/status`, `status`/`note` in `ItemSerializer`
- [x] Tests (service + endpoint + serializer); docs 01/04/05 updated

**Mobile**
- [x] `itemStatusMeta` registry, types/DTO/api, `useItemStatusNote` optimistic hook
- [x] Status pill + note in item sheet; "Status and note" action (`/item/[id]/status` route) + `StatusNoteSheet`
- [x] `ItemRow` status chip + cancelled strikethrough; AR/EN translations; tests

**My log (history of marked items)**
- [x] Backend `items_history` selector + `GET /items/history` (status/type/course filters, cursor pagination); tests; docs 05
- [x] Mobile `history` feature: `ItemHistoryScreen` (`/history`), status filter pills, month groups, edit via `/item/[id]/status`; history pages patched/invalidated with the other item caches; entry points in Settings and Home; tests

## Phase 8 — Device-side university sync (mobile)

**Backend**
- [x] App accounts (supersedes the device binding): `POST /auth/register`, `POST /auth/signin` (lockout), `POST /auth/change-password`; `POST /me/lms/connect`, `DELETE /me/lms`, `GET /me/lms` answers `connected: false`; `/auth/login` kept
- [x] Device binding removed (`device-login`, `LMS_FETCH_MODE`, `DEVICE_SECRET_KEY`, `User.device_secret_hash`/`device_bound_at`, migration 0004)
- [x] `POST /me/lms/ingest`: `PayloadMoodleClient` + the unchanged `SyncMoodleAccount`; strict caps and date ranges; throttle 1/min + 200/day; `lms_status: "expired"`
- [x] Course announcements: optional `announcements` list in `POST /me/lms/ingest` (upsert only, 180-day retention), `CourseAnnouncement` model, new-post push/Telegram notification (kind `announcement`, max 5 per ingest), `GET /announcements`, `developer_name` in `GET /meta/app`
- [x] `MoodleAccount.token_encrypted` optional; periodic task, sync task and `/me/lms/sync` skip token-less accounts
- [x] `POST /me/sis/ingest`: `PayloadSisClient` + the unchanged `SyncSisAccount`; gated by `SIS_INGEST_ENABLED` (default off); password-less SIS accounts skipped by the periodic sync
- [x] Admin: password change form and action "Set a temporary password" (no forgot-password flow yet)
- [x] Tests, `extend_schema`, docs 01/02/05, `.env.example`, backend README, CLAUDE.md rule 2 note

**Mobile**

- [x] `shared/lib/lms`: `LmsClient` interface, Moodle mobile web-service client on its own HttpClient (`EXPO_PUBLIC_MOODLE_URL`), `FakeLmsClient`, Moodle token in secure storage
- [x] Register / sign in with the app account; Settings -> Connect university: Moodle token on the phone -> `POST /me/lms/connect`
- [x] `features/lms`: fetch from Moodle -> `POST /me/lms/ingest`; on app open/foreground (10 min throttle), pull to refresh, "Sync now"; 429 = synced recently; token rejected -> `lms_status: "expired"`
- [x] SIS: `SisClient` + `FakeSisClient` only; SIS screen behind `EXPO_PUBLIC_SIS_ENABLED` (default false)
- [x] Mobile app accounts: combined Sign in / Create account screen, change app password (stores the fresh token pair), `features/lms` connect/disconnect screen, Home call to action, Settings row, sync no-ops while not connected; device secret and `device-login` removed
- [x] Course news (mobile): `LmsClient.announcements` (news forums, `mod_forum_get_forum_discussions` with paginated fallback), `announcements` in the ingest payload (newest 100), `features/announcements` (`GET /announcements`, `AnnouncementCard`, `NewsSection`, `LatestNewsCard`, `/course-news/[id]`), shown in course detail and on Home; tests
- [x] About screen rewritten (hero + floating sections: what the app does, unofficial notice, data and privacy, developer and contact with `developer_name` from `GET /meta/app`); tests
- [ ] Verify on a device against the real Moodle (Expo Go or a dev build) and against the deployed backend
- [x] Real SIS client on the phone (`shared/lib/sis/httpSisClient.ts`): sign in, current academic session, schedule; credentials in secure storage; auto sync on open and Settings -> SIS -> Sync now; posts to `POST /me/sis/ingest`

## Ideas / Later (not in v1)

- Best-effort background fetch (new Moodle items today appear only after the student opens the app)
- Forgot-password flow (staff set a temporary password in the admin today)

- Email channel (just a new `NotificationChannel`)
- Home-screen widget with the next deadline
- Import exam timetable from a PDF/image
- Support other AOU branches (different Moodle URLs)
- Reopen a resolved/closed report automatically when the student adds a follow-up
  (today the status is left unchanged; staff see the reply in the thread)
- Deleting or editing a single lecture occurrence (today: mute it; changes go through
  the lecture schedule)
- Serve report attachments through an authenticated view instead of `MEDIA_URL`
  (file names are unguessable UUIDs today)

## Implementation notes (backend)

Phase 0/1 placeholders are all replaced:

- `User.telegram_linked` is read from `TelegramLink`; `User.onboarding.defaults_confirmed`
  comes from the new `User.reminder_defaults_confirmed_at`, set by
  `POST /reminder-rules/confirm-defaults`.
- `create_default_reminder_rules` creates one `ReminderRule` per type from
  `apps/reminders/defaults.py` (idempotent; also called on every login to fill gaps).
- `sync_moodle_account_task` runs `SyncMoodleAccount` (wired in `config/container.py`).

Decisions taken where the docs were silent (safe defaults):

- **Arrays as JSON.** `offsets_minutes` and `weekdays` are `JSONField` lists, not
  Postgres arrays, so the test suite can run on SQLite. Their value checks (1..5
  offsets, 5..20160, unique; weekdays 0..6) are enforced in the services and
  serializers instead of DB check constraints. All other ERD constraints/indexes
  are real DB constraints.
- **Telegram in default rules.** New rules have `telegram_enabled=false` unless
  Telegram is already linked (the API rejects `telegram_enabled=true` without a
  link). Linking Telegram turns it on for the types whose default includes it
  (quiz, TMA, exam). Unlinking (user action or bot blocked, 403) turns it off
  everywhere and cancels pending Telegram reminders.
- **Channels at scheduling time.** Reminders are scheduled only for channels the
  user has connected; registering the first active device or linking Telegram
  reschedules upcoming items. At dispatch a channel that became unavailable marks
  the row `skipped` (`channel_unavailable`).
- **Re-arming.** A reminder row that was already sent/failed/skipped is only re-armed
  when its item moved later (new `send_at` after the old one, e.g. a TMA deadline
  extension). Otherwise the unique row is never sent again.
- **Dispatch transactions.** Each due row is claimed in its own short transaction
  (`select_for_update(skip_locked=True, of=("self",))` + re-check of `pending`), so
  locks are not held across a whole batch of HTTP calls. One history row is written
  per (item, offset) even when push and Telegram both deliver it.
- **Moodle items without a date** are stored with `scheduled_at = NULL` (column is
  nullable) and never scheduled or listed by `/items`.
- **Lecture occurrences** are read-only through `/items` (`is_editable=false`,
  `item_not_editable`); they are changed through `/lectures`. A schedule keeps the
  user's timezone at creation. Validation: at most 1 year, duration 1..600 minutes.
- **Manual exams** may only reference a course the user is enrolled in.
- **`/me/lms`** returns 404 for accounts without a Moodle account (staff).
  `POST /me/lms/sync` returns the LMS status with `202`, or `lms_token_expired` (401).
- **Account expiry** sends one "Sign in again" system notification (push + Telegram +
  history row) on the active -> expired transition only.
- **Direct notification** (admin, user page): a `Broadcast` with `recipient` set; audience is that one active user (staff allowed when chosen), delivered through the normal broadcast send path.
- **Broadcast audience** is every active non-staff user; `recipients_count` counts
  users reached through at least one channel. Every audience member also gets a
  history row. Re-running a send skips users who already have one.
- **Staff report replies** are delivered by push only (docs/06: "reply triggers push")
  plus a history row; the student's own follow-ups do not notify anyone.
- **Webhook** answers 200 for every authenticated update (even invalid tokens, which
  get a bot reply) so Telegram does not retry; 403 when the secret header is wrong or
  `TELEGRAM_WEBHOOK_SECRET` is empty. Bot replies for unknown chats use Telegram's
  `language_code` (English only when it starts with `en`, Arabic otherwise).
- **`GET /meta/app`** (docs/05) is served from `APP_*` env settings.
- **Translations.** GNU gettext is not installed on the dev machine, so
  `python manage.py compile_po` (pure Python) compiles `locale/*/django.po` to `.mo`.
  `makemessages` / `compilemessages` still work where gettext is available.
- **Django 5.2 LTS.** Django is pinned to 5.2.17 (5.2.8+ is required for Python 3.14;
  older versions crash admin change lists when copying template contexts).
- **Concurrency test.** SQLite (used by `pytest`) has no row locks, so the no-double-send
  guarantee is tested by simulating the race (row claimed by another worker between
  listing and locking); the real multi-thread test is marked PostgreSQL-only and skipped
  on SQLite.

## Implementation notes (Phases 0-5 mobile)

Safe defaults chosen where the docs were silent (details in `mobile/README.md`):

- **After login** the guard runs the post-login steps (screens 5-7), then the Calendar tab
  (see the Phase 2-5 notes below). The Phase 1 placeholder tab is gone.
- **Launch order.** `app/index.tsx` plays the animated splash once per app start, then:
  session -> Calendar; no language chosen -> Language; intro not seen -> Intro; else Login.
  Language and Intro are shown only until completed (the doc said "Splash -> Language"
  for every signed-out launch; repeating them after a logout seemed wrong).
- **Default language before the user picks one** is the device language if it is English,
  otherwise Arabic.
- **Language screen:** tapping a card applies it immediately. If the layout direction
  changes, a non-cancellable dialog ("The app will restart") is shown, then the app reloads
  via `reloadAppAsync` from `expo` (works in dev and release builds, so `expo-updates` is
  not needed for this).
- **Refresh failure = logout only when the server rejects the refresh token** (400/401/403
  from `/auth/refresh`, or no refresh token). Offline, timeouts, 5xx and 429 keep the
  session and fail only the original request, so students are not signed out for being
  offline. A retried request that still gets 401 also logs out.
- **Login errors** map error codes to app translations (`invalid_lms_credentials`,
  `lms_unavailable`, `lms_token_expired`, `throttled`, network, timeout); anything else
  shows a generic message. Server-side validation details are not shown per field.
- **Logout** calls `POST /auth/logout` best effort and always clears the local session and
  the query cache. Since Phase 3 it also sends the current FCM token as `fcm_token`.
- **Preferences** (language, theme mode, intro seen) persist in AsyncStorage through the
  `KeyValueStorage` abstraction; the session persists in `expo-secure-store` through the same
  abstraction. Theme mode defaults to `system`; the picker is in Settings.
- **Intro illustrations** use the item-type icons and colour tokens directly (they predate
  the `itemTypeMeta` registry and show fixed sample content).
- The native splash, adaptive icon and store icon PNGs in `mobile/assets/` were rendered
  from `brand/*.svg`. The Android monochrome (themed) icon is not provided yet.

Phases 2-5 (safe defaults where the docs were silent; none of this has run on a device):

- **Routes.** Onboarding screens 5 and 6 live at `/(onboarding)/allow-notifications` and
  `/(onboarding)/connect-telegram`, because `/notifications` (history) and `/telegram`
  (Settings) already use those URLs. Tabs and secondary screens sit in an `(app)` group
  whose layout holds the `SessionGate`, `GET /me` sync, FCM registration and push-tap routing.
- **Post-login guard.** Session -> notification step (until answered on this device) ->
  Telegram step (skipped when `/me.telegram_linked`, otherwise shown once per device) ->
  defaults step (until `/me.onboarding.defaults_confirmed`) -> Calendar. The two
  "seen" flags are device-level preferences, so another account on the same device skips them.
- **Calendar.** Own month grid instead of `react-native-calendars` (RTL, tokens). Weeks start
  on Saturday in both languages (confirmed by product owner 2026-09-28). The query covers the visible 5-6 weeks in the user's
  timezone (`User.timezone`, default Africa/Cairo). Pull to refresh asks for `POST
  /me/lms/sync` (throttled errors ignored) and reloads items. "Syncing your courses" shows
  while `/me/lms` is active with no `last_synced_at` (polled every 10 s); "Sign in again"
  shows when it is `expired` and opens the connect screen (Moodle password only).
- **Item sheet.** Lecture occurrences are not editable through `/items`, so the sheet's
  Edit / Delete act on the lecture schedule (future occurrences), with a confirmation that
  says so (confirmed by product owner 2026-09-28). Exams use `PATCH/DELETE /items/{id}`. Exam duration is optional and becomes
  `ends_at`; duration fields accept 1..600 minutes.
- **Reminder times.** The "+" chip offers presets (5, 10, 15, 30 min; 1, 2, 3, 6, 12 h;
  1, 2, 3 days; 1, 2 weeks); free-form offsets are not offered. Rule changes save instantly
  with an optimistic update and roll back on error, with an error banner. The per-item
  screen shows the type's times read-only until "Use custom times" is on; turning it off or
  "Reset to default" calls `DELETE /items/{id}/reminders`.
- **Telegram toggle.** Disabled and shown off, with a Connect link, until Telegram is linked
  (the API would reject it). `GET /telegram` refetches whenever the app returns to the
  foreground; a change updates the stored user and refetches the rules.
- **Push.** The FCM `data.route` is not trusted: targets are built from `kind` and ids.
  Foreground messages are displayed with Notifee on an Android channel named "Reminders".
  `expo-doctor` flags `@notifee/react-native` as unmaintained; it is excluded from that
  check in `package.json` because docs/03 prescribes it. If it breaks on the New
  Architecture, the `PushService` interface in `shared/lib/notifications` is the only
  place to change.
- **Reports.** Screenshots come from the photo library only (no camera), re-encoded as JPEG
  at 0.8 quality so iOS HEIC photos are accepted by the API. Files over 5 MB and a 4th file
  are rejected on the client; files whose size the platform does not report are sent and
  left to the server check. Device info sent: platform, OS version, model, app version.
  After sending, a confirmation opens the new report's details.
- **Settings.** Language change asks for confirmation, calls `PATCH /me {language}`, then
  reloads. Delete account uses a destructive confirmation and then clears the session.
  About shows the privacy policy and Telegram contact from `GET /meta/app`.
- **Plurals.** Arabic needs six plural forms; `intl-pluralrules` polyfills
  `Intl.PluralRules` for Hermes. Both locale files carry all six suffixes so the key-parity
  test holds.
- **Offline.** TanStack's `onlineManager` is fed by NetInfo; every screen header shows an
  offline banner and keeps cached data; screens with nothing cached show the error state
  with Retry.
