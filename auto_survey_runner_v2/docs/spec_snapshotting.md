# snapshotting ステップ仕様

## 目的

`snapshotting` は、実行中に蓄積された全体知識を外部共有向けの成果物として確定するステップである。
この段階では新しい知識を生成せず、`integrating` までで確定した統合結果を
Markdown / JSON 形式で出力する。

主な狙い:

- 外部利用者が閲覧しやすいドキュメント (`integrated_report.md`) を作る。
- 機械処理しやすい統合データ (`integrated_report.json`) を作る。
- 出力ファイル群のメタ情報 (`manifest.json`) を作る。
- 中断再開時に再レンダリングを避けるためのチェックポイントを残す。

## 入力

### 知識ストアから読み込む入力

- `knowledge/global_digest.json`
- `knowledge/task_summaries.jsonl`
- `knowledge/claims.jsonl`

### 実行コンテキスト入力

- `task`: 現在完了しようとしている Task（`task_id`, `title`, `slug` など）
- `context["config"]["paths"]["output_dir"]`: 出力先ルート
- `context["task_work_dir"]`: task ごとの作業ディレクトリ（チェックポイント配置先）
- `context["logger"]`: 構造化ログ出力

## 出力

### 1) 外部公開向け成果物

出力先: `outputs/task_<id>_<slug>/`

- `integrated_report.json`
  - `task`: task のスナップショット
  - `global_digest`: 全体統合ダイジェスト
  - `task_summaries`: 全 task の要約一覧
  - `claims`: 累積 claim 一覧
- `integrated_report.md`
  - ハイライト
  - 未解決の問い
  - 次のアクション
  - タスク別サマリー
- `manifest.json`
  - `task_id`, `task_title`
  - 生成ファイル一覧

### 2) 再実行抑止用チェックポイント

- `state/task_work/<task_id>/snapshot.json`
  - 例: `{"output_path": "outputs/task_xxx_yyy"}`

## 処理

1. `context["task_work_dir"] / "snapshot.json"` の存在を確認する。
2. 存在する場合:
   - 既存 `snapshot.json` を読み込んでそのまま返す（再レンダリングしない）。
3. 存在しない場合:
   - 知識ストアから `global_digest`, `task_summaries`, `claims` を読み込む。
   - `render_integrated_outputs(...)` を呼び出し、出力フォルダを生成する。
   - 生成先フォルダを `payload = {"output_path": ...}` として保持する。
   - `snapshot` イベントをログ出力する。
   - `snapshot.json` を保存して返す。

## 例外

- `snapshotting` ステップ自体は `try/except` で例外を握りつぶさない。
- 典型的な失敗要因:
  - JSON 読み書き失敗（権限・破損・ディスク不足）
  - 出力フォルダ作成失敗
  - ログ書き込み失敗
- 例外は Orchestrator に伝播し、task の retry 制御（再キューまたは failed 判定）に委ねる。

## プロンプト

- `snapshotting` 自体は LLM を呼ばないため、専用の system/user prompt は存在しない。
- 本ステップが使う `global_digest` は、前段 `integrating` ステップで
  synthesizer prompt と schema により生成済みの内容である。

## 補足（責務境界）

- `integrating`: 「知識を統合して作る」工程
- `snapshotting`: 「統合済み知識を配布形式に固定する」工程

この分離により、統合ロジック変更と出力フォーマット変更を独立して扱える。
