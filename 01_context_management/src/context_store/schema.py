"""コンテキストストアのスキーマ定義と軽量バリデーション。

各 YAML ファイルは緩く読み込む方針（欠損キーは None / 空で許容）。
ここではファイル名の定義と、最低限の整合チェック（id 参照の妥当性）のみ提供する。
正典のスキーマ説明は ../../schema/context-schema.md を参照。
"""

from __future__ import annotations

# context/<client_id>/ 配下で読み込む YAML ファイル名 → ClientContext の属性名
YAML_FILES = {
    "profile": "profile.yaml",
    "measurement": "measurement.yaml",
    "kpis": "kpis.yaml",
    "site_segments": "site-segments.yaml",
    "customer_understanding": "customer-understanding.yaml",
    "initiatives": "initiatives.yaml",
    "constraints": "constraints.yaml",
    "stakeholders": "stakeholders.yaml",
    "analysis_history": "analysis-history.yaml",
}

# customer-understanding.yaml の journey[].stage_id に許される固定5値（この順で並べる）。
# ここで固定するのは stage_id（06がこのidで障壁・段階を参照する）と、既定の stage_name（表示名）だけ。
# stage_name 自体は自由記述で、特に最終段階（purchase）は01の kpis.yaml（key_events に紐づく
# KPIのname/description）からクライアントごとのCVの実態を表す名称に差し替える運用にする
# （例: コンサル業なら「相談」）。ここに書いた「購入」はkpis.yamlが無い/未登録のときの既定値。
JOURNEY_STAGES = [
    ("daily_business", "日常業務"),
    ("problem_emergence", "課題の発生"),
    ("research", "調査"),
    ("consideration", "検討"),
    ("purchase", "購入"),
]
JOURNEY_STAGE_IDS = [s[0] for s in JOURNEY_STAGES]

# customer-understanding.yaml の evidence_type に許される5値。
# 「hypothesis」は06側（page_profile / create-page-plan）が文字列一致で参照しているため値を変えない。
#   - customer_voice: 実在の顧客の発言・行動が根拠（自社のレビュー・Q&A・SNS・事例インタビュー引用等）
#   - competitor_customer_voice: 同業・競合の公式事例に登場する実在の顧客の発言・行動が根拠。
#     「その属性の顧客が実在すること」は確認できるが、「その人が自社を選ぶか」までは確認できない
#     （customer_voice より一段弱い）。障壁（相手側の内部状態）の裏付けには使ってよいが、
#     刺激（自社の訴求で効くか）に使う場合は「事例に触れること一般」のような会社を問わない
#     機序であることを確認してから使う（自社固有の訴求の裏付けにはしない）
#   - service_derived: 自社が想定する顧客像が根拠（サービスページ・料金ページ等、会社側の公式情報＝
#     自社が書いたもの）
#   - desk_research: 第三者を調べて確認した客観的事実が根拠（レビューサイト・Q&Aサイト・業界データ・
#     公開情報等、自社が書いたものではない第三者の情報を調べた結果）。誰かの発言そのものではない点で
#     customer_voice / competitor_customer_voice と異なり、自社発信ではない点で service_derived と
#     異なる。「調べたが見つからなかった」という不在の確認も、調べて確認した事実として使ってよい
#     （例: 「ITreviewのレビュー0件、Q&Aサイトでの言及0件」）
#   - hypothesis: 上記いずれの裏付けも無い仮説
EVIDENCE_TYPES = ("customer_voice", "competitor_customer_voice", "service_derived", "desk_research", "hypothesis")
EVIDENCE_REQUIRING_TYPES = ("customer_voice", "competitor_customer_voice", "service_derived", "desk_research")

