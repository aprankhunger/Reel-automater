import asyncio
import os
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from config import TELEGRAM_BOT_TOKEN, logger
from storage import get_random_video
from video_processor import process_video

# Initialize bot safely, fallback to a dummy token so it doesn't crash on import
# We handle the missing token later in main()
_token = TELEGRAM_BOT_TOKEN if TELEGRAM_BOT_TOKEN else "123456789:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQR"
bot = Bot(token=_token)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Welcome to the Reel Automater Bot! 🎬\n\n"
        "Send me a quote or a sentence, and I will generate a custom cinematic short video for you."
    )

@dp.message()
async def handle_quote(message: types.Message):
    quote = message.text
    if not quote:
        return
        
    status_msg = await message.answer("🎬 Finding a cinematic video...")
    
    # Use the running event loop to run blocking IO/FFmpeg calls in an executor
    loop = asyncio.get_running_loop()
    
    unique_id = uuid.uuid4().hex[:8]
    raw_video_path = f"raw_{unique_id}.mp4"
    processed_video_path = f"processed_{unique_id}.mp4"
    
    try:
        # Download random video from Google Drive
        downloaded = await loop.run_in_executor(None, get_random_video, raw_video_path)
        
        if not downloaded:
            await status_msg.edit_text("❌ No videos found in the storage.")
            return

        await status_msg.edit_text("✨ Processing video and applying cinematic effects...")
        
        # Process video with FFmpeg
        success = await loop.run_in_executor(
            None, 
            process_video, 
            raw_video_path, 
            processed_video_path, 
            quote
        )
        
        if not success:
            raise Exception("Video processing failed. Check server logs.")
            
        await status_msg.edit_text("📤 Uploading your customized reel...")
        
        # Send video back to the user
        video = FSInputFile(processed_video_path)
        await bot.send_video(
            chat_id=message.chat.id,
            video=video,
            caption="Here is your cinematic reel! 🎥"
        )
        
        # Cleanup the status message
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Error handling request: {e}")
        await status_msg.edit_text(f"❌ An error occurred: {str(e)}\nPlease try again later.")
    finally:
        # Cleanup temporary files
        if os.path.exists(raw_video_path):
            os.remove(raw_video_path)
        if os.path.exists(processed_video_path):
            os.remove(processed_video_path)

async def main():
    logger.info("Starting bot...")
    await dp.start_polling(bot)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Starting health check server on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    # Start dummy web server for Azure App Service health checks
    threading.Thread(target=start_health_server, daemon=True).start()
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in environment. Bot polling will not start, but health server is running.")
        # Keep the main thread alive so the health server can run
        import time
        while True:
            time.sleep(3600)
    else:
        asyncio.run(main())
