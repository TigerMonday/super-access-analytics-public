"""Search Console monthly metrics as fixed-slide-sized semantic charts."""
import html
import math


def search_chart(title, headers, rows):
    from .html_components import _number
    if len(headers) != 5:
        raise ValueError('search chart requires month, impressions, clicks, CTR, position')
    rows = [r for r in rows if len(r) == 5 and '合計' not in r[0]]
    if not rows:
        return ''
    esc = html.escape
    width, left, right = max(1000, len(rows)*68+180), 95, 110
    top, plot_h, height = 82, 170, 330
    plot_w = width-left-right
    charts = []
    for a, b in [(1, 2), (3, 4)]:
        panel_title = f'{title} — {headers[a]}・{headers[b]}'
        parts = [
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(panel_title)}">',
            '<style>.search-label{font-size:13px;fill:var(--gray-700)}.search-title{font-size:16px;font-weight:700;fill:var(--gray-900)}</style>',
            f'<text x="{left}" y="25" class="search-title">{esc(title)}</text>',
        ]
        vals = {c: [_number(r[c]) for r in rows] for c in (a,b)}
        maxes = {c: max([v for v in vals[c] if v is not None]+[1]) for c in (a,b)}
        maxes[b] = math.ceil(maxes[b]) if b == 4 else maxes[b]
        for c, color, anchor, x in [(a,'var(--gray-900)','start',left),(b,'var(--gold-dark)','end',width-right)]:
            name = headers[c] + ('（上ほど良い）' if c == 4 else '')
            parts.append(f'<text x="{x}" y="{top-25}" text-anchor="{anchor}" class="search-title" style="fill:{color}">{esc(name)}</text>')
        for tick in range(5):
            y = top + plot_h*tick/4
            parts.append(f'<line x1="{left}" x2="{width-right}" y1="{y}" y2="{y}" class="chart-grid"/>')
            for c in (a,b):
                value = (1+(maxes[c]-1)*tick/4) if c == 4 else maxes[c]*(1-tick/4)
                label = f'{value:.2f}%' if c == 3 else (f'{value:.1f}位' if c == 4 else f'{value:,.0f}')
                x, anchor = (left-12,'end') if c == a else (width-right+12,'start')
                parts.append(f'<text x="{x}" y="{y+5}" text-anchor="{anchor}" class="search-label">{label}</text>')
        for c, color in [(a,'var(--gray-900)'),(b,'var(--gold-dark)')]:
            segment = []
            for i, value in enumerate(vals[c]):
                if value is None:
                    if segment:
                        parts.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2.5"/>')
                    segment = []
                    continue
                x = left + plot_w*i/max(1,len(rows)-1)
                frac = (value-1)/max(1,maxes[c]-1) if c == 4 else 1-value/maxes[c]
                y = top+plot_h*frac
                segment.append(f'{x:.1f},{y:.1f}')
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"><title>{esc(rows[i][0]+" "+headers[c]+": "+rows[i][c])}</title></circle>')
            if segment:
                parts.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for i, row in enumerate(rows):
            x = left+plot_w*i/max(1,len(rows)-1)
            parts.append(f'<text x="{x:.1f}" y="{top+plot_h+28}" text-anchor="middle" class="search-label">{esc(row[0])}</text>')
        parts.append(f'<text x="{width-right}" y="{top+plot_h+54}" text-anchor="end" class="search-label">月</text>')
        parts.append('</svg>')
        charts.append('<div class="report-chart report-chart-search">' + ''.join(parts) + '</div>')
    return ''.join(charts)
