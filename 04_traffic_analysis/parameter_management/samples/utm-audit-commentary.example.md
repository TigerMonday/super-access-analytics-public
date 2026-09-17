# UTM監査コメント サンプル

**対象**: サンプル株式会社  <!-- leak-ok: ダミー会社名の統一表記（実在の社名ではない） -->
**期間**: 2026-05-01 から 2026-05-31  
**目的**: `Unassigned`、`Direct`、QR流入を、運用可能なUTMルールに落とし込む

---

## [チャネル分類] Unassignedは件数だけでなく中身を示す

| チャネル | セッション | 成果 | CVR | 読み取り |
|---|---:|---:|---:|---|
| Organic Search | 12,000 | 480 | 4.0% | 自然検索が主力 |
| Paid Social | 8,500 | 90 | 1.1% | 認知・比較検討寄り |
| Direct | 6,200 | 310 | 5.0% | 参照元欠損を含む可能性 |
| Unassigned | 420 | 55 | 13.1% | UTMまたはチャネル分類の確認が必要 |

Unassignedの主な中身:

| source / medium | セッション | 推定原因 | 対応案 |
|---|---:|---|---|
| `flyer / qr` | 180 | `qr` が標準チャネルに分類されない | `medium=qr` を維持する場合はカスタムチャネルを作る |
| `shop_sign / qr` | 120 | 店頭QRの独自medium | `source=shop_sign`, `medium=qr` に統一 |
| `instagram / paid` | 90 | `paid` が媒体種別として曖昧 | `source=meta`, `medium=paid_social` に統一 |
| `line / message` | 30 | mediumが標準分類に合わない | `source=line`, `medium=social` または `message` の扱いを決める |

---

## [現行運用] パラメータは媒体・店舗・施策が混在している

観測された値から見ると、現在のUTMは以下のように運用されている可能性がある。

| 観測値 | 推定される運用 | 問題 |
|---|---|---|
| `meta / cpc` | Meta広告をCPC媒体として登録 | GA4上はPaid Searchと誤認される可能性 |
| `ig / paid` | Instagram広告を略称で登録 | `meta / paid_social` と集計が割れる |
| `flyer / qr` | チラシQR | 店舗・配布物の粒度がcampaignに入っていない |
| `shop_sign / qr` | 店頭看板QR | 店舗ごとの比較軸が不足 |

---

## [推奨ルール] 媒体種別をmedium、施策・店舗をcampaignに分ける

| 用途 | 推奨値 | 例 |
|---|---|---|
| 広告媒体 | `utm_source=meta` | Meta広告はFacebook/Instagramで分けすぎない |
| 媒体種別 | `utm_medium=paid_social` | Paid Socialとして安定分類する |
| QR | `utm_medium=qr` | 標準チャネルにない場合はカスタムチャネルで受ける |
| 店舗別 | `utm_campaign={store}_{purpose}_{yyyymm}` | `shibuya_trial_202605` |
| クリエイティブ | `utm_content={creative_id}` | `banner_a`, `flyer_front` |

---

## [修正推奨] 先に直す項目

| 優先度 | 対象 | 修正案 | 担当 |
|---|---|---|---|
| 高 | `ig / paid` | `meta / paid_social` に統一 | 媒体運用 |
| 高 | QR流入 | `source` と `campaign` に店舗・掲出物を入れる | 店舗/媒体運用 |
| 中 | Unassigned | カスタムチャネルで `medium=qr` を定義 | GA4管理 |
| 中 | Direct | 予約ドメイン遷移と参照元除外を確認 | GA4/GTM |

---

## 表現ルール

- `Unassignedが多い` だけで終えず、該当する `source / medium` を必ず書く
- 推奨値は現状値との対応がわかるように書く
- QR、店頭、チラシ、SNSプロフィールなど、広告管理画面に出ない流入を漏らさない
