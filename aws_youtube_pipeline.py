import os
import requests
import json
import re
import pickle
import random
import sys
import time
import subprocess
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from oauth2client.file import Storage

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
PART_MAX_RETRIES = 3  # Maximum retries for a failed video part

# Install required tools in Colab
def install_dependencies():
    print("Installing required dependencies...")
    os.system("pip install -q google-auth-oauthlib oauth2client")
    os.system("apt-get -qq update")
    os.system("apt-get -qq install -y ffmpeg")
    print("Dependencies installed.")

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
        clean_title = "VideoDownload"

    file_name = clean_title.replace(' ', '_')

    if len(file_name) > 200:
        file_name = file_name[:200]

    return file_name

# Function to get video information (duration, resolution, etc.)
def get_video_info(video_path):
    """
    Extract video information using ffprobe

    Args:
        video_path: Path to video file

    Returns:
        dict: Dictionary containing video information
    """
    try:
        # Get video duration
        cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        duration_output = subprocess.check_output(cmd, shell=True, text=True).strip()
        duration = float(duration_output)

        # Get video resolution
        cmd = f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "{video_path}"'
        resolution = subprocess.check_output(cmd, shell=True, text=True).strip()

        # Get video bitrate
        cmd = f'ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        bitrate_output = subprocess.check_output(cmd, shell=True, text=True).strip()
        bitrate = int(bitrate_output) if bitrate_output else None

        # Get file size
        file_size = os.path.getsize(video_path)

        return {
            'duration': duration,
            'duration_formatted': format_duration(int(duration)),
            'resolution': resolution,
            'bitrate': bitrate,
            'bitrate_mbps': bitrate / 1000000 if bitrate else None,
            'file_size': file_size,
            'file_size_mb': file_size / (1024 * 1024)
        }
    except Exception as e:
        print(f"Error getting video info: {str(e)}")
        # Return some defaults if we can't get the info
        return {
            'duration': 0,
            'duration_formatted': "Unknown",
            'resolution': "Unknown",
            'bitrate': None,
            'bitrate_mbps': None,
            'file_size': 0,
            'file_size_mb': 0
        }

# Function to download a video from a direct URL
def download_video(url, output_path, timeout=3600):
    """
    Download a video from a direct URL using requests with streaming

    Args:
        url: Direct URL to the video
        output_path: Where to save the video
        timeout: Timeout in seconds (default 1 hour)

    Returns:
        bool: True if download was successful
    """
    try:
        print(f"Downloading video from: {url}")
        print(f"Saving to: {output_path}")

        # Download with progress tracking
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()  # Check if download went OK

        # Get the total file size if available
        total_size = int(response.headers.get('content-length', 0))

        if total_size:
            print(f"File size: {total_size / (1024 * 1024):.2f} MB")
        else:
            print("File size: Unknown")

        # Download the file in chunks with progress tracking
        downloaded = 0
        progress_pct = 0

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192*1024):  # 8MB chunks
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size:
                        new_progress_pct = int(downloaded / total_size * 100)
                        if new_progress_pct > progress_pct:
                            progress_pct = new_progress_pct
                            print(f"Downloaded: {progress_pct}% ({downloaded / (1024 * 1024):.2f} MB)")

        # Verify the file was downloaded successfully
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            final_size = os.path.getsize(output_path) / (1024 * 1024)
            print(f"Download complete. Final file size: {final_size:.2f} MB")
            return True
        else:
            print("Download appears to have failed. The file is empty or missing.")
            return False

    except Exception as e:
        print(f"Error downloading video: {str(e)}")
        return False

# Function to split video file at specific time points using ffmpeg
def split_video(input_file, output_base, start_time, duration, attempt=1):
    """
    Split a video file into chunks using ffmpeg

    Args:
        input_file: Path to input video file
        output_base: Base filename for output (without extension)
        start_time: Start time in seconds
        duration: Duration to extract in seconds
        attempt: Attempt number (for naming)

    Returns:
        str: Path to the created file
    """
    output_file = f"{output_base}_attempt_{attempt}.mp4"

    try:
        print(f"Splitting video from {format_duration(start_time)} for {format_duration(duration)}")
        print(f"Output file: {output_file}")

        # Use ffmpeg to extract the segment
        cmd = f'ffmpeg -y -ss {start_time} -i "{input_file}" -t {duration} -c copy "{output_file}" -loglevel warning'
        print(f"Running: {cmd}")

        subprocess.check_call(cmd, shell=True)

        # Verify the file was created successfully
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            file_size = os.path.getsize(output_file) / (1024*1024)
            print(f"Split successful. File size: {file_size:.2f} MB")
            return output_file
        else:
            print("Split appears to have failed. Output file is empty or missing.")
            return None

    except Exception as e:
        print(f"Error splitting video: {str(e)}")
        return None

