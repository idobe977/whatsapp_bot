# WhatsApp Survey Bot 🤖

בוט WhatsApp חכם המנהל סקרים דינמיים ומשתמש ב-Green API, Airtable ו-Gemini AI.

## ⚠️ הערת אבטחה

**חשוב**: לעולם אין להעלות פרטי התחברות רגישים ל-Git! יש לשמור על הקבצים הבאים בצורה מאובטחת:
- `credentials/service-account.json`
- `.env`

## 🌟 תכונות עיקריות

### סקרים דינמיים
- טעינת סקרים מקבצי JSON
- תמיכה במגוון סוגי שאלות
- זרימת שאלות מותנית (flow logic)
- החלפת טקסט דינמית עם ערכים מ-Airtable

### יכולות AI מתקדמות
- תמלול הודעות קוליות באמצעות Gemini AI
- יצירת רפלקציות אוטומטיות לתשובות המשתמש
- סיכומים חכמים בסוף השאלון
- תגובות אמפתיות ומקצועיות

### ניהול קבצים
- הצגת מסמכי PDF ותמונות למשתמשים
- קבלת ועיבוד קבצים מהמשתמשים
- תמיכה בכותרות לקבצים ושאלות המשך
- וולידציה אוטומטית של סוגי קבצים
- אחסון מאובטח ב-Airtable

### ניהול פגישות
- קביעת פגישות אוטומטית עם Google Calendar
- בדיקת זמינות חכמה
- שליחת הזמנות אוטומטית

### ניהול משתמשים
- מעקב אחר סטטוס המשתמש
- טיימאאוט אוטומטי לאחר 30 דקות
- אפשרות להפסקת שאלון באמצעות פקודות
- שמירת מצב ותשובות בזיכרון

### התראות ומעקב
- שליחת התראות לקבוצת WhatsApp בסיום שאלון
- עדכון סטטוס אוטומטי ב-Airtable
- שמירת תשובות עם מטמון (caching)

## 🛠️ הגדרה ראשונית

### Google Cloud Platform
1. צור פרויקט חדש
2. הפעל את Google Calendar API
3. צור חשבון שירות (Service Account):
   - עבור ל-"IAM & Admin" > "Service Accounts"
   - לחץ על "Create Service Account"
   - תן לו שם (למשל "whatsapp-bot-calendar")
   - צור מפתח JSON והורד אותו
4. שמור את קובץ המפתח ב-`credentials/service-account.json`
5. שתף את לוח השנה שלך עם כתובת המייל של חשבון השירות
   (הכתובת נראית כך: `bot-name@project-id.iam.gserviceaccount.com`)

### Green API
1. הירשם וקבל מזהה ומפתח API
2. הגדר כתובת webhook בלוח הבקרה של Green API

### Airtable
1. צור בסיס וטבלאות
2. קבל מפתח API ומזהה בסיס

## 📦 התקנה

1. שכפל את המאגר
```bash
git clone <your-repo-url>
cd whatsapp-survey-bot
```

2. התקן תלויות
```bash
pip install -r requirements.txt
```

3. הגדר משתני סביבה ב-`.env`:
```env
# Green API
ID_INSTANCE=your_green_api_instance_id
API_TOKEN_INSTANCE=your_green_api_token

# Gemini AI
GEMINI_API_KEY=your_gemini_api_key

# Airtable
AIRTABLE_API_KEY=your_airtable_api_key
AIRTABLE_BASE_ID=your_airtable_base_id
AIRTABLE_BUSINESS_SURVEY_TABLE_ID=your_business_table_id
AIRTABLE_RESEARCH_SURVEY_TABLE_ID=your_research_table_id

# Google Service Account (לסביבת ייצור)
GOOGLE_SERVICE_ACCOUNT={"type":"service_account","project_id":"..."}
```

## 📝 הגדרת סקרים

צור הגדרות סקר בתיקיית `surveys` בפורמט JSON:

