# WhatsApp Survey Bot

A WhatsApp bot that conducts surveys and manages responses using Green API and Airtable.

## Features

- Multiple survey types support (Business, Research, Satisfaction)
- Voice message transcription
- Poll support
- Automatic meeting scheduling
- Response storage in Airtable
- Automatic summary generation using Gemini AI

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

4. Run the server
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

Make sure to set all required environment variables in your Render dashboard:

- `ID_INSTANCE`
- `API_TOKEN_INSTANCE`
- `GEMINI_API_KEY`
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_BUSINESS_SURVEY_TABLE_ID`
- `AIRTABLE_RESEARCH_SURVEY_TABLE_ID`
- `AIRTABLE_SATISFACTION_SURVEY_TABLE_ID`

## תכונות עיקריות

- ניהול שאלון אפיון מובנה
- תמיכה בהודעות טקסט והקלטות קוליות
- תמלול אוטומטי של הקלטות קוליות באמצעות Gemini AI
- שמירת תשובות אוטומטית ב-Airtable
- ממשק REST API מבוסס FastAPI

## דרישות מערכת

- Python 3.9+
- חשבון Green API לממשק וואטסאפ
- חשבון Airtable
- מפתח API של Google (Gemini)

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

## הרצה מקומית

הרץ את השרת:
```bash
python server.py
```

השרת יתחיל לרוץ על פורט 8000.

## דיפלוי ל-Render.com

1. צור חשבון ב-Render.com
2. צור Web Service חדש
3. התחבר לריפוזיטורי שלך
4. הגדר את המשתנים הבאים:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
5. הוסף את משתני הסביבה מקובץ `.env`

## דיפלוי ל-AWS EC2

1. צור מופע EC2 חדש
2. התחבר למופע דרך SSH
3. התקן את הדרישות:
```bash
sudo apt-get update
sudo apt-get install python3-pip
git clone <repository-url>
cd whatsapp-survey-bot
pip3 install -r requirements.txt
```

4. הגדר את משתני הסביבה:
```bash
sudo nano /etc/environment
# הוסף את כל המשתנים מקובץ .env
```

5. הרץ את השרת עם PM2:
```bash
sudo npm install -g pm2
pm2 start "python3 server.py" --name whatsapp-bot
pm2 save
pm2 startup
```

## נקודות קצה

- `POST /webhook` - נקודת הקצה לקבלת עדכונים מ-Green API
- `GET /health` - בדיקת תקינות השרת

## הערות אבטחה

- וודא שכל המפתחות והטוקנים מאובטחים ולא נחשפים
- השתמש ב-HTTPS בסביבת הייצור
- הגבל גישה לנקודות הקצה רק למקורות מורשים

## תמיכה

לשאלות ותמיכה, צור קשר עם המפתח. 