# personas[].persona_basis に許される3値。ペルソナ全体をどちらの経路で主に構築したか
#   - customer_voice_confirmed: 顧客の声（発言・行動）で実在が確認できたペルソナ
#   - competitor_customer_voice_confirmed: 同業・競合の事例で顧客層の実在は確認できたが、
#     自社を選ぶかまでは未確認のペルソナ（customer_voice_confirmed より一段弱い）
#   - service_derived: サービスからの逆算のみで構築したペルソナ（顧客の声による裏付けは未確認）
PERSONA_BASIS_VALUES = ("customer_voice_confirmed", "competitor_customer_voice_confirmed", "service_derived")

# personas の上限人数。上限は「切り捨て」ではなく、態度変容フロー（障壁・刺激）が近い
# ペルソナを統合する運用にする（03の SKILL.md 参照）。ここでは超過の検出のみ行う。
PERSONA_MAX = 5

# kpis.yaml の kpis[].priority に許される最小値（1が最優先）。
KPI_PRIORITY_MIN = 1

# profile.yaml の preferences.output_formats に許される値。
# common/report_export が変換できる4形式（html/pdf/docx/xlsx）に加え、Googleドキュメント/
# スプレッドシートへの書き込み（gdoc/gsheet）も含める。gdoc/gsheetは厳密には「変換」ではなく
# 「書き込み」だが、利用者から見た問い（成果物をどの形式で見たいか）は同じなので、器を分けず
# 同じ preferences.output_formats に含める（primary_kpi のように、同じ問いに答える場所が
# 2つできると「どちらが正か」が分からなくなるため）。
OUTPUT_FORMATS = ("html", "pdf", "docx", "xlsx", "gdoc", "gsheet")

# output_formats のうち、書き込み先URLが無いと成立しない値 → preferences 側のURLキー名。
#
# なぜURLが要るか: サービスアカウントは自分でファイルを作れない
# （Google Drive API公式ドキュメント: "Service accounts don't have storage quota and
# can't own files."）。回避策の共有ドライブはGoogle Workspaceの有償エディションが前提で、
# 無料アカウントの利用者では成立しない。そのため運用は「利用者が先に空のファイルを作り、
# サービスアカウントのメールアドレス（認証ファイルの client_email）に編集者で共有し、
# そこへ書き込む」形に固定する。だからURLを設定として持たせる必要がある——この理由を
# 消さないこと（消えると「自動作成にすればいい」に後から変えられてしまう）。
OUTPUT_FORMAT_URL_KEYS = {
    "gdoc": "google_doc_url",
    "gsheet": "google_sheet_url",
}

# site-segments.yaml の site_segments[].match に許されるキー。
# 1セグメント内で複数キーを指定した場合はAND（全キーを満たす）、各キーの値はスカラーでも
# リストでもよく、リストの場合はキー内OR（いずれかに一致すればよい）。
# content_group は GA4 側でコンテンツグループ機能（01の計測設計で確認する項目）が設定済みの
# ときに使う。GA4が既にページの役割分類を持っているなら、そちらを正として参照し、
# path_prefix/host_name によるルールをここで二重に作らない（詳細は schema/context-schema.md）。
SITE_SEGMENT_MATCH_KEYS = ("host_name", "path_prefix", "content_group")

# site_segments[].default: true は「他のどの match にも一致しなかったときに落ちる既定セグメント」
# を示すフラグ。SITE_SEGMENT_MATCH_KEYS（match条件のキー）とは別物として扱う——
# match の中には入れず、セグメント直下に置く（`match.default` のような書き方はしない）。
# 既定セグメントは条件で絞る必要が無いため match を持たない（持っていたら validate_site_segments
# が警告する）。詳細は match_site_segment() のdocstring参照。

# site_segments は「そのセクションが何であるか」（役割の名前・一致条件）だけを持つ。
# 「CVの分母に含めるか」は観察できる事実ではなく分析上の判断（メディアも間接的にCVを
# 狙っている場合があり、「狙っていない」と断じるのは踏み込みすぎ）なので、この定義には
# 持たせない。分母をどう扱うかはセグメントごとの実績（セッション・CV・CVR）を並べて示す側
# （02等）の役目とする。根拠（何であるか）と判断（どう使うか）を分ける、という方針に合わせた。
#
# name は自由記述。ただし既定は「本体サイト」「オウンドメディア」の2つに絞る想定——
# 訪問者・目的が本体と同じセクション（サービス紹介・会社紹介・問い合わせ等）は分ける価値が無く、
# 分ける価値があるのは訪問者か目的が本体と違うもの（実質メディアが主）。採用・会員向け・
# サポート等、3つ目以降が要るサイトもあるため2値には固定しないが、細かく割りすぎないこと
# （実データで第1階層が10種類あっても、同じ人に同じ目的で見せているなら1セグメントでよい）。

