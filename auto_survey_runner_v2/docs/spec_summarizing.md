# summarizing ステップ仕様

## 目的
- task 単位の要約を作成する。

## 入力
- `claims.json`
- `extraction_meta.json`

## 処理
1. claim が存在する場合は synthesizer で briefing 指示（Executive Summary + 詳細テーマ分析 + 見出し/箇条書き + 客観的トーン）を付与して summary を生成する。
2. claim が存在しない場合は fallback summary を生成する。
3. fallback 文面は「source 未取得」か「extractor 失敗」かで切り替える。

## 出力
- `summary.json`
- `knowledge/task_summaries.jsonl`
