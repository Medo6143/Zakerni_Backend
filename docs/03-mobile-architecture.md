# 03 — Mobile Architecture (React Native)

Feature-based structure with clean layering. Expo SDK (latest) with a **development build**, TypeScript strict.

## 1. Layers

```
app/ (Expo Router routes)       thin: render a screen
      │
features/<name>/screens          compose components + hooks
      │
features/<name>/hooks            logic, TanStack Query / Zustand
      │
features/<name>/api              HTTP calls + DTO -> model mapping
      │
shared/lib (http, storage, notifications, duration: hours/minutes parsing incl. Arabic digits + shared duration labels)  abstractions over libraries
```

Rules:

- Components never call `fetch`/`axios` or storage directly.
- Screens do not contain business logic; they wire hooks to components.
- `shared/` never imports from `features/`. Features may import from `shared/` and from another feature's **public** `index.ts` only.

## 2. Folder structure

```
mobile/
├── app.config.ts                 # env-based config, RTL support, plugins (firebase, splash)
├── app/                          # Expo Router
│   ├── _layout.tsx               # renders src/providers (AppProviders + RootStack)
│   ├── index.tsx                 # redirect by session/onboarding state (resolveLaunchRoute)
│   ├── splash.tsx                # animated splash (played once per app start, then back to index)
│   ├── (onboarding)/
│   │   ├── language.tsx
│   │   ├── intro.tsx             # 3 slides
│   │   ├── login.tsx             # ?username= prefill after LMS token expiry
│   │   ├── allow-notifications.tsx  # screen 5 (not /notifications: that URL is the history)
│   │   ├── connect-telegram.tsx     # screen 6 in onboarding mode (not /telegram: Settings uses it)
│   │   └── defaults.tsx
│   └── (app)/                    # signed-in group: SessionGate + profile sync + FCM + push taps
│       ├── _layout.tsx
│       ├── (tabs)/
│       │   ├── _layout.tsx       # bottom tabs
│       │   ├── calendar.tsx      # ?item=<id> opens the item sheet
│       │   ├── upcoming.tsx      # current week (Sat-Sat), All + one tab per item type
│       │   ├── reminders.tsx
│       │   └── settings.tsx
│       ├── course/[id].tsx       # course detail (tutor, mute, upcoming by type, lecture times)
│       ├── item/new.tsx          # add (exam | lecture), ?date=yyyy-MM-dd
│       ├── item/[id]/edit.tsx
│       ├── item/[id]/reminders.tsx   # per-item override
│       ├── courses.tsx
│       ├── notifications.tsx     # history
│       ├── telegram.tsx
│       ├── reports/new.tsx
│       ├── reports/index.tsx
│       ├── reports/[id].tsx
│       └── about.tsx
└── src/
    ├── providers/                # composition root: container.ts (only place that knows axios,
    │                             # expo-secure-store, AsyncStorage, Moodle client, expo-crypto), AppProviders, RootStack, useBootstrap
    ├── test/                     # test helpers (renderWithProviders, fake axios adapter)
    ├── features/
    │   ├── auth/            {api, hooks, screens, store/session.ts, types.ts, index.ts}
    │   ├── onboarding/      {screens, components/IntroSlide.tsx, hooks, lib/resolveLaunchRoute.ts, store/launch.ts}
    │   ├── home/            {screens}  # tabs layout + signed-in layout (SessionGate, app-wide effects)
    │   ├── calendar/        {hooks/useCalendarItems.ts, lib/calendarGrid.ts, components/{MonthGrid, DayCell, DayList, ItemRow, ItemSheet}, screens}
    │   ├── upcoming/        {hooks/useUpcomingItems.ts, lib/{upcomingSections.ts, upcomingRange.ts}, components/UpcomingDayGroup, screens}  # reuses ItemRow, ItemSheet from calendar
    │   ├── items/           {api (items, lectures), lib/{itemTypeMeta.ts, teamsLink.ts}, hooks, components/{ItemForm, itemKindForms.ts (per-kind fields registry)}, schemas/itemForm.ts, screens}
    │   ├── reminders/       {api, lib/offsets.ts, hooks, components/{RuleCard, OffsetChips, ChannelToggles}, screens}
    │   ├── courses/         {api, hooks/{useCourses, useCourseDetail, useToggleCourseMute}, lib/lectureTimes.ts, components/{CourseRow, TutorCard, CourseItemsSection, LectureTimes}, screens/{CoursesScreen, CourseDetailScreen}}
    │   ├── announcements/   {api (zod dto -> camelCase, cursor pages), hooks/useAnnouncements (useInfiniteQuery, `course` filter), components/{AnnouncementCard, NewsSection, LatestNewsCard}, screens/CourseNewsScreen}
    │   ├── notifications/   {api (history, devices), hooks, lib/deepLinks.ts, screens}
    │   ├── telegram/        {api, hooks, screens}
    │   ├── support/         {api, lib/{attachments, replyCache, chatEvents}.ts, hooks (useReportChat: live thread), components, schemas, screens}
    │   └── settings/        {api/metaApi.ts, store/preferences.ts, hooks, components/{AboutFeatures, AboutUnofficial, AboutPrivacy, AboutContact}, screens (Settings, About)}
    └── shared/
        ├── ui/              # Button, IconButton, Text, Card, Chip, Switch, Screen, ScreenHeader, EmptyState,
        │                    # ErrorState, DataState, Skeleton, Banner, OfflineBanner, Badge, StatusPill,
        │                    # SegmentedControl, Sheet, Select, DateTimeField, WeekdayPicker, FAB, ListRow
        ├── theme/           # tokens.ts (colors, spacing, radius, typography), ThemeProvider, useTheme
        ├── i18n/            # i18next setup, locales/{ar,en}.json, rtl.ts
        ├── lib/
        │   ├── http/        # HttpClient interface + axios implementation, auth refresh interceptor
        │   ├── storage/     # KeyValueStorage interface + expo-secure-store / AsyncStorage / memory implementations
        │   ├── dates/       # formatting in user tz (date-fns + date-fns-tz), day keys, picker conversions
        │   ├── device/      # DeviceInfo interface + expo-device implementation (reports, /devices)
        │   ├── notifications/ # PushService interface + Firebase Messaging / Notifee implementation
        │   ├── media/       # ImagePickerService interface + expo-image-picker implementation
        │   ├── realtime/    # RealtimeClient interface + native WebSocket implementation (reconnect, backoff, 4401/4403)
        │   ├── network/     # useIsOnline (TanStack onlineManager, fed by NetInfo)
        │   └── validation/  # zod message keys + useFieldError
        └── config/          # env, storage keys, query keys
```

