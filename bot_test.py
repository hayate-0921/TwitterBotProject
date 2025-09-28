# bot_test.py — 最小の認証／接続テスト（リツイートはしない、安全な確認用）
import os
import sys
import logging
from datetime import datetime
import tweepy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bot-test")

API_KEY = os.environ.get("API_KEY")
API_KEY_SECRET = os.environ.get("API_KEY_SECRET")  # ワークフローで定義した名前と一致させること
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")

if not all([API_KEY, API_KEY_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
    logger.error("One or more required env vars are missing.")
    sys.exit(2)

try:
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_KEY_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True
    )
    me = client.get_me().data
    logger.info(f"Authenticated as id={me.id}, username={getattr(me,'username',None)}")
    # オプションでホームタイムラインの直近数件を取得して内容をログに出す
    tl = client.get_home_timeline(max_results=10, tweet_fields=["id","text","created_at"])
    tweets = tl.data or []
    logger.info(f"Retrieved {len(tweets)} tweets from home timeline (sample):")
    for t in tweets[:5]:
        logger.info(f"- [{t.id}] {t.text[:140].replace('\\n',' ')}")
    logger.info("Auth & timeline test completed successfully.")
except Exception as e:
    logger.exception("API call failed: %s", e)
    sys.exit(1)
