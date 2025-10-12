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
# 共通関数：型指定に基づいて環境変数を取得
# ------------------------------------------------------------
def get_typed_env(var_name: str, var_type: str, default=None):
    """
    型を指定して環境変数を取得し、ログ出力を行う。

    Args:
        var_name (str): 環境変数名
        var_type (str): 取得したい型（"str", "int", "float", "bool"）
        default (Any): 環境変数が未設定・変換失敗時のデフォルト値

    Returns:
        Any: 指定型に変換された環境変数の値
    """
    raw_value = os.getenv(var_name)
    logging.info(f"[DEBUG] 環境変数 {var_name} の取得値: '{raw_value}' (指定型: {var_type})")

    if raw_value is None or raw_value == "":
        logging.warning(f"[WARN] 環境変数 {var_name} が設定されていません。デフォルト値 {default} を使用します。")
        return default

    try:
        if var_type == "int":
            converted = int(raw_value)
        elif var_type == "float":
            converted = float(raw_value)
        elif var_type == "bool":
            converted = raw_value.lower() in ["true", "1", "yes"]
        elif var_type == "str":
            converted = str(raw_value)
        else:
            raise ValueError(f"不明な型指定: {var_type}")

        logging.info(f"[DEBUG] {var_name} を {var_type} 型に変換しました: {converted}")
        return converted

    except Exception as e:
        logging.error(f"[ERROR] 環境変数 {var_name} の変換に失敗しました: {e}。デフォルト値 {default} を使用します。")
        return default


def ensure_required_env(required_vars: list[str]):
    """
    必須環境変数が設定されているか確認する。

    Args:
        required_vars (list[str]): 必須変数名のリスト
    """
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logging.critical(f"[FATAL] 必須環境変数が未設定です: {', '.join(missing)}")
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

# ------------------------------------------------------------
# Twitter API関連関数
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


def get_recent_tweets(query: str, hours: int, max_results: int, bearer_token: str) -> list[dict]:
    """
    指定時間内に投稿されたツイートを取得する。

    Args:
        query (str): 検索クエリ
        hours (int): 過去何時間分を取得するか
        max_results (int): 最大取得件数
        bearer_token (str): API認証用トークン

    Returns:
        list[dict]: ツイート情報のリスト
    """
    logging.info(f"[INFO] ツイート取得開始：クエリ='{query}', 対象時間={hours}時間以内")

    headers = create_headers(bearer_token)
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
        logging.error(f"[ERROR] API呼び出し失敗（{response.status_code}）: {response.text}")
        return []

    tweets = response.json().get("data", [])
    logging.info(f"[INFO] {len(tweets)}件のツイートを取得しました。")
    return tweets


def save_tweets_to_json(tweets: list[dict], filename: str = "tweets.json") -> None:
    """
    取得したツイートをJSONファイルとして保存する。

    Args:
        tweets (list[dict]): ツイートリスト
        filename (str): 保存先ファイル名
    """
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)
    logging.info(f"[INFO] ツイート情報を '{filename}' に保存しました。")


# ------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------
def main():
    """
    メイン処理。
    環境変数を型指定で取得し、条件に合致するツイートを取得・保存する。
    """
    logging.info("========== Bot実行開始 ==========")

    # 必須変数チェック
    ensure_required_env(["BEARER_TOKEN", "SEARCH_QUERY"])

    # ここで全環境変数を一括取得・型を整える
    config = {
        "BEARER_TOKEN": get_typed_env("BEARER_TOKEN", "str"),
        "SEARCH_QUERY": get_typed_env("SEARCH_QUERY", "str"),
        "POLL_MAX_RESULTS": get_typed_env("POLL_MAX_RESULTS", "int", 50),
        "POLL_HOURS": get_typed_env("POLL_HOURS", "int", 3),
        "LOG_LEVEL": get_typed_env("LOG_LEVEL", "str", "INFO"),
    }

    logging.info("[INFO] 設定内容:")
    for key, val in config.items():
        logging.info(f"    {key} = {val} (型: {type(val).__name__})")

    # ツイート取得
    tweets = get_recent_tweets(
        query=config["SEARCH_QUERY"],
        hours=config["POLL_HOURS"],
        max_results=config["POLL_MAX_RESULTS"],
        bearer_token=config["BEARER_TOKEN"],
    )

    # 取得結果を保存
    if not tweets:
        logging.warning("[WARN] ツイートが取得できませんでした。")
    else:
        save_tweets_to_json(tweets)

    logging.info("========== Bot実行完了 ==========")


# ------------------------------------------------------------
# エントリポイント
# ------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(f"[FATAL] 実行中にエラーが発生しました: {e}")
        raise