## 3. SOLID in the app

- **S:** `ItemSheet` renders; `useItemActions(item)` holds mute/override/delete logic; `itemsApi` does HTTP.
- **O:** item-type visuals come from one map `itemTypeMeta[type] = { icon, colorToken, labelKey }`. Adding a type touches only this map.
- **L:** `HttpClient` interface has an axios implementation and a mock implementation for tests; both behave the same.
- **I:** hooks return narrow objects (`{ items, isLoading, refetch }`), not whole stores.
- **D:** features receive `HttpClient` (via `useHttp()`) and `KeyValueStorage` (via `getSecureStorage()` / `getLocalStorage()`) from `shared/lib`, never import `axios`, `expo-secure-store` or AsyncStorage directly (enforced by ESLint `no-restricted-imports`). The same applies to push (`getPush()`), device info (`getDeviceInfo()`), the image picker (`getImagePicker()`), the live channel (`getRealtime()`) and connectivity (`useIsOnline()`): Firebase, Notifee, expo-device, expo-application, expo-image-picker and NetInfo are imported only by `src/providers/container.ts` (and by `jest.setup.ts`, which wires the same adapters over native-module mocks). The concrete implementations are wired in `src/providers/container.ts`.
- **LMS on the device:** Moodle returns 403 to datacenter IPs, so the phone talks to Moodle itself, and only after the student optionally connects the university (Settings or the Home call to action). `shared/lib/lms` defines the `LmsClient` interface (`login`, `siteInfo`, `inProgressCourses`, `quizzes`, `assignments`, `calendarEvents`, `announcements`, `courseUserGroups`, `groupMembers`) and `LmsError` (`invalid_credentials`, `unavailable`, `token_expired`); the Moodle implementation (`moodleLmsClient.ts`) uses a **separate** `HttpClient` for the Moodle origin (`EXPO_PUBLIC_MOODLE_URL`) and is wired only in `container.ts`. `FakeLmsClient` is the test double. Course news: `announcements(token, courseIds)` reads `mod_forum_get_forums_by_courses`, keeps forums of type `news` (or whose name contains "announce"), then `mod_forum_get_forum_discussions` (20, newest first) with `mod_forum_get_forum_discussions_paginated` as fallback; a denied function returns `[]` and a failing lookup never fails the sync (`fetchSnapshot` only rethrows an expired token). The sync posts the newest 100 across all courses (by `time_modified`) as the optional upsert-only `announcements` key of `POST /me/lms/ingest`. `features/announcements` reads them back with `GET /announcements` (cursor pages, `course` filter) and the query keys under `queryKeys.announcements` are invalidated by `invalidateItemData` and after every sync. The Moodle token lives in secure storage (`getMoodleToken` / `saveMoodleToken` / `clearMoodleToken`); the password is dropped after the token call. `features/lms` owns the connection: `useLmsStatus` (`GET /me/lms`, `connected` flag), `useConnectLms` (password -> Moodle token -> site info -> `POST /me/lms/connect` -> save the token only after the backend accepted -> first sync), `useDisconnectLms` (`DELETE /me/lms` + clear the token) and `ConnectLmsScreen`. Sync (`useLmsSync` for pull to refresh and "Sync now", `useAutoLmsSync` on open and foreground, at most once per 10 minutes) goes through `syncIfConnected`: it does nothing (no errors, no banners) while `connected` is false, and `POST /me/lms/ingest` is only called for a connected account. A missing or rejected token on a connected account reports `lms_status: "expired"` and the app asks to reconnect (the connect screen). `features/auth` owns the app account (`authApi`: `register`, `signin`, `changePassword`, `refresh`, `logout`; `AuthScreen` with Sign in / Create account modes; `ChangePasswordScreen`). `change-password` returns a fresh token pair that is stored in the session. SIS on the device: `shared/lib/sis` defines `SisClient` (`login`, `schedule`) and `SisError` (`invalid_credentials`, `unavailable`); `httpSisClient.ts` (wired only in `container.ts`, own `HttpClient` for `EXPO_PUBLIC_SIS_URL`) ports the backend parser, sends the raw token plus a base64 `stdtoken` with integer year/semester, and reads the current academic session first (best effort). The SIS has no long-lived token, so the username and password are kept in secure storage on the phone only (`saveSisCredentials` / `getSisCredentials`) and never sent to the backend. `features/sis` connects with `useSisActions` (sign in and read the schedule, `POST /me/sis/ingest`, keep the credentials only after the backend accepted), syncs on open and foreground with `useAutoSisSync` (at most once per 10 minutes, silent failures) and from the screen (`Sync now`), and disconnects with `DELETE /me/sis` plus clearing the phone. A password the SIS rejects is dropped (the username stays) and the screen asks for the new one. All behind `EXPO_PUBLIC_SIS_ENABLED`.
- **Realtime:** `shared/lib/realtime` exposes `RealtimeClient.connect(path, {onMessage, onStatusChange}) -> {send, close}`. The native `WebSocket` implementation (works in Expo Go too) connects to `<API origin with ws/wss><path>?token=<access>`, reconnects with exponential backoff (1 s doubling, max 30 s), on close 4401 refreshes the token once through the session auth handler and reconnects, and on 4403 stops for good. `send` returns false when the socket is not open, which is how `useReportChat` falls back to `POST /reports/{id}/replies`. Incoming `reply.created` frames are merged into the cached report (deduped by id); after a reconnect the report is refetched.
- **Token refresh:** `shared/lib/http/authRefresh.ts` attaches the bearer token and, on 401, runs one shared refresh through an `AuthHandler` supplied by the auth feature (`createSessionAuthHandler`). A rejected refresh (400/401/403 from `/auth/refresh`) clears the session; transient failures keep it.

