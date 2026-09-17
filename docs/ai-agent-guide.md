# AIエージェント共通ガイド

super-access-analytics は、特定のAI製品を必須にしない。Claude Code、Codex、Gemini CLI、GitHub Copilot、Cursor、Windsurf、Cline/Roo Codeなど、リポジトリ内のMarkdownとローカルコマンドを扱えるエージェントから利用できる。

## 基本方針

1. 実行順序・保存先・確認事項の正本は `docs/standard-run-order.md` と各機能の `run.md` / `README.md` / `SKILL.md` とする。
2. GA4/GTMの取得、集計、機械診断、グラフ・HTML生成はローカルのPythonで行う。
3. 数値の解釈、考察、改善案の文章化は、現在このリポジトリを操作しているAIエージェント自身が行う。
4. Pythonから別のAI CLIやAPIを自動で呼ばない。外部LLMバックエンドは、利用者が送信先と対象データを理解して明示指定した場合だけ使う。
5. AIが無い場合も、データ取得・機械診断・既存MarkdownのHTML変換は実行できる。
6. Googleサービスへ接続するときは、[サービスアカウントの接続・運用](./service-account-operations.md)に従う。既定では同じ読み取り用の鍵を使い、別の鍵が明示された場合だけ切り替える。接続先は利用者に確認する。
7. OSツール、Python、ライブラリなどをインストールするときは、何を何のために入れるかを先に説明し、利用者の許可を得てから実行する。

## 利用者への問い合わせ窓口の案内

