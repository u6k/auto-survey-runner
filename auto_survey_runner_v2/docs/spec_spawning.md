# spawning ステップ仕様

## 目的
- planner が提案した派生タスクを queue へ追加する。

## 入力
- `planning.json`
- 既存 `tasks.json`
- runtime 制限 (`max_tasks`, depth, priority)

## 処理
1. planner の subtasks を読む。
2. dedupe / 上限 / 深さ制約を適用する。
3. 採用したタスクを `spawned_tasks.json` に保存する。
4. orchestrator 側で queue / tasks に反映する。

## 出力
- `spawned_tasks.json`