## 4. State

| Kind | Tool | Examples |
|---|---|---|
| Server state | TanStack Query | items, rules, courses, reports, notifications |
| Session | Zustand + SecureStorage | access/refresh tokens, user |
| Preferences | Zustand + AsyncStorage | language, theme, onboarding done |
| Forms | react-hook-form + zod | item form, report form |

Query keys live in `shared/config/queryKeys.ts`.

## 5. Libraries

| Purpose | Library |
|---|---|
| Routing | `expo-router` |
| Server state | `@tanstack/react-query` |
| Client state | `zustand` |
| HTTP | `axios` (wrapped) |
| Forms | `react-hook-form`, `zod`, `@hookform/resolvers` |
| Calendar | custom month grid (`calendar/lib/calendarGrid.ts` + `MonthGrid`) instead of `react-native-calendars`: full control of RTL, theme tokens and the Saturday week start |
| Bottom sheet | `@gorhom/bottom-sheet` |
| Animation | `react-native-reanimated`, `react-native-gesture-handler` |
| Icons | `lucide-react-native` + `react-native-svg` |
| i18n | `i18next`, `react-i18next`, `expo-localization` |
| Push | `@react-native-firebase/app`, `@react-native-firebase/messaging`, `@notifee/react-native` (foreground display) |
| Secure storage | `expo-secure-store` |
| Splash | `expo-splash-screen` (static) + custom animated screen |
| Images (reports) | `expo-image-picker` |
| Dates | `date-fns`, `date-fns-tz`; `@react-native-community/datetimepicker` for date/time fields |
| Connectivity | `@react-native-community/netinfo` (feeds TanStack `onlineManager`) |
| Plurals | `intl-pluralrules` polyfill (Arabic plural forms in i18next on Hermes) |
| Fonts | `@expo-google-fonts/ibm-plex-sans-arabic` |
| Quality | `eslint`, `prettier`, `typescript`, `jest`, `@testing-library/react-native` |

