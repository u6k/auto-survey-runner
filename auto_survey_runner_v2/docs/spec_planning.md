# planning ステップ仕様

## 目的
- 調査テーマを検索クエリと派生タスク候補へ変換する。

## 入力
- `Task.title`
- `Task.description`
- `config.ollama.planner_model`
- `config.models.planner_temperature`

## 処理
1. `state/task_work/<task_id>/planning.json` があれば再利用する。
2. planner モデルへ JSON schema 付きで問い合わせる。
3. `queries` と `subtasks` を task work 配下へ保存する。

## 出力
- `planning.json`
  - `queries: string[]`
  - `subtasks: {title, description, priority}[]`

## エラー時
- LLM 呼び出し例外は orchestrator 側に送出され、task retry 制御に委譲する。
