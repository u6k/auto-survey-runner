# summarizing ステップ仕様

## 目的
- task 単位の要約を作成する。

## 入力
- `claims.json`
- `extraction_meta.json`

## 処理
1. claim が存在する場合は synthesizer で summary を生成する。
2. claim が存在しない場合は fallback summary を生成する。
3. fallback 文面は「source 未取得」か「extractor 失敗」かで切り替える。

## 出力
- `summary.json`
- `knowledge/task_summaries.jsonl`