# 議事録ディレクトリ
MEETINGS_DIR = "meetings"


def _as_list(value) -> list:
    """値をリストとして返す（単一値なら1要素リスト、None/空なら空リスト）."""
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def normalize_gotchas(constraints: dict) -> list[dict]:
    """constraints.yaml の gotchas を `[{'title': str, 'detail': str}]` に正規化する。

    正典形式（schema/context-schema.md）は `id`/`title`/`detail` だが、実運用で
    `id`/`note` 形式や文字列リストで書かれても**無言で捨てない**:
      - `note` は `detail` 扱い
      - `title` が無ければ `id`、それも無ければ note/detail の先頭行を見出しにする
      - dict でも文字列でもない想定外の形式は、そのまま文字列化して表示に回す
    """
    out: list[dict] = []
    for g in _as_list((constraints or {}).get("gotchas")):
        if isinstance(g, dict):
            detail = str(g.get("detail") or g.get("note") or "").strip()
            title = str(g.get("title") or "").strip()
            if not title:
                title = str(g.get("id") or "").strip()
            if not title and detail:
                title = detail.splitlines()[0].strip()
            if not title and not detail:
                # 全キー想定外: 内容を落とさずそのまま文字列化
                title = str(g)
            out.append({"title": title, "detail": detail})
        elif g is not None:
            out.append({"title": str(g).strip(), "detail": ""})
    return out


def normalize_open_questions(constraints: dict) -> list[dict]:
    """constraints.yaml の open_questions を `[{'question': str, 'status': str}]` に正規化する。

    正典形式は `id`/`question`/`hypothesis`/`status` の dict だが、文字列のリストや
    想定外の形式で書かれても**無言で捨てず**、文字列化して表示に回す。
    """
    out: list[dict] = []
    for q in _as_list((constraints or {}).get("open_questions")):
        if isinstance(q, dict):
            question = str(q.get("question") or "").strip()
            if not question:
                # question キーが無い想定外 dict: 内容を落とさず文字列化
                question = str(q)
            out.append({"question": question, "status": str(q.get("status") or "").strip()})
        elif q is not None:
            out.append({"question": str(q).strip(), "status": ""})
    return out


def validate(ctx) -> list[str]:
    """ClientContext の軽量バリデーション。問題点のメッセージ一覧を返す（空なら正常）。

    落とさず警告として返す方針（運用初期の未記入を許容するため）。
    """
    warnings: list[str] = []

    # profile 必須項目
    client = (ctx.profile or {}).get("client", {})
    if not client.get("name"):
        warnings.append("profile.yaml: client.name が未設定です")

    # kpi_id の重複チェック
    kpis = (ctx.kpis or {}).get("kpis", []) or []
    kpi_ids = [k.get("kpi_id") for k in kpis if isinstance(k, dict)]
    dup = {x for x in kpi_ids if kpi_ids.count(x) > 1 and x}
    if dup:
        warnings.append(f"kpis.yaml: kpi_id が重複しています: {sorted(dup)}")

    warnings.extend(validate_kpi_priorities(kpis))

    # initiatives.related_kpi が kpis に存在するか
    valid_kpi_ids = {x for x in kpi_ids if x}
    inits = (ctx.initiatives or {}).get("initiatives", []) or []
    for it in inits:
        if not isinstance(it, dict):
            continue
        rk = it.get("related_kpi")
        if rk and rk not in valid_kpi_ids:
            warnings.append(
                f"initiatives.yaml: {it.get('initiative_id', '?')} の related_kpi "
                f"'{rk}' が kpis.yaml に存在しません"
            )

    # constraints.yaml に中身があるのに gotchas / open_questions が1件も読めない場合は警告
    # （形式ズレで注意事項が無言のまま消えるのを防ぐ）
    constraints = ctx.constraints or {}
    if constraints and not normalize_gotchas(constraints) and not normalize_open_questions(constraints):
        warnings.append(
            "constraints.yaml: gotchas / open_questions が1件も読み取れませんでした"
            "（形式を schema/context-schema.md に合わせてください）"
        )

    warnings.extend(validate_customer_understanding(ctx.customer_understanding or {}))

    segments = (ctx.site_segments or {}).get("site_segments", []) or []
    warnings.extend(validate_site_segments(segments))

    preferences = (ctx.profile or {}).get("preferences", {}) or {}
    warnings.extend(validate_output_format_preference(preferences))

    return warnings


