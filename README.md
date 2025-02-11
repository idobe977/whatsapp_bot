# WhatsApp Survey Bot

A WhatsApp bot that conducts dynamic surveys and manages responses using Green API, Airtable and Gemini AI.

## Features

- Dynamic survey loading from JSON files
- Multiple survey types support
- Voice message transcription using Gemini AI
- Poll support with single and multiple choice options
- Conditional flow logic based on user responses
- Dynamic text replacement with Airtable field values
- Automatic meeting scheduling with Google Calendar
- Response storage in Airtable with caching
- Automatic summary generation using Gemini AI
- Empathetic and professional AI-powered reflections
- Timeout handling for inactive sessions

## Prerequisites

1. Google Cloud Platform Account:
   - Create a new project
   - Enable Google Calendar API
   - Configure OAuth2 consent screen
   - Create OAuth2 credentials (Web application type)
   - Add authorized redirect URIs:
     - For local development: `http://localhost:8003/oauth2callback`
     - For production: `https://your-app-name.onrender.com/oauth2callback`

2. Green API Account:
   - Register and get instance ID and API token
   - Configure webhook URL in Green API dashboard

3. Airtable Account:
   - Create base and tables
   - Get API key and base ID

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
# Green API Configuration
ID_INSTANCE=your_green_api_instance_id
API_TOKEN_INSTANCE=your_green_api_token

# Gemini AI Configuration
GEMINI_API_KEY=your_gemini_api_key

# Airtable Configuration
AIRTABLE_API_KEY=your_airtable_api_key
AIRTABLE_BASE_ID=your_airtable_base_id
AIRTABLE_BUSINESS_SURVEY_TABLE_ID=your_business_table_id
AIRTABLE_RESEARCH_SURVEY_TABLE_ID=your_research_table_id

# Google OAuth2 Configuration
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=https://your-app-name.onrender.com/oauth2callback
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
  "calendar_settings": {
    "working_hours": {
      "sunday": {"start": "09:00", "end": "17:00"}
    },
    "meeting_duration": 30,
    "buffer_between_meetings": 15,
    "days_to_show": 14,
    "timezone": "Asia/Jerusalem",
    "calendar_id": "primary",
    "meeting_title_template": "Meeting with {{name}}",
    "meeting_description_template": "Scheduled via WhatsApp\nPhone: {{phone}}"
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

## Deployment to Render

1. Push your code to GitHub

2. Create new Web Service on Render:
   - Connect your GitHub repository
   - Set build command: `pip install -r requirements.txt`
   - Set start command: `python server.py`
   - Add all environment variables
   - Set Python version to 3.9 or higher

3. Configure OAuth2:
   - Add your Render app URL to authorized redirect URIs in Google Cloud Console
   - Update GOOGLE_REDIRECT_URI in environment variables

4. Initialize Calendar Authentication:
   - Visit `/calendar/auth` endpoint after deployment
   - Complete OAuth2 flow
   - Verify credentials are stored in the credentials directory

## Environment Variables

Required environment variables:
- `ID_INSTANCE`
- `API_TOKEN_INSTANCE`
- `GEMINI_API_KEY`
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_BUSINESS_SURVEY_TABLE_ID`
- `AIRTABLE_RESEARCH_SURVEY_TABLE_ID`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`

## Local Development

1. Run the server:
```bash
python server.py
```

2. Initialize calendar authentication:
   - Visit `http://localhost:8003/calendar/auth`
   - Complete OAuth2 flow
   - Verify credentials in the credentials directory

## Security Notes

- All sensitive data is stored in environment variables
- OAuth2 tokens are stored securely in local files
- HTTPS is required in production
- Access to endpoints should be restricted
- Regular token rotation is recommended

## Support

For questions and support, contact the developer. 