# WhatsApp Survey Bot

A WhatsApp bot that conducts dynamic surveys and manages responses using Green API, Airtable and Gemini AI.

## Features

- Dynamic survey loading from JSON files
- Multiple survey types support
- Voice message transcription using Gemini AI
- Poll support with single and multiple choice options
- Conditional flow logic based on user responses
- Dynamic text replacement with Airtable field values
- Automatic meeting scheduling
- Response storage in Airtable with caching
- Automatic summary generation using Gemini AI
- Empathetic and professional AI-powered reflections
- Timeout handling for inactive sessions

## Survey Features

- JSON-based survey definition
- Support for text questions and polls
- Dynamic question flow based on answers
- Custom messages and reflections per question
- Airtable field value interpolation using {{field_name}} syntax
- Multiple answer types:
  - Text input
  - Voice messages with automatic transcription
  - Single choice polls
  - Multiple choice polls
- Conditional logic flow with if/else_if conditions
- Custom messages based on user responses

## Setup

1. Clone the repository
```bash
git clone <your-repo-url>
cd whatsapp-survey-bot
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Set up environment variables in `.env`:
```env
ID_INSTANCE=your_green_api_instance_id
API_TOKEN_INSTANCE=your_green_api_token
GEMINI_API_KEY=your_gemini_api_key
AIRTABLE_API_KEY=your_airtable_api_key
AIRTABLE_BASE_ID=your_airtable_base_id
AIRTABLE_BUSINESS_SURVEY_TABLE_ID=your_business_table_id
AIRTABLE_RESEARCH_SURVEY_TABLE_ID=your_research_table_id
AIRTABLE_SATISFACTION_SURVEY_TABLE_ID=your_satisfaction_table_id
```

4. Create your survey definitions in the `surveys` directory using JSON format:
```json
{
  "name": "Survey Name",
  "trigger_phrases": ["trigger1", "trigger2"],
  "airtable": {
    "base_id": "your_base_id",
    "table_id": "your_table_id"
  },
  "questions": [
    {
      "id": "question_id",
      "type": "text/poll",
      "text": "Question text {{airtable_field}}",
      "options": ["option1", "option2"],
      "reflection": {
        "type": "empathetic/professional",
        "enabled": true
      },
      "flow": {
        "if": {
          "answer": "specific_answer",
          "then": {
            "say": "Custom message",
            "goto": "next_question_id"
          }
        }
      }
    }
  ]
}
```

5. Run the server
```bash
uvicorn server:app --reload
```

## Deployment

This project is configured for deployment on Render.com. To deploy:

1. Push your code to GitHub
2. Create a new Web Service on Render
3. Connect your GitHub repository
4. Add your environment variables in the Render dashboard
5. Deploy!

## Environment Variables

Make sure to set all required environment variables:

- `ID_INSTANCE`
- `API_TOKEN_INSTANCE`
- `GEMINI_API_KEY`
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_BUSINESS_SURVEY_TABLE_ID`
- `AIRTABLE_RESEARCH_SURVEY_TABLE_ID`
- `AIRTABLE_SATISFACTION_SURVEY_TABLE_ID`

## תכונות עיקריות

- טעינה דינמית של שאלונים מקבצי JSON
- תמיכה במספר סוגי שאלונים
- תמלול אוטומטי של הקלטות קוליות באמצעות Gemini AI
- תמיכה בסקרים עם בחירה יחידה או מרובה
- לוגיקת זרימה מותנית בהתאם לתשובות המשתמש
- החלפת טקסט דינמית עם ערכים מ-Airtable
- קביעת פגישות אוטומטית
- שמירת תשובות ב-Airtable עם מטמון
- יצירת סיכום אוטומטי באמצעות Gemini AI
- תגובות AI אמפתיות ומקצועיות
- טיפול בפסקי זמן לשיחות לא פעילות

## מבנה השאלון

- הגדרת שאלון מבוססת JSON
- תמיכה בשאלות טקסט וסקרים
- זרימת שאלות דינמית בהתאם לתשובות
- הודעות ותגובות מותאמות אישית לכל שאלה
- שילוב ערכים מ-Airtable באמצעות תחביר {{שם_השדה}}
- סוגי תשובות מרובים:
  - קלט טקסט
  - הודעות קוליות עם תמלול אוטומטי
  - סקרים עם בחירה יחידה
  - סקרים עם בחירה מרובה
- זרימת לוגיקה מותנית עם תנאי if/else_if
- הודעות מותאמות אישית בהתאם לתשובות המשתמש

## התקנה

1. שכפל את הריפוזיטורי:
```bash
git clone <repository-url>
cd whatsapp-survey-bot
```

2. התקן את הדרישות:
```bash
pip install -r requirements.txt
```

3. צור קובץ `.env` עם המשתנים הבאים:
```env
ID_INSTANCE=your_green_api_instance_id
API_TOKEN_INSTANCE=your_green_api_token
GEMINI_API_KEY=your_gemini_api_key
AIRTABLE_API_KEY=your_airtable_api_key
AIRTABLE_BASE_ID=your_airtable_base_id
AIRTABLE_TABLE_ID=your_airtable_table_id
```

