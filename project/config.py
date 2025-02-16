import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# WhatsApp (Green API) Configuration
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")

# Airtable Configuration
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

# Google Calendar Configuration
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT")

# Gemini AI Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Cache Configuration
CACHE_TTL = 300  # 5 minutes
MAX_CACHE_SIZE = 1000

# API Configuration
API_PREFIX = "/api/v1"
WEBHOOK_PATH = "/webhook"

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

# Survey Configuration
SURVEY_TIMEOUT = 30  # minutes
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Rate Limiting
MAX_REQUESTS_PER_MINUTE = 60 