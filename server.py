from fastapi import FastAPI, Request
import uvicorn
import logging
from whatsapp_survey_bot import bot, handle_webhook
import multiprocessing
import subprocess
import sys
import os
import socket
import signal
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - INFO - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

def is_port_in_use(port: int) -> bool:
    """Check if a port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def kill_process_on_port(port: int):
    """Kill the process using the specified port"""
    for proc in psutil.process_iter(['pid', 'name', 'connections']):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    logger.info(f"Killing process {proc.pid} on port {port}")
                    os.kill(proc.pid, signal.SIGTERM)
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

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
        # Check if port 8501 is in use and kill the process if needed
        if is_port_in_use(8501):
            logger.info("Port 8501 is in use, attempting to kill existing process")
            if kill_process_on_port(8501):
                logger.info("Successfully killed process on port 8501")
            else:
                logger.warning("Could not kill process on port 8501")

        # Run streamlit directly without importing server
        os.environ["STREAMLIT_SERVER_PORT"] = "8501"  # Ensure consistent port
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py"],
                        env=dict(os.environ))
    except Exception as e:
        logger.error(f"Error starting Streamlit: {e}")

def main():
    """Main function to run both services"""
    # Check if port 8000 is in use and kill the process if needed
    if is_port_in_use(8000):
        logger.info("Port 8000 is in use, attempting to kill existing process")
        if kill_process_on_port(8000):
            logger.info("Successfully killed process on port 8000")
        else:
            logger.warning("Could not kill process on port 8000")
    
    # Start Streamlit in background
    run_streamlit()
    logger.info("Started Streamlit dashboard")
    
    # Run the FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main() 
