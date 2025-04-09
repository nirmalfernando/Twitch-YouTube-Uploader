import os
import requests
import json
import re
import pickle
import random
import sys
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.colab import auth
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from oauth2client.file import Storage

# Twitch API setup (replace with your credentials)
TWITCH_CLIENT_ID = 'your_client_id'
TWITCH_CLIENT_SECRET = 'your_client_secret'

# OAuth scopes needed for YouTube uploads
YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
                 'https://www.googleapis.com/auth/youtube',
                 'https://www.googleapis.com/auth/youtube.force-ssl']

CLIENT_SECRETS_FILE = "/content/client_secrets.json"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
MAX_RETRIES = 10
VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")
REDIRECT_URI = "http://localhost/"  # Added explicit redirect URI
MAX_DURATION = 42600  # 11hr 50min 0sec in seconds
PART_MAX_RETRIES = 3  # Maximum retries for a failed VOD part

# Install required tools in Colab
def install_dependencies():
    print("Installing required dependencies...")
    os.system("pip install -q streamlink google-auth-oauthlib oauth2client")
    os.system("apt-get -qq update")
    os.system("apt-get -qq install -y ffmpeg")
    print("Dependencies installed.")

# Get Twitch API access token
def get_twitch_access_token():
    url = 'https://id.twitch.tv/oauth2/token'
    payload = {
        'client_id': TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        raise Exception(f"Failed to get Twitch access token: {response.text}")
    return response.json()['access_token']

# Function to authenticate with YouTube in Colab using manual token approach
def get_youtube_service():
    print("Authenticating with YouTube...")

    # First, check if we have a client secrets file
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"WARNING: {CLIENT_SECRETS_FILE} not found.")
        print("You need to create a project in Google Cloud Console, enable YouTube API,")
        print("and download the OAuth credentials as client_secrets.json.")
        print("Visit: https://console.cloud.google.com/apis/credentials")

        # Create instructions for user to follow
        create_client_secrets_instructions()

        # Check again after instructions
        if not os.path.exists(CLIENT_SECRETS_FILE):
            raise Exception(f"YouTube API credentials file {CLIENT_SECRETS_FILE} not found.")

    # Check for saved credentials
    creds = None
    token_file = 'youtube_token.pickle'

    # Try to load existing credentials
    if os.path.exists(token_file):
        print("Loading saved credentials...")
        with open(token_file, 'rb') as token:
            try:
                creds = pickle.load(token)
            except Exception as e:
                print(f"Error loading credentials: {e}")
                creds = None

    # If there are no valid credentials, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credentials...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh credentials: {e}")
                creds = None

        if not creds:
            print("Getting new credentials using manual flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, YOUTUBE_SCOPES,
                redirect_uri=REDIRECT_URI)

            # UPDATED: Explicitly set the redirect URI to match what was configured
            auth_url, _ = flow.authorization_url(
                prompt='consent',
                access_type='offline'
            )

            print("\n" + "=" * 70)
            print("MANUAL AUTHENTICATION REQUIRED")
            print("=" * 70)
            print("\n1. Copy the following URL and open it in your browser:")
            print("\n" + auth_url + "\n")
            print("2. Sign in with your Google account that has YouTube access")
            print("3. Allow the permissions requested")
            print("4. After authorizing, you'll be redirected to a page that might show an error")
            print("5. Copy the FULL URL from the address bar (including the 'code=' parameter)")
            print("6. Paste the FULL URL below\n")

            # Get the authorization URL from the user
            auth_response = input("Enter the full redirect URL: ")

            try:
                # Extract the code parameter from the URL
                if "code=" in auth_response:
                    code = auth_response.split("code=")[1].split("&")[0]
                else:
                    code = auth_response
            except:
                print("Could not extract authorization code from input. Using it as-is.")
                code = auth_response

            # Exchange the authorization code for credentials
            try:
                flow.fetch_token(
                    code=code,
                )
                creds = flow.credentials

                # Save the credentials for the next run
                print("Saving credentials for future use...")
                with open(token_file, 'wb') as token:
                    pickle.dump(creds, token)
                    print("Credentials saved to", token_file)
            except Exception as e:
                print(f"Error fetching token: {e}")
                print("Detailed error information:", str(e))
                raise

    print("Authentication successful!")
    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=creds)

