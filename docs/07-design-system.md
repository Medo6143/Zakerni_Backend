# 07 — Design System, Logo, Splash and Onboarding

Live preview of the logo, splash animation and onboarding: `brand/preview.html` (open in a browser).

## 1. Principles

1. **Calm, not noisy.** One accent colour, generous spacing, the next deadline always obvious.
2. **Bilingual by default.** Every layout is designed in Arabic (RTL) first, then checked in English.
3. **No emoji.** Icons (`lucide-react-native`) and colour tokens carry meaning. Colour is never the only signal: every type also has an icon and a label.

## 2. Logo

| File | Use |
|---|---|
| `brand/logo-icon.svg` | App icon (store, launcher), social avatar, Telegram bot avatar |
| `brand/logo-mark.svg` | Indigo mark on light backgrounds (About screen, admin header) |
| `brand/logo-mark-white.svg` | White mark on indigo/dark backgrounds (splash) |

**Concept:** a bell (reminder) with the Arabic letter **ذ** (first letter of ذكّرني) cut into it. The amber circle is both a notification badge and a nod to the dot of ذ, so the mark reads as "a reminder is waiting".

Rules:

- Minimum size: 24 px (mark), 48 px (icon).
- Clear space: at least the badge diameter on every side.
- Do not recolour the badge, rotate, add shadows, or place the white mark on light backgrounds.
- Wordmark: "ذكّرني" in IBM Plex Sans Arabic Bold, "Zakerni" in IBM Plex Sans Arabic SemiBold with 0.5 px tracking. Convert to outlines for final exports.
- Android adaptive icon: foreground = white mark on transparent (66% safe zone), background = `#4F46E5`.

## 3. Colour tokens

### Brand and neutrals

| Token | Light | Dark |
|---|---|---|
| `primary` | `#4F46E5` | `#818CF8` |
| `primaryPressed` | `#4338CA` | `#6366F1` |
| `primarySoft` (chips, selected day) | `#EEF2FF` | `#1E1B4B` |
| `onPrimary` | `#FFFFFF` | `#0B0B1A` |
| `accent` (badge, unread) | `#F59E0B` | `#FBBF24` |
| `background` | `#F8FAFC` | `#0B0B14` |
| `surface` (cards, sheets) | `#FFFFFF` | `#151522` |
| `surfaceAlt` | `#F1F5F9` | `#1E1E2E` |
| `border` | `#E2E8F0` | `#2A2A3C` |
| `text` | `#0F172A` | `#F1F5F9` |
| `textMuted` | `#64748B` | `#94A3B8` |
| `success` | `#16A34A` | `#4ADE80` |
| `warning` | `#D97706` | `#FBBF24` |
| `danger` | `#DC2626` | `#F87171` |

Derived tokens for the hero layout (built from the palette above; existing values never change):

| Token | Light | Dark | Use |
|---|---|---|---|
| `hero` | `#4F46E5` (= `primary`) | `#1E1B4B` (= dark `primarySoft`, deep indigo) | Hero header band, avatar |
| `onHero` | `#FFFFFF` | `#F1F5F9` | Title, icons on the hero |
| `onHeroMuted` | white at 80% | `#F1F5F9` at 75% | Eyebrow, subtitle on the hero |
| `heroTint` | white at 16% | `#818CF8` at 22% | Icon buttons, chips and segmented control on the hero |
| `cardBorder` | `#E2E8F0` at 60% | `#2A2A3C` (= `border`) | Hairline edge of every card (carries the lift in dark mode) |

### Item types (single registry `itemTypeMeta`)

| Type | Icon (lucide) | Light | Dark | Label AR / EN |
|---|---|---|---|---|
| quiz | `FileQuestionMark` (formerly `FileQuestion`) | `#7C3AED` | `#A78BFA` | كويز / Quiz |
| tma | `FileUp` | `#0D9488` | `#2DD4BF` | TMA / TMA |
| exam | `GraduationCap` | `#E11D48` | `#FB7185` | امتحان / Exam |
| lecture | `Presentation` | `#0284C7` | `#38BDF8` | محاضرة / Lecture |

Each type also has a `*Soft` background at 12% opacity for rows and badges.

## 4. Typography

Font: **IBM Plex Sans Arabic** (covers Arabic and Latin with matching metrics). Weights: 400, 500, 600, 700.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `display` | 28 / 36 | 700 | Onboarding titles |
| `title` | 22 / 30 | 700 | Screen titles |
| `heading` | 17 / 26 | 600 | Card titles, sheet title |
| `body` | 15 / 24 | 400 | Default text |
| `bodyStrong` | 15 / 24 | 600 | Item titles |
| `caption` | 13 / 20 | 500 | Meta: course, time |
| `micro` | 11 / 16 | 600 | Badges, tab labels |

