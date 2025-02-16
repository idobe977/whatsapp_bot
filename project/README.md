# WhatsApp Survey Bot

A sophisticated WhatsApp bot that conducts dynamic surveys, manages responses, and schedules meetings using Green API, Airtable, Google Calendar, and Gemini AI.

## Security Notice ⚠️

**IMPORTANT**: Never commit sensitive credentials to Git! The following files should be kept secure and not shared:
- `credentials/service-account.json`
- `.env`

## Credentials Setup

1. **Google Calendar Service Account**:
   - Create a new service account in Google Cloud Console
   - Download the JSON key file
   - Create a `credentials` directory locally: `mkdir credentials`
   - Save the key as `credentials/service-account.json`
   - Share your calendar with the service account email
   - **DO NOT commit this file to Git!**

2. **Environment Variables**:
   - Copy `.env.example` to `.env`: `cp .env.example .env`
   - Fill in your credentials in `.env`
   - **DO NOT commit `.env` to Git!**

### For Production Deployment

For secure deployment (e.g., on Render.com):
1. **DO NOT** upload credentials files to Git
2. Instead, use environment variables or secrets management:
   - For service account: Copy the entire content of `service-account.json` and save it as an environment variable `GOOGLE_SERVICE_ACCOUNT`
   - The bot will automatically create the credentials file from this environment variable

## Features

### Core Features
- Dynamic survey loading from JSON files
- Multiple survey types support (text, poll, voice, meeting scheduler)
- Voice message transcription using Gemini AI
- Poll support with single and multiple choice options
- Conditional flow logic based on user responses
- Dynamic text replacement with Airtable field values
- Response storage in Airtable with efficient caching
- Automatic summary generation using Gemini AI
- Empathetic and professional AI-powered reflections
- Timeout handling for inactive sessions
- Trigger phrases in polls to start new surveys
- Group notifications for survey completions

### Enhanced Meeting Scheduling
- Intelligent calendar integration with Google Calendar
- Automatic availability detection based on working hours
- Configurable buffer times between meetings
- Smart date and time selection via interactive polls
- Automatic ICS file generation for calendar invites
- Support for multiple time zones
- Customizable meeting duration and buffer times
- Flexible working hours configuration per day
- Automatic handling of overlapping appointments
- Built-in minimum scheduling notice (2 hours in advance)

### Advanced Error Handling & Logging
- Comprehensive error logging system
- Detailed process tracking for debugging
- Graceful handling of API failures
- Automatic retry mechanisms for API calls
- Session state monitoring and cleanup
- Detailed logging of meeting scheduling process
- Airtable operation tracking
- Voice message processing logs
- Poll response tracking
- Webhook handling logs

### Data Management
- Efficient Airtable integration with caching
- Automatic record updates and creation
- Dynamic field mapping
- Secure credential management
- Configurable cache timeout
- Automatic cache cleanup
- Record state tracking
- Field value validation

### User Experience
- Interactive poll-based scheduling
- Flexible date and time selection
- Clear confirmation messages
- Automatic calendar invites
- Support for rescheduling
- Timeout notifications
- Error recovery options
- Progress tracking
- Survey state persistence
- Customizable messages and prompts
- Group notifications for completed surveys

### Poll Features
- Support for trigger phrases in poll options
- Automatic survey initiation from poll responses
- Multi-option polls
- Poll response validation
- Emoji support in poll options
- Custom poll messages
- Poll state tracking
- Poll timeout handling

### Group Integration
- Automatic notifications to specified groups
- Survey completion announcements
- Custom notification formats
- Rich text formatting support
- Emoji and formatting in messages
- Error handling for group messages

## Prerequisites

1. Google Cloud Platform Account:
   - Create a new project
   - Enable Google Calendar API
   - Create a Service Account:
     - Go to "IAM & Admin" > "Service Accounts"
     - Click "Create Service Account"
     - Name it (e.g. "whatsapp-bot-calendar")
     - Create a JSON key and download it
   - Place the JSON key file in `credentials/service-account.json`
   - Share your Google Calendar with the service account email
     (The email looks like: `bot-name@project-id.iam.gserviceaccount.com`)

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

# Google Service Account (for production)
GOOGLE_SERVICE_ACCOUNT={"type":"service_account","project_id":"..."}
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
      "sunday": {"start": "09:00", "end": "17:00"},
      "monday": {"start": "09:00", "end": "14:00"},
      "tuesday": {"start": "09:00", "end": "11:00"},
      "wednesday": {"start": "09:00", "end": "14:00"},
      "thursday": {"start": "09:00", "end": "11:00"}
    },
    "meeting_duration": 30,
    "buffer_between_meetings": 15,
    "days_to_show": 14,
    "timezone": "Asia/Jerusalem",
    "calendar_id": "primary",
    "meeting_title_template": "פגישה עם {{שם מלא}}",
    "meeting_description_template": "נקבע דרך וואטסאפ\nטלפון: {{phone}}\nסוג פגישה: {{סוג הפגישה}}"
  },
  "questions": [
    {
      "id": "question_id",
      "type": "text/poll/voice/meeting_scheduler",
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
        },
        "else_if": [
          {
            "answer": "another_answer",
            "then": {
              "say": "Another message",
              "goto": "different_question_id"
            }
          }
        ]
      }
    }
  ],
  "messages": {
    "welcome": "ברוכים הבאים לשאלון!",
    "completion": {
      "text": "תודה על השלמת השאלון!",
      "should_generate_summary": true
    },
    "error": "מצטערים, הייתה שגיאה. נא לנסות שוב."
  },
  "ai_prompts": {
    "reflections": {
      "empathetic": {
        "prompt": "Your empathetic reflection prompt here"
      },
      "professional": {
        "prompt": "Your professional reflection prompt here"
      }
    },
    "summary": {
      "prompt": "Your summary generation prompt here",
      "include_recommendations": true,
      "max_length": 500
    }
  }
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

3. Create the credentials directory and upload service account JSON:
   ```bash
   mkdir -p credentials
   # Copy your service-account.json to credentials/
   ```

## Environment Variables

Required environment variables:
- `ID_INSTANCE`
- `API_TOKEN_INSTANCE`
- `GEMINI_API_KEY`
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_BUSINESS_SURVEY_TABLE_ID`
- `AIRTABLE_RESEARCH_SURVEY_TABLE_ID`

## Local Development

1. Run the server:
```bash
python server.py
```

## Security Notes

- All sensitive data is stored in environment variables
- Service account JSON key should be kept secure
- HTTPS is required in production
- Access to endpoints should be restricted

## Support

For questions and support, contact the developer. 

## Advanced Features

### Meeting Scheduling
The bot now supports sophisticated meeting scheduling with the following features:
- Automatic availability detection based on working hours
- Smart conflict detection with existing appointments
- Buffer time management between meetings
- Interactive date and time selection via polls
- Automatic ICS file generation
- Support for custom meeting types
- Dynamic meeting description templates
- Automatic Airtable record updates
- Timezone support
- Minimum scheduling notice

### Error Handling
The system includes comprehensive error handling:
- Automatic retry for failed API calls
- Graceful degradation on service failures
- Detailed error logging
- User-friendly error messages
- Session state recovery
- Timeout handling
- API rate limiting
- Connection pool management

### Performance Optimizations
- Efficient Airtable caching
- Connection pooling
- DNS caching
- Keepalive connections
- Rate limiting
- Batch operations
- Asynchronous processing
- Resource cleanup 