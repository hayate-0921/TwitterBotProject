#!/usr/bin/env python3
"""
bot.py — X 自動リツイート Bot（最小構成版）

機能：
1. 認証
2. ホームタイムライン取得
3. 各ツイートにフィルタ（RT/Reply 除外、キーワード、投稿時間）適用
4. DRY_RUN に応じてリツイート実行
5. state.json に処理済みツイート ID を記録

注意：
- 現時点では state.json は Runner ローカルに保存されるのみ（GitHub Actions 間の永続化はなし）
- 将来的に commit/push や DB 移行を検討
"""

import os
import re
import json
import logging
from datetime import datetime, timezone, timedelta

import tweepy
from dotenv import load_dotenv

load_dotenv()

# ---------- 設定読み込み ----------
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")

KEYWORDS_PATTERN = os.getenv("KEYWORDS", "歌枠|歌ってみた|cover|カバー")
POLL_MAX_RESULTS = int(os.getenv("POLL_MAX_RESULTS", "50"))
MAX_RETWEETS_PER_RUN = int(os.getenv("MAX_RETWEETS_PER_RUN", "1"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "3"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
STATE_FILE = os.getenv("STATE_FILE", "state.json")

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("自動リツイートBot")

def load_state(path):
    """
    state.json を読み込んで処理済みツイート ID のリストを返す。
    エラー時は空リストを返す。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"processed_ids": []}
    except Exception as e:
        logger.warning("state 読み込み失敗: %s", e)
        return {"processed_ids": []}

def save_state(path, state):
    """
    state を state.json に保存する。
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("state 保存失敗: %s", e)

def make_client():
    """
    Tweepy Client を生成して返す。
    必須環境変数が揃っていない場合は例外を投げる。
    """
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        logger.error("環境変数が不足しています。API_KEY などを確認してください。")
        raise RuntimeError("認証情報不足")
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True
    )
    return client

def is_retweet_or_reply(tweet):
    """
    ツイートがリツイート／リプライ／引用投稿かどうかを判定する。
    引数:
     - tweet: tweepy.Tweet オブジェクトまたはその類似オブジェクト
    戻り値:
     - True: RT/Reply/Quote のいずれか
     - False: 通常のツイート
    """
    try:
        refs = getattr(tweet, "referenced_tweets", None) or getattr(tweet, "data", {}).get("referenced_tweets")
    except Exception:
        refs = None
    if not refs:
        return False
    for r in refs:
        rtype = r.get("type") if isinstance(r, dict) else getattr(r, "type", None)
        if rtype in ("retweeted", "replied_to", "quoted"):
            return True
    return False

keyword_re = re.compile(KEYWORDS_PATTERN, flags=re.IGNORECASE)

def matches_keywords(text: str) -> bool:
    """
    テキストにキーワードが含まれているかを判定する。
    引数:
     - text: ツイート本文文字列
    戻り値:
     - True: キーワードのいずれかにマッチ
     - False: マッチせず
    """
    if not text:
        return False
    return bool(keyword_re.search(text))

def get_created_at(tweet):
    """
    ツイートの作成日時 (datetime) を返す。UTC基準。
    引数:
     - tweet: tweepy.Tweet オブジェクト
    戻り値:
     - datetime オブジェクト（UTC） または None（取得不能時）
    """
    dt = getattr(tweet, "created_at", None)
    if isinstance(dt, datetime):
        return dt
    try:
        raw = getattr(tweet, "data", {}).get("created_at")
        if raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        pass
    return None

def run_once():
    logger.info("処理開始 (DRY_RUN=%s)", DRY_RUN)
    state = load_state(STATE_FILE)
    processed = set(state.get("processed_ids", []))

    client = make_client()

    me = client.get_me().data
    my_user_id = str(getattr(me, "id", None))
    logger.info("認証成功: id=%s username=%s", getattr(me, "id", None), getattr(me, "username", None))

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)

    try:
        resp = client.get_home_timeline(
            max_results=POLL_MAX_RESULTS,
            tweet_fields=["created_at", "referenced_tweets", "author_id", "text"]
        )
    except Exception as e:
        logger.exception("ホームタイムライン取得失敗: %s", e)
        return

    tweets = getattr(resp, "data", None) or []
    logger.info("取得ツイート数 (生データ) = %d", len(tweets))

    tweets = list(reversed(tweets))
    retweeted_count = 0

    for t in tweets:
        tid = str(getattr(t, "id", None) or (getattr(t, "data", {}) or {}).get("id"))
        if not tid:
            continue
        if tid in processed:
            continue

        created_at = get_created_at(t)
        if not created_at:
            logger.debug("作成日時取得失敗: %s をスキップ", tid)
            processed.add(tid)
            continue

        if created_at < cutoff:
            logger.debug("ツイート %s は基準日時 %s より古い (%s) → スキップ", tid, cutoff, created_at)
            processed.add(tid)
            continue

        if is_retweet_or_reply(t):
            logger.debug("ツイート %s は RT/返信/引用 → スキップ", tid)
            processed.add(tid)
            continue

        text = getattr(t, "text", None) or (getattr(t, "data", {}) or {}).get("text", "")
        text_preview = text.replace("\n", " ")[:140]
        if not matches_keywords(text):
            logger.debug("ツイート %s はキーワード未一致 → スキップ 内容=%s", tid, text_preview)
            processed.add(tid)
            continue

        logger.info("対象候補: %s 投稿者=%s 内容=%s", tid, getattr(t, "author_id", (getattr(t, "data", {}) or {}).get("author_id")), text_preview)

        if retweeted_count >= MAX_RETWEETS_PER_RUN:
            logger.info("本実行のリツイート上限 %d に達したため、以降処理を中止します", MAX_RETWEETS_PER_RUN)
            break

        if DRY_RUN:
            logger.info("DRY_RUN モード: %s をリツイート (実行せず)", tid)
            processed.add(tid)
            retweeted_count += 1
        else:
            try:
                resp_rt = client.retweet(tweet_id=tid)
                logger.info("リツイート成功: %s レスポンス=%s", tid, getattr(resp_rt, "data", str(resp_rt)))
                processed.add(tid)
                retweeted_count += 1
            except Exception as e:
                logger.exception("リツイート失敗: %s エラー=%s", tid, e)
                processed.add(tid)
                continue

    state["processed_ids"] = list(processed)
    save_state(STATE_FILE, state)
    logger.info("処理終了 リツイート件数=%d, 総処理済み件数=%d", retweeted_count, len(processed))


if __name__ == "__main__":
    run_once()
