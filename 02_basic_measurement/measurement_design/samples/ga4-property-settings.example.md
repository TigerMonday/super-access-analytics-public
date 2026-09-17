# GA4 設定内容まとめ（サンプル）

> 架空の設定例。GA4 Admin API + Data API + GTMコンテナ解析で埋めた「設定内容の棚卸し（事実のまとめ）」の実例。
> 診断（review）ではなく**設定内容の可読化**に徹する用途。クライアント名・ドメイン・各種IDはダミー値。

- 対象: サンプルサイト - GA4 / `properties/123456789`（アカウント `accounts/1234567`）
- 取得: GA4 Admin API / Data API（直近30日）｜取得日 YYYY-MM-DD
- 出典データ: `_data/phase1.json` / `phase2.json` + GTMコンテナエクスポート

---

## §1 アカウント・プロパティ

| 項目 | 値 | 補足 |
|---|---|---|
| アカウント | `accounts/1234567` | — |
| プロパティ | サンプルサイト - GA4 / `123456789` | 通常プロパティ / GOOGLE_ANALYTICS_STANDARD（無償版） |
| 作成日 | 20XX-XX-XX | — |
| データストリーム | サンプルサイト - GA4 / `987654321` | Webストリーム（1本） | <!-- leak-ok: データストリームIDのダミー例（プロパティIDのダミー123456789と区別するための連番プレースホルダで実IDではない） -->
| 測定ID | `G-XXXXXXXXXX` | — |
| ウェブサイトURL | https://example.co.jp | — |
| 業種 / タイムゾーン / 通貨 | テクノロジー / Asia/Tokyo / JPY | — |

## §2 基本設定

| カテゴリ | 設定項目 | 現在の値 |
|---|---|---|
| データ保持 | イベント / ユーザーデータ保持 | 14か月 / 14か月 |
| データ保持 | 新しいアクティビティでリセット | ON |
| シグナル | Googleシグナル | 有効（同意済み） |
| アトリビューション | レポート用モデル | データドリブン（有料 + オーガニック） |
| アトリビューション | ルックバックウィンドウ | 獲得CV 30日 / その他CV 90日 |

### 拡張計測（Webストリーム）

| 項目 | 状態 |
|---|---|
| スクロール / 離脱クリック / サイト内検索 / 動画 / ファイルDL | いずれも有効 |

### チャネルグループ

| チャネルグループ | 種別 | プライマリ |
|---|---|---|
| Default channel group | システム標準 | — |
| カスタム チャネル グループ | カスタム | **★ プライマリ（メイン）** |

> 分析は **プライマリ**（`sessionPrimaryChannelGroup`）を基準にする。標準（`sessionDefaultChannelGroup`）と取り違えない。両者の実数差が出る場合は定義差（AIチャネル等）を確認する。

## §3 キーイベント（コンバージョン）

| イベント名 | カウント方法 | 区分 | 作成日 |
|---|---|---|---|
| `purchase` | ONCE_PER_EVENT | 既定 | 20XX-XX-XX |
| `ads_conversion___1` | ONCE_PER_EVENT | カスタム（Google広告インポート） | 20XX-XX-XX |
| `complete_document_form` | ONCE_PER_SESSION | カスタム | 20XX-XX-XX |
| `complete_contact_form` | ONCE_PER_EVENT | カスタム | 20XX-XX-XX |

## §4 計測イベントの定義（GTM + 発火実測）

> イベントの厳密なトリガー・パラメータはGTM側にある。GTMコンテナをエクスポートして突き合わせると、「GA4で受信しているが**GTMに定義がない**イベント」（=サイト直gtag/HubSpot/別コンテナ由来）を切り分けられる。

### §4-1 GTMで定義されているGA4イベント（例）

| GTMタグ | GA4イベント名 | トリガー（発火条件） | 送信パラメータ |
|---|---|---|---|
| contact-thanks | `inquiry_complete` | ページビュー: URL に `/contact-thanks` を含む | なし |
| document | `document` | ページビュー: URL に `/document` を含む | なし |
| banner-link | `banner_link` | リンククリック: Click Classes 一致 | クリッククラス |
| file-dl-doc | `file_download_xxx` | リンククリック: Click URL に `.docx` を含む | なし |

### §4-2 GA4「イベントの作成」ルールで生成されるイベント

GTMタグに無いイベント（`view_*` / `complete_*` / CV用イベント等）は、**GA4管理「イベントの作成」ルール**で生成されていることが多い。`phase1.json` の `event_create_rules_{streamId}`（GA4 Admin API `eventCreateRules`）で条件を確認する。**多くがpage_view + URL条件の擬似イベントで、フォーム送信などの実インタラクションではない**点に注意。

| 生成イベント | 生成条件（元=page_view + URL） | 注意 |
|---|---|---|
| `view_contact_form` | `/contact` 始まり かつ `/contact-thanks` 除外 | ページ閲覧で発火 |
| `view_service_detail` | 正規表現 `/service/.+` かつ `/case/` 除外 | ページ閲覧で発火 |
| `complete_contact_form` | `/contact-thanks` 始まり | GTMの `inquiry_complete` と二重計測になりがち |
| `ads_conversion___1`（CV） | `/contact` 始まり | **「/contactを見ただけ」でCV発火→水増し**の典型 |

> ポイント:
> - イベントの生成元は3系統（①GTMタグ ②GA4イベント作成ルール ③自動収集・拡張計測）。**必ず3系統すべてを突き合わせ**、定義の所在と二重計測を明示する。
> - CV用イベントが「page_view + URL条件」で作られている場合、ページ閲覧＝CVになり水増しする。`/contact-thanks` 等で複数イベントが同時発火していないかを確認する。

### §4-3 自動収集・拡張計測イベント

`page_view` / `session_start` / `first_visit` / `user_engagement` / `scroll` / `click`（離脱クリック）/ `file_download`。

## §5 カスタム定義

- カスタムディメンション: N件 / カスタム指標: N件
- 備考: カスタムイベントは送信されていても、パラメータをカスタムディメンション登録していないと探索で分解できない。

## §6 オーディエンス

- 既定（テンプレート）オーディエンスの有無、カスタムオーディエンスの有無を列挙。

## §7 広告・外部連携

| 領域 | 状態 | 補足 |
|---|---|---|
| Google広告リンク | あり / なし | 顧客ID・パーソナライズ設定 |
| Search Console連携 | あり / なし | URL-prefix / ドメインプロパティの別 |
| BigQueryリンク | 連携 / 未連携 | — |
| GTM | コンテナID | 内包タグ（GA4設定 / イベント / HubSpot / Clarity / UA(レガシー) 等） |

---

## このサンプルの使いどころ
- 設定内容を「事実ベースで一覧化」したい依頼（診断・推奨は別物）。
- GTMエクスポートがある場合は §4 でイベント定義の所在と二重計測を必ず突き合わせる。
- チャネルは**プライマリ**を明示してから数値を出す。
