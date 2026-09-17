# 命名規則 (Naming Conventions)

GA4 / GTM 計測設計における命名規則。両サブエージェント (レビュー / 設計) が共通で参照する標準。

## 1. 適用対象

| 対象 | 例 | 場所 |
|------|----|------|
| GA4 イベント名 | `purchase`, `click_cta` | 章 06「イベント設定」 |
| GA4 イベントパラメータ名 | `link_url`, `transaction_id` | 章 07「変数取得」 |
| GA4 ユーザープロパティ名 | `user_id`, `member_grade` | 章 07 |
| GA4 カスタムディメンション / 指標キー | `link_url` (上記と同) | 章 07 |
| GTM タグ名 | `[GA4] purchase` | 既存実装監査 |
| GTM トリガー名 | `[Trigger] form_submit` | 既存実装監査 |
| GTM 変数名 | `[Var] dl - transaction_id` | 既存実装監査 |
| event_category | `サンプル株式会社` | 章 11 / 12 | <!-- leak-ok: ダミー会社名の統一表記（実在の社名ではない） -->
| event_label | `サンプル株式会社>CTA_SegmentA_記事上` | 章 11 / 12 | <!-- leak-ok: ダミー会社名の統一表記（実在の社名ではない） -->

## 2. GA4 側の文字規約

### 2.1 イベント名 / パラメータ名 / カスタム定義キー

| ルール | 内容 |
|--------|------|
| 文字種 | 半角英小文字 (a–z)、数字 (0–9)、アンダースコア (_) のみ |
| 先頭 | 英文字で始める (数字始まり禁止) |
| 最大長 | イベント名: 40 文字、パラメータ名: 40 文字、値: 100 文字 |
| 区切り | 単語の区切りはアンダースコア (`snake_case`) |
| ハイフン | 使わない |
| 大文字 / 全角 | 使わない |

### 2.2 推奨イベントの優先

GA4 の推奨イベント (Recommended Events) が定義されている用途では、独自の名前を作らず推奨イベント名を採用する:

- ログイン → `login`
- 会員登録 → `sign_up`
- 検索 → `search` または `view_search_results`
- 商品閲覧 → `view_item`
- カート操作 → `add_to_cart`, `view_cart`, `remove_from_cart`
- チェックアウト → `begin_checkout`, `add_shipping_info`, `add_payment_info`
- 購入 → `purchase`, `refund`

推奨イベントの完全な一覧と各イベントの必須パラメータは `docs/standards/reserved-words.md` を参照。

### 2.3 自作イベントの命名パターン

| パターン | 用途 | 例 |
|----------|------|----|
| `<動作>_<対象>` | 一般的なクリック・表示系 | `click_cta`, `view_lp`, `submit_form` |
| `<状態>_<対象>` | 状態遷移 | `start_checkout`, `complete_signup` |
| `<対象>_<指標>` | 量的なイベント | `scroll_depth`, `video_progress` |

### 2.4 パラメータ命名パターン

| パターン | 例 | 備考 |
|----------|----|------|
| `<対象>_<属性>` | `item_id`, `item_name`, `link_url` | GA4 推奨と整合 |
| `<対象>_<単位>` | `scroll_depth_pct`, `video_progress_pct` | 単位を明示 |
| `<対象>_id` | `transaction_id`, `chat_session_id` | ID は `_id` 接尾 |

## 3. GTM 側の命名 (運用ルール)

GTM では人が見やすい命名を許容するが、機械的なソートと検索性のため接頭辞を付ける。

### 3.1 タグ名

```
[<カテゴリ>] <event_name> - <補足>
```

| カテゴリ | 用途 | 例 |
|----------|------|----|
| GA4 | GA4 イベントタグ | `[GA4] purchase` |
| GA4-Config | GA4 設定タグ | `[GA4-Config] All Pages` |
| Floodlight | 広告計測 | `[Floodlight] purchase` |
| HTML | カスタム HTML | `[HTML] dataLayer init` |

### 3.2 トリガー名

```
[Trigger] <event_name または条件>
```

| 例 | 用途 |
|----|------|
| `[Trigger] custom - purchase` | カスタムイベント |
| `[Trigger] click - cta` | クリック |
| `[Trigger] page_view - thanks` | ページビュー |

