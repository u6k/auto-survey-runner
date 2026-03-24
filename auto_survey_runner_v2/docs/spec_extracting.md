# extracting ステップ仕様

## 目的
- collecting ステップで収集した source から、**factual claim（事実主張）**を構造化抽出する。
- 後続の summarizing / integrating が使えるよう、claim を task 単位ファイルと全体知識ストアへ永続化する。
- 1 source の失敗で task 全体を止めない「防御的（defensive）」実行を行う。

## 入力
- `state/task_work/<task_id>/collected_sources.json`
  - collecting ステップで作成された source 一覧。
  - source の主なフィールド（実装上）:
    - `source_id`
    - `title`
    - `uri`
    - `content`
- モデル/品質設定
  - `config.ollama.extractor_model`
  - `config.models.extractor_temperature`
  - `config.quality.claim_confidence_threshold`
  - `config.ollama.extractor_disable_thinking`（既定で `think: false`）

## 出力
- `state/task_work/<task_id>/claims.json`
  - 当該 task の抽出済み claim 一覧（チェックポイント）。
- `state/task_work/<task_id>/extraction_meta.json`
  - source 件数 / claim 件数 / 失敗件数 / 失敗詳細。
- `knowledge/claims.jsonl`
  - 全 task 共通の claim 追記ログ。

## 作業
1. チェックポイント確認
   - `claims.json` が既に存在する場合は再抽出せず、その内容を返して終了する。
2. source ごとに抽出プロンプトを構築
   - `content` を HTML/entity/空白の観点で正規化する。
   - `task.title` / `source.title` / `source.uri` からキーワードを抽出する。
   - 行単位でキーワード一致スコアを計算し、関連度の高い行を抜粋して compact excerpt を作る（最大 3000 文字）。
   - 一致行がない場合は先頭 20 行をフォールバックとして使用する。
3. extractor モデルを structured output で呼び出し
   - system prompt + user prompt + JSON schema を与え、`claims` 配列を受け取る。
4. claim フィルタリングと整形
   - `confidence >= claim_confidence_threshold` の claim のみ採用する。
   - 空テキストは除外する。
   - 正規化済み text を使って `claim_id` を安定生成する。
5. 失敗隔離（source 単位）
   - 1 source で例外が発生しても、その source を失敗として記録し、残り source の処理を継続する。
6. 永続化
   - `extraction_meta.json` を保存する。
   - claim を `knowledge/claims.jsonl` に追記し、同内容を `claims.json` に保存する。

## 例外
- 空応答（例: `empty content for structured output`）
  - warning として記録し、処理は継続する。
- その他の source 単位エラー
  - 例外ログを記録し、処理は継続する。
- 失敗情報の保存
  - `extraction_meta.json.failures[]` に以下を保存する。
    - `source_id`
    - `title`
    - `error_message`

## LLM 呼び出し仕様

### System prompt（日本語解説）
extractor の system prompt は次を要求する。
- 日本語調査ワークフロー向けの抽出モデルとして振る舞う。
- source 本文から、事実主張・信頼度・根拠を JSON で返す。
- JSON 以外を返さない。
- source が日本語以外でも、JSON 内の自然言語文字列は日本語で返す。

### User prompt（実装テンプレートの意味）
source ごとに以下の意図で user prompt を組み立てる。
- Source title / Source URL を明示し、文脈を固定する。
- 「本文に**明示的に裏付けられる** factual claim のみ抽出」と指示する。
- ナビゲーション文、カテゴリ一覧、メニュー、宣伝文、重複断片を無視するよう指示する。
- 抜粋が一般的すぎて根拠にならない場合は `claims: []` を返すよう指示する。
- 最後に compact excerpt を `Content:` として渡す。

### 返却 schema
extractor は以下の JSON schema を満たす必要がある。
- ルート
  - `claims`: array（必須）
- claim 要素
  - `text`: string（必須）
  - `confidence`: number（必須）
  - `evidence`: string（必須）

## 例

### 入力例（1 source）
```json
{
  "source_id": "src_001",
  "title": "A社、2025年売上20%増",
  "uri": "https://example.com/a",
  "content": "...本文..."
}
```

### extractor 返却例（schema 準拠）
```json
{
  "claims": [
    {
      "text": "A社の2025年売上は前年比20%増加した。",
      "confidence": 0.92,
      "evidence": "本文中に『2025年売上は前年比20%増』とある。"
    }
  ]
}
```

### ステップ内判定例
- `claim_confidence_threshold = 0.8` の場合、上記 claim は採用。
- 正規化 text から `claim_id` を生成し、`claims.json` と `knowledge/claims.jsonl` へ保存。
- 該当 source が失敗した場合は `extraction_meta.json.failures[]` に記録。
