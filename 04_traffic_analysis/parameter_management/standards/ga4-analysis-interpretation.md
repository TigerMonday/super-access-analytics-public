# GA4基本分析の判断基準

基本分析でGA4の値を解釈するときの基準。値や仕様が不明なときは、一般記事より先に
Google Analytics / Google Search Central の公式資料を確認する。

## CVの定義

- CV数は、利用者が業務上の意味とイベント名を確認したCVイベントの `eventCount`。
- 基本分析のCVRは `CVイベント数 ÷ 同じ切り口のセッション数`。
- 同一セッションでCVイベントが複数回発火すれば100%を超え得る。
- 「CVしたセッションの割合」が必要な05↔06のCVR改善チェーンとは定義を混ぜない。

## GA4値の扱い

- ランディングページの `(not set)`、空値、`(data not available)` は入口ランキング・合計・
  考察から除外し、通常は指摘しない。GA4公式では、ランディングページの `(not set)` は
  `page_view` を持たないセッションで発生し得る。
- `ai-assistant` はGA4公式の媒体値、`AI Assistant` は公式のデフォルトチャネル。
  未知の命名違反として扱わない。
- 見慣れないディメンション値や媒体値を異常と判定する前に、GA4公式ヘルプの
  デフォルトチャネル定義と更新履歴を確認する。

## 事業前提を使った推察

- toBの商材では、mobile CVRがdesktopより低いだけで課題にしない。比較検討や申込みが
  業務時間・PCで行われる商材では自然な差になり得る。モバイル固有の表示崩れ、フォーム離脱、
  ページ速度など別の根拠があるときだけ改善課題にする。
- Organic Search減少時は、検索需要、順位、季節性、サイト改修、AI検索面の変化を候補に置く。
  AIO影響は断定せず、Search Consoleのクリック・表示回数・CTR・掲載順位と、利用可能なら
  生成AI機能の表示データで検証する。GA4の基本分析レポートに「計測欠損かもしれない」を
  安易な逃げ道として書かない。
- 事業形態やフォームページが不明なら、推測で埋めず利用者へ1回にまとめて確認する。

## フォーム・EC・BigQuery

- リードサイトの既定は、フォームページPVを分母、対応する完了イベント数を分子にした
  「フォーム通過率」。`form_start` は取得できている場合だけ補助指標として使う。
- フォームページが不明なら利用者に確認し、確認前の通過率は作らない。
- ECサイトは最初に推奨eコマースイベントの取得有無を確認する。観測されたイベントだけで、
  `view_item_list` → `view_item` → `add_to_cart` → `begin_checkout` →
  `add_shipping_info` → `add_payment_info` → `purchase` を表示する。
- BigQuery連携がある場合だけ、CVしたセッションのページ順をページ群へまとめて上位経路を出す。
  無い場合は近似経路を作らず、レポートにも設定案内の埋め草を置かない。

## 公式・一次資料

- GA4 default channel group
  https://support.google.com/analytics/answer/9756891
- GA4 updates（AI Assistant medium/channel）
  https://support.google.com/analytics/answer/9164320
- GA4 `(not set)`
  https://support.google.com/analytics/answer/13504892
- GA4 ecommerce
  https://developers.google.com/analytics/devguides/collection/ga4/ecommerce
- Google Search generative AI performance
  https://developers.google.com/search/blog/2026/06/gen-ai-performance-reports
- Pew Research Center（AI summary有無と検索結果クリックの観察研究）
  https://www.pewresearch.org/short-reads/2025/07/22/google-users-are-less-likely-to-click-on-links-when-an-ai-summary-appears-in-the-results/

