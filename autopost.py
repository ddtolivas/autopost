"""Automatically post videos from a Google Drive folder to X (Twitter)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import tweepy


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DEFAULT_STATE_PATH = Path(".autopost_state.json")
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass
class Config:
    drive_folder_id: str
    google_service_account_file: Path
    twitter_consumer_key: str
    twitter_consumer_secret: str
    twitter_access_token: str
    twitter_access_token_secret: str
    tweet_template: str
    state_file: Path
    interval_seconds: int


def load_config(args: argparse.Namespace) -> Config:
    env = os.environ

    def require(key: str) -> str:
        value = env.get(key)
        if not value:
            raise ValueError(f"Missing required environment variable: {key}")
        return value

    interval = args.interval if args.interval is not None else int(env.get("POST_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS))
    state_file = Path(args.state_file or env.get("STATE_FILE", DEFAULT_STATE_PATH))

    return Config(
        drive_folder_id=require("GOOGLE_DRIVE_FOLDER_ID"),
        google_service_account_file=Path(require("GOOGLE_SERVICE_ACCOUNT_FILE")),
        twitter_consumer_key=require("TWITTER_CONSUMER_KEY"),
        twitter_consumer_secret=require("TWITTER_CONSUMER_SECRET"),
        twitter_access_token=require("TWITTER_ACCESS_TOKEN"),
        twitter_access_token_secret=require("TWITTER_ACCESS_TOKEN_SECRET"),
        tweet_template=env.get("TWEET_TEMPLATE", "{filename}"),
        state_file=state_file,
        interval_seconds=interval,
    )


def build_drive_service(credentials_file: Path):
    credentials = service_account.Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)


def build_twitter_clients(config: Config):
    auth = tweepy.OAuth1UserHandler(
        config.twitter_consumer_key,
        config.twitter_consumer_secret,
        config.twitter_access_token,
        config.twitter_access_token_secret,
    )
    api_v1 = tweepy.API(auth)

    client_v2 = tweepy.Client(
        consumer_key=config.twitter_consumer_key,
        consumer_secret=config.twitter_consumer_secret,
        access_token=config.twitter_access_token,
        access_token_secret=config.twitter_access_token_secret,
        wait_on_rate_limit=True,
    )
    return api_v1, client_v2


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"posted_ids": []}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def list_drive_videos(service, folder_id: str) -> list[dict[str, str]]:
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        "mimeType contains 'video/'"
    )
    results = service.files().list(
        q=query,
        fields="files(id,name,mimeType,createdTime)",
        orderBy="createdTime",
        pageSize=100,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return results.get("files", [])


def download_drive_file(service, file_id: str, out_path: Path) -> None:
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with out_path.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def post_video(api_v1, client_v2, file_path: Path, tweet_text: str) -> str:
    media = api_v1.media_upload(filename=str(file_path), media_category="tweet_video", chunked=True)
    response = client_v2.create_tweet(text=tweet_text, media_ids=[media.media_id])
    return str(response.data["id"])


def pick_unposted(videos: list[dict[str, str]], posted_ids: set[str]) -> dict[str, str] | None:
    for video in videos:
        if video["id"] not in posted_ids:
            return video
    return None


def run_once(config: Config) -> bool:
    logging.info("Checking Google Drive folder for new videos...")
    drive = build_drive_service(config.google_service_account_file)
    api_v1, client_v2 = build_twitter_clients(config)

    state = load_state(config.state_file)
    posted_ids = set(state.get("posted_ids", []))

    videos = list_drive_videos(drive, config.drive_folder_id)
    video = pick_unposted(videos, posted_ids)

    if not video:
        logging.info("No unposted videos found.")
        return False

    filename = video["name"]
    file_id = video["id"]

    with tempfile.TemporaryDirectory(prefix="autopost_") as temp_dir:
        local_path = Path(temp_dir) / filename
        logging.info("Downloading '%s' from Drive...", filename)
        download_drive_file(drive, file_id, local_path)

        tweet_text = config.tweet_template.format(filename=filename, file_id=file_id)
        logging.info("Uploading and posting '%s' to X...", filename)
        tweet_id = post_video(api_v1, client_v2, local_path, tweet_text)

    posted_ids.add(file_id)
    state["posted_ids"] = sorted(posted_ids)
    save_state(config.state_file, state)

    logging.info("Posted successfully. Tweet ID: %s", tweet_id)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--interval", type=int, default=None, help="Seconds between runs (default 86400).")
    parser.add_argument("--state-file", default=None, help="Path to JSON state file.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

    try:
        config = load_config(args)
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 1

    if args.run_once:
        run_once(config)
        return 0

    logging.info("Starting autopost loop. Interval: %s seconds", config.interval_seconds)
    while True:
        try:
            run_once(config)
        except Exception:
            logging.exception("Autopost cycle failed")
        time.sleep(config.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
