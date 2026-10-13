# 05 — REST API (v1)

Base: `/api/v1/`. JSON. Auth: `Authorization: Bearer <access>` except where noted. Language: `Accept-Language: ar | en`. Times are ISO 8601 UTC (`2026-10-01T19:00:00Z`). Pagination: cursor (`?cursor=`), 20 per page.

Error envelope (all non-2xx):

```json
{"error": {"code": "validation_error", "message": "…translated…", "details": {"field": ["…"]}}}
```

## Auth and profile

| Method | Path | Body / Query | Response |
|---|---|---|---|
| POST | `/auth/login` (public) | `{username, password}` | `200 {access, refresh, user, is_new}` |
| POST | `/auth/register` (public) | `{username, password, language?}` | `201 {access, refresh, user, is_new: true}`. `409 username_taken`, `400 validation_error` (`details.username` / `details.password`), `429 throttled`. See "App accounts" below |
| POST | `/auth/signin` (public) | `{username, password}` | `200 {access, refresh, user, is_new: false}`. `401 invalid_credentials` (same for wrong password, unknown user, unusable password), `429 too_many_attempts` (lockout) or `429 throttled` |
| POST | `/auth/change-password` | `{old_password, new_password}` | `200 {access, refresh}` (existing refresh tokens are blacklisted, the new pair keeps the session). `400 validation_error` (`details.old_password` / `details.new_password`) |
| POST | `/auth/refresh` (public) | `{refresh}` | `200 {access, refresh}` |
| POST | `/auth/logout` | `{refresh, fcm_token?}` | `204` (blacklists refresh, deactivates device) |
| GET | `/me` | | `200 User` |
| PATCH | `/me` | `{language?, timezone?}` | `200 User` |
| DELETE | `/me` | | `204` deletes account and data |
| GET | `/me/lms` | | `200 {connected, status, last_synced_at, last_sync_error}` (`status`: `active` \| `expired` \| `disabled` \| `not_connected`). Always 200: `{connected: false, status: "not_connected", last_synced_at: null, last_sync_error: ""}` when the university is not connected |
| POST | `/me/lms/connect` | `{username, moodle_user_id, full_name, email, site_url}` | `200` same body as `GET /me/lms`. Creates or updates the `MoodleAccount` (no token, status `active`); fills `full_name`/`email` only when empty. `full_name` and `email` may be empty |
| DELETE | `/me/lms` | | `204` disconnects: deletes the `MoodleAccount`, soft-deletes the Moodle-sourced items (reminders cancelled), deactivates enrollments; manual items, lectures and SIS data are kept |
| POST | `/me/lms/sync` | | `202 {status, last_synced_at, last_sync_error}` triggers sync (throttled 1 per 5 min -> `429 throttled`). Does nothing server-side for accounts without a stored token (phone-connected: use the ingest endpoint) |
| POST | `/me/lms/ingest` | `{courses?, groups?, group_members?, quizzes?, assignments?, calendar_events?, lms_status?}` | `200 {status, items_created, items_updated, items_removed, last_synced_at}`. `404` when the user has not called `/me/lms/connect`. See below |

Errors: `username_taken` (409), `invalid_credentials` (401), `too_many_attempts` (429), `invalid_lms_credentials` (401), `lms_unavailable` (503), `lms_token_expired` (401, app shows re-login; also returned by `/me/lms/sync` when the account is expired).

`User`:

```json
{"id": "…", "full_name": "Mohamed Wael", "moodle_username": "…", "email": "…", "language": "ar",
 "timezone": "Africa/Cairo", "telegram_linked": true, "onboarding": {"defaults_confirmed": true}}
```

`onboarding.defaults_confirmed` becomes `true` after `POST /reminder-rules/confirm-defaults`. `PATCH /me` rejects unknown IANA timezones (`validation_error`).

## App accounts and the phone-side university fetch

The app has its own accounts (student number + app password). Connecting the university is optional and done later from Settings. Moodle blocks the server's IPs, so the phone logs in to Moodle itself and posts what it fetched. The Moodle token and password never reach the server.