def create_client_secrets_instructions():
    """Provides instructions for creating client_secrets.json file"""
    print("\n======= HOW TO CREATE CLIENT_SECRETS.JSON ========")
    print("1. Go to https://console.cloud.google.com/")
    print("2. Create a new project or select an existing one")
    print("3. Enable the YouTube Data API v3")
    print("4. Go to 'Credentials' and create an OAuth client ID")
    print("5. Select 'Desktop app' as the application type")
    print("6. Add 'http://localhost/' as an authorized redirect URI")
    print("7. Download the JSON file and rename it to 'client_secrets.json'")
    print("8. Upload it to this Colab notebook's working directory")
    print("====================================================\n")

    # Template file for fallback
    sample_content = {
        "installed": {
            "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
            "project_id": "YOUR_PROJECT_ID",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": "YOUR_CLIENT_SECRET",
            "redirect_uris": ["http://localhost/"]
        }
    }

    with open("client_secrets_template.json", "w") as f:
        json.dump(sample_content, f, indent=4)

    print("I've created a template file 'client_secrets_template.json'")
    print("Replace the placeholders with your actual credentials and rename to 'client_secrets.json'")

# Function to get VOD metadata from Twitch API
def get_vod_metadata(vod_id):
    access_token = get_twitch_access_token()
    url = f'https://api.twitch.tv/helix/videos?id={vod_id}'
    headers = {
        'Client-ID': TWITCH_CLIENT_ID,
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Twitch API error: {response.status_code} - {response.text}")

    data = response.json().get('data', [])
    if not data:
        raise Exception(f"No VOD found with ID: {vod_id}")

    vod_data = data[0]
    title = vod_data['title']
    duration = parse_twitch_duration(vod_data['duration'])
    return {
        'title': title,
        'duration': duration,
        'url': f'https://www.twitch.tv/videos/{vod_id}',
        'thumbnail_url': vod_data.get('thumbnail_url', ''),
        'created_at': vod_data.get('created_at', ''),
        'view_count': vod_data.get('view_count', 0),
        'user_name': vod_data.get('user_name', '')
    }

# Convert Twitch duration format to seconds
def parse_twitch_duration(duration_str):
    hours = minutes = seconds = 0
    if 'h' in duration_str:
        hours = int(duration_str.split('h')[0])
        duration_str = duration_str.split('h')[1]
    if 'm' in duration_str:
        minutes = int(duration_str.split('m')[0])
        duration_str = duration_str.split('m')[1]
    if 's' in duration_str:
        seconds = int(duration_str.split('s')[0])
    return hours * 3600 + minutes * 60 + seconds

# Function to split duration and calculate parts
def calculate_splits(duration):
    if duration <= MAX_DURATION:
        return [duration]
    parts = duration // MAX_DURATION
    remainder = duration % MAX_DURATION
    if remainder < MAX_DURATION * 0.05:
        balanced_part = duration // (parts + 1)
        return [balanced_part] * (parts + 1)
    return [MAX_DURATION] * parts + ([remainder] if remainder else [])

# Clean title for file system compatibility
def clean_title_for_file(title):
    # Remove emojis and other non-ASCII characters
    clean_title = re.sub(r'[^\x00-\x7F]+', '', title)
    # Replace problematic characters with underscores
    clean_title = re.sub(r'[^\w\s\-\.,\(\)\[\]\{\}]', '_', clean_title)
    # Remove consecutive underscores
    clean_title = re.sub(r'_+', '_', clean_title)
    # Remove leading/trailing underscores
    clean_title = clean_title.strip('_')
    # Trim whitespace
    clean_title = clean_title.strip()
    # If title is empty after cleaning, use a default
    if not clean_title or clean_title.isspace():
        clean_title = "TwitchVOD"

    file_name = clean_title.replace(' ', '_')

    if len(file_name) > 200:
        file_name = file_name[:200]

    return file_name

# Function to download a specific chunk of a VOD
def download_vod_chunk(vod_url, title, start_time, duration):
    """
    Download a specific time chunk of a Twitch VOD

    Args:
        vod_url: URL of the Twitch VOD
        title: Title to use for the file
        start_time: Start time in seconds
        duration: Duration to download in seconds

    Returns:
        tuple: (filename, quality, resolution)
    """
    clean_title = clean_title_for_file(title)

    # Format start time for streamlink
    hours = start_time // 3600
    minutes = (start_time % 3600) // 60
    seconds = start_time % 60
    start_offset = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # Create a consistent file name
    file_name = f"{clean_title}_chunk_{start_time}"
    actual_file_path = f"{file_name}.mp4"
    log_file_path = f"{file_name}_download_log.txt"

    print(f"Original title: {title}")
    print(f"Cleaned title for file: {file_name}")
    print(f"Downloading chunk starting at {start_offset} for {duration} seconds")

    # Try different quality options if one fails
    qualities = ["best", "1080p60", "1080p", "720p60", "720p", "480p", "360p", "worst"]

    # Create a log file to record the download process
    with open(log_file_path, "w") as log_file:
        log_file.write(f"Download log for: {title} (chunk at {start_offset})\n")
        log_file.write(f"VOD URL: {vod_url}\n")
        log_file.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        for quality in qualities:
            try:
                log_file.write(f"Attempting quality: {quality}\n")

                # Use streamlink with offset and duration arguments
                command = f'streamlink "{vod_url}" {quality} --hls-start-offset {start_offset} --hls-duration {duration}s -o "{file_name}.mp4"'
                print(f"Attempting to download with quality '{quality}'...")
                print(f"Executing: {command}")
                result = os.system(command)

                if result == 0 and os.path.exists(f"{file_name}.mp4") and os.path.getsize(f"{file_name}.mp4") > 0:
                    file_size = os.path.getsize(f"{file_name}.mp4") / (1024*1024)  # Size in MB
                    log_file.write(f"SUCCESS: Downloaded with quality '{quality}'\n")
                    log_file.write(f"File size: {file_size:.2f} MB\n")
                    print(f"Successfully downloaded VOD chunk with quality '{quality}'")

                    # Get video resolution using ffprobe if available
                    try:
                        resolution_cmd = f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "{file_name}.mp4"'
                        resolution = os.popen(resolution_cmd).read().strip()
                        log_file.write(f"Video resolution: {resolution}\n")
                        print(f"Video resolution: {resolution}")

                        bitrate_cmd = f'ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 "{file_name}.mp4"'
                        bitrate = os.popen(bitrate_cmd).read().strip()
                        if bitrate:
                            bitrate_mb = int(bitrate) / 1000000  # Convert to Mbps
                            log_file.write(f"Video bitrate: {bitrate_mb:.2f} Mbps\n")
                            print(f"Video bitrate: {bitrate_mb:.2f} Mbps")
                    except:
                        log_file.write("Could not determine video resolution/bitrate\n")
                        resolution = "unknown"

                    return file_name, quality, resolution
                else:
                    log_file.write(f"FAILED: Could not download with quality '{quality}'\n")
                    print(f"Failed to download with quality '{quality}', trying next option...")
            except Exception as e:
                error_msg = f"Error downloading with quality '{quality}': {str(e)}"
                log_file.write(f"{error_msg}\n")
                print(error_msg)

        log_file.write("ALL QUALITY OPTIONS FAILED\n")

    raise Exception("Failed to download VOD chunk with any quality setting")

# Function to upload to YouTube with quality info
def upload_to_youtube(file_path, title, description=None, tags=None, privacy="private", youtube_service=None, video_info=None):
    if description is None:
        description = 'Uploaded from Twitch VOD'
    if tags is None:
        tags = ['Twitch', 'VOD']
    if video_info is None:
        video_info = {}

    clean_title = title[:100]  # YouTube title limit is 100 characters

    youtube = youtube_service
    if youtube is None:
        youtube = get_youtube_service()

    print(f"Preparing to upload: {file_path}")
    print(f"Title: {clean_title}")

    # Check if the file exists
    if not os.path.exists(f"{file_path}.mp4"):
        raise Exception(f"File not found: {file_path}.mp4")

    # Get file size for progress reporting
    file_size = os.path.getsize(f"{file_path}.mp4")
    print(f"File size: {file_size / (1024*1024):.2f} MB")

    # Update description with video info if available
    if video_info:
        tech_info = "\n\nVideo Technical Information:\n"
        if "resolution" in video_info:
            tech_info += f"Resolution: {video_info['resolution']}\n"
        if "file_size_mb" in video_info:
            tech_info += f"File size: {video_info['file_size_mb']:.2f} MB\n"
        if "quality" in video_info:
            tech_info += f"Twitch quality: {video_info['quality']}\n"
        description += tech_info

    # Define the body of the request
    body = {
        'snippet': {
            'title': clean_title,
            'description': description,
            'tags': tags,
            'categoryId': '20'  # Gaming category
        },
        'status': {
            'privacyStatus': privacy,
            'status.madeForKids': False
        }
    }

    # Create the media upload object
    media = MediaFileUpload(
        f"{file_path}.mp4",
        chunksize=1024*1024*8,  # 8MB chunks
        resumable=True,
        mimetype='video/mp4'
    )

    # Create the insert request
    insert_request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )

    # This implements an exponential backoff strategy for resumable uploads
    print("Starting upload...")
    response = None
    error = None
    retry = 0
    upload_log_path = None

    while response is None:
        try:
            status, response = insert_request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")
            if response is not None:
                if 'id' in response:
                    video_id = response['id']
                    print(f"Upload complete! Video ID: {video_id}")
                    print(f"Video URL: https://youtu.be/{video_id}")

                    # Log upload details
                    upload_log_path = f"upload_log_{video_id}.txt"
                    with open(upload_log_path, "w") as log_file:
                        log_file.write(f"Upload log for: {clean_title}\n")
                        log_file.write(f"Video ID: {video_id}\n")
                        log_file.write(f"Video URL: https://youtu.be/{video_id}\n")
                        log_file.write(f"Upload time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        log_file.write(f"File size: {file_size / (1024*1024):.2f} MB\n")
                        if video_info:
                            for key, value in video_info.items():
                                log_file.write(f"{key}: {value}\n")

                    return video_id, upload_log_path
                else:
                    raise Exception(f"The upload failed with an unexpected response: {response}")
        except HttpError as e:
            error = f"An HTTP error {e.resp.status} occurred:\n{e.content}"
            if e.resp.status in [500, 502, 503, 504]:  # Retriable status codes
                pass
            else:
                raise
        except (IOError, TimeoutError) as e:
            error = f"A retriable error occurred: {e}"

        if error is not None:
            print(error)
            retry += 1
            if retry > MAX_RETRIES:
                raise Exception("No longer attempting to retry.")

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            print(f"Sleeping {sleep_seconds:.1f} seconds and then retrying...")
            time.sleep(sleep_seconds)
            error = None

# Format duration for display
def format_duration(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}h {minutes}m {secs}s"

# Clean up files after processing
def cleanup_files(file_paths):
    """
    Clean up files after successful processing

    Args:
        file_paths: List of file paths to clean up
    """
    print("\nCleaning up temporary files...")
    for file_path in file_paths:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"Removed: {file_path}")
            except Exception as e:
                print(f"Failed to remove {file_path}: {str(e)}")

