from fastapi import FastAPI, Request
import uvicorn
import logging
from whatsapp_survey_bot import bot, handle_webhook
import multiprocessing
import subprocess
import sys
import os

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

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

def run_streamlit():
    """Run the Streamlit dashboard"""
    try:
        # Run streamlit directly without importing server
        os.environ["STREAMLIT_SERVER_PORT"] = "8501"  # Ensure consistent port
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py"],
                        env=dict(os.environ))
    except Exception as e:
        logger.error(f"Error starting Streamlit: {e}")

def main():
    """Main function to run both services"""
    # Start Streamlit in background
    run_streamlit()
    logger.info("Started Streamlit dashboard")
    
    # Run the FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main() 
