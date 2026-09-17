# 外部調査の方法論根拠

この文書は、外部調査で使う方法論の根拠をまとめた参照資料。実行時の必須ルールは
[`research-quality-standard.md`](./research-quality-standard.md) を正本とし、この文書は
「なぜそのルールなのか」を確認するときに使う。

最終確認日: 2026-09-11

## 1. 3Cの位置づけ

3Cは、顧客・自社・競合を並べて戦略を考える**統合の枠組み**であり、サンプリング、
市場規模推計、ユーザー調査、競合発見の方法を定める調査手法ではない。

大前研一『The Mind of the Strategist』の出版社による目次でも、Strategic Triangleに続いて
Customer-Based、Corporate-Based、Competitor-Basedの各戦略が扱われている。この原型を尊重しつつ、
情報収集の妥当性は別の調査基準で担保する。

- [McGraw Hill: The Mind of the Strategist](https://www.mheducation.com/highered/mhp/product/mind-strategist-art-japanese-business.html)

したがって本プロダクトでは、先に調査目的・市場境界・収集方法を決め、根拠を集めた後に3Cへ統合する。
3Cの三つの欄を埋めただけで「市場調査済み」とは扱わない。

## 2. 採用する公的・原典ベースの方法論

| 情報源 | このプロダクトで採用する考え方 | 適用先 |
|---|---|---|
| [ICC/ESOMAR International Code 2025](https://community.esomar.org/uploads/public/knowledge-and-standards/codes-and-guidelines/ICCESOMAR-International-Code_English.pdf) | 目的に適した設計、対象母集団を反映する収集、限界・偏り・AI利用・人の監督の透明性を確保する | 全調査 |
| [AAPOR Disclosure Standards](https://aapor.org/standards-and-ethics/disclosure-standards/) | 対象、抽出・収集方法、期間、件数、除外、処理、品質確認を第三者が追える形で開示する | レビュー・Q&A・SNS・アンケート・内容分析 |
| [OECD Competition Assessment Toolkit](https://www.oecd.org/content/dam/oecd/en/publications/reports/2019/01/competition-assessment-toolkit-principles-version-4-0-volume-2_59982ed7/b6b938e9-en.pdf) | 商品・サービス、地域、代替可能性をもとに市場境界を定め、狭い定義と広い定義の両方を検討する | 市場定義・競合発見 |
| [Harvard Business School: The Five Forces](https://www.isc.hbs.edu/strategy/business-strategy/Pages/the-five-forces.aspx) | 既存競合だけでなく、代替手段、新規参入、買い手・売り手の力を確認する | 業界構造・競争要因 |
| [Harvard Business School: The Value Chain](https://www.isc.hbs.edu/strategy/business-strategy/Pages/the-value-chain.aspx) | 公開情報で観測できる活動の違いを、価値提供やコスト構造の仮説として整理する | 自社・競合の差別化仮説 |
| [GOV.UK: Learning about users and their needs](https://www.gov.uk/service-manual/user-research/start-by-learning-user-needs) | 既存データと、実際または将来の利用者への調査を組み合わせる。利用者以外の意見は検証前の仮説とする | 顧客理解・ペルソナ |
| [Pew Research Center: Alternative social media methodology](https://www.pewresearch.org/journalism/2022/10/06/alternative-social-media-methodology/) | 内容分析では対象範囲、抽出、コードブック、複数人の判定一致度を明らかにする | SNS・レビューの分類集計 |
| [総務省統計局: e-Stat活用ナビ](https://www.stat.go.jp/info/guide/public/kouhou/index.html) | 日本市場の人口・事業所・産業等は、まず政府統計の定義と数値を確認する | 市場規模・構成・地域差 |

Five ForcesやValue Chainは毎回表を埋めるための飾りではない。業界収益性、代替、参入障壁、
活動の違いが意思決定に関係するときだけ使う。

## 3. 情報源は「有名か」ではなく「その主張を証明できるか」で選ぶ

| 主張 | 優先する情報源 | そのまま証拠にしないもの |
|---|---|---|
| 市場規模・人口・事業所数 | 政府統計、規制当局、統計の定義と調査方法が公開された業界団体 | 出典をたどれないまとめ記事、検索結果の数字 |
| 法令・制度・規制 | 官公庁、法令データベース、規制当局 | 解説記事だけの要約 |
| 企業の売上・方針・商品仕様 | 法定開示、IR、公式料金・製品・ヘルプページ | 第三者による推測、検索スニペット |
| 市場シェア | 母集団、期間、計算方法が明記された統計 | 自称の導入実績、検索順位、レビュー件数 |
| 顧客の行動・障壁 | 実利用者・見込み利用者の調査、行動データ、出所を示せる顧客発言 | 自社や競合のマーケティング文だけから作った断定 |
| 顧客の体験談 | レビュー、Q&A、SNS、事例インタビュー | 投稿者全体を市場の代表とみなす推計 |
| 競合の提供内容 | 競合の公式ページ、規約、価格表、公開デモ | 公式ページに書かれた「業界No.1」等を市場事実として流用 |

有名企業の記事でも、方法と原典が示されていなければ補助資料にとどめる。一方、知名度の低い
業界団体でも、対象、期間、定義、調査方法が開示されていれば、該当業界の統計として採用できる。

## 4. 標準の調査順序

1. 何を決めるための調査か、判断に必要な問いを定める。
2. 顧客の課題、商品・サービス、地域、対象顧客、期間で市場境界を定める。
3. 公式統計・規制・市場構造を調べ、分からない部分と使う代替指標を明記する。
4. 直接競合、同じ課題を別の方法で解く代替手段、参入し得る企業を発見する。
5. 実利用者・見込み利用者の行動や発言を調べる。Web上の声は探索用であり、母集団推計にしない。
6. 自社の公開情報と利用者確認済みの内部情報を分けて整理する。
7. 3Cへ統合し、顧客の重要課題、競合・代替の空白、自社が実証できる能力の交点だけを機会候補とする。
8. 事実、解釈、提案、未確認事項を分け、調査方法と限界を開示する。

## 5. 更新ルール

- 規範や公式ページが改訂されたら、リンクと採用ルールを確認し最終確認日を更新する。
- 二次解説を追加する場合も、上表の原典より優先しない。
- 新しいフレームワークを追加するときは、どの意思決定に必要かを先に書く。毎回必須にはしない。