Arabic needs taller line height than Latin; the values above already account for it. Respect system font scaling up to 1.3x.

## 5. Spacing, radius, elevation

- Spacing scale (4 pt): `xs 4, sm 8, md 12, lg 16, xl 24, 2xl 32, 3xl 48`. Screen side padding: 16.
- Radius: `sm 8` (chips, small icon tiles), `md 12` (inputs, icon tiles), `lg 16` (item cards, stat tiles), `xl 24` (floating cards, bottom sheet top, tab bar top), `2xl 32` (hero bottom corners), `full` (pills, FAB, avatar).
- Elevation: `sm` (item cards, notification and course rows), `card` (floating cards: indigo-tinted soft shadow, radius 16, offset 6), `raised` (FAB, bottom sheet, tab bar). Shadows apply in light mode only; in dark mode every card keeps `surface` plus a `cardBorder` hairline.
- Sizes added for the hero layout: `heroOverlap 40` (how far the first floating card overlaps the hero), `iconTile 44` / `iconTileSm 32`, `avatar 56`, `heroMark 64` (logo on Login), `tabPillWidth 56` / `tabPillHeight 32`, `tabBarHeight 68`, `iconStroke 2` / `iconStrokeActive 2.5`.
- Touch targets: minimum 44 x 44.

## 5a. Hero header + floating cards

Every tab and secondary screen (not the splash or the intro pager) uses the same layout:

- **Hero** (`HeroHeader`, passed as `Screen`'s `hero` prop): an edge-to-edge `hero` band that runs under the status bar (light status bar icons), with `2xl` rounded bottom corners. Title in `onHero` (`title`, or `display` with `size="large"`), optional `eyebrow` above and `subtitle` below in `onHeroMuted`, optional back button, actions at the end of the title row followed by the pinned actions (the tab bell), optional `top` content (logo on Login, icon on Language) and `children` (month navigation, filter pills). The offline banner sits at the bottom of the hero. Controls inside the hero (`IconButton`, `Chip`, `SegmentedControl`) read `HeroContext` and switch to `onHero` / `heroTint` automatically.
- **Floating cards**: with `overlap` on both `HeroHeader` and `Screen`, the content is pulled up by `heroOverlap` so the first `Card floating` sits over the hero bottom. `floating` = `surface`, radius `xl`, `lg` padding, `cardBorder` hairline, `elevation.card` in light mode.
- Home: large hero with the date (eyebrow), a time-of-day greeting with the first name ("Good morning, Mohamed"; morning 05:00-11:59, afternoon 12:00-16:59, evening otherwise, in the user's timezone via `dayPeriod` in `shared/lib/dates`, Intl-based) and "You have N items today". The floating card holds one `StatTile` per item type (next 7 days, from `itemTypeMeta`).
- Calendar: hero with month title, previous/next and Today; the month grid is the floating card. Upcoming: hero with the week range and the type filter as pills on the hero. Reminders: rule cards are floating cards with an `IconTile` header. Settings: profile card (initials avatar, name, student id, LMS status, Sync now) floating over the hero, then grouped floating sections whose rows lead with a primary `IconTile`. Login: large hero with the static logo mark, the form in a floating card.
- **Bottom tab bar**: `surface` bar with `xl` top corners, `raised` shadow and an active `primarySoft` pill behind the active icon (`TabBarIcon`).

## 5b. Admin panel (Unfold)

The Django admin (django-unfold) is themed to match the app. No logic changed, only visuals.

- Palette: the app tokens from `tokens.ts` (light and dark) are mirrored as CSS variables in `backend/static/admin/zakerni.css`. Primary indigo `#4F46E5` (dark `#818CF8`), accent amber `#F59E0B`, type colours quiz `#7C3AED`, TMA `#0D9488`, exam `#E11D48`, lecture `#0284C7`; dark surfaces `#0B0B14` / `#151522` / `#1E1E2E`.
- Shapes: 16px cards with the soft indigo shadow, pill buttons / filters / sidebar items, indigo gradient hero (dashboard, login, sidebar header) using the unmodified white logo mark.
- Font: IBM Plex Sans Arabic 400/500/600/700 for both languages (`backend/static/fonts`, SIL OFL licence in `OFL.txt`), with a system fallback stack.
- RTL: Unfold ships physical margins, so the CSS flips them under `[dir="rtl"]`.
- Dashboard: KPI cards with a type-coloured accent, quick actions row, 14-day chart (indigo = sent, amber = failed).
- Changing the primary colour: edit the `UNFOLD["COLORS"]["primary"]` scale (rgb triplets, 600 is the brand shade) in `backend/config/settings/base.py` and the `--zk-primary*` variables at the top of `zakerni.css`. The logo artwork is never recoloured.

## 6. Core components (`shared/ui`)

`Screen` (`hero`, `overlap`), `HeroHeader`, `IconTile`, `StatTile`, `RelativeTimeChip`, `Text`, `Button` (primary / secondary / ghost / danger, loading state), `IconButton`, `Card`, `Chip` (selectable, removable), `Switch`, `SegmentedControl`, `TextField` (label, error, secure toggle), `Select` (sheet-based), `DateTimeField`, `WeekdayPicker`, `Badge`, `StatusPill`, `EmptyState`, `ErrorState`, `Skeleton`, `Banner`, `Sheet`, `FAB`, `ItemRow`, `RuleCard`, `OffsetChips`.

`ItemRow` anatomy (LTR shown, mirrored in RTL): a card (`surface`, radius `lg`, `cardBorder`, `elevation.sm`).

```
┌───────────────────────────────────────────────┐
│ [ic]  Quiz 2 closes                  10:00 PM │
│       MT129 Calculus                          │
│       (clock in 5 hours) (status pill)        │
└───────────────────────────────────────────────┘
 type IconTile  bold title + time, course, RelativeTimeChip + ItemStatusPill
```

Cancelled items keep the strikethrough title; past items are dimmed.

## 7. Motion

| Token | Duration | Easing | Use |
|---|---|---|---|
| `fast` | 150 ms | ease-out | Press states, toggles |
| `base` | 250 ms | ease-in-out | Screen elements, chips |
| `sheet` | spring (damping 18, stiffness 180) | | Bottom sheet |
| `emphasis` | spring (damping 10, stiffness 140) | | Badge pop, FAB |

Respect "Reduce motion": skip the bell swing and slide transitions, use cross-fades only.

## 8. Splash animation

Two stages, so there is no white flash:

1. **Native static splash** (`expo-splash-screen`): background `#4F46E5`, white mark centred at 120 px. Shown while JS loads.
2. **Animated splash** (`/splash`, Reanimated), same background and mark position, so the hand-off is invisible.

Timeline (total about 1.6 s):

| Time | Element | Animation |
|---|---|---|
| 0 - 400 ms | Mark | scale 0.7 -> 1.0 (spring), opacity 0 -> 1 |
| 350 - 1050 ms | Bell | swing around the top knob: rotate -14, +10, -6, +3, 0 degrees |
| 700 - 950 ms | Badge | scale 0 -> 1.15 -> 1.0 (`emphasis` spring) |
| 950 - 1350 ms | Wordmark | "ذكّرني" then "Zakerni" fade in + translateY 12 -> 0, 80 ms stagger |
| 1350 - 1600 ms | Whole | hold, then cross-fade to next route (session check runs in parallel) |

If the session check takes longer, keep the final frame (no looping). If it finishes early, still wait for the animation (max 1.6 s).

## 9. Onboarding (3 intro slides)

Layout: illustration (top 55%), title (`display`), body (`body`, `textMuted`), page dots, primary button. "Skip" at the top end. Swipe between slides; the button reads "Next" then "Get started" on the last slide. Illustrations are built from app components (cards, chips, icons), not stock art, so they match both themes.

| # | Illustration | Title AR | Title EN | Body AR | Body EN |
|---|---|---|---|---|---|
| 1 | Stack of item rows (quiz, TMA, exam, lecture) | كل مواعيدك في مكان واحد | All your deadlines in one place | تُجمع الكويزات والـ TMA تلقائيًا من الـ LMS، وتضيف أنت امتحاناتك ومحاضراتك. | Quizzes and TMAs sync from the LMS automatically. Add your exams and lectures yourself. |
| 2 | Clock with offset chips (قبلها بيوم، قبلها بـ 3 ساعات، +) | أنت تحدد وقت التذكير | You choose when | اختر متى نذكّرك لكل نوع: قبلها بيوم، بثلاث ساعات، أو أي وقت يناسبك. | Pick your reminder times for each type: a day before, three hours before, or whatever suits you. |
| 3 | Phone notification card + Telegram message bubble | لن يفوتك موعد بعد اليوم | Never miss a deadline again | يصلك التذكير إشعارًا على هاتفك وعلى تليجرام. | Get reminders as phone notifications and on Telegram. |

Slide transition: illustration parallax (moves at 0.6x swipe speed), text cross-fade, dots animate width 8 -> 24 for the active one.
