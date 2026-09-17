# データレイヤー仕様書

> 対象: {{クライアント名}} | 作成日: {{YYYY-MM-DD}}

---

## 概要

GTM のデータレイヤー (`window.dataLayer`) に push するオブジェクトの仕様。
フロントエンド実装者はこの仕様に従って `dataLayer.push()` を実装すること。

---

## イベント別仕様

### {{event_name}}

**発火タイミング:** {{timing_description}}

**dataLayer.push() の実装例:**

```javascript
window.dataLayer = window.dataLayer || [];
window.dataLayer.push({
  event: '{{event_name}}',
  {{param_name}}: '{{param_value_example}}',
  // 追加パラメータ
});
```

**パラメータ仕様:**

| パラメータ名 | 型 | 必須 | 値の例 | 説明 |
|-----------|----|----|------|------|
| `event` | String | ✅ | `'{{event_name}}'` | GTM カスタムイベント名（固定値） |
| `{{param_name}}` | {{type}} | {{required}} | `{{example}}` | {{description}} |

---

## 実装上の注意事項

1. `dataLayer.push()` は GTM スニペット読み込み後に実行すること
2. `null` や `undefined` はパラメータとして送信しないこと
3. 個人情報（氏名・メールアドレス等）はデータレイヤーに含めないこと
4. トランザクション ID は重複しないユニーク値を使用すること
