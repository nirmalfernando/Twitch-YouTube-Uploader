# Twitch VOD Downloader and YouTube Uploader for Google Colab

This project is a Colab-based Python script to download Twitch VODs in chunks and upload them directly to YouTube. It’s designed to bypass Colab’s limited storage by downloading, uploading, and cleaning up each chunk sequentially.

## Features
- **Twitch VOD Download:** Fetches and splits long Twitch VODs into manageable chunks.
- **YouTube Upload:** Uploads each chunk to YouTube with automatic metadata and quality info.
- **Dynamic Quality Selection:** Automatically chooses the best available Twitch stream quality.
- **Error Handling & Retrying:** Handles Twitch and YouTube API errors with exponential backoff.
- **File Cleanup:** Removes downloaded files after upload to manage Colab’s storage.

## Libraries Used
This script leverages several powerful libraries and tools:
- **`requests`**: Handles HTTP requests to interact with Twitch and YouTube APIs.
- **`json`**: Parses JSON data from API responses.
- **`googleapiclient.discovery`**: Provides access to the YouTube Data API.
- **`google_auth_oauthlib.flow`**: Manages OAuth2 authentication flow.
- **`pickle`**: Serializes and saves user authentication tokens.
- **`os`**: Handles file operations and system commands.
- **`re`**: Performs regex operations for cleaning up video titles.
- **`time`**: Implements retry and delay mechanisms.
- **`streamlink`**: A command-line utility that extracts video streams from online services like Twitch and pipes them into video players or files. It’s used here to download Twitch VODs efficiently.
- **`ffmpeg`**: A powerful multimedia framework used for processing, converting, and streaming audio and video. It’s used in this project to check video resolution and bitrate after downloading.

## Requirements
1. Google Colab environment.
2. Twitch API credentials:
   - `TWITCH_CLIENT_ID`
   - `TWITCH_CLIENT_SECRET`
3. Google Cloud Console project with YouTube Data API enabled.
4. OAuth client secrets JSON file (`client_secrets.json`).

## Setup
### 1. Get Twitch API credentials
1. Go to [Twitch Developer Console](https://dev.twitch.tv/console/apps)
2. Click on **Register Your Application**.
3. Fill in the following details:
   - **Name:** Choose a name for your app.
   - **OAuth Redirect URLs:** Use `http://localhost`
   - **Category:** Choose "Other".
4. After registering, you will get your `Client ID`.
5. Click on **Manage** for your app and then click **New Secret** to get your `Client Secret`.

### 2. Get YouTube client_secrets.json
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one.
3. In the sidebar, go to **APIs & Services > Library** and enable **YouTube Data API v3**.
4. Go to **APIs & Services > Credentials**.
5. Click **Create Credentials > OAuth client ID**.
6. Select **Web application** as the application type.
7. Under **Authorized redirect URIs**, add `http://localhost/`.
8. Click **Create** and download the JSON file.
9. Rename the file to `client_secrets.json` and upload it to Colab’s working directory.

### 3. Copy the `.ipynb` file
Open this notebook and copy its contents into a Colab notebook of your own.

## Usage
1. **Enter Twitch VOD ID or URL:** When prompted, enter the Twitch video ID or the full URL.
2. **Authorize YouTube Access:** Follow the manual flow and paste the redirect URL when requested.
3. **Confirm Download & Upload:** Confirm when prompted to proceed.

## File Structure
- `client_secrets.json`: Google OAuth credentials.
- `youtube_token.pickle`: Saved YouTube API access token.
- Downloaded video chunks in `.mp4` format.
- Upload logs and download logs.

## Troubleshooting
- **`client_secrets.json` not found:** Ensure the file is uploaded to Colab and named correctly.
- **YouTube token expired:** Delete `youtube_token.pickle` and re-authenticate.
- **Twitch API error:** Ensure Twitch API credentials are correct and valid.

## Contributing
Feel free to open issues or submit pull requests for improvements.
