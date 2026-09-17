---
marp: true
theme: tiger
size: 16:9
paginate: true
math: false
---

<!--
  GA4簡易分析レポートの実物大サンプル（架空データ）。
  社名・ドメイン・各種ID・店舗名・数値はすべて架空で、実在の案件データではない。
  構成と分析の型を確認するための例として使う。
  tigerテーマのMarp原稿サンプル（ビルド一式は本リポジトリには含まない）。
  ※ EC/SaaS案件ベース。非ECサイトでは申込・店舗まわりの章を取捨する。
-->


<!-- _class: cover no-copy no-pagenum -->
<!-- _paginate: false -->

<div class="cover-client">サンプル株式会社 御中</div><!-- leak-ok: ダミー会社名の統一表記（実在の社名ではない） -->
<div class="cover-grid">
  <div class="cover-left">
    <h1>GA4<br>簡易分析レポート</h1>
    <div class="cover-date">2026.06.03</div>
  </div>
  <div class="cover-right"></div>
</div>

---

<!-- _class: toc no-pagenum -->
<!-- _paginate: false -->

## 目次

<div class="toc-list">
  <div class="toc-item"><span class="num">01</span><span class="bar">|</span><span class="ttl">2026年5月の概況</span></div>
  <div class="toc-item"><span class="num">02</span><span class="bar">|</span><span class="ttl">2025年5月から2026年5月の推移</span></div>
  <div class="toc-item"><span class="num">03</span><span class="bar">|</span><span class="ttl">流入・ドメイン・ページ分析</span></div>
  <div class="toc-item"><span class="num">04</span><span class="bar">|</span><span class="ttl">示唆と次アクション</span></div>
</div>

---

<!-- _class: section-cover no-pagenum -->
<!-- _paginate: false -->

<div class="big-num">01</div>
<div class="sec-title">
  <div class="sec-check"></div>
  <div class="sec-text">
    <h2>2026年5月の概況</h2>
    <div class="en">May 2026 summary</div>
  </div>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">01</div>

## [全体像] 2026年5月は流入微増、CVは大幅増だが計測注記が必要

<div class="lead">2026年5月は前年同月比でセッションが+6.6%、ユーザーが+6.9%。CVは大きく増えているが、期間中にCV計測の定義・発火状態の影響があるため、事業成果として単純比較しない。</div>

<div class="kpi-cards" style="grid-template-columns: repeat(5, 1fr);">
  <div class="kpi-card">
    <div class="kpi-name">sessions</div>
    <div class="kpi-current">60,000</div>
    <div class="kpi-target">前年同月比 +6.6%</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-name">totalUsers</div>
    <div class="kpi-current">42,000</div>
    <div class="kpi-target">前年同月比 +6.9%</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-name">pageViews</div>
    <div class="kpi-current">140,000</div>
    <div class="kpi-target">前年同月比 +2.2%</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-name">本申込CV</div>
    <div class="kpi-current">6,300</div>
    <div class="kpi-target">CVR 10.5% / 前年同月 1,050<br><code>cv_checkout_success</code></div>
  </div>
  <div class="kpi-card">
    <div class="kpi-name">体験利用CV</div>
    <div class="kpi-current">3,500</div>
    <div class="kpi-target">CVR 5.8% / 前年同月 500<br><code>cv_trial_success</code></div>
  </div>
</div>

<div class="page-key-bar">読み取りの中心は、流入構成・ページ構成・デバイス構成。CV数は計測設計の影響を分けて確認する。</div>

<div class="meta">
  <span>GA4 Data API / property: 123456789</span>
  <span>比較: 2025-05-01から2025-05-31 vs 2026-05-01から2026-05-31</span>
</div>

---

<!-- _class: content -->

<div class="chapter-num">01</div>

## [2026年5月] Organic SearchとDirectが成果の大半を占める

<div class="lead">2026年5月の成果はOrganic Search、Direct、Paid Searchに集中している。Paid Socialはセッション数が大きい一方、成果率は低く、認知・比較検討寄りの流入として評価する必要がある。</div>