### 3.3 変数名

```
[Var] <種別> - <内容>
```

| 種別 | 内容 |
|------|------|
| dl | データレイヤー変数 |
| const | 定数 |
| lookup | Lookup Table |
| js | カスタム JavaScript |
| cookie | 1st-party Cookie |

例: `[Var] dl - transaction_id`, `[Var] lookup - content_group`

## 4. event_category / event_label の規約

> **これは UA 時代の名残であり、GA4 の設計思想には合わない。**
> GA4 は「イベント名＋意味のあるパラメータ」で表現する。`event_category` / `event_label` に
> 階層を詰め込む設計を**新規に提案しない**。既に使われている案件で、現状を書くときと
> 移行の途中経過を書くときにだけ、この規約を適用する（章 11 / 12 で使う管理表用）。

| 項目 | ルール |
|------|--------|
| 文字種 | 全角・半角混在可 (ただしカンマ・改行 NG) |
| 区切り | 階層は `>` (半角不等号) で区切る |
| 例 | `event_category="サンプル株式会社"`, `event_label="サンプル株式会社>CTA_SegmentA_記事上"` | <!-- leak-ok: ダミー会社名の統一表記（実在の社名ではない） -->

## 5. 禁止事項

- PII (個人情報) を含む値の送信 (氏名・電話番号・住所・メールアドレス)
- GA4 予約イベント名・予約パラメータ名と同一の自作命名 (詳細: `reserved-words.md`)
- 大文字混在のイベント名 (例: `ClickCTA` は NG、`click_cta` にする)
- 命名の意味が同じだが綴りが違うもの (例: `cv_signup` と `signup_cv` を併用しない)
- スペース・タブを含む名前

## 6. レビュー観点

レビューで既存実装を確認する観点。新規設計の推奨規則と、既存名に修正を求める重要度は分けて扱う:

| 観点 | 検出方法 |
|------|---------|
| 文字種違反 | 数字/アンダースコア始まり、予約プレフィックス、40文字超、ハイフン以外の記号は High。ハイフンだけなら Low の参考情報 |
| 予約語衝突 | `reserved-words.md` のリストと文字列一致 |
| 長さ超過 | 40 文字 (キー) / 100 文字 (値) を超えるか |
| 重複・表記ゆれ | 編集距離 / 同義語マッピングで近似一致 |
| 大文字混在 | Low の参考情報。既存名の修正は必須にしない |

## 6.5 違反の発生源を特定する

**違反を見つけたら、直す前に「どこで作られた名前か」を突き止める。**
発生源が分からないまま修正案を出すと、直せない場所を直せと書くことになる。

| 発生源 | 見る場所 | 特徴 |
|---|---|---|
| GTM のタグ | `_data/09-gtm.json` | 修正はこちらで完結する。いちばん直しやすい |
| **GA4 のイベント作成ルール** | `_data/01-property.json` | **GTM をいくら見ても出てこない。** 日本語イベント名（`コラムページ到達` 等）はここが発生源のことが多い |
| ソースへの gtag 直書き | GTM にもルールにも無い | サイト改修が要る。工数の見積もりが変わる |
| 外部SaaS | [`third-party-tools.md`](./third-party-tools.md) | **こちらでは変えられない。**「違反」ではなくツールの仕様として扱う |

実際の案件では、命名規則違反の多くが **GA4 のイベント作成ルール由来**だったことがある。
GTM だけを見て「発生源不明」と書くところだった。

外部SaaS が送る名前（`optx_experience` 等）を違反として並べない。
`scroll` / `page_view` / `click` などの自動収集・拡張計測・推奨イベントも同様（[`reserved-words.md`](./reserved-words.md)）。

## 7. 命名衝突回避の優先順位

複数候補がある場合の優先順位:

1. GA4 推奨イベント名 / GA4 標準パラメータ名 — 最優先
2. 案件内で既に使われている名前 (一貫性) — 次点
3. 業界一般で使われている名前 — その次
4. 新規命名 — 最後

## 8. 関連

- 予約語・自動収集イベント: [`reserved-words.md`](./reserved-words.md)
- 外部SaaS が送る名前: [`third-party-tools.md`](./third-party-tools.md)
- 各章テンプレート: `templates/design-doc/`
