"""CV別・初回CV前の経路とページ閲覧後CV率。SQLは1ジョブで集計する。"""
from datetime import date


def build_sql(project, dataset, start, end, key_events, max_steps, limit, page_groups=None):
    from google.cloud import bigquery
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('開始日が終了日より後です')
    groups = page_groups or []
    if not isinstance(groups, list):
        raise ValueError('page_groups は配列です')
    # SQLに埋め込む分類条件は番号だけ。名前・prefixはパラメータ化する。
    clauses, params = [], []
    for i, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError('ページ群はオブジェクトで指定してください')
        prefixes = group.get('path_prefix', [])
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if not group.get('name') or not prefixes or not all(isinstance(p, str) and p for p in prefixes):
            raise ValueError('ページ群にはnameと空でないpath_prefixが必要です')
        clauses.append(f"WHEN EXISTS(SELECT 1 FROM UNNEST(@prefixes_{i}) p WHERE IF(p = '/', url_path = '/', STARTS_WITH(url_path, p))) THEN @group_{i}")
        params.extend([bigquery.ArrayQueryParameter(f'prefixes_{i}', 'STRING', prefixes), bigquery.ScalarQueryParameter(f'group_{i}', 'STRING', group['name'])])
    classification = 'CASE ' + ' '.join(clauses) + " ELSE 'その他' END" if groups else 'page'
    sql = f"""
WITH raw AS (
 SELECT user_pseudo_id,
 (SELECT value.int_value FROM UNNEST(event_params) WHERE key='ga_session_id') session_id,
 event_name, event_timestamp,
 REGEXP_EXTRACT((SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_location'), r'^[^?#]+') page
 FROM `{project}.{dataset}.events_*`
 WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
 AND (event_name='page_view' OR event_name IN UNNEST(@key_events))
), events AS (
 SELECT * FROM raw WHERE user_pseudo_id IS NOT NULL AND session_id IS NOT NULL
), sessions AS (
 SELECT user_pseudo_id, session_id, key_event,
 MIN(IF(event_name=key_event,event_timestamp,NULL)) cv_time
 FROM events CROSS JOIN UNNEST(@key_events) key_event
 GROUP BY 1,2,3
), totals AS (
 SELECT key_event, COUNTIF(cv_time IS NOT NULL) total_cv_sessions FROM sessions GROUP BY 1
), before_cv AS (
 SELECT s.*, e.event_timestamp, e.page,
 COALESCE(REGEXP_EXTRACT(e.page,r'^https?://[^/]+(/[^?#]*)'),'/') url_path
 FROM sessions s JOIN events e USING(user_pseudo_id,session_id)
 WHERE e.event_name='page_view' AND e.page IS NOT NULL
 AND (s.cv_time IS NULL OR e.event_timestamp < s.cv_time)
), labeled AS (
 SELECT *, {classification} label FROM before_cv
), sequenced AS (
 SELECT *, LAG(label) OVER(PARTITION BY user_pseudo_id,session_id,key_event ORDER BY event_timestamp,page) previous_label
 FROM labeled WHERE cv_time IS NOT NULL
), paths AS (
 SELECT user_pseudo_id, session_id,key_event,
 STRING_AGG(label,' -> ' ORDER BY event_timestamp,page LIMIT {max_steps}) path,
 COUNT(*) > {max_steps} truncated
 FROM sequenced WHERE previous_label IS NULL OR label != previous_label
 GROUP BY 1,2,3
), path_counts AS (
 SELECT key_event,path,truncated,COUNT(*) converted_sessions FROM paths GROUP BY 1,2,3
), page_sessions AS (
 SELECT DISTINCT user_pseudo_id,session_id,key_event,page,cv_time IS NOT NULL converted
 FROM before_cv
), page_counts AS (
 SELECT key_event,page path,COUNTIF(converted) converted_sessions,COUNT(*) viewed_sessions
 FROM page_sessions GROUP BY 1,2
), result AS (
 SELECT 'path' record_type,p.key_event,path,converted_sessions,0 viewed_sessions,total_cv_sessions,truncated
 FROM path_counts p JOIN totals USING(key_event)
 QUALIFY ROW_NUMBER() OVER(PARTITION BY key_event ORDER BY converted_sessions DESC,path,truncated) <= {limit}
 UNION ALL
 SELECT 'page',p.key_event,path,converted_sessions,viewed_sessions,total_cv_sessions,FALSE
 FROM page_counts p JOIN totals USING(key_event)
 QUALIFY ROW_NUMBER() OVER(PARTITION BY key_event ORDER BY converted_sessions DESC,viewed_sessions DESC,path) <= {limit}
 UNION ALL
 SELECT 'summary',key_event,'',0,0,total_cv_sessions,FALSE FROM totals
)
SELECT * FROM result ORDER BY key_event,record_type,converted_sessions DESC,path
"""
    params.extend([
        bigquery.ScalarQueryParameter('start_suffix','STRING',start.replace('-','')),
        bigquery.ScalarQueryParameter('end_suffix','STRING',end.replace('-','')),
        bigquery.ArrayQueryParameter('key_events','STRING',list(dict.fromkeys(key_events))),
    ])
    return sql, params


def render(rows, start, end, max_steps):
    def cell(value):
        return str(value).replace('|','&#124;').replace('<','&lt;').replace('>','&gt;').replace('\n',' ')
    lines = [f'# CV前の行動分析（{start} ～ {end}）', '',
        '同一セッション・CV別の最初のCVまでを集計。CV後の閲覧は除外。対象期間外の閲覧、識別子欠損は含まない。同時刻のCVと閲覧は順序不明のため除外し、同時刻の閲覧同士の並びは確定できない。', '',
        f'経路は連続する同一ページ（分類指定時は同一ページ群）をまとめ、先頭{max_steps}段階まで表示。省略のある経路は明示する。', '']
    for cv in sorted({r['key_event'] for r in rows}):
        subset = [r for r in rows if r['key_event']==cv]
        total = max((r['total_cv_sessions'] for r in subset),default=0)
        lines += [f'## {cell(cv)}', f'対象CVセッション数：{total:,}', '', '### CVまでの主なページ遷移', '',
            '| 経路 | CVセッション数 | 全対象CVセッションに占める構成比 |', '|---|---:|---:|']
        for r in subset:
            if r['record_type']=='path':
                ratio = f"{r['converted_sessions']/total:.2%}" if total else '—'
                lines.append(f"| {cell(r['path'])}{' → …（後続省略）' if r['truncated'] else ''} | {r['converted_sessions']:,} | {ratio} |")
        lines += ['', '### ページ閲覧後のCV率', '',
            '| ページURL | 対象閲覧セッション数 | 閲覧後CVセッション数 | ページ閲覧後のCV率 |', '|---|---:|---:|---:|']
        for r in subset:
            if r['record_type']=='page':
                ratio = f"{r['converted_sessions']/r['viewed_sessions']:.2%}" if r['viewed_sessions'] else '—'
                lines.append(f"| {cell(r['path'])} | {r['viewed_sessions']:,} | {r['converted_sessions']:,} | {ratio} |")
        lines += ['', '分母は当該CV前にそのページを閲覧したセッション（非CVセッションを含む）。反復閲覧は1件。CV後だけの閲覧は分母にも含めない。関連を示す率であり、ページの因果的な貢献度ではない。上位表は全経路・全ページではない。', '']
    return '\n'.join(lines)+'\n'
