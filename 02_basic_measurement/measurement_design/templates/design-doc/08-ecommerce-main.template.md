# 章 08: E コマース変数設計_本体

> サンプル設計書の「Eコマース変数設計_本体」シート相当。本サイトの EC イベントと、各イベントで送信するパラメータのクロス表。

## メタ情報

| 項目 | 値 |
|------|----|
| 対象プロパティ | {{プロパティ名}} |
| 最終更新日 | {{YYYY-MM-DD}} |
| 対象範囲 | 本体サイト (LP・チャットボットは章 09) |

## EC イベント一覧

GA4 推奨 EC イベントから本案件で使うものを列挙する:

| event_name | 計測タイミング | 主なパラメータ | 備考 |
|-----------|---------------|--------------|------|
| `view_item_list` | アイテム一覧表示 | `item_list_id`, `item_list_name`, `items` | |
| `select_item` | 一覧からアイテム選択 | `item_list_id`, `item_list_name`, `items` | |
| `view_promotion` | プロモーション表示 | `promotion_id`, `promotion_name`, `items` | |
| `select_promotion` | プロモーションから選択 | `promotion_id`, `promotion_name`, `items` | |
| `view_item` | 商品詳細表示 | `items`, `value`, `currency` | |
| `add_to_wishlist` | お気に入り追加 | `items`, `value`, `currency` | |
| `add_to_cart` | カート追加 | `items`, `value`, `currency` | |
| `view_cart` | カート表示 | `items`, `value`, `currency` | |
| `remove_from_cart` | カートから削除 | `items`, `value`, `currency` | |
| `begin_checkout` | チェックアウト開始 | `items`, `value`, `currency`, `coupon` | |
| `add_shipping_info` | 配送情報入力 | `items`, `value`, `currency`, `shipping_tier` | |
| `add_payment_info` | 支払い情報入力 | `items`, `value`, `currency`, `payment_type` | |
| `purchase` | 購入完了 | `transaction_id`, `value`, `currency`, `tax`, `shipping`, `coupon`, `items` | |
| `refund` | 返品 | `transaction_id`, `value`, `currency`, `items` | |

## items 配列のスキーマ

| キー | 型 | 説明 | 値の例 |
|------|----|------|--------|
| `item_id` | STRING | 商品 SKU / コード | `{{SKU-0001}}` |
| `item_name` | STRING | 商品名 | `{{...}}` |
| `affiliation` | STRING | 販売元 (本体 / LP 等) | `本体` |
| `coupon` | STRING | クーポンコード | `{{...}}` |
| `currency` | STRING | 通貨 (ISO 4217) | `JPY` |
| `discount` | FLOAT | 値引き額 | `{{0}}` |
| `index` | INTEGER | リスト内の位置 | `{{1}}` |
| `item_brand` | STRING | ブランド | `{{ブランド名}}` |
| `item_category` | STRING | カテゴリ 1 | `{{スキンケア}}` |
| `item_category2` | STRING | カテゴリ 2 | {{...}} |
| `item_category3` | STRING | カテゴリ 3 | {{...}} |
| `item_category4` | STRING | カテゴリ 4 | {{...}} |
| `item_category5` | STRING | カテゴリ 5 | {{...}} |
| `item_list_id` | STRING | リスト ID | `{{list_top_recommend}}` |
| `item_list_name` | STRING | リスト名 | `{{TOP レコメンド}}` |
| `item_variant` | STRING | バリアント | {{容量 / 色 など}} |
| `location_id` | STRING | 場所 ID | {{...}} |
| `price` | FLOAT | 単価 (税抜 / 税込は案件規約) | `{{0}}` |
| `quantity` | INTEGER | 数量 | `{{0}}` |

## URL × イベント の組み合わせ

| URL パターン | view_item_list | select_item | view_promotion | select_promotion | view_item | add_to_wishlist | add_to_cart | view_cart | remove_from_cart | begin_checkout | purchase |
|-------------|----------------|-------------|----------------|------------------|-----------|-----------------|-------------|-----------|------------------|----------------|----------|
| `/products/list` | {{✓}} | {{✓}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} |
| `/products/detail/*` | {{...}} | {{...}} | {{...}} | {{...}} | {{✓}} | {{✓}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} |
| `/cart` | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{✓}} | {{✓}} | {{...}} | {{...}} |
| `/checkout` | | | | | | | | | | {{✓}} | |
| `/complete` | | | | | | | | | | | {{✓}} |

## 値の単位・規約

| パラメータ | 規約 |
|-----------|------|
| `value` | 税抜 / 税込 / 送料込み のどれか — 案件で固定 |
| `currency` | ISO 4217 (`JPY`) |
| `transaction_id` | 二重計測を避けるため案件で一意なフォーマット (`TX-YYYYMMDD-NNNNN` 等) |
| `coupon` | クーポンコード文字列 (PII を含まないこと) |

## 注記

- LP / チャットボット用の派生設計は章 09 参照。
- アイテム情報を持たない LP では `items` を省略可だが、`value` `currency` は必須にしておくと購入計上が崩れにくい。