<table class="dense">
  <thead><tr><th>チャネル</th><th class="num">セッション</th><th class="num">成果</th><th class="num">CVR</th><th>読み取り</th></tr></thead>
  <tbody>
    <tr><td>Organic Search</td><td class="num">24,900</td><td class="num">4,470</td><td class="num">18.0%</td><td>最大の成果源</td></tr>
    <tr><td>Direct</td><td class="num">12,200</td><td class="num">2,670</td><td class="num">21.9%</td><td>成果大。流入元欠損を含む可能性</td></tr>
    <tr><td>Paid Search</td><td class="num">5,500</td><td class="num">1,720</td><td class="num">31.3%</td><td>効率が高い</td></tr>
    <tr><td>Paid Social</td><td class="num">14,600</td><td class="num">220</td><td class="num">1.5%</td><td>流入量は大きいが成果率は低い</td></tr>
    <tr><td>Unassigned</td><td class="num">700</td><td class="num">480</td><td class="num">68.6%</td><td>計測分類の確認が必要</td></tr>
  </tbody>
</table>

<div class="meta">
  <span>dimension: sessionDefaultChannelGroup</span>
  <span>指標: sessions / keyEvents</span>
</div>

---

<!-- _class: section-cover no-pagenum -->
<!-- _paginate: false -->

<div class="big-num">02</div>
<div class="sec-title">
  <div class="sec-check"></div>
  <div class="sec-text">
    <h2>13か月推移</h2>
    <div class="en">May 2025 to May 2026</div>
  </div>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">02</div>

## [月次推移] 2026年春に流入が戻り、CVポイントも増加している

<div class="lead">2026年5月は60,000セッション。<code>cv_checkout_success</code> と <code>cv_trial_success</code> はどちらも4月から増加している。</div>

