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
        subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py"], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running Streamlit: {e}")
    except Exception as e:
        logger.error(f"Unexpected error running Streamlit: {e}")

if __name__ == "__main__":
    # Start Streamlit in a separate process
    streamlit_process = multiprocessing.Process(target=run_streamlit)
    streamlit_process.start()
    logger.info("Started Streamlit dashboard")
    
    try:
        # Run the FastAPI server
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        # Cleanup when the FastAPI server stops
        streamlit_process.terminate()
        streamlit_process.join()
        logger.info("Stopped Streamlit dashboard") 
