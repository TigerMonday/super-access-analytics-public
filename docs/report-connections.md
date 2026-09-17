# レポートの接続・参照版チェック

市場・基本分析・施策の3レポートを連携する場合、最新版本文とcustomer-understanding.yamlを読み、意味の対応を確認してから `outputs/{client_id}/report-connections.json` を保存する。JSONは非公開の内部記録。本文へ混ぜない。

記録項目は `files`（market/basic/plan/context各項目にリポジトリ相対pathとSHA256）、`metrics`（basic/plan各項目にstart/end/numerator/denominator）、`mappings`（各行にmarket/basic/plan本文の対応箇所を正確な短い抜粋で記載）、`review_note`（単位差・仮説・制約の確認結果）とする。SHA256は `Get-FileHash -Algorithm SHA256` 等で実ファイルから取得する。

入力を読む際と完成後・変換前に `python tools/validate_report_connections.py outputs/{client_id}/report-connections.json` を実行する。未作成・失敗時は3レポートの接続確認済みとして配布しない。初回は内容確認後に作成する。入力変更なら該当する下流レポートを再レビューし、必要な更新後に記録を更新する。チェックを通すためだけにハッシュを取り直してはならない。

基本分析のみの実行では、未完成の施策レポートを要求しない。3本が揃った段階でこの検査を行う。市場を省略した軽量分析を、3レポート接続確認済みと呼ばない。

検査は参照欠落・内容変更・本文対応箇所の不存在・指標記録の不足を検出する。数値の正しさ、本文と指標記録の意味的一致、因果・仮説の妥当性は自動判定しない。各生成プロンプトからエージェントが実行するゲートであり、汎用HTML変換器の強制フックではない。
