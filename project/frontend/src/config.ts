const isDevelopment = process.env.NODE_ENV === 'development';

export const config = {
  apiBaseUrl: process.env.REACT_APP_API_URL || (isDevelopment 
    ? 'http://localhost:8000/api'
    : 'https://whatsapp-bot-api.onrender.com/api'),
  
  // הגדרות נוספות
  maxRetries: 3,
  retryDelay: 2000,
  timeoutDuration: 30000,
  
  // הגדרות לוקליזציה
  locale: 'he-IL',
  timezone: 'Asia/Jerusalem',
  
  // הגדרות קאש
  cacheDuration: 5 * 60 * 1000, // 5 דקות
  maxCacheSize: 1000,
  
  // הגדרות לוגים
  logLevel: process.env.NODE_ENV === 'development' ? 'debug' : 'error',
  
  // הגדרות UI
  theme: {
    direction: 'rtl',
    primaryColor: '#1976d2',
    secondaryColor: '#dc004e'
  }
}; 
