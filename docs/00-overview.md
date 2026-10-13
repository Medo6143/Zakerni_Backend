# 00 — Product Overview

## Name

| | |
|---|---|
| Arabic | ذكّرني |
| English | Zakerni |
| Telegram bot | `@ZakerniBot` (to be reserved) |
| Package id | `net.zakerni.app` (to be confirmed) |

## Problem

AOU Egypt students miss quizzes and TMA deadlines because the university LMS (Moodle, `egylms.arabou.edu.kw`) does not send reliable reminders, and exam/lecture schedules live outside the LMS.

## Solution (v1 — one feature)

**Reminders.** Nothing else.

| Item type | Source | Default reminders |
|---|---|---|
| Quiz | Synced from Moodle; the student can also add one manually (quiz dates published outside Moodle) | 1 day before, 3 hours before |
| TMA | Synced from Moodle | 3 days before, 1 day before |
| Exam (MTA / Final) | Entered by student | 3 days before, 1 day before |
| Lecture | Entered by student, repeats weekly until term end | 30 minutes before |

The student controls:

- Reminder offsets per item type (add/remove any number of offsets).
- Channels per item type: FCM push, Telegram, or both.
- Per-item override (custom offsets or mute one item).
- Per-course mute.

## Decisions log

| # | Decision | Why |
|---|---|---|
| D1 | Mobile app in **React Native (Expo dev build)** | Single codebase for Android and iOS |
| D2 | Backend **Django + DRF + Celery**, **PostgreSQL**, **Redis** | Server-side scheduling needed for Telegram and reliable push |
| D3 | Dev infra: **Postgres + Redis in Docker**, Django/Celery on host | Simple local setup |
| D4 | Login with **LMS credentials** only (no separate sign-up) | Zero friction; account created on first login |
| D5 | Use the **Moodle Web Service API** (`moodle_mobile_app`), not scraping | Stable and official |
| D6 | Store Moodle **token encrypted**, never the Moodle password | Security |
| D6a | Optional **SIS connection** (Settings): exam schedule and lecture timetable imported every 6 hours. The **SIS password is stored Fernet-encrypted** (the SIS has no long-lived token), never returned or logged, deleted on disconnect or account deletion | Product owner decision, accepted exception to the no-password rule |
| D7 | Exams and lectures are **entered by the student**; quizzes can also be added manually | Not available in the LMS (some quiz dates are published outside Moodle) |
| D8 | Push via **FCM** (`@react-native-firebase/messaging`, `firebase-admin`) | Requirement |
| D9 | Telegram via bot + deep-link account linking | No manual chat id copying |
| D10 | All reminders **scheduled and sent by the server** | One source of truth for both channels |
| D11 | Admin panel = **Django Admin with Unfold theme** | Fast, supports Arabic/RTL |
| D12 | Admin v1: reports management, broadcast, statistics | Scope |
| D13 | Calendar is the home tab (3 tabs: Calendar, Reminders, Settings) | Scope |
| D14 | Item details in a **bottom sheet**; one add/edit form for exam+quiz+lecture | UX |
| D15 | Extra v1 screens: courses, per-item reminder, notification history, about & privacy | Scope |
| D16 | Theme follows device (light/dark), overridable in settings | UX |
| D17 | Brand: **indigo**, logo = bell + the letter ذ | Brand |
| D18 | 3 intro onboarding slides + animated splash | UX |
| D19 | **No emoji anywhere** (UI, notifications, Telegram, docs, code) | Product rule |
| D20 | Docs and code in English; product copy in Arabic and English | Convention |

## Open questions / risks

| # | Item | Status |
|---|---|---|
| R1 | Is the Moodle mobile web service enabled on `egylms.arabou.edu.kw`? Test by logging in with the official Moodle app. | **Blocker for Phase 1** |
| R2 | Moodle token lifetime at AOU (tokens usually do not expire, but password change invalidates them). | Handle `invalidtoken` -> ask user to re-login |
| R3 | Holding tokens (and, for students who connect the SIS, encrypted SIS passwords) for many students is sensitive. Privacy policy must be explicit. | Covered by About & Privacy screen and the SIS screen text; SIS is opt-in and can be disconnected at any time |
| R4 | The SIS API is undocumented (contract read from its public web client). It can change without notice. | Defensive client: unknown fields skipped, shape mismatches logged and recorded as a sync error |
| R4 | The app is unofficial. Do not use the university logo or colours. | Enforced by brand |

## Out of scope for v1

Grades, announcements, forum, file downloads, chat, web version, email reminders, sharing between students, AI features.
