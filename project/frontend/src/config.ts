const isDevelopment = process.env.NODE_ENV === 'development';

export const config = {
  apiBaseUrl: isDevelopment 
    ? 'http://localhost:8000/api'
    : 'https://whatsapp-bot-api.onrender.com/api',
  
  // Add other configuration settings here
}; 
