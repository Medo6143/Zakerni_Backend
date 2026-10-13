# تكامل تطبيق Zakerni مع نظام معلومات الطلاب (SIS)

## SIS integration proposal — Arab Open University, Egypt

هذا المستند موجّه إلى إدارة تقنية المعلومات بالجامعة. يشرح كيف يقترح تطبيق Zakerni
قراءة جدول الطالب ومواعيد امتحاناته من نظام SIS، والبيانات المطلوبة بالتحديد،
وطريقة الوصول الرسمية المطلوبة من الجامعة.

This document is addressed to the university IT department. It explains how the
Zakerni app proposes to read a student's class schedule and exam dates from the
SIS, exactly which data it needs, and the official access method requested.

---

## 1. ما هو التطبيق — What the app is

Zakerni (ذكّرني) تطبيق موبايل يذكّر طلاب الجامعة العربية المفتوحة (فرع مصر)
بمواعيد الكويزات والـ TMA والامتحانات والمحاضرات، عبر إشعارات Push وتيليجرام،
بالعربية والإنجليزية.

- الكويزات والـ TMA تُزامَن تلقائيًا من نظام Moodle (`egylms.arabou.edu.kw`).
- مواعيد الامتحانات وجداول المحاضرات هي ما نرغب في قراءته من SIS.
- الطالب يتحكم في مواعيد التذكير لكل نوع ولكل مادة.

## 2. البيانات المطلوبة فقط — Data requested (only this)

نطلب الحد الأدنى اللازم للتذكيرات، ولا نطلب أي بيانات شخصية أو مالية:

| الغرض | الحقول المطلوبة |
|---|---|
| جدول المحاضرات | كود المادة، اسم المادة، اليوم، وقت البداية والنهاية، القاعة/الرابط، اسم المحاضر، إن كانت أونلاين |
| مواعيد الامتحانات | المادة، التاريخ، الوقت، القاعة |
| الفصل الدراسي الحالي | السنة والفصل الأكاديمي الحالي |

**لا نطلب** بيانات الهوية، ولا العناوين، ولا الأرقام القومية، ولا أي بيانات مالية.

## 3. نقاط النهاية التي اطّلعنا عليها — Endpoints observed

تمت دراسة هذه النقاط من واجهة الويب العامة للنظام (`https://sisegy.arabou.edu.kw/SPAPIEGY`):

| الغرض | الطلب |
|---|---|
| تسجيل الدخول | `POST /api/Student/GetStudentByCredentials` body `{Username, Password}` |
| الفصل الدراسي الحالي | `GET /api/AcademicSession/GetCurrentWebRegistrationAcademicSessions` |
| جدول الطالب | `GET /api/StudentSchedule/GetStudentSchedules?sessionId=<studentId>_<timestamp>` |

- بعد تسجيل الدخول يرسل الموقع ترويسات `Authorization` و `stdtoken` مع كل طلب،
  إضافة إلى كوكي جلسة (`_spaoutkn`).
- استجابة الجدول تحتوي على صفوف بنوع الحدث (`Event_Type`: 1 محاضرة، 2 امتحان).

### 3.1 شكل الطلب والرد — Request / response shapes

القيم أدناه وهمية للتوضيح فقط. The values below are illustrative placeholders.

**تسجيل الدخول — Login**

```
POST /api/Student/GetStudentByCredentials
Content-Type: application/json

{ "Username": "<student-id>", "Password": "<password>" }
```

الرد عند النجاح (الحقول المهمة فقط) — successful response (relevant fields only):

```json
{
  "Id": "<student-id>",
  "IsValid": true,
  "Token": "<session-token>",
  "TokenExpiryDate": "2026-10-02T12:38:40Z",
  "AcademicYear": 2026,
  "AcademicSem": 1,
  "StudentSharedInfo": { "StudentId": "<student-id>", "BranchId": 5, "CenterId": 51 }
}
```

عند فشل الدخول ترجع نفس البنية بكل الحقول فارغة و `"IsValid": false`.
On failure the same structure is returned with empty fields and `"IsValid": false`.

**جدول الطالب — Student schedule**

```
GET /api/StudentSchedule/GetStudentSchedules?sessionId=<student-id>_<yyyyMMddHHmmssSSS>
Authorization: <token-from-login>
stdtoken: <base64 of {"StudentId","AcademicYear","AcademicSem"}>
Cookie: _spaoutkn=<session-cookie>
```

الرد قائمة من الصفوف، كل صف محاضرة أو امتحان (الحقول المتوقّعة) —
the response is a list of rows, each a lecture or an exam (expected fields):

```json
[
  {
    "Event_Type": "1",
    "CourseCode": "M110",
    "CourseName": "Python Programming",
    "Day": "Saturday",
    "StartTime": "12:30",
    "EndTime": "14:30",
    "Room": "Lab 2 / Teams link",
    "Instructor": "Dr. ...",
    "Date": null
  },
  {
    "Event_Type": "2",
    "CourseCode": "M110",
    "CourseName": "Python Programming",
    "Date": "2027-01-15",
    "StartTime": "09:00",
    "Room": "Hall A"
  }
]
```

ملاحظة: الأسماء الدقيقة لحقول الجدول تحتاج تأكيدًا من فريق الجامعة، فهي غير موثّقة
رسميًا. The exact schedule field names need confirmation from the university team,
as they are not officially documented.

## 4. المشكلة الحالية — The current situation

النظام مُهيّأ عمدًا لمنع الوصول من خارج متصفح الويب الرسمي للجامعة
(`disableDevTools`، ورفض الطلبات غير القادمة من جلسة المتصفح). وهذا سلوك صحيح
أمنيًا من جانب الجامعة. لذلك **لن نحاول تجاوز هذه الحماية**، وننتظر وصولًا رسميًا.

## 5. المطلوب من الجامعة — What we request

أيٌّ من الخيارات التالية يكفي لتفعيل التكامل بشكل آمن ورسمي:

1. **مفتاح API مخصّص للتطبيق** (API key / client credentials) لقراءة الجدول
   والامتحانات فقط.
2. **إضافة عنوان خادم التطبيق إلى قائمة السماح** (IP allowlist) مع توثيق طريقة
   المصادقة المقبولة من الخادم. عنوان الخادم الحالي على Railway:
   `web-production-a871f.up.railway.app`.
3. **توثيق رسمي** لطريقة الوصول إلى الـ API من تطبيق خارجي معتمد.

## 6. الخصوصية والأمان — Privacy and security

- كلمات مرور Moodle لا تُخزَّن إطلاقًا؛ تُستخدم مرة واحدة للحصول على رمز ثم تُحذف.
- التوكنات تُخزَّن مشفّرة (Fernet)، ولا تظهر في أي واجهة أو سجل.
- التطبيق سيكون **خاصًا بالجامعة**، تحت إشرافها.
- كل الاتصالات عبر HTTPS.

## 7. ملاحظة — Note

التطبيق جاهز تقنيًا لاستقبال بيانات SIS وتحويلها إلى تذكيرات؛ الجزء الوحيد المتبقّي
هو طريقة الوصول الرسمية المطلوبة في القسم 5. فور توفيرها يُفعَّل التكامل.