## 6. RTL and language

- On language change: `i18n.changeLanguage`, `I18nManager.forceRTL(lang === 'ar')`, then `reloadAppAsync()` from `expo` (RTL needs a reload; this works in dev and release builds without `expo-updates`). Tell the user before reloading. Helpers live in `shared/i18n/rtl.ts`.
- All layout uses logical properties (`marginStart`, `paddingEnd`, `start`, `end`).
- Directional icons (chevrons, back) are flipped with a `useIsRTL()` helper.
- Numbers: Western digits in both languages (clearer for times and course codes).

## 7. Notifications in the app

- The system permission prompt is shown only after "Allow" on the explanation screen (onboarding step 5). On login and on every app start (when the signed-in layout mounts): if permission is granted, get the FCM token and `POST /devices`; re-register on token refresh. Logout sends the current token as `fcm_token`.
- Foreground messages: shown with Notifee (Android channel "Reminders"); history and unread count are refetched.
- Tap on notification (background, quit, foreground): the target is built from `data.kind` and the ids (`notifications/lib/deepLinks.ts`), never from an arbitrary `data.route`. Reminder -> `/calendar?item=<id>` opens the item sheet on the item's day. Report reply -> `/reports/<id>`. Broadcast -> `/notifications`. LMS expired -> `/login`.
- Without `google-services.json` / `GoogleService-Info.plist` the Firebase plugins are left out of the build (see `mobile/README.md`); the push service then reports "not supported" and the rest of the app works.