def validate_output_format_preference(preferences: dict) -> list[str]:
    """`profile.yaml` の `preferences.output_formats`（成果物の書き出し先）の軽量バリデーション。

    未設定（`output_formats` キー自体が無い）は許容する（一度も聞いていない状態を壊さない、
    他の validate_* と同じ方針）。警告にするのは以下の2点だけに絞る:
      - `OUTPUT_FORMATS` に無い値が混ざっている
      - `gdoc` / `gsheet` を選んでいるのに対応するURL（`google_doc_url` / `google_sheet_url`）が空
        （サービスアカウントは自分でファイルを作れないため、書き込み先URLが無いと成立しない。
        理由は `OUTPUT_FORMAT_URL_KEYS` のコメント参照）
    """
    warnings: list[str] = []
    if not isinstance(preferences, dict) or "output_formats" not in preferences:
        return warnings

    formats = preferences.get("output_formats")
    if not isinstance(formats, list):
        return warnings
    formats = [str(f).strip() for f in formats if str(f).strip()]

    unknown = [f for f in formats if f not in OUTPUT_FORMATS]
    if unknown:
        warnings.append(
            f"profile.yaml: preferences.output_formats に未知の値があります: {unknown}"
            f"（許容値: {list(OUTPUT_FORMATS)}）"
        )

    for fmt, url_key in OUTPUT_FORMAT_URL_KEYS.items():
        if fmt in formats and not str(preferences.get(url_key) or "").strip():
            warnings.append(
                f"profile.yaml: preferences.output_formats に '{fmt}' がありますが "
                f"preferences.{url_key} が未設定です（{fmt} への書き出しにはURLが必要です。"
                "利用者が先に空のファイルを作り、サービスアカウントに編集者で共有した先のURL）"
            )

    return warnings


def validate_kpi_priorities(kpis: list) -> list[str]:
    """kpis.yaml の kpis[].priority（どのCVを主に見るか）の軽量バリデーション。

    「未設定」は許容する（優先度をまだ聞いていない既存クライアントが多数いるため、これを
    エラーにすると既存データが壊れる）。警告にするのは、聞いたはずなのに書き方が中途半端な
    ケース（一部のKPIにだけ付いている／値が重複している／1未満）だけに絞る。
    KPIが1件だけのときは優先度を聞く意味が無いため、未設定でもチェックしない。
    """
    warnings: list[str] = []
    dict_kpis = [k for k in kpis if isinstance(k, dict)]
    if len(dict_kpis) <= 1:
        return warnings

    with_priority = [k for k in dict_kpis if k.get("priority") is not None]
    if not with_priority:
        return warnings  # 全KPIが未設定 = まだ聞いていない。止めずに進む

    if len(with_priority) != len(dict_kpis):
        missing = [k.get("kpi_id", "?") for k in dict_kpis if k.get("priority") is None]
        warnings.append(
            f"kpis.yaml: 一部のKPIにだけ priority が設定されています（未設定: {missing}）。"
            "複数KPIがあるときはどれが主かを揃えて設定してください"
        )

    values: list[int] = []
    for k in with_priority:
        raw = k.get("priority")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            warnings.append(
                f"kpis.yaml: {k.get('kpi_id', '?')} の priority が整数ではありません: {raw!r}"
            )
            continue
        if value < KPI_PRIORITY_MIN:
            warnings.append(
                f"kpis.yaml: {k.get('kpi_id', '?')} の priority は{KPI_PRIORITY_MIN}以上にしてください: {value}"
            )
        values.append(value)

    dup_values = {v for v in values if values.count(v) > 1}
    if dup_values:
        warnings.append(
            f"kpis.yaml: priority の値が重複しています（どれが最優先か一意に決まりません）: {sorted(dup_values)}"
        )

    return warnings


