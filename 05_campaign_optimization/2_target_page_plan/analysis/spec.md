# spec: ② 施策｜分析エージェント（05）

| 項目 | 内容 |
|---|---|
| 概要 | ①の方針タイプに該当するページ群を分析し、各ページの規模・反応・ファネル位置・目的を事実ベースで出す |
| レイヤー | ② 施策（対象ページ選定＋改善案） / 分析（05） |
| データソース | GA4 Data API（ページ別）＋ page_profile の判定。BigQueryはV2 |
| 入力 | ①の確定方針（やるタイプ・対象範囲・CVR分母）/ GA4 / page_profile / 01コンテキスト |
| 出力 | ページ別分析レポート（事実）`outputs/{client}/05_cvr/_past/05-page-analysis.md` |
| 次段 | 05/2_target_page_plan/analysis_review（検算）→ 05/2_target_page_plan/creation（対象ページ選定＋改善案の作成） |

## 持ち物
- `prompts/analyze.md` / `scripts/{auth,fetch_ga4}.py` / `pyproject.toml`

## 注意
- 対象ページの決定・優先順位は出さない（事実とページ目的まで）
- 生CV率の高低だけで優劣をつけない（目的と規模を併記）
- CVR分母は①の取り方を引き継ぐ／`landingPagePlusQueryString` の名寄せに注意
- エンゲージ率は選定に使わない。離脱は定義済み指標が無ければ計測不能とし、engagementRate/bounceRateで代用しない
- 全件一覧は生データへ保存し、個別分析は累積カバー率・最大件数・CV直結度で範囲を固定する
