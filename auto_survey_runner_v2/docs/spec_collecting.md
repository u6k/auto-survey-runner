# collecting ステップ仕様

## 目的
- ローカル文書と Web 文書を source として収集・正規化・ランキングする。

## 入力
- `planning.json` の `queries`
- `paths.local_docs_dir`
- Brave Search API 設定

## 処理
1. ローカル文書 (`.txt`, `.md`, `.html`, `.htm`) を読み込む。
2. Brave Search で query ごとに Web source を収集する。
3. HTML / entity / snippet を正規化する。
4. 語彙重なりベースでランキングし、上位 source を残す。
5. task work と `knowledge/sources.jsonl` へ永続化する。

## 出力
- `collected_sources.json`
- `knowledge/sources.jsonl`

## エラー時
- 個別 URL の取得失敗はログに残して継続する。
- Brave Search の 422 は locale なしで再試行する。
- Brave Search の 429 は backoff 後に再試行する。
