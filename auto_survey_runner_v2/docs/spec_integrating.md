# integrating ステップ仕様

## 目的
- 累積された task summary（`knowledge/task_summaries.jsonl`）と factual claim（`knowledge/claims.jsonl`）を統合し、全体知識の要約である global digest を更新する。
- `snapshotting` など後続工程が常に参照できるよう、claim が 0 件でも fallback digest を必ず生成して処理を継続可能にする。
- 中断・再実行時の無駄な再計算を避けるため、task 作業ディレクトリのチェックポイントを再利用する。

## 入力
- 永続知識ストア
  - `knowledge/task_summaries.jsonl`
  - `knowledge/claims.jsonl`
- task 作業ディレクトリ
  - `extraction_meta.json`（`failed_source_count` を参照）
  - `global_digest.json`（存在時は再利用）
- 実行コンテキスト
  - `config`（`ollama.synthesizer_model`, `models.synthesizer_temperature`）
  - `client`（`chat_json` 呼び出し）
  - `logger`（stage ログ出力）
  - `store`（knowledge I/O）

## 出力
- ファイル
  - `task_work/<task_id>/global_digest.json`
  - `knowledge/global_digest.json`
- データ構造（必須キー）
  - `highlights: string[]`
  - `open_questions: string[]`
  - `next_actions: string[]`
- 付加フィールド
  - `updated_at`（ISO-8601 UTC 時刻）

## 処理
1. **チェックポイント確認**
   - `task_work/<task_id>/global_digest.json` が存在する場合はそれを読み込み、`knowledge/global_digest.json` に反映して即時 return する。
2. **入力ロード**
   - `task_summaries = store.read_task_summaries()`
   - `claims = store.read_claims()`
   - `extraction_meta = read_json(task_work/extraction_meta.json, {})`
3. **claims 0 件時の fallback 分岐**
   - `failed_source_count = extraction_meta.get("failed_source_count", 0)` を参照。
   - fallback payload を組み立てる。
     - `highlights`: 「統合対象が未蓄積」である旨
     - `open_questions` / `next_actions`: 
       - `failed_source_count > 0` の場合は「抽出失敗（空応答など）調査」を優先
       - それ以外は「source 不足（検索結果/ローカル文書不足）調査」を優先
   - `logger.log_event("global_digest_fallback", ...)` を記録。
   - task_work と knowledge の両方へ書き込み return。
4. **claims あり時の統合生成**
   - プロンプト入力を構築。
     - `task_summaries` の `summary` を連結
     - `claims[:200]` の `text` を連結（上限 200 件）
     - 連結文字列を `[:12000]` で切り詰め
   - synthesizer を structured output で呼び出す。
     - `client.chat_json(model=config["ollama"]["synthesizer_model"], ...)`
     - `schema=GLOBAL_DIGEST_SCHEMA`
     - `temperature=float(config["models"]["synthesizer_temperature"])`
   - `updated_at` を付与し、`logger.log_event("global_digest", ...)` を記録。
   - task_work と knowledge の両方へ書き込み return。

## プロンプト仕様
- system prompt: `SYNTHESIZER_SYSTEM_PROMPT`
  - 日本語研究ワークフローの synthesizer として振る舞う。
  - claim を統合して summary / global digest を作る。
  - **有効な JSON のみ**を返す。
  - 自然言語文字列は **日本語**で返す。
- schema: `GLOBAL_DIGEST_SCHEMA`
  - 必須キー: `highlights`, `open_questions`, `next_actions`
  - 各キーは文字列配列。

## 主な変数・パラメータ（実装語彙）
- `task_summaries`: task 単位要約の蓄積。統合時の高レベル文脈として使う。
- `claims`: factual claim の蓄積。統合時の主要根拠テキストとして使う。
- `failed_source_count`: fallback 文面を「抽出失敗寄り」か「source不足寄り」かに切り替える判定値。
- `ollama.synthesizer_model`: integrating で使用する生成モデル。
- `models.synthesizer_temperature`: 生成の多様性・揺らぎを制御。
- `claims[:200]` / prompt `[:12000]`: 入力サイズ抑制のための上限。
- `updated_at`: digest の更新時刻。

## エラー/再実行に関する振る舞い
- integrating ステップ自体で例外を握りつぶさず、上位オーケストレータの再試行ポリシーへ委譲する。
- 中間ファイル（`task_work/<task_id>/global_digest.json`）が存在する場合は再計算を行わず、再開時の処理時間と失敗面積を抑える。