4. צור את הגדרות השאלון בתיקיית `surveys` בפורמט JSON:
```json
{
  "name": "שם השאלון",
  "trigger_phrases": ["מילת_טריגר1", "מילת_טריגר2"],
  "airtable": {
    "base_id": "מזהה_בסיס",
    "table_id": "מזהה_טבלה"
  },
  "questions": [
    {
      "id": "מזהה_שאלה",
      "type": "text/poll",
      "text": "טקסט השאלה {{שדה_אירטייבל}}",
      "options": ["אפשרות1", "אפשרות2"],
      "reflection": {
        "type": "empathetic/professional",
        "enabled": true
      },
      "flow": {
        "if": {
          "answer": "תשובה_ספציפית",
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

## הרצה מקומית

הרץ את השרת:
```bash
python server.py
```

השרת יתחיל לרוץ על פורט 8000.

## נקודות קצה

- `POST /webhook` - נקודת הקצה לקבלת עדכונים מ-Green API
- `GET /health` - בדיקת תקינות השרת

## הערות אבטחה

- וודא שכל המפתחות והטוקנים מאובטחים ולא נחשפים
- השתמש ב-HTTPS בסביבת הייצור
- הגבל גישה לנקודות הקצה רק למקורות מורשים

## תמיכה

לשאלות ותמיכה, צור קשר עם המפתח.

## הגדרת Google Calendar

1. היכנס ל-[Google Cloud Console](https://console.cloud.google.com/)
2. צור פרויקט חדש או בחר פרויקט קיים
3. הפעל את Google Calendar API:
   - חפש "Calendar API" בשורת החיפוש
   - לחץ על "Enable"
4. צור API Key:
   - לך לתפריט "Credentials"
   - לחץ על "Create Credentials"
   - בחר "API Key"
   - העתק את המפתח שנוצר
5. הוסף את המפתח לקובץ `.env`:
```env
GOOGLE_API_KEY=your_api_key_here
```

## פקודות חדשות בבוט

- `פגישה` או `קביעת פגישה` - התחלת תהליך קביעת פגישה
- הבוט יציג לוח שנה עם ימים פנויים
- בחר יום על ידי הקלדת המספר שלו
- בחר שעה מרשימת השעות הפנויות
- הפגישה תיקבע אוטומטית ביומן שלך

## תכונות עיקריות

- טעינה דינמית של שאלונים מקבצי JSON
- תמיכה במספר סוגי שאלונים
- תמלול אוטומטי של הקלטות קוליות באמצעות Gemini AI
- תמיכה בסקרים עם בחירה יחידה או מרובה
- לוגיקת זרימה מותנית בהתאם לתשובות המשתמש
- החלפת טקסט דינמית עם ערכים מ-Airtable
- קביעת פגישות אוטומטית
- שמירת תשובות ב-Airtable עם מטמון
- יצירת סיכום אוטומטי באמצעות Gemini AI
- תגובות AI אמפתיות ומקצועיות
- טיפול בפסקי זמן לשיחות לא פעילות

## מבנה השאלון

- הגדרת שאלון מבוססת JSON
- תמיכה בשאלות טקסט וסקרים
- זרימת שאלות דינמית בהתאם לתשובות
- הודעות ותגובות מותאמות אישית לכל שאלה
- שילוב ערכים מ-Airtable באמצעות תחביר {{שם_השדה}}
- סוגי תשובות מרובים:
  - קלט טקסט
  - הודעות קוליות עם תמלול אוטומטי
  - סקרים עם בחירה יחידה
  - סקרים עם בחירה מרובה
- זרימת לוגיקה מותנית עם תנאי if/else_if
- הודעות מותאמות אישית בהתאם לתשובות המשתמש

## התקנה

1. שכפל את הריפוזיטורי:
```bash
git clone <repository-url>
cd whatsapp-survey-bot
```

2. התקן את הדרישות:
```bash
pip install -r requirements.txt
```

3. צור קובץ `.env` עם המשתנים הבאים:
```env
ID_INSTANCE=your_green_api_instance_id
API_TOKEN_INSTANCE=your_green_api_token
GEMINI_API_KEY=your_gemini_api_key
AIRTABLE_API_KEY=your_airtable_api_key
AIRTABLE_BASE_ID=your_airtable_base_id
AIRTABLE_TABLE_ID=your_airtable_table_id
```

4. צור את הגדרות השאלון בתיקיית `surveys` בפורמט JSON:
```json
{
  "name": "שם השאלון",
  "trigger_phrases": ["מילת_טריגר1", "מילת_טריגר2"],
  "airtable": {
    "base_id": "מזהה_בסיס",
    "table_id": "מזהה_טבלה"
  },
  "questions": [
    {
      "id": "מזהה_שאלה",
      "type": "text/poll",
      "text": "טקסט השאלה {{שדה_אירטייבל}}",
      "options": ["אפשרות1", "אפשרות2"],
      "reflection": {
        "type": "empathetic/professional",
        "enabled": true
      },
      "flow": {
        "if": {
          "answer": "תשובה_ספציפית",
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

## הרצה מקומית

הרץ את השרת:
```bash
python server.py
```

השרת יתחיל לרוץ על פורט 8000.

## נקודות קצה

- `POST /webhook` - נקודת הקצה לקבלת עדכונים מ-Green API
- `GET /health` - בדיקת תקינות השרת

## הערות אבטחה

- וודא שכל המפתחות והטוקנים מאובטחים ולא נחשפים
- השתמש ב-HTTPS בסביבת הייצור
- הגבל גישה לנקודות הקצה רק למקורות מורשים

## תמיכה

לשאלות ותמיכה, צור קשר עם המפתח. 