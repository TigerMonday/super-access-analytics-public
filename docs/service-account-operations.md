# サービスアカウントの接続・運用

GA4、Search Console、GTM、BigQueryをAIエージェントやローカルツールから接続する際の共通ルール。特定のクライアントやAI製品に依存しない。

## 1. 管理原則

1. GA4、Search Console、GTM、BigQueryは、同じ読み取り用サービスアカウントを使える。組織の方針で分ける場合は、ツールごとに別の鍵を指定する。
2. 編集が必要な場合は、読み取り用アカウントへ権限を足さず、編集用アカウントを分ける。
3. Search Consoleは制限付きユーザーとして追加する。サイトマップ送信やインデックス登録は担当者のアカウントで行う。
4. 鍵はリポジトリ外に置き、Git、`outputs/`、チャット、ログへ出さない。組織の秘密管理サービスがある場合は、そこを正本とする。
5. 接続時は、サービスアカウントのメールアドレス、接続先、権限を確認する。別のサイトへ自動で切り替えない。

## 2. ローカルの既定配置

| ツール | 既定パス | 上書き用環境変数 |
|---|---|---|
| GA4 | `~/.saa/credentials/google-analytics/sa-key.json` | `GA4_SA_KEY_PATH` |
| Search Console | GA4用鍵を使用 | `SC_SA_KEY_PATH`（別の鍵を使う場合） |
| BigQuery | GA4用鍵を使う構成ではGA4の指定先 | `BQ_SA_KEY_PATH` |
| Google Docs / Sheets出力 | `~/.saa/credentials/google-export/sa-key.json` | `SAA_GOOGLE_EXPORT_SA_KEY_PATH` |

GTMもGA4用の鍵を使う。ツールごとに鍵を分ける場合は、各機能の手順書に従う。

## 3. 新しいクライアントへ接続する流れ

1. 台帳で対象ツールの読み取り用サービスアカウントと権限範囲を確認する。
2. クライアント側の対象プロパティまたはデータセットへ、必要最小限の権限を付与してもらう。
3. 組織の秘密管理基盤から、該当する鍵だけを既定パスへ配備する。既存ファイルを上書きする前に `client_email` を確認する。
4. APIで閲覧可能な対象を一覧またはURL照合し、登録済みのサイト・プロパティと一致することを確認する。
5. 一致した対象だけをクライアントコンテキストへ保存する。候補が複数ある場合や一致しない場合は利用者に確認する。
6. レポートには、利用したデータソースと対象期間を書く。サービスアカウント名や鍵の場所は書かない。

## 4. Search Consoleの接続確認

GA4用のサービスアカウントをSearch Consoleへ追加したあと、基本分析のフォルダで次を実行する。

```powershell
uv run python scripts/fetch_search_console.py --match-site-url https://example.com/
```

期待するURLと `siteRestrictedUser` が返れば、読み取り接続は完了している。何も返らない場合は、次を順に確認する。

- 鍵の `client_email` と、Search Consoleに追加したユーザーが一致しているか
- 対象URLがURLプレフィックスかドメインプロパティか
- Search Console APIが、鍵を発行したGCPプロジェクトで有効か
- 別の鍵を使う場合は、`SC_SA_KEY_PATH`が正しいファイルを指しているか

## 5. Windowsでgcloudの証明書エラーが出る場合

ウイルス対策ソフトや社内プロキシがHTTPS通信を検査している環境では、ブラウザ認証後のトークン交換で `CERTIFICATE_VERIFY_FAILED` が出ることがある。証明書検証を無効にしない。

1. OSで信頼されている検査用CA証明書の実ファイルを確認する。
2. 現在のPowerShellだけに適用する場合は、次のようにgcloud専用の環境変数へ設定する。

```powershell
$env:CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE = 'C:\path\to\trusted-ca.pem'
gcloud auth login user@example.com --no-activate --force
```

`--force` は証明書検証を無効にする指定ではなく、期限切れの保存済み認証を再利用せず、新しいログイン処理を開始する指定である。ブラウザで「認証完了」と表示されても、PowerShell側で成功メッセージが出る前に証明書エラーになった場合は認証情報が保存されていない。

接続先を切り替えるために別のGoogleアカウントへ勝手にログインしたり、`auth/disable_ssl_validation` を有効にしたりしない。
