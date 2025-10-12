import os
import json
import logging
from datetime import datetime, timedelta, timezone
import requests

# ------------------------------------------------------------
# ログ設定
# ------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ------------------------------------------------------------
# 環境変数取得関数群
# ------------------------------------------------------------
def get_env_str(var_name: str, default: str = "") -> str:
    """
    文字列型の環境変数を取得し、内容をログに出力する。

    Args:
        var_name (str): 環境変数名
        default (str): デフォルト値

    Returns:
        str: 環境変数の値（文字列）
    """
    raw_value = os.getenv(var_name, default)
    logging.info(f"[DEBUG] 環境変数 {var_name}: '{raw_value}' (型: {type(raw_value).__name__})")
    if raw_value == "":
        logging.warning(f"[WARN] 環境変数 {var_name} が設定されていません。デフォルト値 '{default}' を使用します。")
    return raw_value


def get_env_int(var_name: str, default: int) -> int:
    """
    整数型の環境変数を取得し、変換結果をログに出力する。

    Args:
        var_name (str): 環境変数名
        default (int): デフォルト値

    Returns:
        int: 整数型の値
    """
    raw_value = os.getenv(var_name, "")
    logging.info(f"[DEBUG] 取得した環境変数 {var_name} の値: '{raw_value}' (型: {type(raw_value).__name__})")

    if raw_value == "":
        logging.warning(f"[WARN] 環境変数 {var_name} が空文字です。デフォルト値 {default} を使用します。")
        return default

    try:
        converted = int(raw_value)
        logging.info(f"[DEBUG] {var_name} を整数型に変換しました: {converted}")
        return converted
    except ValueError:
        logging.error(f"[ERROR] 環境変数 {var_name}='{raw_value}' は整数に変換できません。デフォルト値 {default} を使用します。")
        return default


def ensure_required_env(vars_required):
    """
    必須環境変数の存在確認を行う。未設定の変数がある場合はエラー終了する。

    Args:
        vars_required (list[str]): 必須変数名のリスト
    """
    missing = [v for v in vars_required if not os.getenv(v)]
    if missing:
        logging.critical(f"[FATAL] 必須環境変数が未設定です: {', '.join(missing)}")
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")


# ------------------------------------------------------------
# 環境変数の取得
# ------------------------------------------------------------
ensure_required_env(["BEARER_TOKEN", "SEARCH_QUERY"])

BEARER_TOKEN = get_env_str("BEARER_TOKEN")
SEARCH_QUERY = get_env_str("SEARCH_QUERY")
POLL_MAX_RESULTS = get_env_int("POLL_MAX_RESULTS", 50)
POLL_HOURS = get_env_int("POLL_HOURS", 3)

# ------------------------------------------------------------
# Twitter API関連
# ------------------------------------------------------------
def create_headers(bearer_token: str) -> dict:
    """
    API認証用のHTTPヘッダーを生成する。

    Args:
        bearer_token (str): X（旧Twitter）APIのベアラートークン

    Returns:
        dict: 認証ヘッダー
    """
    return {"Authorization": f"Bearer {bearer_token}"}


def get_recent_tweets(query: str, hours: int, max_results: int) -> list[dict]:
    """
    指定時間内に投稿されたツイートを取得する。

    Args:
        query (str): 検索クエリ（例："Python OR AI"）
        hours (int): 取得対象とする過去時間（単位：時間）
        max_results (int): 取得する最大件数（10〜100）

    Returns:
        list[dict]: ツイート情報のリスト
    """
    logging.info(f"[INFO] ツイート取得を開始します。検索クエリ: '{query}', 対象時間: 過去{hours}時間")

    headers = create_headers(BEARER_TOKEN)
    endpoint = "https://api.twitter.com/2/tweets/search/recent"

    now_utc = datetime.now(timezone.utc)
    start_time = now_utc - timedelta(hours=hours)

    params = {
        "query": query,
        "max_results": max_results,
        "start_time": start_time.isoformat(timespec="seconds"),
        "tweet.fields": "id,text,created_at,author_id",
    }

    response = requests.get(endpoint, headers=headers, params=params)

    if response.status_code != 200:
        logging.error(f"[ERROR] API呼び出しに失敗しました。ステータスコード: {response.status_code}")
        logging.error(response.text)
        return []

    data = response.json().get("data", [])
    logging.info(f"[INFO] {len(data)} 件のツイートを取得しました。")
    return data


def save_tweets_to_json(tweets: list[dict], filename: str = "tweets.json") -> None:
    """
    取得したツイートをJSONファイルとして保存する。

    Args:
        tweets (list[dict]): ツイートのリスト
        filename (str): 保存先ファイル名（デフォルト: tweets.json）
    """
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)
    logging.info(f"[INFO] ツイート情報を '{filename}' に保存しました。")


# ------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------
def main():
    """
    メイン実行関数。
    指定された条件でツイートを取得し、結果をファイルに保存する。
    """
    logging.info("========== Bot実行開始 ==========")
    tweets = get_recent_tweets(SEARCH_QUERY, POLL_HOURS, POLL_MAX_RESULTS)

    if not tweets:
        logging.warning("[WARN] ツイートが取得できませんでした。")
    else:
        save_tweets_to_json(tweets)

    logging.info("========== Bot実行完了 ==========")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(f"[FATAL] 実行中に予期せぬエラーが発生しました: {e}")
        raise