窓口は [スーパーアクセス解析のお問い合わせフォーム](https://sdjhe.share.hsforms.com/2YuKJnaAHSpW95m9Hqw5kqA)。使い方の疑問、不具合、改善要望、感想を受け付ける。

- 初めて使う利用者への最初の案内（準備・セットアップ・初回利用）で、通常の説明に添えて一度だけリンクを伝える。同じ会話で案内済みなら毎回繰り返さない。
- 利用者が質問・不具合・改善要望・感想を伝えたときは、必要に応じて運営への連絡先としてリンクを添える。回答できる疑問や解決できる不具合にはその場で対応し、フォームへの誘導だけで作業を終えない。運営へ連絡したいと言われた場合は必ず案内する。
- 案内例：「使い方の疑問や改善要望は、[お問い合わせフォーム](https://sdjhe.share.hsforms.com/2YuKJnaAHSpW95m9Hqw5kqA)から運営へ送れます。クライアント情報やアクセス解析の実データ、認証情報は入力しないでください。」
- 公開Issueへの投稿を受付方法として案内しない。フォームへの自動送信や、ログ・レポート・クライアント情報の自動添付はしない。利用者自身が内容を確認して送信する。
- 脆弱性の詳細は公開せず、[SECURITY.md](../SECURITY.md) の報告方法へ案内する。

## 初回セットアップを頼まれた場合

利用者から「セットアップしたい」「初期設定をしたい」「GA4につなぎたい」「使える状態にして」と頼まれたら、分析を始める前に[`setup-workflow.md`](./setup-workflow.md)を読む。

AI自身が現在の設定状況を確認し、完了済みの手順を飛ばしながら案内する。利用者へコマンドの実行を頼まず、Googleの管理画面など本人にしかできない操作だけを一度に一まとまりずつ案内する。Pythonやライブラリなどのインストールは、内容と用途を説明して利用者の許可を得てから行う。GA4接続後は、GTM・Search Console・BigQueryを同じサービスアカウントで追加するか3つまとめて確認する。セットアップ完了後は次に行うことを質問し、基本分析やサイト改善まで行う場合は「市場・顧客理解 → 基本分析 → サイト改善案」の順を案内する。

## 初回の準備だけを頼まれた場合

READMEの導入手順で「GA4に接続せず、sample-clientの入力ファイルを確認して」と頼まれたら、サイト登録や分析には進まず、次の準備を行う。

1. リポジトリの場所と`uv`を実行できることを確認する。見つからなければ、用途を説明して許可を得てから、READMEの「必要なツールをインストールする」「AIエージェントでフォルダを開く」に沿って案内する。
2. [セットアップ案内の手順1](./setup-workflow.md#1-インストールせずに現在の状態を確認する)に沿って、必要なPythonとライブラリを入れてよいか確認する。許可された場合だけ準備し、`02_basic_measurement/measurement_design`で`uv run --no-sync python run.py validate --client sample-client`を実行する。
3. 終了コードと検証結果を確認し、ファイルの読み込みに成功したかを伝える。これはレポート生成やGoogleとの接続確認ではない。鍵を読んだり、GA4/GTMからデータを取得したりしない。
4. 成功したら、READMEの「GA4につなぐ」へ案内する。鍵がすでに用意されていても、この準備だけの依頼では接続まで進めない。

## エージェント共通の開始手順

BigQueryを使うときは `docs/bigquery-cost-guardrails.md` を読み、費用見積もりと必要な同意を実行前に確認する。

利用者から「アクセス解析をしたい」と依頼されたら、次の順に読む。

1. `docs/standard-run-order.md`
2. 目的に対応する機能の正本
3. レポートを作る場合は `docs/report-consultation-quality.md`（作成前・途中の相談と4レポートの完成基準）、続けて `docs/report-writing-style.md`
4. 図表を作る場合は `common/report_export/design_system/visualization-guidelines.md`
5. HTMLを作る場合は `common/report_export/design_system/design-system.md`

目的と正本の対応は次のとおり。

| 目的 | 正本 |
|---|---|
| 計測チェック・計測設計 | `02_basic_measurement/measurement_design/README.md` |
| 市場・顧客理解（3C・ペルソナ・カスタマージャーニー） | `03_external_research/web_research/external-research-coordinator/SKILL.md` |
| 集客・UTM分析 | `04_traffic_analysis/parameter_management/run.md` |
| 単発分析 | `07_adhoc_analysis/run.md` |
| CVR改善 | `05_campaign_optimization/run.md` |
| 効果検証 | `06_effect_verification/` 以下の手順書 |
| サイト情報の登録 | `01_context_management/run.md` |

## ツール別の入口

| 環境 | 入口 | 呼び出し方 |
|---|---|---|
| Claude Code | `CLAUDE.md` | 自然文 |
| Codex | `AGENTS.md` | 自然文 |
| Gemini CLI | `GEMINI.md` | 自然文 |
| GitHub Copilot | `.github/copilot-instructions.md` | 自然文 |
| Cursor | `.cursor/rules/saa.mdc` | 自然文 |
| Windsurf | `AGENTS.md` と `.windsurf/rules/saa.md` | 自然文 |
| Cline | `AGENTS.md` と `.clinerules/saa.md` | 自然文 |
| Continue | `.continue/rules/saa.md` | 自然文 |
| Aider | `.aider.conf.yml` から `AGENTS.md` を読込 | 自然文 |
| Roo CodeなどAGENTS.md対応環境 | `AGENTS.md` | 自然文 |
| その他 | このファイル | 自然文 |

入口ファイルは案内だけに留める。同じ分析手順を複数の入口へコピーしない。すべての環境で専用スラッシュコマンドを前提にせず、「計測チェックして」「市場と顧客を調べて」「基本分析して」「サイト改善案を作って」のような自然文から目的に対応する正本へ進む。

## 外部LLMを任意で使う場合

計測チェックのPython CLI（`02_basic_measurement/measurement_design/run.py`）は既定で `--llm-backend none` として動き、外部AIへデータを送らない。互換機能として次を明示指定できる。

```bash
# Claude Code CLIへ送る
uv run python run.py review --client CLIENT_ID --llm-backend claude_cli

# Anthropic APIへ送る（ANTHROPIC_API_KEYが必要）
uv run python run.py review --client CLIENT_ID --llm-backend anthropic_api
```

この指定を行う前に、`docs/data-handling.md` を読み、利用者から送信先と送信対象について承認を得る。

CodexやGeminiなどのサブスクリプションを、Pythonの内部処理から汎用APIとして利用できるとは限らない。そのため、各社CLIを次々に子プロセス対応するのではなく、現在のエージェント自身が共通手順を実行する方式を標準とする。
