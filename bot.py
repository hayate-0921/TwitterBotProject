#!/usr/bin/env python3
"""
x-retweet-bot: フォロー中の投稿からキーワードに一致する投稿を自動でリツイートする
依存: tweepy, python-dotenv (ローカル用)
注意: 実運用前に GitHub Secrets に認証情報を設定すること
"""

import os
import re
import sqlite3
import logging
import time
from datetime import datetime
from typing import List

import tweepy
from dotenv import load_dotenv

# ローカル実行時のみ .env を読み込む（GitHub Actions 等では環境変数が入っている想定）
load_dotenv()

# ---- 設定（環境変数） ----
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")

KEYWORDS = os.environ.get("KEYWORDS", "歌枠|カラオケ|カバー")
POLL_MAX_RESULTS = int(os.environ.get("POLL_MAX_RESULTS", "100"))
MAX_RETWEETS_PER_RUN = int(os.environ.get("MAX_RETWEETS_PER_RUN", "10"))  # 安全のため上限
DATABASE_PATH = os.environ.get("DATABASE_PATH", "processed.db")

# ---- ログ設定 ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("x-retweet-bot")

# ---- DB 初期化 ----
def init_db(path: str):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS processed (
                   tweet_id TEXT PRIMARY KEY,
                   action TEXT,
                   created_at TEXT
               )""")
    conn.commit()
    return conn

# ---- Tweepy Client 初期化 ----
def make_client():
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        raise RuntimeError("API keys/tokens are not fully set in env variables.")
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True
    )
    return client

# ---- キーワードマッチの判定関数 ----
pattern = re.compile(KEYWORDS)

def matches_keywords(text: str) -> bool:
    if not text:
        return False
    return bool(pattern.search(text))

# ---- ツイートがリツイートやリプライかの簡易判定 ----
def is_retweet_or_reply(tweet) -> bool:
    # v2 Tweet オブジェクトは referenced_tweets を持つ場合がある
    try:
        refs = getattr(tweet, "referenced_tweets", None) or tweet.data.get("referenced_tweets", None)
    except Exception:
        refs = None
    if not refs:
        return False
    # referenced_tweets は list of dicts like {"type":"retweeted","id":"..."}
    for r in refs:
        rtype = r.get("type") if isinstance(r, dict) else getattr(r, "type", None)
        if rtype in ("retweeted", "replied_to", "quoted"):
            return True
    return False

# ---- メイン処理 ----
def run_once():
    conn = init_db(DATABASE_PATH)
    client = make_client()

    # 自分の user id を取得（認証ユーザ）
    me = client.get_me().data
    my_user_id = str(me.id)
    logger.info(f"Authenticated as user id={my_user_id}")

    # ホームタイムラインを取得（最新 N 件）
    resp = client.get_home_timeline(max_results=POLL_MAX_RESULTS, tweet_fields=["id","text","created_at","referenced_tweets","author_id"])
    tweets = resp.data or []
    if not tweets:
        logger.info("No tweets retrieved.")
        return

    # 古い順（処理の安定化のため）
    tweets = list(reversed(tweets))

    retweeted_count = 0
    for t in tweets:
        tid = str(t.id)
        text = t.text or ""
        author_id = str(getattr(t, "author_id", t.data.get("author_id", "")))

        # 既処理チェック
        cur = conn.execute("SELECT 1 FROM processed WHERE tweet_id=?", (tid,)).fetchone()
        if cur:
            continue

        # 自分の投稿はスキップ
        if author_id == my_user_id:
            logger.debug(f"Skip own tweet {tid}")
            conn.execute("INSERT OR IGNORE INTO processed(tweet_id,action,created_at) VALUES(?,?,?)", (tid, "skipped_own", datetime.utcnow().isoformat()))
            conn.commit()
            continue

        # リツイート／リプライ／引用ツイートはスキップ（オプション）
        if is_retweet_or_reply(t):
            logger.debug(f"Skip retweet/reply/quote {tid}")
            conn.execute("INSERT OR IGNORE INTO processed(tweet_id,action,created_at) VALUES(?,?,?)", (tid, "skipped_ref", datetime.utcnow().isoformat()))
            conn.commit()
            continue

        # キーワード判定
        if matches_keywords(text):
            logger.info(f"Match: {tid} -> {text[:80]}")
            # 上限チェック
            if retweeted_count >= MAX_RETWEETS_PER_RUN:
                logger.info("Reached MAX_RETWEETS_PER_RUN; stopping for this run.")
                break
            try:
                # 実行：retweet
                # Tweepy Client.retweet() を使用（OAuth1 user context を使用）
                resp_rt = client.retweet(tweet_id=tid)
                logger.info(f"Retweeted {tid} ; response={getattr(resp_rt,'data', resp_rt)}")
                conn.execute("INSERT OR IGNORE INTO processed(tweet_id,action,created_at) VALUES(?,?,?)", (tid, "retweeted", datetime.utcnow().isoformat()))
                conn.commit()
                retweeted_count += 1
                # 任意の短いウェイト（API負荷を下げる）
                time.sleep(1.0)
            except Exception as e:
                logger.exception(f"Failed to retweet {tid}: {e}")
                # ここは再試行ロジックや別テーブルに失敗を記録する方がよい
                # とりあえず現在は失敗は記録せず、次回再試行する設計
                continue
        else:
            # キーワードにマッチしなければ processed に記録して重複検査を軽くする
            conn.execute("INSERT OR IGNORE INTO processed(tweet_id,action,created_at) VALUES(?,?,?)", (tid, "no_match", datetime.utcnow().isoformat()))
            conn.commit()

    logger.info(f"Run complete. retweeted_count={retweeted_count}")
    conn.close()


if __name__ == "__main__":
    run_once()
