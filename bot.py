# =========================================================
# bot.py — X(Twitter) 自動リツイートBot
# =========================================================
# 概要:
#   - Tweepyを利用してX(Twitter) APIへアクセス
#   - GitHub Actionsの環境変数を用いて認証および設定を管理
#   - 指定キーワードでフィルタリングしたツイートを取得
#   - リツイート数などの条件に基づいて自動リツイートを実施
# =========================================================

import os
import logging
import tweepy
from datetime import datetime, timedelta, timezone


# =========================================================
# ログ設定
# =========================================================
def setup_logger(level: str) -> logging.Logger:
    """
    ログの設定を行う。

    Args:
        level (str): ログレベル文字列（例："INFO", "DEBUG" など）

    Returns:
        logging.Logger: 設定済みのロガーインスタンス
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='[%(asctime)s] %(levelname)s: %(message)s',
    )
    logger = logging.getLogger(__name__)
    return logger


# =========================================================
# 型指定付き環境変数取得メソッド
# =========================================================
def load_env_var(name: str, vtype: str):
    """
    環境変数を取得し、指定の型に変換して返す。

    Args:
        name (str): 環境変数名
        vtype (str): 変換したい型 ("int", "float", "bool", "str")

    Returns:
        任意の型: 変換後の値。存在しない場合は例外を送出。
    """
    value = os.getenv(name)
    if value is None or value == "":
        raise ValueError(f"環境変数 '{name}' が設定されていません。")

    # 型に応じて変換
    if vtype == "int":
        converted = int(value)
    elif vtype == "float":
        converted = float(value)
    elif vtype == "bool":
        converted = value.lower() in ("true", "1", "yes")
    elif vtype == "str":
        converted = str(value)
    else:
        raise ValueError(f"型 '{vtype}' はサポートされていません。")

    print(f"[DEBUG] {name} 読み取り値: '{value}' → 型変換後: {converted} ({vtype})")
    return converted


# =========================================================
# Tweepy クライアント生成
# =========================================================
def create_client() -> tweepy.Client:
    """
    GitHub Secrets に設定された認証情報を用いて Tweepy クライアントを生成する。

    Returns:
        tweepy.Client: 認証済みクライアント

    Raises:
        RuntimeError: 認証情報が不足している場合
    """
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    access_token = os.getenv("ACCESS_TOKEN")
    access_secret = os.getenv("ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("必要なAPIキーまたはトークンが環境変数に設定されていません。")

    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
        wait_on_rate_limit=True
    )
    return client


# =========================================================
# ツイート取得処理
# =========================================================
def fetch_tweets(client: tweepy.Client, keywords: str, lookback_hours: int, max_results: int, logger: logging.Logger):
    """
    指定キーワードに基づいてツイートを検索する。

    Args:
        client (tweepy.Client): 認証済みTwitterクライアント
        keywords (str): OR区切りの検索キーワード（例："歌枠 OR カバー OR cover"）
        lookback_hours (int): 取得対象とする過去時間（時間単位）
        max_results (int): 一度に取得する最大件数
        logger (logging.Logger): ロガーインスタンス

    Returns:
        list[tweepy.Tweet]: 条件に合致したツイートのリスト
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=lookback_hours)

    # ---------------------------------------------------------
    # フィルタリング条件（ここを明示）
    #   - 指定キーワード（OR条件）
    #   - リツイートを除外
    #   - 指定時間以降のツイート
    # ---------------------------------------------------------
    query = f"({keywords}) -is:retweet"

    logger.info(f"ツイート検索条件: {query}")
    logger.info(f"検索期間: {start_time.isoformat()} 以降")

    tweets = client.search_recent_tweets(
        query=query,
        tweet_fields=["created_at", "public_metrics", "author_id"],
        start_time=start_time,
        max_results=max_results
    )

    if not tweets.data:
        logger.info("該当するツイートはありませんでした。")
        return []
    return tweets.data


# =========================================================
# リツイート実行処理
# =========================================================
def perform_retweets(client: tweepy.Client, tweets, max_retweets: int, dry_run: bool, logger: logging.Logger):
    """
    指定ツイートリストに対してリツイートを実行する。

    Args:
        client (tweepy.Client): 認証済みTwitterクライアント
        tweets (list[tweepy.Tweet]): リツイート対象ツイートリスト
        max_retweets (int): 実行上限件数
        dry_run (bool): True の場合は実行せず出力のみ
        logger (logging.Logger): ロガーインスタンス
    """
    count = 0
    for tweet in tweets:
        tweet_id = tweet.id
        tweet_text = tweet.text.replace("\n", " ")

        if count >= max_retweets:
            logger.info("リツイート上限に達しました。")
            break

        if dry_run:
            logger.info(f"[DRY RUN] リツイート対象: ID={tweet_id} 内容={tweet_text[:50]}")
        else:
            try:
                client.retweet(tweet_id)
                logger.info(f"リツイート実行: ID={tweet_id} 内容={tweet_text[:50]}")
                count += 1
            except Exception as e:
                logger.error(f"リツイート失敗: ID={tweet_id}, エラー: {e}")

    logger.info(f"処理完了: リツイート実行数 = {count}")


# =========================================================
# メイン処理
# =========================================================
def main():
    """
    Bot全体のメイン処理。

    フロー:
      1. 環境変数の読み込みと型変換
      2. Tweepyクライアント生成
      3. 指定キーワードでツイート検索
      4. 条件に合致したツイートのリツイート
    """
    # --- 設定読み込み ---
    KEYWORDS = load_env_var("KEYWORDS", "str")
    POLL_MAX_RESULTS = load_env_var("POLL_MAX_RESULTS", "int")
    MAX_RETWEETS_PER_RUN = load_env_var("MAX_RETWEETS_PER_RUN", "int")
    DRY_RUN = load_env_var("DRY_RUN", "bool")
    LOOKBACK_HOURS = load_env_var("LOOKBACK_HOURS", "int")
    LOG_LEVEL = load_env_var("LOG_LEVEL", "str")

    logger = setup_logger(LOG_LEVEL)
    logger.info("Bot 実行開始")

    # --- クライアント生成 ---
    client = create_client()

    # --- ツイート検索 ---
    tweets = fetch_tweets(client, KEYWORDS, LOOKBACK_HOURS, POLL_MAX_RESULTS, logger)

    # --- 条件に合致するツイートがある場合のみリツイート ---
    if tweets:
        perform_retweets(client, tweets, MAX_RETWEETS_PER_RUN, DRY_RUN, logger)
    else:
        logger.info("リツイート対象ツイートはありません。")

    logger.info("Bot 実行完了")


# =========================================================
# エントリーポイント
# =========================================================
if __name__ == "__main__":
    main()