<table class="monthly-bars" style="width:1050px; min-width:1050px; max-width:1050px; transform:scale(1.25); transform-origin:top left;">
  <thead><tr><th>月</th><th>セッション</th><th><code>cv_checkout_success</code><br>CV / CVR</th><th><code>cv_trial_success</code><br>CV / CVR</th></tr></thead>
  <tbody>
    <tr><td>2025/05</td><td><div class="barcell"><span class="val">56,300</span><span class="mini"><i style="width:85.8%"></i></span></div></td><td><div class="barcell"><span class="val">1,050 / 1.9%</span><span class="mini yellow"><i style="width:16.7%"></i></span></div></td><td><div class="barcell"><span class="val">500 / 0.9%</span><span class="mini pale"><i style="width:14.3%"></i></span></div></td></tr>
    <tr><td>2025/06</td><td><div class="barcell"><span class="val">64,000</span><span class="mini"><i style="width:97.6%"></i></span></div></td><td><div class="barcell"><span class="val">2,800 / 4.4%</span><span class="mini yellow"><i style="width:44.4%"></i></span></div></td><td><div class="barcell"><span class="val">1,290 / 2.0%</span><span class="mini pale"><i style="width:36.9%"></i></span></div></td></tr>
    <tr><td>2025/07</td><td><div class="barcell"><span class="val">47,900</span><span class="mini"><i style="width:73.0%"></i></span></div></td><td><div class="barcell"><span class="val">2,220 / 4.6%</span><span class="mini yellow"><i style="width:35.2%"></i></span></div></td><td><div class="barcell"><span class="val">1,090 / 2.3%</span><span class="mini pale"><i style="width:31.1%"></i></span></div></td></tr>
    <tr><td>2025/08</td><td><div class="barcell"><span class="val">65,600</span><span class="mini"><i style="width:100.0%"></i></span></div></td><td><div class="barcell"><span class="val">3,460 / 5.3%</span><span class="mini yellow"><i style="width:54.9%"></i></span></div></td><td><div class="barcell"><span class="val">2,160 / 3.3%</span><span class="mini pale"><i style="width:61.7%"></i></span></div></td></tr>
    <tr><td>2025/09</td><td><div class="barcell"><span class="val">38,400</span><span class="mini"><i style="width:58.5%"></i></span></div></td><td><div class="barcell"><span class="val">2,650 / 6.9%</span><span class="mini yellow"><i style="width:42.1%"></i></span></div></td><td><div class="barcell"><span class="val">1,900 / 4.9%</span><span class="mini pale"><i style="width:54.3%"></i></span></div></td></tr>
    <tr><td>2025/10</td><td><div class="barcell"><span class="val">43,900</span><span class="mini"><i style="width:66.9%"></i></span></div></td><td><div class="barcell"><span class="val">3,090 / 7.0%</span><span class="mini yellow"><i style="width:49.0%"></i></span></div></td><td><div class="barcell"><span class="val">1,840 / 4.2%</span><span class="mini pale"><i style="width:52.6%"></i></span></div></td></tr>
    <tr><td>2025/11</td><td><div class="barcell"><span class="val">33,000</span><span class="mini"><i style="width:50.3%"></i></span></div></td><td><div class="barcell"><span class="val">2,740 / 8.3%</span><span class="mini yellow"><i style="width:43.5%"></i></span></div></td><td><div class="barcell"><span class="val">1,540 / 4.7%</span><span class="mini pale"><i style="width:44.0%"></i></span></div></td></tr>
    <tr><td>2025/12</td><td><div class="barcell"><span class="val">28,400</span><span class="mini"><i style="width:43.3%"></i></span></div></td><td><div class="barcell"><span class="val">2,180 / 7.7%</span><span class="mini yellow"><i style="width:34.6%"></i></span></div></td><td><div class="barcell"><span class="val">1,500 / 5.3%</span><span class="mini pale"><i style="width:42.9%"></i></span></div></td></tr>
    <tr><td>2026/01</td><td><div class="barcell"><span class="val">43,300</span><span class="mini"><i style="width:66.0%"></i></span></div></td><td><div class="barcell"><span class="val">3,450 / 8.0%</span><span class="mini yellow"><i style="width:54.8%"></i></span></div></td><td><div class="barcell"><span class="val">2,200 / 5.1%</span><span class="mini pale"><i style="width:62.9%"></i></span></div></td></tr>
    <tr><td>2026/02</td><td><div class="barcell"><span class="val">39,500</span><span class="mini"><i style="width:60.2%"></i></span></div></td><td><div class="barcell"><span class="val">3,640 / 9.2%</span><span class="mini yellow"><i style="width:57.8%"></i></span></div></td><td><div class="barcell"><span class="val">2,020 / 5.1%</span><span class="mini pale"><i style="width:57.7%"></i></span></div></td></tr>
    <tr><td>2026/03</td><td><div class="barcell"><span class="val">43,000</span><span class="mini"><i style="width:65.5%"></i></span></div></td><td><div class="barcell"><span class="val">3,180 / 7.4%</span><span class="mini yellow"><i style="width:50.5%"></i></span></div></td><td><div class="barcell"><span class="val">2,480 / 5.8%</span><span class="mini pale"><i style="width:70.9%"></i></span></div></td></tr>
    <tr><td>2026/04</td><td><div class="barcell"><span class="val">48,400</span><span class="mini"><i style="width:73.8%"></i></span></div></td><td><div class="barcell"><span class="val">4,870 / 10.1%</span><span class="mini yellow"><i style="width:77.3%"></i></span></div></td><td><div class="barcell"><span class="val">2,940 / 6.1%</span><span class="mini pale"><i style="width:84.0%"></i></span></div></td></tr>
    <tr class="mark"><td>2026/05</td><td><div class="barcell"><span class="val">60,000</span><span class="mini"><i style="width:91.5%"></i></span></div></td><td><div class="barcell"><span class="val">6,300 / 10.5%</span><span class="mini yellow"><i style="width:100.0%"></i></span></div></td><td><div class="barcell"><span class="val">3,500 / 5.8%</span><span class="mini pale"><i style="width:100.0%"></i></span></div></td></tr>
  </tbody>
</table>

<div class="meta">
  <span>期間: 2025-05-01から2026-05-31</span>
  <span>CVRは各月セッションに対するCVポイント別発火率</span>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">02</div>

## [計測注記] 成果数は期間全体で単純比較しない

