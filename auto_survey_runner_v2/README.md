# auto_survey_runner_v2

`auto_survey_runner_v2` は、ローカル文書と Web 収集を組み合わせて段階的にサーベイを進めるための Python 実装です。Planner / Extractor / Synthesizer の役割を分離し、状態管理を明示化することで、中断・再開・再試行に強いワークフローを目指します。

## 目的

- 調査テーマから段階的にタスクを生成し、優先度付きキューで探索する。
- `state/`, `knowledge/`, `outputs/` を完全に分離し、再開可能な実行状態と、蓄積知識、レンダリング済み成果物を分離する。
- タスクごとに `planning -> collecting -> extracting -> summarizing -> spawning -> integrating -> snapshotting -> done` の段階を進める。
- 各タスクの完了時点で「そのタスク単体」ではなく、そこまでに集まった全体成果を統合して出力する。

## 設計概要

### ディレクトリ設計

- `state/`: 実行状態、キュー、進行中タスク、タスク別ワークディレクトリ。
- `knowledge/`: claim / source / summary / digest などの知識蓄積。
- `outputs/`: Markdown / JSON の外部共有向け成果物。
- `modelfiles/`: Ollama 用の役割別 Modelfile。
- `survey_runner/`: 実装本体。

### 状態 / 知識 / 成果物の分離

#### state/

- `run_state.json`: 現在の run 状態、設定、進行中タスク、統計。
- `tasks.json`: 全 Task の永続化。
- `queue.json`: 未完了タスクの単純 list。
- `state/task_work/<task_id>/`: 段階ごとの中間生成物。
- `state/logs/execution.jsonl`: 実行全体の構造化ログ。
- `state/task_work/<task_id>/events.jsonl`: task 単位の構造化ログ。

#### knowledge/

- `claims.jsonl`: 抽出済み claim。
- `sources.jsonl`: 利用済み source。
- `task_summaries.jsonl`: タスク要約。
- `global_digest.json`: 全体統合ダイジェスト。

#### outputs/

- `task_<id>_<slug>/integrated_report.json`
- `task_<id>_<slug>/integrated_report.md`
- `task_<id>_<slug>/manifest.json`

## コンテキスト初期化

`python run.py init --config config.yaml` を実行すると、設定検証後に必要ディレクトリと初期状態ファイルを生成します。初期 root task は設定ファイルの `research.topic` をもとに作られ、queue に投入されます。

## 状態仕様

### Task モデル

Task は少なくとも以下の情報を持ちます。

- `task_id`, `title`, `slug`, `description`
- `priority`, `depth`, `status`, `current_stage`
- `parent_task_id`, `created_at`, `updated_at`
- `retry_count`, `error_message`
- `planned_queries`, `collected_source_ids`, `extracted_claim_ids`, `summary_id`
- `spawned_task_ids`, `dedupe_key`, `notes`

### run_state.json

主に以下を保持します。

- 実行状態 (`idle`, `running`, `completed`, `failed`)
- `current_task_id`
- 直近更新日時
- 実行済み / 失敗数などの統計
- ルート task ID
- 直近エラーの概要 (`last_error_message`)

## 知識仕様

### SourceDoc

- ローカル文書または Web 取得文書の共通表現。
- 対応拡張子は `.txt`, `.md`, `.html`, `.htm` のみです。
- PDF は未対応です。

### Claim

- 文単位の知見。
- 正規化テキストで重複除去されます。
- どの task / source に由来するかを追跡します。

### Global Digest

全タスク統合の知識スナップショットです。各 task 完了時に更新・再レンダリングされます。

## 段階遷移

1. `planning`: planner が検索計画とサブトピック候補を生成。
2. `collecting`: ローカル文書と Brave Search API ベースの Web 文書を収集・ランキング。
3. `extracting`: extractor が structured output で claim を抽出。
4. `summarizing`: task 単位の要約を生成。source / claim が空の場合は LLM を呼ばずにフォールバック要約を作る。
5. `spawning`: 条件付きで派生 task を queue へ追加。
6. `integrating`: global digest を更新。
7. `snapshotting`: 全体統合成果物を `outputs/` に出力。
8. `done`: task 完了。

各段階は中間ファイルが存在する場合に再計算を避けます。これにより中断後の再開時に不要な再実行が発生しません。さらに、各段階の開始・完了、LLM に送った prompt、LLM から返った生テキスト、例外発生時の traceback を JSONL ログに残します。

## 再開

`run_state.json` の `current_task_id` が `running` の場合、Orchestrator はその task を再開します。そうでなければ `queue.json` から最大 priority の task を選びます。

## 再試行

task が失敗した場合、`retry_count < max_retry_per_task` なら queue に戻して再試行します。このとき run 全体は即座に終了扱いにせず、`run_state.json` は `idle` に戻り、`last_error_message` に原因を残します。上限を超えた task は `failed` のまま残り、run 全体の統計にも反映されます。

## 実手順

1. `cp config.example.yaml config.yaml`
2. `config.yaml` を編集し、必要なら `search.brave_api_key` または環境変数 `BRAVE_SEARCH_API_KEY` を設定する。
3. `python run.py init --config config.yaml`
4. `python run.py run --config config.yaml --steps 1`
5. 状態確認は `python run.py status --config config.yaml`

`--steps` は 1 回の実行で何 task 進めるかを制御します。

## モデル役割分離

- Planner: 検索クエリと派生調査候補を構造化生成。
- Extractor: 収集文書から claim を構造化抽出。
- Synthesizer: task summary と global digest を生成。

3 つの Modelfile は同じベースモデル `qwen3.5:9b` を使いますが、温度と生成長、system prompt を分離しています。

## 制約

- PDF 未対応。
- Brave Search API と URL 取得はネットワーク状況と API key に依存。source が空でもフォールバック成果物は出力されるが、内容は限定的になる。
- ranking は簡易な語彙重なりベース。
- structured output の品質は Ollama 側の schema 対応とモデル挙動に依存。

## 今後の改善候補

- PDF / DOCX / RSS 対応。
- 埋め込みベースの高精度ランキング。
- task の cancellation / backoff / timeout 制御。
- グローバルな重み付き evidence aggregation。
- HTML の本文抽出改善。
- 並列収集と並列抽出。