# function to ensure mp4 files are cleaned up regardless of size or failure status
def ensure_mp4_cleanup(base_file_name):
    """
    Ensures any .mp4 files with the given base name are cleaned up
    regardless of their size or download status

    Args:
        base_file_name: Base file name without extension
    """
    try:
        mp4_path = f"{base_file_name}.mp4"
        if os.path.exists(mp4_path):
            file_size_mb = os.path.getsize(mp4_path) / (1024*1024)
            print(f"Cleaning up mp4 file: {mp4_path} (size: {file_size_mb:.2f} MB)")
            os.remove(mp4_path)
            print(f"Successfully removed: {mp4_path}")
        else:
            print(f"No mp4 file found at: {mp4_path}")

        # Also check for any partial downloads or temp files
        for temp_file in os.listdir():
            if temp_file.startswith(base_file_name) and temp_file.endswith('.mp4'):
                try:
                    file_size_mb = os.path.getsize(temp_file) / (1024*1024)
                    print(f"Cleaning up partial mp4 file: {temp_file} (size: {file_size_mb:.2f} MB)")
                    os.remove(temp_file)
                    print(f"Successfully removed: {temp_file}")
                except Exception as e:
                    print(f"Error removing partial file {temp_file}: {str(e)}")
    except Exception as e:
        print(f"Error while trying to remove mp4 file {base_file_name}.mp4: {str(e)}")