<div class="lead">2025年5月から7月は合算CVR（本申込+体験利用）が2.8%から6.9%にとどまり、8月以降（8.6%以上）より明確に低い。成果イベントの発火条件や実装状況の影響が疑われるため、月次成果の増減は、計測設計の整理後に再評価する。</div>

<table class="roomy">
  <thead><tr><th>確認ポイント</th><th>見えている事象</th><th>分析上の扱い</th></tr></thead>
  <tbody>
    <tr><td>2025年5から7月</td><td>合算CVRが2.8%から6.9%、8月以降より明確に低い</td><td>成果イベントの発火条件・実装状況が期間内で変わった可能性を疑う</td></tr>
    <tr><td>2026年5月</td><td>合算CVR16.3%、DirectとUnassignedの成果比率が高い</td><td>参照元・クロスドメインの確認とセットで読む</td></tr>
    <tr><td>イベント数</td><td>2026年5月は約300万件、前年同月比+614.3%</td><td><code>gtm.*</code> 混入により行動量としては読みにくい</td></tr>
    <tr><td>分析方針</td><td>流入・ページ・デバイス構成は比較しやすい</td><td>成果数は参考値として扱い、計測修正後に再集計</td></tr>
  </tbody>
</table>

<div class="page-key-bar">本レポートでは、成果の絶対値よりも「どこから来て、どのページ・デバイスで成果に近い行動が起きているか」を中心に見る。</div>

<div class="meta">
  <span>関連: GA4計測設計・設定監査レポート</span>
  <span>主な論点: <code>gtm.*</code> / URL判定成果 / Direct・Unassigned</span>
</div>

---

<!-- _class: section-cover no-pagenum -->
<!-- _paginate: false -->

<div class="big-num">03</div>
<div class="sec-title">
  <div class="sec-check"></div>
  <div class="sec-text">
    <h2>流入・ドメイン・ページ分析</h2>
    <div class="en">Acquisition, domains, pages</div>
  </div>
</div>

---

<!-- _class: content -->

<div class="chapter-num">03</div>

## [流入元] 検索が主力、DirectとQRは計測分類を確認する

<div class="lead">2026年5月は <code>google / organic</code> が最大の流入・成果源。<code>(direct) / (none)</code> とQR系は成果率が高く、クロスドメインやUTM分類の影響を分けて確認する。</div>

<table class="dense">
  <thead><tr><th>source / medium</th><th class="num">セッション</th><th class="num">成果</th><th class="num">CVR</th><th>読み取り</th></tr></thead>
  <tbody>
    <tr><td><code>google / organic</code></td><td class="num">19,800</td><td class="num">3,810</td><td class="num">19.2%</td><td>主力の自然検索</td></tr>
    <tr><td><code>meta / cpc</code></td><td class="num">14,200</td><td class="num">210</td><td class="num">1.5%</td><td>流入獲得中心</td></tr>
    <tr><td><code>(direct) / (none)</code></td><td class="num">12,200</td><td class="num">2,670</td><td class="num">21.9%</td><td>流入元欠損を含む可能性</td></tr>
    <tr><td><code>google / cpc</code></td><td class="num">5,500</td><td class="num">1,720</td><td class="num">31.3%</td><td>効率が高い</td></tr>
    <tr><td><code>flyer / qr</code></td><td class="num">300</td><td class="num">350</td><td class="num">116.7%</td><td>QR成果が大きいが過剰発火に注意</td></tr>
    <tr><td><code>signage / qr</code></td><td class="num">200</td><td class="num">140</td><td class="num">70.0%</td><td>店舗看板QR</td></tr>
  </tbody>
</table>

<div class="meta">
  <span>期間: 2026-05-01から2026-05-31</span>
  <span>QR系はUTM標準化とカスタムチャネル分類が必要</span>
</div>

---

<!-- _class: content -->

<div class="chapter-num">03</div>

## [キャンペーン] 指名検索と店舗別Instagram広告を分けて見る

<div class="lead">キャンペーンでは <code>brand</code> が高い成果率を示している。Instagram広告は店舗別campaignで取れているが、成果率は店舗ごとに差があり、source / mediumの表記統一が前提になる。</div>