```json
{
  "name": "שם הסקר",
  "trigger_phrases": ["טריגר1", "טריגר2"],
  "airtable": {
    "base_id": "your_base_id",
    "table_id": "your_table_id"
  },
  "calendar_settings": {
    "working_hours": {
      "sunday": {"start": "09:00", "end": "17:00"}
    },
    "meeting_duration": 30,
    "buffer_between_meetings": 15,
    "days_to_show": 14,
    "timezone": "Asia/Jerusalem",
    "calendar_id": "primary",
    "meeting_title_template": "פגישה עם {{name}}",
    "meeting_description_template": "נקבע דרך WhatsApp\nטלפון: {{phone}}"
  },
  "ai_prompts": {
    "reflections": {
      "empathetic": {
        "prompt": "צור תגובה אמפתית",
        "enabled": true
      },
      "professional": {
        "prompt": "צור תגובה מקצועית",
        "enabled": true
      }
    },
    "summary": {
      "prompt": "צור סיכום",
      "include_recommendations": true,
      "max_length": 500
    }
  },
  "questions": [
    {
      "id": "question_id",
      "type": "text/poll/file/file_to_send",
      "text": "טקסט השאלה {{airtable_field}}",
      "options": ["אופציה1", "אופציה2"],
      "file": {
        "path": "path/to/file",
        "caption": "תיאור הקובץ"
      },
      "allowed_types": ["document", "image"],
      "reflection": {
        "type": "empathetic/professional",
        "enabled": true
      },
      "flow": {
        "if": {
          "answer": "תשובה ספציפית",
          "then": {
            "say": "הודעה מותאמת",
            "goto": "מזהה_שאלה_הבאה"
          }
        }
      }
    }
  ]
}
```

## 🚀 פריסה ל-Render

1. העלה את הקוד ל-GitHub

2. צור שירות Web חדש ב-Render:
   - חבר את מאגר ה-GitHub שלך
   - הגדר פקודת בנייה: `pip install -r requirements.txt`
   - הגדר פקודת הפעלה: `python server.py`
   - הוסף את כל משתני הסביבה
   - הגדר גרסת Python ל-3.9 ומעלה

3. צור את תיקיית ההרשאות והעלה את קובץ חשבון השירות:
   ```bash
   mkdir -p credentials
   # העתק את service-account.json לתיקיית credentials/
   ```

## 🔒 הערות אבטחה

- כל המידע הרגיש נשמר במשתני סביבה
- יש לשמור על מפתח JSON של חשבון השירות בצורה מאובטחת
- נדרש HTTPS בסביבת ייצור
- יש להגביל גישה לנקודות הקצה

## 📞 תמיכה

לשאלות ותמיכה, צור קשר עם המפתח.

## File Handling

The bot supports three types of file interactions:

1. **Sending Files to Users (`file_to_send`)**:
   - Send files from the bot to users
   - Files are stored locally in the `assets` directory
   - Supports all WhatsApp-compatible file types
   - Can include text messages before sending files
   - Example:
   ```json
   {
     "id": "terms_review",
     "type": "file_to_send",
     "text": "Please review this document:",
     "file": {
       "path": "assets/terms.pdf",
       "caption": "Terms of Service 📄"
     }
   }
   ```

2. **Requesting Files (`file`)**:
   - Request and validate file uploads from users
   - Files are stored securely in Airtable
   - Support for multiple file types in one question
   - Example:
   ```json
   {
     "id": "portfolio",
     "type": "file",
     "text": "Please upload your portfolio:",
     "allowed_types": ["document", "image"]
   }
   ```

3. **File Type Validation**:
   - Comprehensive MIME type validation
   - Support for multiple file types:
     - `image`: JPEG, PNG, GIF, WEBP
     - `document`: PDF, DOC, DOCX
     - `video`: MP4, 3GPP, QuickTime, MKV
     - `audio`: MP3, OGG, WAV, M4A, WEBM
     - `any`: Accept any file type
   - Human-readable error messages in Hebrew
   - Size limit validation (5MB by default)

### File Storage

Files can be stored in two ways:
1. **Bot Files** (`file_to_send`):
   - Stored in the `assets` directory
   - Part of the project repository
   - Quick access and delivery
   - Perfect for terms of service, forms, etc.

2. **User Uploads** (`file`):
   - Stored in Airtable as attachments
   - Automatic conversion to Airtable format
   - Secure storage with backup
   - Perfect for user submissions

### File Type Configuration

The bot supports flexible file type configuration:
```python
ALLOWED_FILE_TYPES = {
    'image': ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
    'document': ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    'video': ['video/mp4', 'video/3gpp', 'video/quicktime', 'video/x-matroska'],
    'audio': ['audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/x-m4a', 'audio/webm'],
    'any': None  # Accept any file type
}
```

You can combine multiple types in one question:
```json
{
  "id": "portfolio",
  "type": "file",
  "text": "Upload your portfolio (document or images):",
  "allowed_types": ["document", "image"]
}
```

### Project Structure

```
project/
├── assets/           # Store bot files to send to users
├── surveys/          # Survey JSON definitions
├── services/         # Bot service modules
└── ...
``` 