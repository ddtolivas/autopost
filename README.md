Automatically posts videos from a google drive file to twitter
Automatically post videos from a Google Drive folder to X (Twitter) once a day.

## What this script does

- Reads videos from a specific Google Drive folder (oldest first)
- Tracks which files have already been posted in a local JSON state file
- Downloads the next unposted video
- Uploads and posts it to X/Twitter
- Repeats every 24 hours (or custom interval)

## Requirements

- Python 3.10+
- A Google Cloud service account JSON key with Drive API access
- The Drive folder shared with that service account email
- X/Twitter API keys and access tokens that can upload media and post tweets

Install dependencies:

```bash
pip install -r requirements.txt
```

## Setup

1. Copy env example and set values:

```bash
cp .env.example .env
```

2. Export env vars (or load from `.env` with your preferred tool).

Required environment variables:

- `GOOGLE_DRIVE_FOLDER_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `TWITTER_CONSUMER_KEY`
- `TWITTER_CONSUMER_SECRET`
- `TWITTER_ACCESS_TOKEN`
- `TWITTER_ACCESS_TOKEN_SECRET`

Optional:

- `TWEET_TEMPLATE` (default: `{filename}`)
- `POST_INTERVAL_SECONDS` (default: `86400`)
- `STATE_FILE` (default: `.autopost_state.json`)

## Usage

Run one time:

```bash
python autopost.py --run-once
```

Run forever in a loop (once per day by default):

```bash
python autopost.py
```

Custom interval (example: every hour):

```bash
python autopost.py --interval 3600
```

## Run daily with cron (recommended)

If you prefer one run per day without a long-running process:

```cron
0 9 * * * cd /workspace/autopost && /usr/bin/python3 autopost.py --run-once >> autopost.log 2>&1
```

This example runs daily at 09:00 server time.
