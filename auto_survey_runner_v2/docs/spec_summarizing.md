# summarizing ステップ仕様

## 目的
- 1つの task（調査単位）について、`extracting` ステップで得られた claim 群を統合し、後続工程で再利用しやすい task-level summary を作成する。
- claim が 0 件でも処理を停止させず、`integrating` ステップが継続できるようにフォールバック summary を必ず生成・永続化する。

## 入力
- `claims.json`
  - `extracting` ステップで保存された claim の配列。
  - 通常経路では、このうち最大 100 件の `text` を連結して synthesizer への `user_prompt` を作る。
- `extraction_meta.json`

## 処理
  - claim 未取得時の原因判定に使うメタ情報。
  - 主に `source_count` と `failed_source_count` を参照し、フォールバック文面を分岐する。
- 実行コンテキスト（内部入力）
  - `config`: `ollama.synthesizer_model` / `models.synthesizer_temperature`
  - `client`: `chat_json(...)` 呼び出しに利用
  - `store`: `append_task_summary(...)` で知識ストア追記
  - `task_work_dir`: `summary.json` など task 配下ファイルの読み書き先

## 出力
- `summary.json`
  - task ワークディレクトリに保存する task 単位の要約 JSON。
- `knowledge/task_summaries.jsonl`
  - 全 task の要約レコードを蓄積する JSONL。`append_task_summary(...)` で追記される。
- Task 更新情報（orchestrator 側）
  - ステップ完了後、`task.summary_id = "summary:{task_id}"` が設定される。

## 作業
1. **再実行回避（冪等）**
   - `summary.json` が既に存在する場合は再計算せず、その内容を返す。
2. **入力読み込み**
   - `claims.json` と `extraction_meta.json` を読み込む。
3. **claim 有無で分岐**
   - claim がある場合:
     - `claims[:100]` の `text` を改行連結して `user_prompt` を作成。
     - synthesizer モデルに `chat_json` で問い合わせ、`TASK_SUMMARY_SCHEMA` 準拠の JSON を受け取る。
     - `task_id` / `task_title` を付与して `summary_row` を構成。
   - claim がない場合:
     - LLM は呼ばず、フォールバック `summary_row` を構成。
     - `failed_source_count > 0` なら抽出失敗寄りの文面、そうでなければ収集不足寄りの文面を採用。
     - `key_findings` は空配列、`open_questions` は原因確認に関する項目を設定。
4. **ログと永続化**
   - 通常経路: `task_summary` イベントを記録。
   - フォールバック経路: `task_summary_fallback` イベントを記録。
   - いずれも `store.append_task_summary(summary_row)` と `write_json(summary.json, summary_row)` を実行。

## 例外・境界ケース
- **claim 0 件**
  - 例外として停止せず、フォールバック要約を生成して処理を継続する。
- **抽出失敗と収集不足の切り分け**
  - `failed_source_count` を見て、同じ「claim なし」でも open question と説明文を切り替える。
- **再開実行時の重複計算防止**
  - `summary.json` が存在する場合は再生成を行わない。
- **出力形式の保証**
  - 通常経路は JSON Schema 制約（`summary` / `key_findings` / `open_questions` 必須）で構造を固定。

## プロンプト
- `system_prompt`: `SYNTHESIZER_SYSTEM_PROMPT`
  - 役割: claim を要約へ統合する synthesizer。
  - 制約: JSON のみ、自然言語文字列は日本語。
- `user_prompt`
  - 内容: claim テキスト（最大 100 件）を改行連結した本文。
- `schema`: `TASK_SUMMARY_SCHEMA`
  - 必須キー: `summary`（文字列）, `key_findings`（文字列配列）, `open_questions`（文字列配列）。
- `model` / `temperature`
  - `config["ollama"]["synthesizer_model"]`
  - `float(config["models"]["synthesizer_temperature"])`

## 代表的な出力イメージ

### 通常経路（claim あり）
```json
{
  "task_id": "task:example",
  "task_title": "例: 生成AI関連規制の整理",
  "summary": "主要な規制論点は透明性要件と責任分界であり、国・地域で要求水準が異なる。",
  "key_findings": [
    "EU系の枠組みはリスク分類ベースで要件が段階化される",
    "米国は州・分野ごとの差が大きく、連邦一律ではない"
  ],
  "open_questions": [
    "高リスク用途の監査証跡要件をどの粒度で実装すべきか",
    "各地域の改訂頻度に追従する運用体制をどう設計するか"
  ]
}
```

### フォールバック経路（claim なし）
```json
{
  "task_id": "task:example",
  "task_title": "例: 生成AI関連規制の整理",
  "summary": "十分な source / claim を収集できなかったため、暫定サマリーのみを出力しました。",
  "key_findings": [],
  "open_questions": [
    "Brave Search API の検索結果やローカル文書が取得できていない原因を確認する必要があります。",
    "対象トピックに対して利用可能な一次情報を追加収集する必要があります。"
  ]
}
```
