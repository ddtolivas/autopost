"""Automatically post videos from a local folder to X (Twitter)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tweepy

DEFAULT_STATE_PATH = Path(".autopost_state.json")
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@dataclass
class Config:
    videos_folder: Path
    twitter_consumer_key: str
    twitter_consumer_secret: str
    twitter_access_token: str
    twitter_access_token_secret: str
    caption: str
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
    caption = args.caption if args.caption is not None else env.get("POST_CAPTION", "")

    return Config(
        videos_folder=Path(require("LOCAL_VIDEO_FOLDER")).expanduser().resolve(),
        twitter_consumer_key=require("TWITTER_CONSUMER_KEY"),
        twitter_consumer_secret=require("TWITTER_CONSUMER_SECRET"),
        twitter_access_token=require("TWITTER_ACCESS_TOKEN"),
        twitter_access_token_secret=require("TWITTER_ACCESS_TOKEN_SECRET"),
        caption=caption,
        state_file=state_file,
        interval_seconds=interval,
    )


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
        return {"posted_files": []}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def list_local_videos(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"LOCAL_VIDEO_FOLDER does not exist or is not a directory: {folder}")

    videos = [
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(videos, key=lambda p: p.stat().st_mtime)


def post_video(api_v1, client_v2, file_path: Path, caption: str) -> str:
    media = api_v1.media_upload(filename=str(file_path), media_category="tweet_video", chunked=True)
    response = client_v2.create_tweet(text=caption, media_ids=[media.media_id])
    return str(response.data["id"])


def pick_unposted(videos: list[Path], posted_files: set[str]) -> Path | None:
    for video in videos:
        if str(video) not in posted_files:
            return video
    return None


def run_once(config: Config) -> bool:
    logging.info("Checking local folder for new videos: %s", config.videos_folder)
    api_v1, client_v2 = build_twitter_clients(config)

    state = load_state(config.state_file)
    posted_files = set(state.get("posted_files", []))

    videos = list_local_videos(config.videos_folder)
    video = pick_unposted(videos, posted_files)

    if not video:
        logging.info("No unposted videos found.")
        return False

    logging.info("Uploading and posting '%s' to X...", video.name)
    tweet_id = post_video(api_v1, client_v2, video, config.caption)

    posted_files.add(str(video))
    state["posted_files"] = sorted(posted_files)
    save_state(config.state_file, state)

    logging.info("Posted successfully. Tweet ID: %s", tweet_id)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--interval", type=int, default=None, help="Seconds between runs (default 86400).")
    parser.add_argument("--caption", default=None, help="Custom caption text to use for every post.")
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
