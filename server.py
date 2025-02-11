from fastapi import FastAPI, Request, HTTPException
import uvicorn
import logging
import os
from whatsapp_survey_bot import bot, handle_webhook
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - INFO - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    """Handle incoming webhooks from Green API"""
    try:
        webhook_data = await request.json()
        logger.info(f"Received webhook: {webhook_data}")
        await handle_webhook(webhook_data)
        return {"status": "OK"}
    except Exception as e:
        logger.error(f"Error in webhook handler: {str(e)}")
        return {"status": "Error", "message": str(e)}

@app.get("/oauth2callback")
async def oauth2callback(code: str, state: str = None):
    """Handle OAuth2 callback from Google"""
    try:
        # Extract user_id from state if provided
        user_id = state or 'default'
        
        # Handle the OAuth callback
        success = await bot.calendar_manager.handle_oauth_callback(user_id, code)
        
        if success:
            return {"status": "success", "message": "Authentication successful"}
        else:
            raise HTTPException(status_code=400, detail="Authentication failed")
            
    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/calendar/auth")
async def start_auth(user_id: str = 'default'):
    """Start OAuth2 authentication flow"""
    try:
        # Check if already authenticated
        if bot.calendar_manager.ensure_authenticated(user_id):
            return {"status": "success", "message": "Already authenticated"}
            
        # Start auth flow
        auth_url = bot.calendar_manager.start_auth_flow(user_id)
        
        # Add state parameter with user_id
        params = {
            'state': user_id
        }
        redirect_url = f"{auth_url}&{urlencode(params)}"
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        logger.error(f"Error starting auth: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    # Get port from environment variable (Render.com sets this)
    port = int(os.environ.get("PORT", 8003))
    
    # Log the port being used
    logger.info(f"Starting server on port {port}")
    
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=port) 