def match_site_segment(
    segments: list,
    host_name: str | None = None,
    page_path: str | None = None,
    content_group: str | None = None,
) -> str | None:
    """1ページを `site-segments.yaml` の site_segments に照らして分類し、一致した `segment_id` を返す。

    - `match.host_name` / `match.path_prefix` / `match.content_group` はいずれも省略可で、
      スカラー値でもリストでも渡せる（`_as_list` で正規化。例: `path_prefix: ["/media/", "/blog/"]`
      で複数パスをまとめて1セグメント扱いできる）。
    - **1セグメント内で複数キーを指定した場合は AND（すべて満たす）**として扱う。絞り込み条件を
      重ねる操作は一般的に「絞り込みを厳しくする」ものであり、OR（どれか一つで一致）にすると
      条件を足すほどそのセグメントが広がってしまい直感に反する。パスだけで分ける・ホスト名だけで
      分ける・両方で分ける、をサイトごとに使い分けたいという要望とも整合する。
    - 各キー内（host_name同士、path_prefix同士）は OR（いずれかに一致すればよい）。
    - `content_group` は GA4 側でコンテンツグループが設定済みのサイト向け。設定済みなら
      それが役割分類の正であり、path_prefix/host_nameで同じ境界を再定義する必要が無い
      （01の計測設計がコンテンツグループの設定有無を判定している。未設定なら
      path_prefix/host_nameで代用する）。
    - 定義順に見て最初に一致したセグメントを返す（複数セグメントの条件が重なる場合は先勝ち。
      重複させたくない場合は呼び出し側で条件を見直す）。
    - どのキーも指定されていない（＝条件が空の）セグメントは絶対に一致しない（空条件を
      「すべてに一致」として扱うと、そのセグメントが他の全ページを飲み込んでしまう事故に
      つながるため、安全側に倒す。`validate_site_segments` が警告する）。ただし
      `default: true` を持つセグメントはこのチェックの対象外（下記）。
    - **`default: true` を持つセグメント（既定セグメント）は match を評価しない。** 他のどの
      セグメントの条件にも一致しなかったページは、既定セグメントがあればそこに落ちる
      （定義順で最初に見つかった `default: true` を採用。2件以上の `default: true` は
      `validate_site_segments` が警告する）。
    - **`default: true` が1件も無い場合に限り、どれにも一致しなかったとき `None` を返す。**
      「オウンドメディアのようにサイト内で役割が違うセクションだけを切り出し、それ以外
      （トップ・about・お問い合わせ・LP等）はすべて本体サイトに落ちる」という前提に立った
      設計——一致条件を書くのは切り出したいセクションだけでよく、「その他」という3つ目の
      バケツを作る必要が無い。ただし**「分けて集計した合計が全体と一致すること」という目的**
      （過去に『独立した切り口の合計が全体を29,361件上回っていた』事故があった）は引き続き
      死守する必要があるため、`default: true` を1件も設定していないクライアントに限り
      旧来どおり `None`（その他）を返す。この場合は呼び出し側（02等）が `None` の件数を
      集計に残すこと——除外すると同じ事故が再発する。`validate_site_segments` は
      既定セグメント未設定を警告するので、通常はこの分岐に入らない想定。
    """
    host_name = str(host_name or "").strip()
    page_path = str(page_path or "").strip()
    content_group = str(content_group or "").strip()
    default_segment_id: str | None = None
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if seg.get("default") is True:
            if default_segment_id is None:
                default_segment_id = seg.get("segment_id")
            continue  # 既定セグメントは match を見ない（後段のフォールバックとしてのみ使う）
        match = seg.get("match")
        if not isinstance(match, dict):
            continue
        hosts = [str(h).strip() for h in _as_list(match.get("host_name")) if str(h).strip()]
        prefixes = [str(p).strip() for p in _as_list(match.get("path_prefix")) if str(p).strip()]
        groups = [str(g).strip() for g in _as_list(match.get("content_group")) if str(g).strip()]
        if not hosts and not prefixes and not groups:
            continue  # 条件が空のセグメントは何にも一致しない
        host_ok = (not hosts) or (host_name.lower() in [h.lower() for h in hosts])
        prefix_ok = (not prefixes) or any(page_path.startswith(p) for p in prefixes)
        group_ok = (not groups) or (content_group in groups)
        if host_ok and prefix_ok and group_ok:
            return seg.get("segment_id")
    return default_segment_id


