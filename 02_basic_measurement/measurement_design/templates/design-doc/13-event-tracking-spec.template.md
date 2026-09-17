# 章 13: イベントトラッキング計測仕様

> サンプル設計書の「イベントトラッキング計測仕様」シート相当。実装者向けの HTML / JavaScript / dataLayer 規約。

## メタ情報

| 項目 | 値 |
|------|----|
| 対象プロパティ | {{プロパティ名}} |
| 最終更新日 | {{YYYY-MM-DD}} |
| 対象 | フロント実装担当者 |

## 1. 共通方針

- 計測タグの埋め込みは原則 GTM 経由 (`gtag.js` を直接置かない)
- ページ内 `<head>` に GTM スニペットを 1 つ、`<body>` 直後に noscript を 1 つ
- 環境変数による GTM コンテナ切替 (開発 / ステージング / 本番) は実装側で対応

## 2. CTA / 一般要素 (data 属性方式)

### 2.1 リンク要素

```html
<a href="..."
   data-gtm-link="<event_category>,<event_name>,<event_label>">
  ボタンテキスト
</a>
```

例:

```html
<a href="/signup"
   data-gtm-link="ヘッダー,click_cta,ヘッダー>新規登録ボタン">
  新規登録はこちら
</a>
```

GTM 側は「Click - Just Links」トリガーで `data-gtm-link` 属性を持つ要素を検知し、3 値に分割して送信する。

### 2.2 非リンク要素

```html
<div class="..."
     data-gtm-event="<event_category>,<event_name>,<event_label>">
  ...
</div>
```

### 2.3 値内で使えない文字

- カンマ (`,`) — 区切り文字なので NG。代替: `>` または全角カンマ
- 改行 / タブ — NG
- ダブルクォート (`"`) — 属性値を壊すので NG

## 3. dataLayer push 方式 (リッチイベント)

CTA / 一般要素では表現しきれない情報 (商品データ・取引データ等) を含むイベントは、JavaScript で直接 `dataLayer.push` する。

### 3.1 基本形

```javascript
window.dataLayer = window.dataLayer || [];
window.dataLayer.push({
  event: '<event_name>',
  // 任意の追加プロパティ
  <param_name>: <値>,
});
```

### 3.2 EC イベント例

```javascript
window.dataLayer.push({
  event: 'purchase',
  ecommerce: {
    transaction_id: 'TX-20260519-00001',
    value: 5980,
    currency: 'JPY',
    tax: 543,
    shipping: 0,
    coupon: '',
    items: [
      {
        item_id: 'SKU-0001',
        item_name: '...',
        item_brand: '...',
        item_category: 'スキンケア',
        price: 5980,
        quantity: 1,
      },
    ],
  },
});
```

### 3.3 ユーザープロパティ

```javascript
window.dataLayer.push({
  event: 'user_property_update',
  user_id: '<ハッシュ済 ID>',
  user_segment: 'repeat',
});
```

## 4. dataLayer の型ルール

| 型 | 例 | 注意 |
|----|----|------|
| 数値 | `123`, `123.45` | クォート不要。文字列で送ると GA4 上の指標として扱えない |
| 文字列 | `'value'` | クォート必須 |
| 真偽値 | `true` / `false` | `'true'` (文字列) と混ぜない |
| 配列 | `[ {...}, {...} ]` | `items` で利用 |

## 5. デバッグ手順

1. GTM のプレビューモードを起動
2. 対象ページで該当要素を操作
3. Tag Assistant でタグの発火を確認
4. GA4 の DebugView で受信を確認
5. 不要なパラメータが付いていないか確認

## 6. リリース前チェックリスト

- [ ] STG での DebugView 検証完了 (章 11 / 12 の各行が OK)
- [ ] 命名規則に違反していない
- [ ] 予約語と衝突していない
- [ ] PII (個人情報) が含まれていない
- [ ] 重複計測になっていない
- [ ] GTM コンテナのバージョン名に案件 ID / 日付を入れて公開

## 7. 関連

- 命名規則: `docs/standards/naming-conventions.md`
- 予約語: `docs/standards/reserved-words.md`
- 管理表: 章 11 (CTA) / 章 12 (一般)
