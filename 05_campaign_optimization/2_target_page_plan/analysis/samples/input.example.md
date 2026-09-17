# 入力例: ② 個別施策｜分析エージェント

```
①全体施策で「LPOを最優先・対象は有料流入の着地LP」と決まった。
この方針で、対象候補のLPを分析してほしい。

- クライアント名: 自社サイト / client_id: sample-client
- GA4 プロパティID: <GA4_PROPERTY_ID>（自社値は 01 コンテキストストア参照）
- 対象タイプ: LPO / 対象範囲: 有料流入(Paid Other)が着地するLP
- CVR分母: 広告LP着地で絞る（①から引き継ぎ）
- page_profile: 実施済み（outputs/sample-client/05_cvr/_past/page-profile.md）
```

※ ①の確定方針ファイルと page_profile があれば、それを読んで候補ページを絞り込む。