### `POST /auth/register` (public)

Throttled like `/auth/login` (5/min per IP, `429 throttled`). Body:

| Field | Type | Rules |
|---|---|---|
| `username` | string | the student number; stripped and lowercased; 3 to 32 ASCII letters or digits |
| `password` | string | min 8 characters, Django validators (not too common, not all numeric, not similar to the username) |
| `language` | `ar` \| `en` | optional |

Creates the user (`moodle_username` = username, hashed password, default reminder rules). `201` returns the login body `{"access", "refresh", "user": User, "is_new": true}`. An existing username, including a legacy account with an unusable password, answers `409 username_taken`; a weak password answers `400 validation_error` with `details.password`.

### `POST /auth/signin` (public)

Body `{username, password}`. `200` returns `{"access", "refresh", "user", "is_new": false}`. Every failure returns `401 invalid_credentials` with the same message. After 10 failures for a username within 15 minutes the username answers `429 too_many_attempts` until the window expires (a successful sign-in or an admin temporary password resets it).

### `POST /auth/change-password`

Authenticated; body `{old_password, new_password}`. A wrong old password gives `400` with `details.old_password`, a weak new one `details.new_password`. On success all the user's refresh tokens are blacklisted and `200 {access, refresh}` returns a fresh pair.

### `POST /me/lms/connect`

Authenticated. Body (`full_name` and `email` may be empty):

| Field | Type | Rules |
|---|---|---|
| `username` | string | the Moodle username typed on the phone, 1-150 characters (informational) |
| `moodle_user_id` | integer | 1 to 2147483647 |
| `full_name` | string | max 255, may be empty |
| `email` | string | valid email or empty |
| `site_url` | string | URL, max 200 |

Creates or updates the `MoodleAccount` (`site_url`, `moodle_user_id`, `status: active`, no token; any older stored token is cleared) and fills `User.full_name` / `email` only when they are empty. No sync is enqueued and Moodle is never contacted. Response: the `GET /me/lms` body.

### `POST /me/lms/ingest`

Authenticated; throttled to 1 request per minute and 200 per day per user (`429 throttled`). Field names are the snake_case names of the dataclasses in `apps/moodle/protocols.py`; unknown keys are ignored. Every list is optional but at least one of the six lists, `announcements` or `lms_status` must be present. A request with only `announcements` is valid and does not run the snapshot sync (nothing is removed). The body is a **full snapshot** of the student's current term: whatever is missing from it is treated as gone (items are soft deleted, courses deactivated), exactly as when the server fetched the data. Items need their course, so `quizzes`/`assignments`/`calendar_events` without `courses` are rejected. Duplicate keys inside a list are collapsed. Timestamps are Unix seconds between 2015-01-01 and now + 5 years (`0` = no date; `null` allowed where shown).

