# NovelAutoForge — Public REST API (v1)

เอกสารนี้อธิบาย REST API สำหรับให้ระบบภายนอกดึงข้อมูลนิยายแต่ละตอนในรูปแบบ JSON

---

## Base URL

```
https://<your-domain>/api/v1
```

---

## Authentication

API รองรับ 2 วิธี:

### 1. Bearer Token (แนะนำสำหรับ server-to-server)

เพิ่ม header ทุก request:

```http
Authorization: Bearer <API_SECRET_KEY>
```

ตั้งค่า `API_SECRET_KEY` ใน `.env`:

```env
# สร้าง secret ด้วย: openssl rand -base64 48
API_SECRET_KEY="your-secret-key-here"
```

### 2. Session Cookie (สำหรับ browser / same-origin)

ใช้ NextAuth session cookie เดิมที่ได้จากการ login ผ่านหน้าเว็บ (`/login`)

---

## Endpoints

---

### GET `/api/v1/series/{seriesId}/chapters`

ดึงรายการตอนทั้งหมดของนิยายในรูป JSON พร้อม pagination

#### Path Parameters

| Parameter  | Type   | Required | Description        |
|------------|--------|----------|--------------------|
| `seriesId` | string | ✅       | ID ของนิยาย (series) |

#### Query Parameters

| Parameter | Type   | Default | Description                                              |
|-----------|--------|---------|----------------------------------------------------------|
| `page`    | number | `1`     | หน้าที่ต้องการ                                           |
| `limit`   | number | `50`    | จำนวนตอนต่อหน้า (สูงสุด 200)                             |
| `bookId`  | string | —       | กรอง เฉพาะ book ที่ระบุ                                  |
| `status`  | string | —       | กรอง เฉพาะ status: `OUTLINE` \| `DRAFT` \| `REVISED` \| `FINAL` |

#### Request ตัวอย่าง

```http
GET /api/v1/series/clx1234abc/chapters?page=1&limit=20&status=FINAL
Authorization: Bearer sk-abc123...
```

#### Response `200 OK`

```json
{
  "series": {
    "id": "clx1234abc",
    "title": "มังกรสีแดง",
    "genre": "Fantasy",
    "logline": "เด็กหมู่บ้านค้นพบว่าตนเองเป็นทายาทมังกรโบราณ...",
    "status": "ONGOING"
  },
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 120,
    "totalPages": 6
  },
  "chapters": [
    {
      "id": "clx9876xyz",
      "order": 1,
      "title": "บทที่ 1: จุดเริ่มต้น",
      "status": "FINAL",
      "wordCount": 3200,
      "outline": "พระเอกออกจากหมู่บ้านครั้งแรก...",
      "content": "<p>เนื้อหาบทที่ 1...</p>",
      "bookId": null,
      "linkedStage": "call-to-adventure",
      "generatedAt": "2026-03-01T08:00:00.000Z",
      "createdAt": "2026-03-01T07:55:00.000Z",
      "updatedAt": "2026-03-01T08:10:00.000Z"
    }
  ]
}
```

#### Chapter Fields

| Field          | Type            | Description                                    |
|----------------|-----------------|------------------------------------------------|
| `id`           | string          | ID ของตอน (cuid)                               |
| `order`        | number          | ลำดับตอน (1-based)                             |
| `title`        | string          | ชื่อตอน                                        |
| `status`       | string          | `OUTLINE` / `DRAFT` / `REVISED` / `FINAL`      |
| `wordCount`    | number          | จำนวนคำที่นับล่าสุด                            |
| `outline`      | string \| null  | โครงเรื่องตอนนี้                               |
| `content`      | string \| null  | เนื้อหาฉบับเต็ม (HTML)                         |
| `bookId`       | string \| null  | ID ของ book ที่ตอนนี้อยู่                      |
| `linkedStage`  | string \| null  | Plot stage ที่ผูกไว้ (เช่น `call-to-adventure`) |
| `generatedAt`  | ISO8601 \| null | เวลาที่ AI สร้างเนื้อหาล่าสุด                  |
| `createdAt`    | ISO8601         | เวลาสร้างตอน                                   |
| `updatedAt`    | ISO8601         | เวลาแก้ไขล่าสุด                                |

---

### GET `/api/v1/series/{seriesId}/chapters/{chapterId}`

ดึงข้อมูลตอนเดียวแบบละเอียด พร้อมประวัติเวอร์ชัน (ล่าสุด 10 เวอร์ชัน)

#### Path Parameters

| Parameter   | Type   | Required | Description            |
|-------------|--------|----------|------------------------|
| `seriesId`  | string | ✅       | ID ของนิยาย            |
| `chapterId` | string | ✅       | ID ของตอนที่ต้องการ    |

#### Request ตัวอย่าง

```http
GET /api/v1/series/clx1234abc/chapters/clx9876xyz
Authorization: Bearer sk-abc123...
```

#### Response `200 OK`

