import os
from video_processor import process_video
from config import logger

def test_processor():
    input_video = "sample.mp4"
    output_video = "output_sample.mp4"
    quote = "The only way to do great work is to love what you do. - Steve Jobs"
    
    if not os.path.exists(input_video):
        logger.error(f"Please place a video named '{input_video}' in this directory to test.")
        return
        
    logger.info(f"Testing video processing with quote: {quote}")
    success = process_video(input_video, output_video, quote)
    
    if success:
        logger.info(f"Success! Output saved to {output_video}")
    else:
        logger.error("Failed to process video.")

if __name__ == "__main__":
    test_processor()
