import os
import re
import json
import time
import logging
from datetime import datetime, timedelta
import tweepy
from dotenv import load_dotenv

# =========================================================
# 環境変数読み込みと型変換
# =========================================================
def load_env_var(name: str, var_type: str):
    """
    指定した型で環境変数を取得する。
    - name: 環境変数名
    - var_type: "str" | "int" | "bool" | "float"
    """
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"環境変数 '{name}' が設定されていません。")

    if var_type == "int":
        return int(value)
    elif var_type == "float":
        return float(value)
    elif var_type == "bool":
        return value.lower() in ("true", "1", "yes", "y", "t")
    elif var_type == "str":
        return value.strip()
    else:
        raise ValueError(f"サポートされていない型指定です: {var_type}")

# =========================================================
# Tweepy クライアント生成
# =========================================================
def create_client():
    """
    GitHub Secrets で管理されている認証トークンを使用してクライアントを作成。
    """
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    if not all([bearer_token, api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("必要なAPIキーまたはトークンが環境変数に設定されていません。")

    client = tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
        wait_on_rate_limit=True
    )
    return client

# =========================================================
# ログ設定
# =========================================================
def setup_logger(log_level: str):
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="[%(asctime)s] %(levelname)s: %(message)s")

# =========================================================
# 状態ファイル操作
# =========================================================
def load_state(state_file: str):
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state_file: str, state_data: dict):
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, ensure_ascii=False, indent=2)

# =========================================================
# ツイート検索処理
# =========================================================
def search_tweets(client, query: str, lookback_hours: int, max_results: int):
    start_time = datetime.utcnow() - timedelta(hours=lookback_hours)
    tweets = client.search_recent_tweets(
        query=query,
        tweet_fields=["id", "text", "author_id", "created_at"],
        max_results=max_results
    )
    if tweets.data is None:
        return []
    return [t for t in tweets.data if t.created_at >= start_time]

# =========================================================
# Retweet 実行
# =========================================================
def retweet_tweets(client, tweets, state_data, max_retweets: int, dry_run: bool):
    retweeted_count = 0
    for tweet in tweets:
        if str(tweet.id) in state_data.get("retweeted_ids", []):
            continue

        logging.info(f"対象ツイート: https://twitter.com/i/web/status/{tweet.id}")

        if not dry_run:
            try:
                client.retweet(tweet.id)
                logging.info("→ Retweet 成功")
            except Exception as e:
                logging.error(f"Retweet 失敗: {e}")
                continue
        else:
            logging.info("DRY_RUN モードのためRetweetは実行されません")

        state_data.setdefault("retweeted_ids", []).append(str(tweet.id))
        retweeted_count += 1
        if retweeted_count >= max_retweets:
            break
    return retweeted_count

# =========================================================
# main
# =========================================================
def main():
    # .env (config.env) の読み込み
    load_dotenv("config.env")

    # --- 環境変数読み込みと型変換 ---
    KEYWORDS = load_env_var("KEYWORDS", "str")
    POLL_MAX_RESULTS = load_env_var("POLL_MAX_RESULTS", "int")
    MAX_RETWEETS_PER_RUN = load_env_var("MAX_RETWEETS_PER_RUN", "int")
    DRY_RUN = load_env_var("DRY_RUN", "bool")
    LOOKBACK_HOURS = load_env_var("LOOKBACK_HOURS", "int")
    LOG_LEVEL = load_env_var("LOG_LEVEL", "str")
    STATE_FILE = load_env_var("STATE_FILE", "str")

    setup_logger(LOG_LEVEL)
    logging.info("Bot 実行開始")

    client = create_client()
    state_data = load_state(STATE_FILE)

    # 検索クエリ作成
    query = f"({KEYWORDS}) -is:retweet"

    # ツイート検索
    tweets = search_tweets(client, query, LOOKBACK_HOURS, POLL_MAX_RESULTS)
    logging.info(f"検索ヒット数: {len(tweets)}")

    # Retweet実行
    count = retweet_tweets(client, tweets, state_data, MAX_RETWEETS_PER_RUN, DRY_RUN)
    logging.info(f"実行済みRetweet数: {count}")

    # 状態ファイル更新
    save_state(STATE_FILE, state_data)
    logging.info("Bot 実行終了")

if __name__ == "__main__":
    main()