<table class="dense">
  <thead><tr><th>campaign</th><th class="num">セッション</th><th class="num">成果</th><th class="num">CVR</th><th>読み取り</th></tr></thead>
  <tbody>
    <tr><td><code>brand</code></td><td class="num">3,600</td><td class="num">1,290</td><td class="num">35.8%</td><td>指名系。成果に近い</td></tr>
    <tr><td><code>ig-shop-a</code></td><td class="num">1,800</td><td class="num">50</td><td class="num">2.8%</td><td>店舗別Instagram広告</td></tr>
    <tr><td><code>ig-shop-b</code></td><td class="num">1,100</td><td class="num">30</td><td class="num">2.7%</td><td>店舗別Instagram広告</td></tr>
    <tr><td><code>local_area</code></td><td class="num">1,100</td><td class="num">210</td><td class="num">19.1%</td><td>店舗・立地文脈の流入</td></tr>
    <tr><td><code>ig</code></td><td class="num">1,000</td><td class="num">0</td><td class="num">0.0%</td><td>粒度が粗く、評価しづらい</td></tr>
  </tbody>
</table>

<div class="action-notes">
  <div class="note"><span class="label"><span class="note-icon">!</span>修正推奨</span>店舗別campaignは維持し、source / mediumを <code>meta / paid_social</code> に統一</div>
</div>

<div class="meta">
  <span>dimension: sessionCampaignName</span>
  <span><code>(organic)</code> / <code>(direct)</code> は除き、主要な手動campaignを抜粋</span>
</div>

---

<!-- _class: content -->

<div class="chapter-num">03</div>

## [デバイス] 成果のほとんどはモバイルで発生している

<div class="lead">モバイルはセッションの92.2%、成果の96.8%を占める。広告・SEOの改善だけでなく、スマートフォン上の店舗選択、プラン選択、申込完了までの体験が成果に直結する。</div>

<table class="roomy">
  <thead><tr><th>デバイス</th><th class="num">セッション</th><th class="num">成果</th><th class="num">CVR</th><th>読み取り</th></tr></thead>
  <tbody>
    <tr class="mark"><td>mobile</td><td class="num">55,300</td><td class="num">9,490</td><td class="num">17.2%</td><td>主な対象領域。最優先で改善</td></tr>
    <tr><td>desktop</td><td class="num">4,300</td><td class="num">290</td><td class="num">6.7%</td><td>補助接点</td></tr>
    <tr><td>tablet</td><td class="num">400</td><td class="num">20</td><td class="num">5.0%</td><td>少量</td></tr>
  </tbody>
</table>

<div class="page-key-bar">LPやフォームの改善検証は、まずモバイルの店舗ページ・申込導線に絞ると効果が出やすい。</div>

<div class="meta">
  <span>dimension: deviceCategory</span>
  <span>期間: 2026年5月</span>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">03</div>

## [ドメイン] 入口は本サイト、申込・成果はSaaS側に分かれている

<div class="lead">入口は <code>www.example-svc.jp</code>、成果地点は <code>entry.example-svc.jp</code>。LP全件では <code>/store/</code> 開始が9,400セッションあり、店舗来店者の利用開始の手続きにも使われている可能性が高い。</div>

<table class="dense">
  <thead><tr><th>ホスト名</th><th class="num">セッション</th><th class="num">PV</th><th class="num">成果</th><th>読み取り</th></tr></thead>
  <tbody>
    <tr><td><code>www.example-svc.jp</code></td><td class="num">48,800</td><td class="num">79,200</td><td class="num">0</td><td>集客入口</td></tr>
    <tr class="mark"><td><code>entry.example-svc.jp</code></td><td class="num">16,100</td><td class="num">60,600</td><td class="num">9,800</td><td>申込・成果地点</td></tr>
    <tr><td><code>dev.example-svc.local</code></td><td class="num">10</td><td class="num">-</td><td class="num">0</td><td>開発環境の混入</td></tr>
  </tbody>
</table>

<div class="page-key-bar">店舗ID付きの <code>/store/</code> 開始は7,800セッション。うちDirectは3,700セッションあり、媒体別評価から分けて確認する。</div>

<div class="meta">
  <span>dimension: hostName / landingPagePlusQueryString</span>
  <span>期間: 2026年5月</span>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">03</div>