```json
{
  "chapter": {
    "id": "clx9876xyz",
    "order": 1,
    "title": "บทที่ 1: จุดเริ่มต้น",
    "status": "FINAL",
    "wordCount": 3200,
    "outline": "พระเอกออกจากหมู่บ้านครั้งแรก...",
    "content": "<p>เนื้อหาบทที่ 1...</p>",
    "notes": "ควรเพิ่มรายละเอียดฉากภูเขา",
    "bookId": null,
    "linkedStage": "call-to-adventure",
    "aiModel": "gemini-2.0-flash",
    "generatedAt": "2026-03-01T08:00:00.000Z",
    "ttsStatus": "DONE",
    "ttsVoice": "th-TH-PremwadeeNeural",
    "audioUrl": "/api/voice/audio?chapterId=clx9876xyz",
    "createdAt": "2026-03-01T07:55:00.000Z",
    "updatedAt": "2026-03-01T08:10:00.000Z",
    "series": {
      "id": "clx1234abc",
      "title": "มังกรสีแดง",
      "genre": "Fantasy"
    },
    "versions": [
      {
        "id": "clxver001",
        "version": 3,
        "wordCount": 3200,
        "createdAt": "2026-03-01T08:10:00.000Z"
      },
      {
        "id": "clxver002",
        "version": 2,
        "wordCount": 2900,
        "createdAt": "2026-03-01T07:30:00.000Z"
      }
    ]
  }
}
```

#### Chapter Fields (เพิ่มเติมจาก list endpoint)

| Field          | Type            | Description                                            |
|----------------|-----------------|--------------------------------------------------------|
| `notes`        | string \| null  | หมายเหตุของนักเขียน                                    |
| `aiModel`      | string \| null  | โมเดล AI ที่ใช้สร้าง (เช่น `gemini-2.0-flash`)        |
| `ttsStatus`    | string          | สถานะ TTS: `NONE` / `PENDING` / `PROCESSING` / `DONE` / `ERROR` |
| `ttsVoice`     | string \| null  | ชื่อเสียง TTS (เช่น `th-TH-PremwadeeNeural`)           |
| `audioUrl`     | string \| null  | URL ของไฟล์เสียง                                       |
| `series`       | object          | ข้อมูลนิยายแบบย่อ                                      |
| `versions`     | array           | ประวัติเวอร์ชันล่าสุด 10 รายการ                        |

---

## Error Responses

| Status | Body                            | สาเหตุ                                  |
|--------|---------------------------------|-----------------------------------------|
| `401`  | `{ "error": "Unauthorized" }`   | ไม่มี token หรือ token ผิด              |
| `404`  | `{ "error": "Series not found" }` | ไม่พบ series หรือไม่มีสิทธิ์เข้าถึง   |
| `404`  | `{ "error": "Chapter not found" }` | ไม่พบตอน หรือ seriesId ไม่ตรง         |

---

## ตัวอย่างการใช้งาน

### cURL

```bash
# ดึงตอนทั้งหมด (หน้า 1, 50 ตอน)
curl -H "Authorization: Bearer $API_SECRET_KEY" \
  "https://your-domain.com/api/v1/series/clx1234abc/chapters"

# ดึงเฉพาะตอนที่สถานะ FINAL พร้อม pagination
curl -H "Authorization: Bearer $API_SECRET_KEY" \
  "https://your-domain.com/api/v1/series/clx1234abc/chapters?status=FINAL&page=2&limit=10"

# ดึงตอนเดียว
curl -H "Authorization: Bearer $API_SECRET_KEY" \
  "https://your-domain.com/api/v1/series/clx1234abc/chapters/clx9876xyz"
```

### JavaScript (fetch)

```js
const API_BASE = "https://your-domain.com/api/v1";
const API_KEY  = process.env.API_SECRET_KEY;

const headers = { Authorization: `Bearer ${API_KEY}` };

// ดึงตอนทั้งหมด
const res = await fetch(`${API_BASE}/series/${seriesId}/chapters?limit=100`, { headers });
const data = await res.json();
console.log(data.chapters);

// ดึงตอนเดียว
const res2 = await fetch(`${API_BASE}/series/${seriesId}/chapters/${chapterId}`, { headers });
const { chapter } = await res2.json();
console.log(chapter.content);
```

### Python (requests)

```python
import requests, os

API_BASE = "https://your-domain.com/api/v1"
headers  = {"Authorization": f"Bearer {os.environ['API_SECRET_KEY']}"}

# ดึงตอนทั้งหมด
r = requests.get(f"{API_BASE}/series/{series_id}/chapters", headers=headers,
                 params={"limit": 100, "status": "FINAL"})
data = r.json()
for ch in data["chapters"]:
    print(ch["order"], ch["title"], ch["wordCount"])

# ดึงตอนเดียว
r2 = requests.get(f"{API_BASE}/series/{series_id}/chapters/{chapter_id}", headers=headers)
chapter = r2.json()["chapter"]
print(chapter["content"])
```

---

## แผนผัง Endpoints

```
/api/v1/
└── series/
    └── {seriesId}/
        └── chapters/               GET  → list chapters (paginated)
            └── {chapterId}/        GET  → single chapter + versions
```

---

## Files ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|------|---------|
| `src/lib/apiAuth.ts` | ตรวจสอบ Bearer token / Session |
| `src/app/api/v1/series/[seriesId]/chapters/route.ts` | List endpoint |
| `src/app/api/v1/series/[seriesId]/chapters/[chapterId]/route.ts` | Single chapter endpoint |
