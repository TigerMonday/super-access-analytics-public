# Search Consoleを読めるようにする（任意）

Google検索での表示回数や検索語を分析するための設定です。最初の計測チェックには不要です。

GA4用のサービスアカウントを、そのままSearch Consoleでも使います。鍵を新しく作る必要はありません。先に[GA4の初回セットアップ](./setup-ga4.md)を済ませてください。

## 1. サービスアカウントのメールアドレスを確認する

Google Cloud Consoleで、GA4用サービスアカウントのメールアドレスを確認します。`...iam.gserviceaccount.com`で終わるものです。

Search Consoleへ追加するのは、このメールアドレスです。鍵ファイルを渡す必要はありません。

## 2. Search Consoleで読む権限を与える

この操作には、対象サイトのSearch Consoleの「所有者」権限が必要です。所有者でなければ、次の操作を担当者に依頼してください。

1. [Google Search Console](https://search.google.com/search-console/)を開き、対象サイトを選びます。
2. 「設定」→「ユーザーと権限」を開きます。
3. 「ユーザーを追加」を押し、手順1（サービスアカウントのメールアドレスを確認する）で確認したメールアドレスを入力します。
4. 権限は「制限付き」を選びます。

対象サイトがSearch Consoleに未登録の場合は、先にサイトの管理担当者へ登録を依頼してください。権限については[Google公式の説明](https://support.google.com/webmasters/answer/7687615?hl=ja)も参照できます。

## 3. Search Console APIを有効にする

1. [Google Cloud Console](https://console.cloud.google.com/)で、GA4用サービスアカウントを作ったプロジェクトを選びます。
2. 「APIとサービス」→「ライブラリ」で「Search Console API」を検索します。
3. 「有効にする」を押します。すでに有効なら、そのまま次へ進みます。

## 4. AIに接続確認を頼む

このフォルダを開いているAIに、次のように伝えます。URLは自分のサイトに置き換えてください。

> GA4用のサービスアカウントをSearch Consoleへ制限付きユーザーとして追加し、Search Console APIも有効にしました。対象サイトは https://example.com/ です。読み取れるか確認してください。鍵の中身は表示しないでください。

AIが表示したURLまたは`sc-domain:example.com`が対象サイトと一致しているか確認します。複数ある場合は、使うサイトを選んでから保存します。

接続できたら設定は完了です。同じAIのチャットで「Search Consoleも含めて基本分析をしてください」と頼めます。

### 自分で確認する場合

AIに頼んだ場合は不要です。README.mdがあるフォルダで、次の2行を実行します。URLは自分のサイトに置き換えてください。

```bash
cd 04_traffic_analysis/parameter_management
uv run python scripts/fetch_search_console.py --match-site-url "https://example.com/"
```

対象サイトと`siteRestrictedUser`が表示されれば接続できています。

## 別のサービスアカウントを使う場合

会社の運用でGA4とSearch Consoleのアカウントを分ける場合だけ、Search Console用の鍵を用意します。リポジトリ外へ保存し、環境変数`SC_SA_KEY_PATH`にファイルの絶対パスを設定してください。

## うまくいかないとき

| 症状 | 確認すること | 対処 |
|---|---|---|
| 鍵が見つからない | GA4用鍵の保存先 | [GA4の初回セットアップ](./setup-ga4.md)で保存先を確認する |
| 対象サイトが見つからない | 追加したメールアドレスとサイト | GA4用サービスアカウントが、対象サイトに「制限付き」で追加されているか確認する |
| APIが無効と表示される | Google Cloudのプロジェクト | GA4用サービスアカウントを作ったプロジェクトでSearch Console APIを有効にする |
| `siteRestrictedUser`以外が表示される | Search Consoleの権限 | 所有者に「制限付き」への変更を依頼する |

解決できなくても、GA4だけで分析できます。AIに「Search Consoleは未接続なので、GA4だけで進めてください」と伝えてください。

APIの詳細は[Search Console API公式資料](https://developers.google.com/webmaster-tools/v1/api_reference_index)を参照してください。
