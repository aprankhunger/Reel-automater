import os
from dotenv import load_dotenv
import logging

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

# Configure logging
log_dir = "/home/LogFiles"
if not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True)
    except:
        pass # fallback for local testing
log_file = os.path.join(log_dir, "bot.log") if os.path.exists(log_dir) else "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