## [サイト構造] PVは申込フォーム・店舗系ページに集中している

<div class="lead">ページ別アクセス数をクエリなしの<code>pagePath</code>全件でまとめると、申込フォーム・確認、店舗詳細、店舗一覧・検索でPVの約82%を占める。サンクスページは別グループとして切り出し、成果発生地点として見る。</div>

<table class="dense">
  <thead><tr><th>サイトグループ</th><th class="num">PV</th><th class="num">セッション</th><th class="num">ページ数</th><th>読み取り</th></tr></thead>
  <tbody>
    <tr class="mark"><td>申込フォーム・確認</td><td class="num">57,500</td><td class="num">36,600</td><td class="num">29</td><td>プラン選択、登録、確認、決済前後。PVの41.1%</td></tr>
    <tr><td>店舗詳細</td><td class="num">38,300</td><td class="num">35,500</td><td class="num">60</td><td>店舗別の比較・検討。PVの27.4%</td></tr>
    <tr><td>店舗一覧・検索</td><td class="num">19,400</td><td class="num">13,000</td><td class="num">17</td><td>都道府県・店舗検索。PVの13.9%</td></tr>
    <tr><td>コラム</td><td class="num">9,400</td><td class="num">9,600</td><td class="num">79</td><td>SEO流入の受け皿</td></tr>
    <tr><td>トップ</td><td class="num">7,700</td><td class="num">6,500</td><td class="num">1</td><td>指名・直接流入の入口</td></tr>
    <tr><td>サンクスページ</td><td class="num">4,000</td><td class="num">3,800</td><td class="num">266</td><td>本申込・体験利用の成果発生地点</td></tr>
    <tr><td>ニュース</td><td class="num">1,300</td><td class="num">1,200</td><td class="num">91</td><td>低流入。お知らせ用途</td></tr>
  </tbody>
</table>

<div class="meta">
  <span>dimension: pagePath / 2026年5月 / 全860ページパスを集計</span>
  <span>分類はURL構造から作成</span>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">03</div>

## [ページ] コラムは集客、店舗・申込ページは検討と成果に近い

<div class="lead">ランディングページではトップ・店舗ページが成果に近く、ページアクセスでは申込フォームが大きい。コラムは流入を作っているため、店舗一覧・近隣店舗への導線を確認する。</div>

<div class="two-col">
<div class="col">
<h3>入口になっているページ</h3>
<table class="dense" style="font-size:9.5pt;">
  <thead><tr><th>ランディングページ</th><th class="num">セッション</th><th class="num">CV</th><th>役割</th></tr></thead>
  <tbody>
    <tr><td><code>/</code></td><td class="num">3,600</td><td class="num">630</td><td>トップ</td></tr>
    <tr><td><code>/shop/</code></td><td class="num">1,300</td><td class="num">170</td><td>店舗一覧</td></tr>
    <tr><td><code>/shop/store-a/</code></td><td class="num">1,000</td><td class="num">240</td><td>店舗LP</td></tr>
    <tr><td><code>/shop/store-b/</code></td><td class="num">700</td><td class="num">110</td><td>店舗LP</td></tr>
    <tr><td><code>/column/sample-article/</code></td><td class="num">1,000</td><td class="num">0</td><td>集客記事</td></tr>
  </tbody>
</table>
</div>
<div class="col">
<h3>閲覧されているページ</h3>
<table class="dense" style="font-size:9.5pt;">
  <thead><tr><th>ページ</th><th>グループ</th><th class="num">PV</th><th class="num">セッション</th></tr></thead>
  <tbody>
    <tr class="mark"><td><code>/store/plan</code></td><td>申込</td><td class="num">11,500</td><td class="num">8,000</td></tr>
    <tr><td><code>/store/register</code></td><td>申込</td><td class="num">7,800</td><td class="num">2,800</td></tr>
    <tr><td><code>/</code></td><td>トップ</td><td class="num">7,700</td><td class="num">6,500</td></tr>
    <tr><td><code>/shop/</code></td><td>店舗一覧</td><td class="num">6,700</td><td class="num">5,100</td></tr>
    <tr><td><code>/store/checkout-success</code></td><td>サンクス</td><td class="num">2,700</td><td class="num">2,500</td></tr>
  </tbody>
