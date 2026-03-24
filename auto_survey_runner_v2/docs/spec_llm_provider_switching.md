# LLM プロバイダ切替設計メモ（検討）

## 背景

現状は `survey_runner/ollama_client.py` と `config.yaml` の `ollama.*` 設定に強く依存しており、OpenAI など他プロバイダに切り替えるにはコード変更が必要です。

目的は **設定変更のみで LLM プロバイダを切替可能にすること** です。

## 現状整理

- Orchestrator は `OllamaClient` を直接 new している。
- `chat_json` / `chat_text` という呼び出しインターフェースは stage 側で共通利用できる。
- structured output は Ollama の `format` スキーマを使っている。

このため、切替対応の要点は以下の 2 点です。

1. クライアント生成をファクトリ経由にする（DI 化）。
2. provider ごとの structured output 差異を吸収する。

## LiteLLM 採用の評価

### 良い点

- OpenAI / Anthropic / Gemini / Ollama / OpenRouter 等を同一 API で扱える。
- モデル文字列（例: `openai/gpt-4o-mini`, `ollama/qwen2.5:7b`）で provider を切替しやすい。
- 将来的な routing/fallback/retry を導入しやすい。

### 注意点

- 依存追加によりトラブルシュート対象が 1 層増える。
- provider ごとの JSON schema サポート差異があり、完全互換ではない。
- レスポンスオブジェクト形状の差があるため、既存ログ実装に変換レイヤが必要。

### 結論（現時点）

**LiteLLM は「設定で切替」要件にかなり適合**します。特に将来 provider を増やす前提なら有力です。

一方、最小実装であれば「自前の `ProviderClient` 抽象 + `OpenAIClient` / `OllamaClient` 実装」でも達成可能です。まずは LiteLLM 前提で設計し、問題が出た場合に自前実装へ戻せるよう境界を薄く保つのが安全です。

## 推奨アーキテクチャ（段階導入）

### 1) 設定スキーマ

```yaml
llm:
  provider: "litellm"
  model_map:
    planner: "openai/gpt-4o-mini"
    extractor: "openai/gpt-4o-mini"
    synthesizer: "openai/gpt-4o"
  temperature:
    planner: 0.2
    extractor: 0.0
    synthesizer: 0.3
  timeout_seconds: 1800
```

- `ollama.*` への直接依存は廃止し、`llm.*` に一本化する。
- モデル名は role 単位（planner/extractor/synthesizer）で定義する。

### 2) クライアント抽象

`BaseLlmClient` インターフェースを導入し、以下を固定する。

- `chat_text(...) -> str`
- `chat_json(...) -> dict[str, Any]`

Orchestrator は `create_llm_client(config, logger)` 経由でインスタンス化する。

### 3) structured output 方針

優先順を統一する。

1. provider ネイティブ JSON schema
2. ツール呼び出し/JSON mode
3. プロンプト強制 + JSON 抽出（最終フォールバック）

これにより provider 差を実装内で吸収し、stage 側は変更最小で済む。

### 4) ログ方針

既存の `log_llm_request` / `log_llm_response` は維持し、provider 非依存の共通形式を追加する。

- `provider`
- `model`
- `raw_request`（秘匿情報はマスク）
- `raw_response`
- `parsed_payload`（chat_json 時）

## 移行ステップ（提案）

1. `BaseLlmClient` と `create_llm_client` を追加し、呼び出し経路を provider 非依存化する。
2. `Orchestrator` の直結依存をファクトリ経由へ差し替え。
3. LiteLLM 実装を追加（まず OpenAI + Ollama のみサポート）。
4. `config.example.yaml` を `llm.*` 中心に更新。
5. README に provider 切替例を追加。
6. `ollama.*` 参照コードを削除し、設定バリデーションを `llm.*` 専用にする。

## リスクと対策

- JSON パース失敗増加: 既存フォールバック（抽出再試行）を provider 共通化。
- モデル差による品質変動: role ごとにデフォルトモデルを固定し、温度も role 管理。
- API キー設定ミス: 起動時バリデーションで `provider` 別必須項目を明示する。

## まず着手する最小スコープ

- まずは「設計変更 + 実装変更」: Orchestrator の依存逆転と LiteLLM クライアント導入を同時に行う。
- 設定は `llm.*` のみサポートし、`ollama.*` は読み込まない。
- OpenAI と Ollama の 2 パターンで e2e 動作確認する。

この順なら、破壊的変更を抑えながら段階的に「設定で切替」へ移行できます。