| Key | Max items | Item fields |
|---|---|---|
| `courses` | 200 | `moodle_course_id` (int >= 1), `code` (max 64), `name` (max 255), `start_date` (Unix seconds, `0` if unknown) |
| `groups` | 1000 | `moodle_course_id`, `group_id`, `name` (max 255): the student's groups per course |
| `group_members` | 5000 | `group_id`, `user_id`, `full_name` (max 255), `roles` (list of up to 20 role shortnames, e.g. `["teacher"]`) |
| `quizzes` | 2000 | `moodle_course_id`, `instance_id`, `name` (max 255), `time_open` (nullable), `time_close` (nullable), `url` (max 500) |
| `assignments` | 2000 | `moodle_course_id`, `instance_id`, `name` (max 255), `due_date` (nullable), `url` (max 500), `allow_submissions_from` (nullable) |
| `announcements` | 500 | `moodle_course_id`, `forum_id`, `discussion_id` (ints >= 1), `group_id` (int >= 0, `0` = every group), `subject` (max 255), `message` (HTML or text, max 20000, no NUL), `author_name` (max 255, may be empty), `time_created`, `time_modified` (Unix seconds, required, not 0), `pinned` (bool), `url` (max 500, may be empty). **Not a snapshot**: posts are only upserted by `discussion_id` and never removed because they are missing. Posts of courses the student is not actively enrolled in are skipped. See "Announcements" below |
| `calendar_events` | 2000 | `event_id`, `moodle_course_id` (`0` for the student's own events), `name` (max 255), `time_start` (required, not 0), `duration_seconds` (0 to 2592000), `description` (raw HTML, max 20000), `url` (max 500), `module_name` (max 64; empty for lectures, `quiz`/`assign` events are ignored by the sync) |

`lms_status: "expired"` (the only accepted value, alone or with data) means Moodle rejected the phone's token: the account becomes `expired`, one "sign in again" notification is sent (once) and nothing is synced. A normal ingest of an `expired` account re-activates it.

Response `200`: `{"status": "success" | "failed", "items_created": 0, "items_updated": 0, "items_removed": 0, "last_synced_at": "2026-10-01T08:00:00Z"}` (`failed` when the sync did not run: `lms_status: "expired"`, or a disabled account; `last_synced_at` is `null` before the first success). Errors: `400 validation_error` (caps, lengths, dates, missing keys), `401`, `404 not_found` (no `MoodleAccount`: log in first), `429 throttled`. Course names and codes of courses that already exist are never overwritten by an ingest.

### Announcements

The phone reads the "news" forum of each course and posts the discussions in `announcements`. The server stores them per student (`course_announcement`, unique `(user, discussion_id)`; group posts never reach other students), converts `message` to plain text (tags stripped, entities decoded, whitespace collapsed, paragraphs kept as newlines), extracts the first Teams meeting link into `teams_url`, updates subject/body/pinned/modified time when they change, and deletes the student's announcements posted more than 180 days ago on every ingest. For each announcement **created** by an ingest whose `time_modified` is within the last 3 days, one history notification (`kind: "announcement"`, title `<course code>: <subject>`, body the first 140 characters) is created and sent through the push and Telegram channels the student has (in the student's language; delivery failures never fail the ingest). At most 5 are sent per ingest; the rest are summarised in one "N more announcements" notification. Updates and old posts are silent.

`GET /announcements` (authenticated): newest `posted_at` first (pinned posts are not moved up), cursor paginated, 20 per page: `200 {results: Announcement[], next, previous}`. Query: `cursor`, `course` (Course id uuid; `400 validation_error` if not a uuid). Only the caller's rows. `Announcement`: `{id, course: {id, code, name} | null, subject, body (plain text), author_name, pinned, posted_at, modified_at, url, teams_url, group_id}`.

## SIS (Student Information System, optional)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/me/sis` | | `200 SisStatus` (also when not connected: `connected: false`) |
| POST | `/me/sis` | `{username, password}` | `201 SisStatus`. Signs in to the SIS once to verify; on success stores the password Fernet-encrypted and enqueues a sync. Nothing is stored on failure. Also used to reconnect after `invalid_credentials` |
| DELETE | `/me/sis` | | `204`. Deletes the account and password, soft deletes future SIS exams (reminders cancelled) and deletes SIS timetables with their future lecture occurrences (`404` when not connected) |
| POST | `/me/sis/sync` | | `202 SisStatus`, enqueues a sync (throttled 1 per 5 min -> `429 throttled`; `404` when not connected) |

`SisStatus` (never contains the password):

```json
{"connected": true, "username": "2026123456", "status": "active",
 "last_synced_at": "2026-10-01T08:00:00Z", "last_sync_error": ""}
```

`status`: `active` | `invalid_credentials` | `error` | `disabled` (`null` when not connected).

### `POST /me/sis/ingest` (device mode, off by default)

Answers `404 not_found` unless `SIS_INGEST_ENABLED=true` (the SIS is switched on only when the university grants official access). Authenticated; throttled to 1 per minute and 50 per day per user. Body `{"entries": [...]}` (required, at most 2000, may be empty = nothing scheduled any more), each entry with the field names of `SisScheduleEntry` in `apps/sis/protocols.py`:

`kind` (`"lecture"` \| `"exam"`), `day` (`YYYY-MM-DD`, 2015 to today + 5 years), `course_code` (1-64), `start_time` (`HH:MM` or `HH:MM:SS`, local SIS time), `end_time` (nullable), `location_en`, `location_ar`, `lecturer_en`, `lecturer_ar`, `exam_name` (each max 255, default empty), `is_online` (default false).

Runs the existing SIS sync over the entries as a full snapshot (future exams and timetables that are missing are removed). No SIS password is stored and the server never calls the SIS. Response `200 {status, items_created, items_updated, items_removed, last_synced_at}` like the LMS ingest; errors `400 validation_error`, `401`, `404`, `429`. The SIS status endpoint reports such an account as connected with an empty `username`.

Errors: `sis_invalid_credentials` (400, not 401 so the app does not try to refresh its JWT; also returned
by `/me/sis/sync` when the stored password no longer works), `sis_unavailable` (503).

SIS items appear in `/items` with `source: "sis"`, `is_editable: false`; SIS lecture schedules are
rejected by `PATCH`/`DELETE /lectures/{id}` with `item_not_editable`.

## Calendar items

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/items` | `from` (ISO 8601 or `now`), `to?` (max 62 days after `from`, default `from` + 62 days), `type?`, `course?` | `200 Item[]` (not paginated) |
| GET | `/items/history` | `status?` (comma separated, e.g. `attended,done`; default any set status), `type?`, `course?`, `cursor?` | `200 {results: Item[], next, previous}` (newest `scheduled_at` first, 20 per page) |
| GET | `/items/{id}` | | `200 Item` |
| POST | `/items` | `ItemCreate` (exam or quiz; lectures go through `/lectures`) | `201 Item` |
| PATCH | `/items/{id}` | manual items only | `200 Item` |
| DELETE | `/items/{id}` | manual items only | `204` |
| PATCH | `/items/{id}/mute` | `{is_muted}` | `200 Item` |
| PATCH | `/items/{id}/status` | `{status?, note?}` | `200 Item` |

- `/items` returns items with `from <= scheduled_at < to`, sorted by `scheduled_at`. `from=now` means the current server time, so `GET /items?type=quiz&from=now` lists the upcoming quizzes of the next 62 days, nearest first. `type` is `quiz` | `tma` | `exam` | `lecture`. Moodle items without a close/due date have `scheduled_at = null` and are never returned by the range query.
- `ItemCreate`: `{type: "exam" | "quiz" (default "exam"), course_id?, title, scheduled_at, ends_at?, available_from?, location?}`. For a quiz `scheduled_at` is the close time (reminder anchor, quiz rule) and `available_from` the optional opens-at time, which must be before `scheduled_at`. `course_id` must be one of the user's courses; `ends_at` must be after `scheduled_at`. Any other `type` is `400 validation_error`.
- `/items/history` ("My log"): the user's non-deleted, dated items whose `status` is set (empty status is excluded), across all dates and including past-term courses. An unknown value in `status` returns `400 validation_error`. Cursor paginated like `/notifications`.
- `PATCH /items/{id}`: any subset of `{course_id, title, scheduled_at, ends_at, available_from, location}`. Only items with `is_editable = true` (manual exams and quizzes): Moodle items and lecture occurrences return `400 item_not_editable` (lectures are changed via `/lectures`). `DELETE` has the same rule and soft-deletes the item.
- `PATCH /items/{id}/status`: any subset of `{status, note}`, the student's own annotation. Works for **every** item type and source (including Moodle/SIS items). `status` is `planned | attended | postponed | cancelled | done`, or `""` to clear it (any other value is `400 validation_error`); `note` is free text up to 2000 characters. This endpoint **never touches reminders** (status/note are independent of scheduling). Items of other users return `404 not_found`.
- Items of other users return `404 not_found`.

`Item`:

```json
{"id": "…", "type": "quiz", "source": "moodle", "title": "Quiz 2",
 "course": {"id": "…", "code": "MT129", "name": "Calculus"},
 "available_from": "2026-09-30T19:00:00Z", "scheduled_at": "2026-10-01T19:00:00Z",
 "ends_at": null, "location": "", "url": "https://egylms.arabou.edu.kw/mod/quiz/view.php?id=…",
 "status": "", "note": "",
 "is_muted": false, "is_editable": false,
 "reminders": {"offsets_minutes": [1440, 180], "is_override": false, "next_at": "2026-09-30T19:00:00Z"},
 "lecture_schedule_id": null}