def validate_site_segments(segments: list) -> list[str]:
    """`site-segments.yaml` の site_segments の軽量バリデーション。

    未設定（`site_segments` が空リスト、またはキー自体が無い）のクライアントは今まで通り
    警告0件——**役割の違うセクションを持たないサイトの方が多く、この機能自体が任意** なため
    （`kpis[].priority` が未設定を許容するのと同じ方針。加えてこの機能は利用者が事前に定義する
    ものではなく、01/03が実際のページ一覧から気づいて提案し、確認が取れたものだけを保存する
    運用のため、そもそも「聞いたのに未設定」という状態が起きにくい）。警告にするのは、
    定義した以上は中途半端であってはならない状態（条件が空・segment_idの重複・
    既定セグメントの過不足）に絞る。
    """
    warnings: list[str] = []
    dict_segments = [s for s in segments if isinstance(s, dict)]
    if not dict_segments:
        return warnings

    seg_ids = [s.get("segment_id") for s in dict_segments if s.get("segment_id")]
    dup_ids = {x for x in seg_ids if seg_ids.count(x) > 1}
    if dup_ids:
        warnings.append(f"site-segments.yaml: segment_id が重複しています: {sorted(dup_ids)}")

    default_segments = [s for s in dict_segments if s.get("default") is True]
    if len(default_segments) > 1:
        default_ids = [s.get("segment_id", "?") for s in default_segments]
        warnings.append(
            f"site-segments.yaml: default: true が複数のセグメントに設定されています: "
            f"{sorted(default_ids)}（どのセグメントに落ちるか決まりません。本体サイトに"
            "相当する1件だけに絞ってください）"
        )
    elif not default_segments:
        warnings.append(
            "site-segments.yaml: default: true のセグメントがありません"
            "（どの条件にも一致しないページが『その他』として黙って残ります。本体サイトに"
            "相当するセグメントに default: true を付けると、合計が全体とずれる心配が無くなります）"
        )

    for s in dict_segments:
        seg_id = s.get("segment_id", "?")
        is_default = s.get("default") is True
        match = s.get("match")
        if not isinstance(match, dict):
            match = {}
        hosts = _as_list(match.get("host_name"))
        prefixes = _as_list(match.get("path_prefix"))
        groups = _as_list(match.get("content_group"))
        has_match_condition = bool(hosts or prefixes or groups)

        if is_default:
            # 既定セグメントは条件で絞る役割ではない（残り全部を受け取る）ので、
            # match を持っていること自体が矛盾（どちらの役目か曖昧になる）。
            if has_match_condition:
                warnings.append(
                    f"site-segments.yaml: {seg_id} は default: true なのに match 条件も"
                    "設定されています（既定セグメントは絞り込みをしない役割なので、match は"
                    "持たせないでください）"
                )
            continue  # 既定セグメントは match が空でよい（それが仕様）なので下のチェックはしない

        if not has_match_condition:
            warnings.append(
                f"site-segments.yaml: {seg_id} は match条件"
                "（host_name / path_prefix / content_group）が空です"
                "（このセグメントはどのページにも一致しません）"
            )

    return warnings


