import os
import random
import io
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth import default
from google.oauth2 import service_account
from config import logger, DRIVE_FOLDER_ID

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    # If a direct JSON string is provided in the environment (useful for cloud deployments)
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_str:
        try:
            creds_info = json.loads(creds_json_str)
            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=SCOPES)
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            logger.error(f"Failed to parse GOOGLE_CREDENTIALS_JSON: {e}")

    # If GOOGLE_APPLICATION_CREDENTIALS is set and points to a file, use service_account
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and os.path.exists(creds_path):
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES)
    else:
        # Fallback to default credentials (works well in cloud environments)
        creds, _ = default(scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_random_video(download_path="raw_video.mp4"):
    """
    Selects a random video from the configured Google Drive folder
    and downloads it to download_path.
    """
    if not DRIVE_FOLDER_ID:
        raise ValueError("DRIVE_FOLDER_ID is not set in config.")
        
    service = get_drive_service()
    
    # Search for video files in the folder
    query = f"'{DRIVE_FOLDER_ID}' in parents and mimeType contains 'video/' and trashed = false"
    
    results = service.files().list(
        q=query,
        pageSize=100,
        fields="nextPageToken, files(id, name)"
    ).execute()
    
    items = results.get('files', [])
    
    if not items:
        logger.error(f"No video files found in folder {DRIVE_FOLDER_ID}.")
        return None
        
    # Select random file
    selected_file = random.choice(items)
    file_id = selected_file['id']
    file_name = selected_file['name']
    
    logger.info(f"Selected random video: {file_name} ({file_id})")
    
    # Download the file
    request = service.files().get_media(fileId=file_id)
    with open(download_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                logger.info(f"Downloading {file_name}: {int(status.progress() * 100)}%.")
                
    logger.info(f"Downloaded {file_name} to {download_path}")
    return download_path
