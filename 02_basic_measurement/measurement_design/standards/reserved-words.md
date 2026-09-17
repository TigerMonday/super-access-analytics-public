# GA4 予約語 (Reserved Words)

GA4 が予約しているイベント名・パラメータ名・ユーザープロパティ名の一覧。**自作命名でこれらと衝突させない** ためのチェックリスト。

> 出典: GA4 公式ドキュメント。仕様変更が起きるため、実装時は Google 公式ヘルプ (Recommended events / Restricted events / Reserved names) を最新で参照すること。

## 1. 予約イベント名 (Reserved Events)

これらの名前で **自作イベントを定義してはならない**。Google が将来用途を変える可能性がある、または既に内部で使われている。

```
ad_activeview
ad_click
ad_exposure
ad_impression
ad_query
ad_reward
adunit_exposure
app_clear_data
app_exception
app_install
app_remove
app_store_refund
app_store_subscription_cancel
app_store_subscription_convert
app_store_subscription_renew
app_update
app_upgrade
dynamic_link_app_open
dynamic_link_app_update
dynamic_link_first_open
error
first_open
first_visit
in_app_purchase
notification_dismiss
notification_foreground
notification_open
notification_receive
notification_send
os_update
screen_view
session_start
user_engagement
```

## 2. 自動収集 / 拡張計測機能で使われるイベント名

これらは自動収集または拡張計測機能で送信される。**同名で自作カスタムを作ると二重計上または上書き** になる:

```
page_view
scroll
click
view_search_results
video_start
video_progress
video_complete
file_download
form_start
form_submit
```

## 3. 推奨イベント名 (Recommended Events)

下記用途では Google が事前定義した名前を使うのが推奨。自作する場合も同じ名前を使えば GA4 のレポート / 機械学習機能が活用できる:

### 3.1 全プロパティ共通

```
ad_impression
earn_virtual_currency
generate_lead
join_group
level_end
level_start
level_up
login
post_score
purchase_refund (アプリ)
search
select_content
share
sign_up
spend_virtual_currency
tutorial_begin
tutorial_complete
unlock_achievement
```

### 3.2 オンライン販売 (E コマース)

```
add_payment_info
add_shipping_info
add_to_cart
add_to_wishlist
begin_checkout
purchase
refund
remove_from_cart
select_item
select_promotion
view_cart
view_item
view_item_list
view_promotion
```

### 3.3 ジョブ・教育・旅行 (Job, Education, Travel)

```
view_job
search_job
view_search_results
apply_job
apply_complete
view_course
view_program
view_property
book_property
```

## 4. 予約パラメータ名 (Reserved Parameters)

イベントパラメータとして使えない / 特別な意味を持つもの。

### 4.1 自動収集パラメータ (上書き不可)

```
ga_session_id
ga_session_number
session_engaged
engagement_time_msec
engaged_session_event
firebase_event_origin
firebase_screen
firebase_screen_class
firebase_screen_id
google_analytics_4_xx_xx (内部用)
```

### 4.2 GA4 のデフォルトイベントパラメータ (送信は可能だが意味固定)

```
page_location
page_referrer
page_title
page_path
content_group
language
screen_resolution
client_id
user_id
```

### 4.3 EC パラメータ (推奨イベント用、決まった意味で使う)

```
affiliation
coupon
currency
discount
index
item_brand
item_category
item_category2
item_category3
item_category4
item_category5
item_id
item_list_id
item_list_name
item_name
item_variant
items
location_id
price
promotion_id
promotion_name
quantity
shipping
shipping_tier
tax
transaction_id
value
```

## 5. 予約ユーザープロパティ接頭辞

ユーザープロパティ名で以下の接頭辞は使えない:

```
google_
ga_
firebase_
```

## 6. その他の制約

| 制約 | 内容 |
|------|------|
| イベント名最大長 | 40 文字 |
| パラメータ名最大長 | 40 文字 |
| パラメータ値最大長 | 100 文字 |
| 1 イベントあたりのパラメータ数 | 25 個 |
| プロパティあたりのカスタムディメンション (イベントスコープ) | 50 |
| プロパティあたりのカスタムディメンション (ユーザースコープ) | 25 |
| プロパティあたりのカスタム指標 | 50 |

## 7. 衝突検出パターン

> **重要 — 「観測された」と「衝突」は別物**
> GA4 のレポート/イベント一覧に §2（自動収集・拡張計測）や §3（推奨イベント）の名前が**現れること自体は正常**であり、違反ではない。GA4 自身がこれらを送信する。衝突として扱うのは、**ユーザーが §1 の予約イベント名を流用して自作イベントを定義している**ケースに限る。
> `review` の機械検出（`src/measurement_design/review/diagnoser.py`）は、observed イベントのうち §2・§3 に該当する標準イベント名を予約語衝突の対象から除外する（`GA4_STANDARD_EVENTS`）。`scroll` / `page_view` / `click` / `share` / `video_*` / `file_download` 等を Critical 検出していたら誤検知。

レビューサブが既存実装に対し衝突を検出するための手順:

1. §1 / §4.1 にリストされた名前を**自作イベント/プロパティで流用** → Critical（observed なだけの §2・§3 標準イベントは対象外）
2. §3 (推奨イベント名) を自作しているのに、推奨イベントの必須パラメータが揃っていない → High
3. §4.2 / §4.3 のパラメータ名を別の意味で使っている → High
4. §5 の接頭辞をユーザープロパティで使用 → Critical
5. §6 の上限を超える → High
6. 数字/アンダースコア始まり・予約プレフィックス・40文字超・ハイフン以外の記号は High として修正案を出す。大文字・ハイフンだけなら Low の参考情報にとどめ、既存名の修正を促さない。新規命名は有効な snake_case に揃える

## 8. 注記

- 本ファイルは Google 公式仕様のスナップショット。**仕様変更があり得るため**、メジャーな計測設計レビュー時は最新の公式ヘルプを再参照すること。
- 「予約イベント名」と「推奨イベント名」は別物。前者は使ってはいけない、後者は積極的に使う。
- 関連: `docs/standards/naming-conventions.md`
