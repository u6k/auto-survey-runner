# planning ステップ仕様

## 目的
- 調査タスクを、後続ステップで実行可能な検索計画へ変換する。
- 具体的には以下を同時に生成する。
  - `queries`: collecting ステップに渡す検索クエリ群
  - `subtasks`: spawning ステップで評価する派生タスク候補群
- 生成結果を task ごとの永続チェックポイントとして保存し、再開時の再計算を避ける。

## 入力
- `Task.title`
- `Task.description`
- `config.ollama.planner_model`
- `config.models.planner_temperature`
- `PLANNER_SYSTEM_PROMPT`
- `QUERY_PLAN_SCHEMA`

### 入力の補足

#### 1) `Task.title` / `Task.description` の由来
- ルートタスクでは、`config.yaml` の `research.topic` / `research.description` から初期化される。
- 派生タスクでは、planner が返した `subtasks`（title/description）から生成されるため、直接 `config.yaml` の値ではない場合がある。

## プロンプト仕様（重要）

### planner への問い合わせ内容
planning ステップは、planner モデルに対して structured output（JSON schema）で問い合わせる。

- `model`: `config["ollama"]["planner_model"]`
- `system_prompt`: `PLANNER_SYSTEM_PROMPT`
  - 意図（日本語要約）:
    - あなたは日本語リサーチワークフロー用の planning モデルである
    - 検索クエリと派生タスク候補を簡潔に返す
    - 出力は **valid JSON only**
    - JSON 内の自然言語値はすべて日本語で記述する
- `user_prompt`:
  - `Task: {task.title}`
  - `Description: {task.description}`
  - 上記 2 行を改行で連結したテキスト
- `schema`: `QUERY_PLAN_SCHEMA`
  - 必須フィールドは `queries` と `subtasks`
  - `subtasks` 要素は `title`, `description`, `priority` を必須とする
- `temperature`: `config["models"]["planner_temperature"]`
- `log_context`: `{"task_id": task.task_id, "stage": "planning"}`

## 出力
- `state/task_work/<task_id>/planning.json`
  - `queries: string[]`
  - `subtasks: { title: string, description: string, priority: number }[]`

## 処理
1. `state/task_work/<task_id>/planning.json` の存在確認を行う。
2. 既存ファイルがある場合はそれを読み込み、LLM 呼び出しを行わず終了する（チェックポイント再利用）。
3. 既存ファイルがない場合、planner モデルへ問い合わせる（上記プロンプト仕様）。
4. 返却 JSON を `planning.json` として保存する。
5. orchestrator は `result["queries"]` を `task.planned_queries` に反映し、次ステップ（collecting）へ進める。

## 再開判定

### A. どの task を再開するか（run レベル）
- `run_state.current_task_id` が存在し、かつ該当 task の `status == "running"` のとき、その task を再開対象とする。
- 上記条件を満たさない場合は queue から次 task を選択する。

### B. どの stage から再開するか（task レベル）
- `task.current_stage` を再開地点として使う。
- `STAGE_ORDER` 上で `current_stage` より前の stage はスキップする。
- planning 実行時は `planning.json` が存在すれば即再利用し、再生成しない。

## エラー時
- planning 内での LLM 呼び出し例外は orchestrator に送出される。
- orchestrator は retry 方針（`max_retry_per_task`）に従って task を `pending` または `failed` に遷移させる。
