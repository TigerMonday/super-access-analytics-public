# 入力例: 自社コーポレートサイト

このサンプルは入力フォーマットの参考。実運用では対話形式（質問返し）で済むことも多い。

---

## 1. 媒体・施策一覧

| 媒体名 | 種別 | 目的 | 施策内容 |
|---|---|---|---|
| Google広告（検索） | 広告 | 獲得 | ブランド指名キャンペーン、CV最適化 |
| Yahoo広告 | 広告 | 獲得 | 検索広告、リターゲ |
| Google広告（GDN） | 広告 | 認知 | リターゲ広告 → サービス紹介 |
| Meta広告 | 広告 | 獲得 | リード獲得広告（WPダウンロード誘導） |
| LinkedIn広告 | 広告 | 認知 | スポンサードコンテンツ → 事例ページ |
| メルマガ | メール | 既存接点維持 | 月2回、お役立ちコンテンツ・セミナー案内 |
| LINE公式 | メッセージ | 獲得 | 月2配信、セミナー案内・新規問合せ誘導 |
| Facebook（オーガニック） | SNS | 認知 | 自社投稿、事例シェア |
| 提携メディア（Nikkei xTech） | タイアップ | 認知 | 月1本タイアップ記事 |

---

## 2. 既存命名規則

社内ルール未整備のため、デフォルト適用（[standards/naming-conventions.md](../standards/naming-conventions.md)）でお願いします。

---

## 3. GA4 流入データ

> このセクションは `scripts/fetch_ga4_traffic.py --property-id {ID} --days 28` の出力をそのまま貼り付ける。

例（実際の出力イメージ）:

```
## 4. GA4 流入データ（2026-04-23 ～ 2026-05-20）

### utm_source × utm_medium × utm_campaign 別セッション数

| utm_source | utm_medium | utm_campaign | セッション | エンゲージ | CV |
|---|---|---|---:|---:|---:|
| google | organic | (organic) | 6,200 | 4,100 | 18 |
| google | cpc | 2026q2_brand | 1,800 | 1,250 | 12 |
| Google | cpc | brand_camp | 320 | 220 | 2 |
| yahoo | cpc | search | 1,100 | 780 | 7 |
| yss | cpc | search | 180 | 130 | 1 |
| facebook | paid_social | wp_dl | 850 | 620 | 9 |
| meta_ads | cpc | wp_dl | 230 | 170 | 3 |
| linkedin | social | (not set) | 240 | 160 | 0 |
| mailmag | email | 202605_seminar | 600 | 450 | 8 |
| newsletter | mail | tips | 90 | 60 | 1 |
| line | (not set) | seminar | 320 | 240 | 4 |
| (not set) | (not set) | (not set) | 1,200 | 800 | 5 |
| (direct) | (none) | (not set) | 1,400 | 950 | 6 |
| nikkei_xtech | referral | tieup | 180 | 130 | 2 |

### 補足
- データ行数: 47
- 全体セッション: 14,390
- `(not set)` 合計: 1,200（8.3%）
- `(direct)` 合計: 1,400（9.7%）
- `organic` 合計: 6,200（43.1%）
```

---

## 4. 追加情報（任意）

### 既存 GTM タグ概要

- GA4 設定タグ: 1個（全ページ共通）
- GA4 イベントタグ: 12個（page_view 標準＋ form_start, form_submit, file_download, scroll_75 等）
- Google Ads コンバージョン: 2個
- Meta Pixel: 1個
- LinkedIn Insight Tag: 1個

### 広告媒体管理画面側の utm 設定状況

- Google広告（検索）: 自動タグ（auto-tagging）ON、手動 utm 併用なし
- Google広告（GDN）: 手動 utm 設定あり
- Yahoo広告: 手動 utm 設定（campaign 単位、不統一あり）
- Meta広告: 手動 utm 設定（campaign 単位、命名不統一）
- LinkedIn広告: 手動 utm 設定なし ❌
- メルマガ: 配信ツールで自動 utm 付与（source=mailmag, medium=email）
- LINE公式: utm 設定不明（要確認）
- Nikkei xTech: 先方側で utm 付与（こちらでコントロール不可）