# Function to calculate splits for a video
def calculate_splits(duration):
    if duration <= MAX_DURATION:
        return [duration]
    parts = int(duration // MAX_DURATION)
    remainder = duration % MAX_DURATION
    if remainder < MAX_DURATION * 0.05:
        balanced_part = duration // (parts + 1)
        return [balanced_part] * (parts + 1)
    return [MAX_DURATION] * parts + ([remainder] if remainder else [])

# Format duration for display
def format_duration(seconds):
    hours = int(seconds) // 3600
    minutes = (int(seconds) % 3600) // 60
    secs = int(seconds) % 60
    return f"{hours}h {minutes}m {secs}s"

# Function to upload to YouTube with quality info
def upload_to_youtube(file_path, title, description=None, tags=None, privacy="private", youtube_service=None, video_info=None):
    if description is None:
        description = 'Uploaded video'
    if tags is None:
        tags = ['Video', 'Upload']
    if video_info is None:
        video_info = {}

    clean_title = title[:100]  # YouTube title limit is 100 characters

    youtube = youtube_service
    if youtube is None:
        youtube = get_youtube_service()

    print(f"Preparing to upload: {file_path}")
    print(f"Title: {clean_title}")

    # Check if the file exists
    if not os.path.exists(file_path):
        raise Exception(f"File not found: {file_path}")

    # Get file size for progress reporting
    file_size = os.path.getsize(file_path)
    print(f"File size: {file_size / (1024*1024):.2f} MB")

    # Update description with video info if available
    if video_info:
        tech_info = "\n\nVideo Technical Information:\n"
        if "resolution" in video_info:
            tech_info += f"Resolution: {video_info['resolution']}\n"
        if "file_size_mb" in video_info:
            tech_info += f"File size: {video_info['file_size_mb']:.2f} MB\n"
        if "duration_formatted" in video_info:
            tech_info += f"Duration: {video_info['duration_formatted']}\n"
        description += tech_info

    # Define the body of the request
    body = {
        'snippet': {
            'title': clean_title,
            'description': description,
            'tags': tags,
            'categoryId': '22'  # People & Blogs category
        },
        'status': {
            'privacyStatus': privacy,
            'status.madeForKids': False
        }
    }

    # Create the media upload object
    media = MediaFileUpload(
        file_path,
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

# Function to process a single video part
def process_video_part(part_num, total_parts, title, input_file, start_time, duration, description_base, tags, youtube_service):
    """
    Process a single video part with retry logic

    Args:
        part_num: Part number (1-based)
        total_parts: Total number of parts
        title: Base title for the video
        input_file: Path to the input video file
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
    print(f"Extract chunk starting at {format_duration(start_time)} for {format_duration(duration)}")

    # Track files created for this part
    part_files_to_cleanup = []

    # Generate a consistent base file name for this part
    base_file_name = f"{clean_title_for_file(title)}_part_{part_num}"

    # Try to process this part up to PART_MAX_RETRIES times
    attempt = 1
    while attempt <= PART_MAX_RETRIES:
        print(f"\nAttempt {attempt} of {PART_MAX_RETRIES} for part {part_num}")
        split_file = None

        try:
            # Split the video using ffmpeg
            split_file = split_video(input_file, base_file_name, start_time, duration, attempt)

            if not split_file:
                raise Exception("Failed to split video - output file missing or empty")

            # Add to cleanup list
            part_files_to_cleanup.append(split_file)

            # Get video info for this chunk
            chunk_video_info = get_video_info(split_file)

            # Update description with technical info
            tech_description = f"\n\nTechnical Information:\n"
            tech_description += f"Video resolution: {chunk_video_info['resolution']}\n"
            tech_description += f"File size: {chunk_video_info['file_size_mb']:.2f} MB\n"
            tech_description += f"Segment: {format_duration(start_time)} to {format_duration(start_time + duration)}"

            full_description = part_description + tech_description

            # Upload this chunk
            print(f"\nUploading part {part_num} to YouTube...")
            video_id, upload_log_path = upload_to_youtube(
                split_file,
                part_full_title,
                full_description,
                tags=tags,
                youtube_service=youtube_service,
                video_info=chunk_video_info
            )

            if upload_log_path:
                part_files_to_cleanup.append(upload_log_path)

            # Clean up after successful upload
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

# Main function to process an AWS/direct URL video
def process_aws_video(url, title=None, youtube_service=None, specific_parts=None):
    try:
        # Generate a clean filename from the URL if no title is provided
        if not title:
            # Extract filename from URL
            url_filename = url.split('/')[-1].split('?')[0]
            # Remove extension
            title = os.path.splitext(url_filename)[0]
            # Clean it up
            title = title.replace('-', ' ').replace('_', ' ')
            # Capitalize words
            title = ' '.join(word.capitalize() for word in title.split())

        clean_name = clean_title_for_file(title)
        temp_video_path = f"{clean_name}_full.mp4"

        # Download the complete video
        print(f"Downloading video from AWS URL: {url}")
        download_success = download_video(url, temp_video_path)

        if not download_success:
            print("Failed to download video. Aborting.")
            return False

        # Get video metadata
        print("Getting video information...")
        video_info = get_video_info(temp_video_path)
        duration = video_info['duration']

        print(f"\nVideo Information:")
        print(f"Title: {title}")
        print(f"Duration: {video_info['duration_formatted']}")
        print(f"Resolution: {video_info['resolution']}")
        if video_info['bitrate_mbps']:
            print(f"Bitrate: {video_info['bitrate_mbps']:.2f} Mbps")
        print(f"File size: {video_info['file_size_mb']:.2f} MB")

        # Calculate splits if needed
        splits = calculate_splits(duration)
        if len(splits) > 1:
            print(f"\nVideo will be split into {len(splits)} parts due to length")
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
        confirmation = input("\nProceed with processing and upload? (y/n): ")
        if confirmation.lower() != 'y':
            print("Operation cancelled by user.")
            return False

        # Generate base description with video information
        description_base = f"""
Video Title: {title}
Original URL: {url}
Resolution: {video_info['resolution']}
Duration: {video_info['duration_formatted']}

This video was automatically uploaded using AWS Video Downloader.
        """.strip()

        # Generate meaningful tags
        tags = ['Video', 'Upload', 'AWS']

        # Process the selected parts
        part_results = []  # Store results for all parts

        for part_index in specific_parts:
            # Convert to 0-based index for calculations
            i = part_index - 1

            # Calculate start time for this part
            start_time = sum(splits[:i])
            split_duration = splits[i]

            # Process this part with retry logic
            result = process_video_part(
                part_num=part_index,
                total_parts=len(splits),
                title=title,
                input_file=temp_video_path,
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
                    retry_result = process_video_part(
                        part_num=part_index,
                        total_parts=len(splits),
                        title=title,
                        input_file=temp_video_path,
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

        # Clean up the original downloaded file
        try:
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                print(f"Removed temporary file: {temp_video_path}")
        except Exception as e:
            print(f"Error removing temporary file: {str(e)}")

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
        print(f"\nError processing video: {str(e)}")
        return False

# Main program for Colab
def main():
    print("==== AWS Video Downloader and YouTube Uploader for Colab ====")
    print("This program will download videos from AWS/direct URLs in chunks and upload them to YouTube.")
    print("Optimized for Colab's limited storage: Each chunk is processed and deleted before the next.")

    # Install dependencies first
    install_dependencies()

    # Authenticate with YouTube once (reuse the service)
    try:
        youtube_service = get_youtube_service()
    except Exception as e:
        print(f"Error during initial authentication: {str(e)}")
        print("You can still try to process videos, authentication will be attempted again.")
        youtube_service = None

    while True:
        # Get video URL from user
        print("\n" + "-" * 50)
        video_url = input("Enter AWS/direct video URL (or 'q' to quit): ")

        if video_url.lower() == 'q':
            print("Exiting program. Goodbye!")
            break

        # Optional: Let user specify a custom title
        custom_title = input("Enter custom title (leave blank to use filename): ").strip()
        if not custom_title:
            custom_title = None

        # Process the video
        process_aws_video(video_url, title=custom_title, youtube_service=youtube_service)

if __name__ == "__main__":
    main()