```

## Lectures (recurring)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/lectures` | | `200 LectureSchedule[]` |
| POST | `/lectures` | `{course_id?, title, weekdays[], start_time "18:00", duration_minutes, location, starts_on, ends_on}` | `201` (items generated immediately) |
| PATCH | `/lectures/{id}` | same fields | `200` (future items regenerated) |
| DELETE | `/lectures/{id}` | | `204` (future items removed) |

`LectureSchedule`: `{id, course: {id, code, name} | null, title, weekdays, start_time: "18:00", duration_minutes, location, starts_on, ends_on, timezone}`.
`weekdays` uses `0 = Monday .. 6 = Sunday`; `start_time` is local time in `timezone` (the user's timezone at creation). Every future occurrence up to `ends_on` is generated on create/update (a daily job only fills gaps). Validation: at least one unique weekday, `ends_on >= starts_on`, span at most one year, `duration_minutes` 1..600. `PATCH` accepts any subset of the POST fields.

## Courses

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/courses` | | `200 [{id, code, name, is_muted, upcoming_count}]` |
| GET | `/courses/{id}` | | `200 CourseDetail` |
| PATCH | `/courses/{id}` | `{is_muted}` | `200 {id, code, name, is_muted, upcoming_count}` |

Only active enrollments are listed; `id` is the course id; `upcoming_count` counts the user's items from now on.

`CourseDetail`: `{course: {id, code, name}, is_muted, group_name, tutor_name, upcoming_items: [Item], lecture_schedules: [LectureSchedule]}`. `group_name` / `tutor_name` come from the Moodle sync (blank when unknown). `upcoming_items` are the user's items of the course from now to 30 days ahead, all types, same shape and order as `GET /items`; `lecture_schedules` are the user's schedules for the course. `404` unless the course is one of the requester's active enrollments. Items of one course in any range: `GET /items?course=<id>&from=&to=`.

## Reminder rules

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/reminder-rules` | | `200 Rule[]` (always 4, one per type) |
| PUT | `/reminder-rules/{type}` | `{offsets_minutes[], push_enabled, telegram_enabled}` | `200 Rule` |
| POST | `/reminder-rules/confirm-defaults` | | `204` (onboarding step 6) |
| PUT | `/items/{id}/reminders` | `{offsets_minutes[]}` | `200 Item` (creates/updates override) |
| DELETE | `/items/{id}/reminders` | | `204` (back to type rule) |

Validation: 1..5 offsets, each 5..20160 minutes, unique. `telegram_enabled` requires a linked Telegram (`telegram_not_linked`).

`Rule`: `{item_type: "quiz" | "tma" | "exam" | "lecture", offsets_minutes: [1440, 180], push_enabled, telegram_enabled}` (offsets are returned largest first). `{type}` in the path is the `item_type`; an unknown type is `404`.
New users get `telegram_enabled = false`; linking Telegram turns it on for quiz, TMA and exam (their defaults), unlinking turns it off for all types.

## Devices (FCM)

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/devices` | `{fcm_token, platform, app_version, os_version, model}` | `201` / `200` (upsert) `{id, platform, app_version, os_version, model, is_active, last_seen_at}` |
| DELETE | `/devices/{fcm_token}` | | `204` (deactivates the device) |

`platform`: `android` | `ios`. The token is never echoed back. A token already registered to another user moves to the current user.

## Telegram

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/telegram` | | `200 {linked, username, linked_at}` |
| POST | `/telegram/link` | | `200 {url, expires_at}` |
| DELETE | `/telegram` | | `204` unlink |
| POST | `/telegram/webhook` (public, secret header) | Telegram Update | `200` (`403 forbidden` if `X-Telegram-Bot-Api-Secret-Token` is wrong) |

`GET /telegram` when not linked: `{linked: false, username: null, linked_at: null}`. Invalid, expired or reused link tokens are answered by the bot in chat; the webhook still returns `200`.

## Notifications (history)

| Method | Path | Response |
|---|---|---|
| GET | `/notifications` | `200 {results: Notification[], next, previous}` (newest first; `next` is a full URL with `?cursor=`) |
| GET | `/notifications/unread-count` | `200 {count}` |
| POST | `/notifications/mark-read` | body `{ids?: []}` (empty = all) -> `204` |

`Notification`: `{id, kind, title, body, item_id, report_id, read_at, created_at}`.

## Support (reports)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/reports/categories` | | `200 [{code, label}]` (translated) |
| POST | `/reports` | multipart: `category, description, device_info (json), attachments[] (<=3 images, 5MB)` | `201 Report` |
| GET | `/reports` | | `200 Report[]` (mine) |
| GET | `/reports/{id}` | | `200 Report` with `replies[]` |
| POST | `/reports/{id}/replies` | `{body}` | `201` (user follow-up) |

`Report`: `{id, category, category_label, description, status, status_label, attachments: [url], replies: [{id, body, is_staff, created_at}], created_at}`.

- `category`: `reminder_not_received` | `wrong_date` | `login` | `telegram` | `other`. `status`: `new` | `in_progress` | `resolved` | `closed`.
- `POST /reports` accepts the files as `attachments` or `attachments[]` (JPEG, PNG or WEBP); `device_info` is a JSON object (a JSON string in multipart). A JSON body without files is also accepted. Limit: 10 reports per day per user (`429 throttled`).
- `POST /reports/{id}/replies` returns `201 {id, body, is_staff, created_at}`.
- Replies created through REST, the admin or the WebSocket are also broadcast live (below).
- Notification `data` payloads (FCM): reminder `{kind: "reminder", item_id, route: "/calendar?item=<id>"}`, report reply `{kind: "report_reply", report_id, route: "/reports/<id>"}`, broadcast `{kind: "broadcast", broadcast_id, route: "/notifications"}`, LMS expired `{kind: "system", route: "/login"}`.

### Real-time report chat (WebSocket)

Not part of the OpenAPI schema (drf-spectacular cannot describe it; the Swagger description links here).

- URL: `ws://<host>/ws/v1/reports/<report_id>/?token=<JWT access token>` (`wss://` behind HTTPS). The admin page uses the Django session cookie instead of `token` (only accepted when the `Origin` header matches `ALLOWED_HOSTS`).
- Access: the report owner or a staff user. The server accepts the handshake and then closes with:
  - `4401`: `token` missing, invalid or expired (or the user is inactive). Refresh the access token and reconnect.
  - `4403`: the report does not exist or belongs to someone else.
- Client -> server: `{"type": "message", "body": "<text>"}`. It goes through the same reply service as `POST /reports/{id}/replies` (a staff user posts a staff reply, which also pushes to the student). `body` is trimmed, 1..5000 characters.
- Server -> client, on a problem with a message (the socket stays open): `{"type": "error", "error": {"code": "validation_error", "message": "<translated>", "details": {"body": ["..."]}}}` (same envelope as REST; also for an unknown `type` or invalid JSON).
- Server -> every client of the thread (the sender included): `{"type": "reply.created", "reply": {"id", "body", "is_staff", "created_at"}}`. `reply` has exactly the shape of an element of `replies[]` in `GET /reports/{id}`. It is sent after the database commit, for replies from the WebSocket, `POST /reports/{id}/replies` and the admin. Clients should de-duplicate by `reply.id`.
- No history is sent on connect: load `GET /reports/{id}` first, then merge live replies.

## Meta

| Method | Path | Response |
|---|---|---|
| GET | `/meta/app` (public) | `{min_supported_version, latest_version, privacy_url, support_telegram, developer_name}` (`developer_name` from `APP_DEVELOPER_NAME`, empty by default) |
| GET | `/api/schema/` | OpenAPI 3 (drf-spectacular) |
