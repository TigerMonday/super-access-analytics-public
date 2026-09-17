# common/ga4_fetch — GA4取得の共通レイヤー

`fetch_ga4.py`（GA4 Data API 取得CLI）と `auth.py`（サービスアカウント認証）の実体。
07_adhoc_analysis・06/1・06/2・04_traffic_analysis/parameter_management の `scripts/fetch_ga4.py` は本ディレクトリを呼ぶ互換シム。

- **修正はここ1箇所だけ**行う（3箇所コピー同期は廃止。code-review-0702 §C / architecture-review P-4 対応）
- 依存パッケージは呼び出し元エージェントの uv 環境を使う（本ディレクトリに pyproject は置かない）
- SA鍵のパスは環境変数 `GA4_SA_KEY_PATH` で上書き可能（未指定時はホームフォルダ配下の `~/.saa/credentials/google-analytics/sa-key.json`。準備手順は docs/setup-ga4.md）
- 生データの保存先はCVR改善チェーンでは `outputs/{client_id}/_data/ga4/`（取得日プレフィックス付き）

## 自然言語から取得するときの検証

AIは依頼文を直接Data APIへ渡さず、`query-plan.example.json` と同じ構造の取得計画へ変換する。
共通フェッチャーはデータ取得前に、対象プロパティの `properties.getMetadata` と
`properties.checkCompatibility` を実行する。

- Metadataに存在しないディメンション・指標は実行しない。対象プロパティのカスタム定義もMetadataで確認する
- ディメンションフィルタに指標を指定するなど、項目種別が違う場合は実行しない
- ディメンション・指標・フィルタの組み合わせが `INCOMPATIBLE` なら実行しない
- 非互換時に項目を黙って削除・置換しない。取得目的に影響するため、候補を示して利用者へ確認する
- 取得後はレスポンスの列名・列数が取得計画と一致することを確認する
- `--all-rows` 指定時に全行を取得できなければ、途中結果を完成データとして返さない

公式仕様:

- https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/getMetadata
- https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/checkCompatibility

実行例:

```bash
uv run python scripts/fetch_ga4.py \
  --query-plan outputs/{client_id}/_data/ga4/question.query.json \
  --write-query-plan outputs/{client_id}/_data/ga4/question.validated-query.json \
  --output outputs/{client_id}/_data/ga4/question.md
```

`validated-query.json` はMetadata・互換性確認とデータ取得が成功した場合だけ保存される。

この検証で保証できるのは「GA4上に存在し、APIとして組み合わせ可能な取得条件であること」まで。
`sessions` と `totalUsers` のどちらが依頼者のいう「アクセス数」か、CVにどのイベントを使うか、
計測設計そのものが正しいかまではAPIでは判定できない。そのため、業務上の意味が分かれる語は
次のルールで確認し、取得結果にはGA4のしきい値・高カーディナリティ警告も表示する。

### 曖昧な言葉

次の語は機械的に1項目へ決めない。

| 依頼文 | 候補 | 対応 |
|---|---|---|
| アクセス数 | `sessions` / `totalUsers` / `screenPageViews` | セッション、利用者、閲覧回数のどれか確認する |
| ユーザー数 | `totalUsers` / `activeUsers` | 利用者全体か、アクティブユーザーか確認する |
| コンバージョン | 確認済みの完了イベント | イベント名と業務上の意味を確認し、推測しない |
| 流入元 | `sessionSource` / `sessionSourceMedium` / `sessionDefaultChannelGroup` | 必要な粒度を確認する |
