# snapshotting ステップ仕様

## 目的
- 外部共有向け成果物を Markdown / JSON で出力する。

## 入力
- `knowledge/global_digest.json`
- `knowledge/task_summaries.jsonl`
- `knowledge/claims.jsonl`

## 処理
1. 出力フォルダ `outputs/task_<id>_<slug>/` を用意する。
2. `integrated_report.json` を生成する。
3. `integrated_report.md` を生成する。
4. `manifest.json` を生成する。

## 出力
- `outputs/task_<id>_<slug>/integrated_report.json`
- `outputs/task_<id>_<slug>/integrated_report.md`
- `outputs/task_<id>_<slug>/manifest.json`