# Function to process a single VOD part with retry logic
def process_vod_part(part_num, total_parts, title, vod_url, start_time, duration, description_base, tags, youtube_service):
    """
    Process a single VOD part with retry logic

    Args:
        part_num: Part number (1-based)
        total_parts: Total number of parts
        title: Base title for the VOD
        vod_url: URL of the VOD
        start_time: Start time in seconds
        duration: Duration of this part in seconds
        description_base: Base description for all parts
        tags: Tags to apply to the video
        youtube_service: YouTube API service object

    Returns:
        dict: Dictionary with status (success/failed) and result (video_id or error)
    """
    part_full_title = f"{title} (Part {part_num}/{total_parts})" if total_parts > 1 else title
    part_description = f"{description_base}"
    if total_parts > 1:
        part_description += f"\n\nPart {part_num} of {total_parts}"

    print(f"\n{'='*50}")
    print(f"Processing part {part_num} of {total_parts}")
    print(f"Download chunk starting at {format_duration(start_time)} for {format_duration(duration)}")

    # Track files created for this part
    part_files_to_cleanup = []

    # Generate a consistent base file name for this part
    base_file_name = f"{clean_title_for_file(title)}_part_{part_num}"

    # Try to process this part up to PART_MAX_RETRIES times
    attempt = 1
    while attempt <= PART_MAX_RETRIES:
        print(f"\nAttempt {attempt} of {PART_MAX_RETRIES} for part {part_num}")
        downloaded_file = None

        try:
            # Generate chunk file name for this attempt (with attempt number to avoid conflicts)
            chunk_file = f"{base_file_name}_chunk_{attempt}"

            # Download this specific chunk
            downloaded_file, quality, resolution = download_vod_chunk(vod_url, f"{title}_part_{part_num}", start_time, duration)

            # Make sure we track the actual file that was created
            part_files_to_cleanup.append(f"{downloaded_file}.mp4")
            part_files_to_cleanup.append(f"{downloaded_file}_download_log.txt")

            # Add video info for this chunk
            chunk_video_info = {
                "quality": quality,
                "resolution": resolution,
                "file_size_mb": os.path.getsize(f"{downloaded_file}.mp4") / (1024*1024),
                "start_time": format_duration(start_time),
                "duration": format_duration(duration)
            }

            # Update description with technical info
            tech_description = f"\n\nTechnical Information:\n"
            tech_description += f"Downloaded with Twitch quality setting: {quality}\n"
            tech_description += f"Video resolution: {resolution}\n"
            tech_description += f"File size: {chunk_video_info['file_size_mb']:.2f} MB\n"
            tech_description += f"Segment: {format_duration(start_time)} to {format_duration(start_time + duration)}"

            full_description = part_description + tech_description

            # Upload this chunk
            print(f"\nUploading part {part_num} to YouTube...")
            video_id, upload_log_path = upload_to_youtube(
                downloaded_file,
                part_full_title,
                full_description,
                tags=tags,
                youtube_service=youtube_service,
                video_info=chunk_video_info
            )

            if upload_log_path:
                part_files_to_cleanup.append(upload_log_path)

            # Clean up after successful upload
            ensure_mp4_cleanup(downloaded_file)
            cleanup_files(part_files_to_cleanup)

            # Return success result with video ID
            return {
                "status": "success",
                "part_num": part_num,
                "video_id": video_id,
                "title": part_full_title
            }

        except Exception as e:
            error_msg = f"Error in attempt {attempt} for part {part_num}: {str(e)}"
            print(error_msg)

            # Always clean up the actual downloaded file if it exists
            if os.path.exists(f"{downloaded_file}.mp4"):
                ensure_mp4_cleanup(downloaded_file)

            # Also clean up based on the attempted chunk file name
            ensure_mp4_cleanup(chunk_file)

            # Also clean up the base file name in case it got created with that name
            ensure_mp4_cleanup(base_file_name)

            # Clean up any files from this attempt
            for file_path in part_files_to_cleanup:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"Cleaned up: {file_path}")
                    except:
                        pass

            # Clear the list for next attempt
            part_files_to_cleanup = []

            # If we've reached max retries, return failure
            if attempt >= PART_MAX_RETRIES:
                return {
                    "status": "failed",
                    "part_num": part_num,
                    "error": str(e),
                    "title": part_full_title
                }

            # Wait before retrying
            retry_wait = 5 * attempt  # Increase wait time with each attempt
            print(f"Will retry part {part_num} in {retry_wait} seconds...")
            time.sleep(retry_wait)

            # Increment attempt counter
            attempt += 1