</table>
</div>
</div>

<div class="action-notes">
  <div class="note"><span class="label"><span class="note-icon">!</span>修正推奨</span>流入の多いコラムから店舗一覧・近隣店舗への導線を確認</div>
</div>

<div class="meta">
  <span>LP: landingPagePlusQueryString / 閲覧: pagePath</span>
  <span><code>(not set)</code> LPは7,700セッションあり、計測上の確認が必要</span>
</div>

---

<!-- _class: section-cover no-pagenum -->
<!-- _paginate: false -->

<div class="big-num">04</div>
<div class="sec-title">
  <div class="sec-check"></div>
  <div class="sec-text">
    <h2>示唆と次アクション</h2>
    <div class="en">Insights and actions</div>
  </div>
</div>

---

<!-- _class: content title-fit -->

<div class="chapter-num">04</div>

## [分析示唆] SEOと指名・検索広告は強く、MetaとQRは評価設計が必要

<div class="lead">2026年5月の集客は自然検索と検索広告が成果面で強い。Meta広告は流入量の役割、QRは店頭施策の役割が大きいため、同じCVR指標だけで比較せず、目的別に見る。</div>

<table class="roomy">
  <thead><tr><th>領域</th><th>見えていること</th><th>次に見るべきこと</th></tr></thead>
  <tbody>
    <tr><td>SEO</td><td>Organic Searchが成果の45.6%</td><td>店舗ページへ送客できる記事・検索語を特定</td></tr>
    <tr><td>検索広告</td><td>Paid SearchのCVRは31.3%</td><td>指名・非指名、店舗別の効率を分ける</td></tr>
    <tr><td>Meta広告</td><td>流入は多いがCVRは1.5%</td><td>店舗別campaignとLP遷移後の行動を確認</td></tr>
    <tr><td>QR</td><td>少量だが成果が大きい</td><td>UTM統一と計測過剰の有無を確認</td></tr>
    <tr><td>Direct</td><td>成果の27.2%を占める</td><td>クロスドメイン・参照元除外後に再評価</td></tr>
  </tbody>
</table>

<div class="meta">
  <span>比較軸: 流入量 / 成果率 / 計測信頼度</span>
  <span>成果は計測修正後に再集計する前提</span>
</div>

---

<!-- _class: content -->

<div class="chapter-num">04</div>

## [次アクション] 計測を整えてから施策別の改善に入る

<div class="lead">今のデータでも流入の大枠は読めるが、成果評価には計測課題が残る。まず計測の土台を整え、その後にSEO、検索広告、Meta広告、QRを同じ基準で比較する。</div>

<table class="dense">
  <thead><tr><th>優先</th><th>対応</th><th>狙い</th></tr></thead>
  <tbody>
    <tr class="mark"><td>1</td><td><code>gtm.*</code> と成果イベントの過剰発火を整理</td><td>成果数とイベント数を分析可能にする</td></tr>
    <tr class="mark"><td>2</td><td>クロスドメイン・参照元除外・内部除外を確認</td><td>Direct / Unassignedを本来の流入元へ戻す</td></tr>
    <tr><td>3</td><td>UTMをMeta広告・店舗看板QRで統一</td><td>媒体別・店舗別の比較を安定させる</td></tr>
    <tr><td>4</td><td>店舗・プラン・金額をイベントパラメータ化</td><td>どの店舗・プランが成果につながるか見る</td></tr>
    <tr><td>5</td><td>修正後に2026年5月相当の月次レポートを再作成</td><td>改善効果を同じ基準で比較する</td></tr>
  </tbody>
</table>

<div class="page-key-bar">分析レポートは、計測設計・設定監査レポートの修正項目とセットで運用する。</div>

<div class="meta">
  <span>次工程: 計測修正後の再集計</span>
  <span>対象: 2026年5月 / 2025年5月から2026年5月</span>
</div>

---

<!-- _class: closing no-copy no-pagenum -->
<!-- _paginate: false -->

<div class="logo-area"></div>
