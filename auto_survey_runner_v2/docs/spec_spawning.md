# spawning ステップ仕様

## 目的

- planning ステップが提案した派生タスク候補（`subtasks`）を、実行可能な子タスクとして確定する。
- 具体的には「候補生成」と「実際にキューへ投入する判断」を分離し、上限・深さ・重複ルールを一元適用する。
- 確定結果を永続化して、再開時に同じ判定を再実行しないようにする。

## 入力

spawning が参照する主な入力は以下。

1. `planning.json`
   - `subtasks`（配列）を読む。
   - 各要素は原則 `title`, `description`, `priority` を持つ。
2. 既存タスク一覧（`tasks.json` 相当の in-memory 状態）
   - 既存の `dedupe_key` と総タスク数を参照する。
3. runtime 制限
   - `runtime.max_tasks`: 全体タスク総数の上限
   - `runtime.max_depth`: 派生深さの上限
   - `runtime.min_priority`: 採用する候補の最小優先度

> 注: `quality.spawn_confidence_threshold` は config 上の必須キーだが、現行の spawning 判定ロジックでは直接参照していない。

## 出力

- `state/task_work/<task_id>/spawned_tasks.json`
  - 採用された子タスクの配列（Task のシリアライズ）を保存する。
- orchestrator 側での反映
  - 親 task の `spawned_task_ids` を更新
  - `tasks` に子タスクを追加
  - `queue` に子タスク ID を追加

## 処理

### 0. チェックポイント再利用

- `spawned_tasks.json` がすでに存在する場合は、それを読み込んで終了する。
- これにより再開時の二重生成を防ぐ。

### 1. 候補読み込み

- `planning.json` を読み、`subtasks` を候補集合として扱う。

### 2. 早期終了条件

- 親 task の `depth >= max_depth` の場合は派生を行わない。
- 既存タスク数 `>= max_tasks` の場合も派生を行わない。

### 3. 候補ごとの採否判定

候補ごとに以下を適用する。

1. **優先度フィルタ**
   - 候補 `priority < min_priority` なら除外。
2. **件数上限フィルタ**
   - 採用済み候補を含めると `max_tasks` を超える場合は除外。
3. **重複排除（dedupe）**
   - `title + description` を正規化して `dedupe_key` を作る。
   - 正規化は「小文字化」「空白正規化」「記号除去」。
   - 既存 `dedupe_key` に含まれる場合は除外。

### 4. 子タスク生成

採用候補は Task として具体化する。

- `task_id`: `sha1("{parent_task_id}:{dedupe_key}")[:12]`
- `slug`: `title` から生成
- `description`: 候補 description
- `priority`: 候補 priority
- `depth`: `parent.depth + 1`
- `parent_task_id`: 親 task ID
- `dedupe_key`: 上記の正規化キー

### 5. 永続化・ログ

- 採用結果を `spawned_tasks.json` に保存する。
- `task_spawning` イベントとして `spawned_task_count` を記録する。

### 6. orchestrator での反映

- stage 戻り値から Task を復元して `tasks` へ追加する。
- 新規 task ID を `queue` へ追加する。
- 親 task の `spawned_task_ids` を更新する。

## 例外・再試行

- spawning ステップ自体は例外を内部で握りつぶさず、上位へ送出する。
- orchestrator 側で以下を適用する。
  - `retry_count` をインクリメント
  - `retry_count < runtime.max_retry_per_task` なら `pending` に戻して再キュー
  - 上限超過時は `failed` に遷移
- run state には `last_error_message` が記録される。

## プロンプト仕様

### 原則

- spawning ステップ自体は LLM を呼び出さない（プロンプトを持たない）。
- よって、spawning が扱う候補品質は planning ステップのプロンプト定義に依存する。

### planning 側で定義される前提

- `PLANNER_SYSTEM_PROMPT`
  - 日本語リサーチ向け planner として、JSON only で `queries` と `subtasks` を出力する。
- `QUERY_PLAN_SCHEMA`
  - `queries`, `subtasks` を必須とし、`subtasks` の各要素に
    `title`, `description`, `priority` を要求する。

## データ契約（要点）

- 入力契約: `planning.json.subtasks[*]` が「タイトル・説明・優先度」を持つこと。
- 判定契約: 上限・優先度・重複の順で採否が決まること。
- 出力契約: 採用結果は `spawned_tasks.json` と queue/tasks 更新に反映されること。
- 冪等性契約: 既存 `spawned_tasks.json` がある場合、同じ結果を再利用すること。
