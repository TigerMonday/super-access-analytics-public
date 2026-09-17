# utm 命名規則（デフォルト標準）

クライアント固有の命名規則が提供されない場合に、本ドキュメントをデフォルトとして適用する。

---

## 共通ルール

- すべて **小文字スネークケース**（`utm_source=google_search`）
- 半角英数とアンダースコアのみ。日本語・全角・スペース禁止
- 各値は **40文字以内** を目安（GA4 制限は500バイトだが集計性を考慮）
- `utm_medium` には GA4 標準チャネル分類との整合性を意識

---

## utm_source（流入元の識別子）

媒体・サービス名を**正規化された短い識別子**で記載。

| 媒体カテゴリ | 推奨 utm_source 例 |
|---|---|
| 検索エンジン | `google` / `yahoo` / `bing` |
| SNS | `facebook` / `instagram` / `x` / `linkedin` / `youtube` |
| 広告ネットワーク | `gdn` / `ydn` / `meta_ads` / `tiktok_ads` / `line_ads` |
| メールマーケ | `mailmag` / `newsletter` / `transactional_mail` |
| 提携メディア | `<media-name>`（例: `nikkei_xtech`） |
| 自社別サイト | `<service>` |

**禁則**: 同一意味で `Google` と `google`、`yss` と `yahoo` 等を混在させない。

---

## utm_medium（流入の種類）

GA4 のデフォルトチャネルグループに準拠した値を推奨。

| 流入の種類 | utm_medium 値 |
|---|---|
| 自然検索 | `organic`（通常は自動付与、手動設定不要） |
| 有料検索 | `cpc` |
| ディスプレイ広告 | `display` |
| 動画広告 | `video` |
| ソーシャル（オーガニック） | `social` |
| ソーシャル（有料） | `paid_social` |
| アフィリエイト | `affiliate` |
| メール | `email` |
| QR / オフライン | `qr` / `offline` |
| パートナーシップ | `partner` |
| リファラル（手動指定時のみ） | `referral` |
| AIアシスタント | `ai-assistant`（GA4が認識済み参照元へ自動付与する公式値。手動UTMの推奨値ではない） |

**禁則**: `mail`（→ `email`）、`paid`（→ `cpc` / `paid_social`）等の非標準値は使わない。

見慣れない値を禁則と判断する前に、GA4公式のデフォルトチャネル定義と更新履歴を確認する。
`ai-assistant` は2026年5月から公式値であり、命名違反として指摘しない。

---

## utm_campaign（施策・キャンペーン）

**命名規則**: `{年月}_{目的}_{施策名}` を推奨

例:
- `2026q2_acquisition_summer_lp`
- `202605_awareness_brand`
- `202606_lead_whitepaper_dl`

**禁則**: 日付なし、目的なしの曖昧な名（`new_campaign` 等）

---

## utm_content（クリエイティブ・配信面）

A/Bテストや複数クリエイティブの識別。

例:
- `banner_a` / `banner_b`
- `headline1` / `headline2`
- `lp_v1` / `lp_v2`

---

## utm_term（キーワード・ターゲティング）

検索広告のキーワードや、ターゲティング種別。

例:
- `アクセス解析+サービス`
- `audience_high_intent`
- `keyword_brand`

---

## GA4 / GTM 予約語との衝突回避

以下は **utm_*** 各値に使用禁止（自動取得パラメータと衝突するため）:
- `gclid`, `gad_source`, `gbraid`, `wbraid`（Google広告自動付与）
- `fbclid`（Meta広告自動付与）
- `yclid`（Yahoo広告自動付与）
- `msclkid`（Microsoft広告自動付与）
- `event_name`, `event_category`, `event_label`（GA4予約）

---

## カスタムディメンション（推奨追加）

媒体・施策の効果検証を深めるため、以下のカスタムディメンションを GA4 側で用意することを推奨:

| CD名 | 用途 | 取得元 |
|---|---|---|
| `creative_id` | クリエイティブ単位の効果比較 | `utm_content` or 独自 |
| `placement` | 配信面の特定（FB Feed, Stories 等） | 媒体側パラメータ |
| `audience_segment` | オーディエンスセグメント別効果 | 媒体側パラメータ |
| `lp_variant` | LP バリエーション識別 | クエリパラメータ or URL |
| `abtest_group` | A/Bテスト群識別 | 実験ツール連携 |

---

## 更新履歴

- 2026-05-21 初版作成（西）