# Process VOD in chunks
def process_vod_in_chunks(vod_id, youtube_service=None, specific_parts=None):
    try:
        # Get metadata for the VOD
        print(f"Fetching metadata for VOD ID: {vod_id}")
        metadata = get_vod_metadata(vod_id)
        title = metadata['title']
        duration = metadata['duration']
        vod_url = metadata['url']

        print(f"\nVOD Information:")
        print(f"Title: {title}")
        print(f"Channel: {metadata['user_name']}")
        print(f"Duration: {format_duration(duration)}")
        print(f"Views: {metadata['view_count']}")
        print(f"Created at: {metadata['created_at']}")

        # Calculate splits if needed
        splits = calculate_splits(duration)
        if len(splits) > 1:
            print(f"\nVOD will be split into {len(splits)} parts due to length")
            for i, split_duration in enumerate(splits):
                print(f"  Part {i+1}: {format_duration(split_duration)}")

        # Confirmation for processing specific parts or all parts
        if specific_parts is None:
            # Ask if user wants to process all parts or select specific ones
            part_selection = input("\nProcess all parts sequentially or select specific parts? (a/s): ")
            if part_selection.lower() == 's':
                parts_input = input(f"Enter part numbers to process (comma-separated, 1-{len(splits)}): ")
                try:
                    specific_parts = [int(part.strip()) for part in parts_input.split(',')]
                    # Validate part numbers
                    for part in specific_parts:
                        if part < 1 or part > len(splits):
                            print(f"Invalid part number: {part}. Must be between 1 and {len(splits)}.")
                            return False
                except ValueError:
                    print("Invalid input. Please enter numbers separated by commas.")
                    return False
            else:
                # Process all parts sequentially
                specific_parts = list(range(1, len(splits) + 1))

        # Confirm with user
        confirmation = input("\nProceed with download and upload? (y/n): ")
        if confirmation.lower() != 'y':
            print("Operation cancelled by user.")
            return False

        # Generate base description with VOD information
        description_base = f"""
Twitch VOD: {title}
Channel: {metadata['user_name']}
Original broadcast date: {metadata['created_at']}
Original URL: {vod_url}

This video was automatically uploaded from Twitch.
        """.strip()

        # Generate meaningful tags
        tags = ['Twitch', 'VOD', metadata['user_name']]

        # Add any hashtags from title as tags
        hashtags = re.findall(r'#\w+', title)
        if hashtags:
            tags.extend([tag.strip('#') for tag in hashtags])

        # Process the selected parts
        part_results = []  # Store results for all parts

        for part_index in specific_parts:
            # Convert to 0-based index for calculations
            i = part_index - 1

            # Calculate start time for this part
            start_time = sum(splits[:i])
            split_duration = splits[i]

            # Process this part with retry logic
            result = process_vod_part(
                part_num=part_index,
                total_parts=len(splits),
                title=title,
                vod_url=vod_url,
                start_time=start_time,
                duration=split_duration,
                description_base=description_base,
                tags=tags,
                youtube_service=youtube_service
            )

            # Add result to our list
            part_results.append(result)

            # If this part failed, ask the user what to do
            if result["status"] == "failed":
                print(f"\nPart {part_index} failed: {result['error']}")
                action = input("Continue with next part, retry this part, or stop? (y/r/n): ")

                if action.lower() == 'n':
                    print("Process stopped by user after failure.")
                    break
                elif action.lower() == 'r':
                    print(f"Retrying part {part_index}...")
                    # Remove the failed result before retrying
                    part_results.pop()

                    # Retry this part
                    retry_result = process_vod_part(
                        part_num=part_index,
                        total_parts=len(splits),
                        title=title,
                        vod_url=vod_url,
                        start_time=start_time,
                        duration=split_duration,
                        description_base=description_base,
                        tags=tags,
                        youtube_service=youtube_service
                    )

                    # Add the retry result
                    part_results.append(retry_result)

                    # If retry still failed, ask again
                    if retry_result["status"] == "failed":
                        print(f"\nRetry of part {part_index} also failed: {retry_result['error']}")
                        action = input("Continue with next part or stop? (y/n): ")
                        if action.lower() != 'y':
                            print("Process stopped by user after retry failure.")
                            break
                # If 'y', continue with next part (default behavior)

        # Report final results
        print("\n" + "="*70)
        print("UPLOAD SUMMARY REPORT")
        print("="*70)

        successful_parts = [part for part in part_results if part["status"] == "success"]
        failed_parts = [part for part in part_results if part["status"] == "failed"]

        print(f"\nSuccessfully uploaded {len(successful_parts)} of {len(part_results)} processed parts")

        if successful_parts:
            print("\nSUCCESSFUL UPLOADS:")
            for part in successful_parts:
                print(f"Part {part['part_num']}: https://youtu.be/{part['video_id']} - {part['title']}")

        if failed_parts:
            print("\nFAILED UPLOADS:")
            for part in failed_parts:
                print(f"Part {part['part_num']}: FAILED - {part['title']}")
                print(f"   Error: {part['error']}")

        return len(successful_parts) > 0

    except Exception as e:
        print(f"\nError processing VOD {vod_id}: {str(e)}")
        return False

# Main program for Colab
def main():
    print("==== Twitch VOD Downloader and YouTube Uploader for Colab ====")
    print("This program will download Twitch VODs in chunks and upload them to YouTube.")
    print("Optimized for Colab's limited storage: Each chunk is downloaded, uploaded, and deleted before the next.")

    # Install dependencies first
    install_dependencies()

    # Authenticate with YouTube once (reuse the service)
    try:
        youtube_service = get_youtube_service()
    except Exception as e:
        print(f"Error during initial authentication: {str(e)}")
        print("You can still try to process VODs, authentication will be attempted again.")
        youtube_service = None

    while True:
        # Get VOD ID from user
        print("\n" + "-" * 50)
        vod_input = input("Enter Twitch VOD ID or URL (or 'q' to quit): ")

        if vod_input.lower() == 'q':
            print("Exiting program. Goodbye!")
            break

        # Extract VOD ID if full URL was provided
        vod_id = vod_input
        if 'twitch.tv/videos/' in vod_input:
            vod_id = vod_input.split('twitch.tv/videos/')[1].split('?')[0]

        # Process the VOD in chunks
        process_vod_in_chunks(vod_id, youtube_service=youtube_service)

if __name__ == "__main__":
    main()