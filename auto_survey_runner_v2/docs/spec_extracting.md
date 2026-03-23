# extracting ステップ仕様

## 目的
- source から claim を構造化抽出する。

## 入力
- `collected_sources.json`
- `config.ollama.extractor_model`
- `config.models.extractor_temperature`
- `config.quality.claim_confidence_threshold`

## 処理
1. source ごとに task title / source title / URL 由来のキーワードを作る。
2. 関連度の高い行だけを抜粋して compact prompt を構築する。
3. extractor に JSON schema 付きで問い合わせる。
4. claim ごとに confidence しきい値を適用する。
5. source 単位の失敗は隔離し、残り source を継続する。
6. `claims.json` と `extraction_meta.json` を保存する。

## 出力
- `claims.json`
- `extraction_meta.json`
- `knowledge/claims.jsonl`

## エラー時
- 空応答は warning として記録し継続する。
- source ごとの失敗件数とメッセージは `extraction_meta.json` に保存する。
