# WhatsApp Survey Bot

בוט חכם לניהול סקרים וקביעת פגישות דרך WhatsApp, עם אינטגרציה ל-Airtable, Google Calendar ו-Gemini AI.

## התקנה מקומית

1. התקן Python 3.10:
```bash
# Windows
# הורד והתקן מ-https://www.python.org/downloads/release/python-3109/

# Linux/Mac
pyenv install 3.10.9
pyenv global 3.10.9
```

2. צור והפעל סביבה וירטואלית:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate  # Windows
```

3. התקן את הדרישות:
```bash
pip install -r project/requirements.txt
```

4. הגדר משתני סביבה:
העתק את קובץ `.env.example` ל-`.env` והגדר את המשתנים הנדרשים:
```bash
cp .env.example .env
# ערוך את .env והוסף את המפתחות הנדרשים
```

5. הרץ את השרת:
```bash
python -m uvicorn project.main:app --reload
```

## דפלוי ל-Vercel

1. צור חשבון ב-[Vercel](https://vercel.com)

2. התקן את ה-CLI של Vercel:
```bash
npm i -g vercel
```

3. התחבר ל-Vercel:
```bash
vercel login
```

4. דפלוי:
```bash
vercel
```

5. הגדר משתני סביבה ב-Vercel:
- פתח את הפרויקט בממשק של Vercel
- לך ל-Settings > Environment Variables
- הוסף את כל המשתנים מקובץ `.env`

## משתני סביבה נדרשים

```env
# Green API (WhatsApp)
ID_INSTANCE=your_instance_id
API_TOKEN_INSTANCE=your_api_token

# Airtable
AIRTABLE_API_KEY=your_airtable_key
AIRTABLE_BASE_ID=your_base_id

# Google Calendar
GOOGLE_SERVICE_ACCOUNT={"type": "service_account", ...}

# Gemini AI
GEMINI_API_KEY=your_gemini_key
```

## פיתוח

1. הוסף שאלונים חדשים בתיקיית `surveys/`
2. ערוך את הקונפיגורציה ב-`config.py`
3. הרץ בדיקות:
```bash
pytest
```

## תרומה לפרויקט

1. Fork את הריפו
2. צור branch חדש
3. Commit את השינויים שלך
4. פתח Pull Request

## רישיון

MIT 