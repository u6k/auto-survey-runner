# collecting ステップ仕様

## 目的
- ローカル文書と Web 文書を source として収集し、後続の extracting ステップで扱えるように正規化・ランキングする。
- 収集結果を task 単位のチェックポイントと、全 task 横断の知識ストアに永続化する。

## 入力
- `planning.json` の `queries`（実装上は task の `planned_queries`）
- `paths.local_docs_dir`
- Brave Search API 設定
  - `search.brave_api_key` または環境変数 `BRAVE_SEARCH_API_KEY`
  - `search.country`, `search.search_lang`, `search.max_queries_per_task`
  - `search.retry_attempts`, `search.retry_delay_seconds`
- 収集上限設定
  - `collection.max_web_results`
  - `collection.max_sources_per_task`

## 出力
- `state/task_work/<task_id>/collected_sources.json`
  - 当該 task の収集済み source 一覧（再開時のチェックポイントとして利用）
- `knowledge/sources.jsonl`
  - 全 task 共通の source 追記ログ

## 作業
1. チェックポイント確認
   - `collected_sources.json` が既に存在する場合は再収集せず、その内容を返す。
2. ローカル source の収集
   - `local_docs_dir` 直下の `.txt`, `.md`, `.html`, `.htm` を読み込む。
   - HTML/entity/空白を正規化し、`kind="local"` の source として保持する。
3. Web source の収集（query ごと）
   - Brave Search API に問い合わせ、検索結果を取得する。
   - query 実行数は `search.max_queries_per_task` で上限をかける。
   - URL 重複は除外する。
4. snippet と本文の正規化・統合
   - 検索レスポンスの `description` と `extra_snippets` を結合して `snippet` を作る。
   - `snippet` と取得本文をそれぞれ正規化する。
   - 両方ある場合は `title + snippet + 本文` の順で `content` を構成する。
   - `metadata.snippet` には元の snippet 文字列を保持する。
5. ランキング
   - query 語と source 本文語の語彙重なり率で `rank_score` を計算する。
   - `collection.max_sources_per_task` 件まで上位を採用する。
6. 永続化
   - 採用 source を `knowledge/sources.jsonl` に追記する。
   - 同内容を `collected_sources.json` に保存する。

## 例外
- 個別 URL の取得失敗
  - ログを残して当該 URL をスキップし、処理は継続する。
- Brave Search query の失敗
  - ログを残して当該 query をスキップし、次の query へ進む。
- Brave Search API キー未設定
  - 例外を送出する（`search.brave_api_key` または `BRAVE_SEARCH_API_KEY` が必要）。

### HTTP ステータスコードの扱い
- `422`
  - locale 付きパラメータ（`country`, `search_lang`, `extra_snippets`）での検索が受理されなかったケースとして扱う。
  - locale 指定なしパラメータへ切り替えて再試行する。
- `429`
  - レート制限として扱う。
  - `retry_delay_seconds * (attempt + 1)` の backoff で再試行する。
- 上記以外の HTTP エラー
  - Brave API 呼び出し側では再送出し、呼び出し元（query ループ）でログ化して継続する。

## 補足
- `snippet` は検索エンジン側の要約テキストであり、本文取得が不完全な場合でも初期文脈として利用できる。
- 正規化対象には HTML タグ、script/style/comment、HTML entity、過剰空白・改行が含まれる。