def validate_customer_understanding(cu: dict) -> list[str]:
    """customer-understanding.yaml の軽量バリデーション。

    「根拠の無い刺激を、根拠ありのふりで書かない」ことを守らせるための最低限のチェック。
    落とさず警告として返す方針は他の validate と揃える。
    """
    warnings: list[str] = []
    if not cu:
        return warnings

    if not cu.get("created_date"):
        warnings.append(
            "customer-understanding.yaml: created_date が未設定です"
            "（いつ作ったか分からないと、古くなったことに気づけません）"
        )

    personas = cu.get("personas", []) or []
    if len(personas) > PERSONA_MAX:
        warnings.append(
            f"customer-understanding.yaml: personas が{PERSONA_MAX}人を超えています"
            f"（現在{len(personas)}人）。単純に切り捨てず、態度変容フロー（障壁・刺激）が近い"
            "ペルソナ同士を統合してください"
        )

    if len(personas) > 1:
        for p in personas:
            if not isinstance(p, dict):
                continue
            if not str(p.get("distinguishing_factor") or "").strip():
                warnings.append(
                    f"customer-understanding.yaml: {p.get('persona_id', '?')} に "
                    "distinguishing_factor（何が違うから分けたか）がありません"
                )

    for p in personas:
        if not isinstance(p, dict):
            continue
        pid = p.get("persona_id", "?")

        basis = p.get("persona_basis")
        if basis not in PERSONA_BASIS_VALUES:
            warnings.append(
                f"customer-understanding.yaml: {pid} は persona_basis が "
                f"{PERSONA_BASIS_VALUES} のどちらでもありません"
                "（顧客の声で実在確認できたか、サービスからの逆算のみかを明示する）"
            )

        journey = p.get("journey", []) or []
        stage_ids = [j.get("stage_id") for j in journey if isinstance(j, dict)]
        if stage_ids != JOURNEY_STAGE_IDS:
            warnings.append(
                f"customer-understanding.yaml: {pid} の journey が5段階固定順"
                f"{JOURNEY_STAGE_IDS} になっていません（現状: {stage_ids}）"
            )
        for j in journey:
            if not isinstance(j, dict):
                continue
            stage_id = j.get("stage_id")
            warnings.extend(_check_evidence_items(pid, stage_id, "障壁", j.get("barriers", []) or [], "barrier_id"))
            warnings.extend(_check_evidence_items(pid, stage_id, "刺激", j.get("stimuli", []) or [], "stimulus_id"))

    return warnings


def _check_evidence_items(
    persona_id: str, stage_id, label: str, items: list, id_key: str
) -> list[str]:
    """journey[].barriers / journey[].stimuli 共通の evidence_type チェック。

    「根拠の無い項目を、根拠ありのふりで書かない」ことを守らせる。barriers は従来
    evidence_type を持たなかったが、06側（page_profile / create-page-plan）の記述が
    「障壁・刺激」双方の evidence_type を前提にしているため、stimuli と同じ扱いにする。
    """
    warnings: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get(id_key, "?")
        ev_type = item.get("evidence_type")
        if ev_type not in EVIDENCE_TYPES:
            warnings.append(
                f"customer-understanding.yaml: {persona_id}/{stage_id} の{label} "
                f"{item_id} は evidence_type が {EVIDENCE_TYPES} のいずれでもありません"
            )
        elif ev_type in EVIDENCE_REQUIRING_TYPES and not str(item.get("evidence") or "").strip():
            warnings.append(
                f"customer-understanding.yaml: {persona_id}/{stage_id} の{label} "
                f"{item_id} は evidence_type: {ev_type} なのに evidence（根拠）が空です"
            )
    return warnings
