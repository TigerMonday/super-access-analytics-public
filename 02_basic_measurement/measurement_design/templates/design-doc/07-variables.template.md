# 章 07: 変数取得

> サンプル設計書の「変数取得」シート相当。イベントパラメータ・ユーザープロパティ・カスタムディメンション・カスタム指標の一覧。

## メタ情報

| 項目 | 値 |
|------|----|
| 対象プロパティ | {{プロパティ名}} |
| 最終更新日 | {{YYYY-MM-DD}} |

## ユーザープロパティ

| # | イベントパラメータ名 | 説明 | カスタムディメンション登録 (0/1) | キー | 型 | 値の例 | 備考 |
|---|--------------------|------|-------------------------------|------|----|--------|------|
| 1 | {{user_id}} | ユーザー ID | {{0 / 1}} | `user_id` | STRING | `"02a25607fb"` | {{ハッシュ化 ID}} |
| 2 | {{user_segment}} | ユーザーセグメント | {{...}} | `user_segment` | STRING | {{`new` / `repeat`}} | {{...}} |
| 3 | {{member_grade}} | 会員ランク | {{...}} | `member_grade` | STRING | {{...}} | {{...}} |

## イベントスコープのカスタムディメンション

| # | パラメータ名 | 説明 | キー (GA4 上) | 型 | 値の例 | 取得元イベント | 備考 |
|---|-------------|------|--------------|----|--------|----------------|------|
| 1 | `link_url` | リンク URL | `link_url` | STRING | `/products/123` | `click_cta` | |
| 2 | `link_text` | リンクテキスト | `link_text` | STRING | `新規登録はこちら` | `click_cta` | |
| 3 | `click_position` | クリック位置 | `click_position` | STRING | `header / footer / content` | `click_cta` | |
| 4 | `search_term` | 検索キーワード | `search_term` | STRING | `スキンケア` | `view_search_results` | |
| 5 | `content_group` | コンテンツグループ | `content_group` | STRING | `blog` | `page_view` | {{章 10 参照}} |
| 6 | `transaction_id` | 取引 ID | `transaction_id` | STRING | `TX-{{...}}` | `purchase` | EC |
| {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} |

## カスタム指標 (Custom Metrics)

| # | パラメータ名 | 説明 | キー | 単位 | 値の例 | 取得元イベント | 備考 |
|---|-------------|------|------|------|--------|----------------|------|
| 1 | {{scroll_depth_pct}} | スクロール深度 (%) | `scroll_depth_pct` | パーセント | `75` | `scroll` | |
| 2 | {{video_progress_pct}} | 動画再生進捗 (%) | `video_progress_pct` | パーセント | `50` | `video_progress` | |

## GA4 上での登録方針

- カスタムディメンション登録列が `1` のパラメータは GA4 管理画面で「カスタム定義」に登録する
- 登録上限は 50 (イベントスコープ) / 25 (ユーザースコープ) — 上限近くなる案件では使い回しを優先
- 型は GA4 が許容する範囲 (STRING / INTEGER / FLOAT / BOOLEAN)

## 注記

- 命名は半角小文字+アンダースコア。GA4 予約パラメータ (`page_title`, `page_location` 等) と重複しないこと: `docs/standards/reserved-words.md`。
- 個人情報 (氏名・電話番号・住所など) は **送信しない** こと。ハッシュ化済み user_id は許容。
