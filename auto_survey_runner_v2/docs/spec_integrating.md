# integrating ステップ仕様

## 目的
- 累積 summary / claims から global digest を更新する。

## 入力
- `knowledge/task_summaries.jsonl`
- `knowledge/claims.jsonl`
- `extraction_meta.json`

## 処理
1. claim がある場合は synthesizer で digest を生成する。
2. claim がない場合は fallback digest を生成する。
3. fallback 文面は extractor 失敗有無で切り替える。
4. `knowledge/global_digest.json` に書き戻す。

## 出力
- `global_digest.json`
- `knowledge/global_digest.json`
