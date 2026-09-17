# UTMパラメータ監査（GA4実測ベース・サンプル）

> 架空の設定例。GA4 Data API の手動UTM（`sessionManual*`）ディメンションで、`utm_*` の付与実態を棚卸しした監査の実例。
> `utm-audit-commentary.example.md`（コメント中心）に対し、こちらは**GA4実数からの付与状況の確認手順**を示す。クライアント名・ドメイン・数値はダミー。

- 対象: サンプルサイト / `properties/123456789`（example.co.jp）
- 期間: 直近12か月
- 目的: `utm_*` の付与実態を棚卸しし、`Direct` / `Unassigned` / AI流入を運用可能なUTMルールに落とす

---

## 0. 使用チャネルグループを必ず明示する

> **使用チャネルグループ: プライマリ（「カスタム チャネル グループ」）= `sessionPrimaryChannelGroup`**。
> 標準（`sessionDefaultChannelGroup`）と取り違えると、クライアントがレポートで見る数字とズレる。監査の冒頭でどちらを使ったか明記する。

## §1 チャネル分類の全体像

| チャネル | セッション | CV | 読み取り |
|---|---:|---:|---|
| Direct | 30,000 | 3,600 | 参照元欠損・スパム流入を含みうる |
| Organic Search | 15,000 | 1,200 | 主力 |
| Referral | 2,800 | 880 | 誤用UTMの一部もここに混在 |
| Unassigned | 250 | 12 | 大半がAIアシスタント（§3） |
| Organic Social / AI Assistant / Email | 少量 | — | — |

## §2 UTM付与の実態（項目別の充足度）★この表が監査の核

| パラメータ | 確認ディメンション | 付与状況の例 | 中身 |
|---|---|---|---|
| `utm_source` | `sessionManualSource` | ほぼ未付与 | 能動的タグ付けはメール/SNS程度 |
| `utm_medium` | `sessionManualMedium` | ほぼ未付与 + 誤用 | 有効値は `email` / `social` 程度。記事スラッグを medium に入れる誤用が混在 |
| `utm_campaign` | `sessionCampaignName` | **実質ゼロ** | 全て `(direct)`/`(organic)`/`(referral)`/`(not set)` ＝施策タグ付けなし |
| `utm_content` | `sessionManualAdContent` | 数件のみ | 機械ID（例 `ab12cd34`）や `link_in_bio` |
| `utm_term` | `sessionManualTerm` | ほぼ未付与 | organicの `(not provided)` 以外はほぼ無し（日本語句の誤用が混じることも） |

> 取得例:
> ```
> fetch_ga4.py --dimensions sessionManualSource,sessionManualMedium --metrics sessions,conversions
> fetch_ga4.py --dimensions sessionCampaignName,sessionMedium --metrics sessions
> fetch_ga4.py --dimensions sessionManualAdContent,sessionManualTerm --metrics sessions
> ```

## §3 Direct / Unassigned / AI流入の中身（必ず source/medium を示す）

| source / medium | セッション | 推定原因 | 対応案 |
|---|---:|---|---|
| `(not set)` | 多 | 参照元・UTM欠損 | GTM/参照元除外の確認 |
| `chatgpt.com / (not set)` ほかAI | 中 | AI流入が標準チャネル未分類 | カスタムチャネル「AI」を定義 |
| `ss-block / block-*-xxx` | 少 | サイト内ブロック導線の medium 誤用 | campaign/content へ移す |

## §4 「項目が減った（劣化した）」かの確認

> ユーザーから「以前のスライドより項目がしょぼい」と言われたら、**期間を前半/後半で割って medium・campaign の種類を比較**する。
> 多くの場合「劣化」ではなく「元々ほぼ未運用」で、スライドの豊富な項目は**提案側の推奨スキーム**だったというケースが典型。実装の実態と提案を切り分けて伝える。

## §5 推奨UTMルール（媒体種別=medium、施策・店舗=campaign）

| 用途 | 推奨値 | 例 |
|---|---|---|
| メール | `utm_source=hs_email` / `utm_medium=email` | `utm_campaign=nl_YYYYMM` |
| SNS（自然/広告） | `utm_medium=social` / `paid_social` | `utm_content=link_in_bio` |
| 広告 | 自動タグ(gclid)＋リンク維持 | 手動UTMと二重付与しない |
| 施策 | `utm_campaign={施策}_{yyyymm}` | `webinar_202607` |
| クリエイティブ | `utm_content={人が読める識別子}` | `banner_a` |

---

## このサンプルの使いどころ
- 「UTM監査して」と言われたら、§0でチャネルグループを明示 → §2で項目別の充足度 → §3でUnassigned/Directの中身 → §5で推奨ルール、の順で組む。
- `utm_medium` に記事スラッグ・施策名が入る誤用、`utm_content` の機械ID化はよくある指摘ポイント。
- Google広告リンクがあるのに `cpc`/`paid_*` medium が無い場合は「配信停止 or 自動タグ不発でDirectに流入」を疑う。
