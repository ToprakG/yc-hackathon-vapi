"""Helpers that run INSIDE the Freya workflow (code nodes and hooks). Embedded as source by compiler/snippets.py.

Rules (docs/tools-and-code.md "Rules for snippets"): standard modules json, re, datetime only; no double braces
anywhere in this file; never raise to the platform (callers wrap in try/except); routing flags are strings; every
date rule starts from vars['now']. The parameter that carries the variable table is named `vars` on purpose, so the
workflow linter sees every literal key written.
"""
import datetime
import json
import re

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']
FALLBACK_KEY = {'nr_no_callback': 'nr_unclear', 'nr_callback': 'nr_unclear', 'nr_wrong_number': 'nr_unclear',
                'nr_deceased': 'nr_unclear', 'nv_declined': 'nv_failed', 'nv_failed': 'nr_unclear',
                'np_hardship': 'np_refused', 'np_dispute': 'np_refused', 'np_service_error': 'np_refused',
                'paid': 'np_refused', 'tr_support': 'np_hardship', 'tr_human': 'np_refused',
                'tr_restructuring': 'np_refused', 'np_refused': 'nr_unclear', 'promise': 'np_refused'}
STATUS_KEY = {'refused': 'np_refused', 'hardship': 'np_hardship', 'dispute': 'np_dispute', 'paid': 'paid',
              'service_error': 'np_service_error', 'open': 'np_refused'}


def parse_now(value):
    s = str(value or '').strip().replace(' ', 'T').rstrip('Z')
    for fmt, size in (('%Y-%m-%dT%H:%M:%S', 19), ('%Y-%m-%dT%H:%M', 16), ('%Y-%m-%d', 10)):
        try:
            return datetime.datetime.strptime(s[:size], fmt)
        except ValueError:
            pass
    raise ValueError('cannot read now: ' + s)


def hol_set(cfg):
    out = set()
    for h in cfg.get('holidays') or []:
        try:
            out.add(datetime.date.fromisoformat(str(h)[:10]))
        except ValueError:
            pass
    return out


def is_bd(d, hol):
    return d.weekday() < 5 and d not in hol


def next_bd_after(d, hol):
    x = d + datetime.timedelta(days=1)
    while not is_bd(x, hol):
        x = x + datetime.timedelta(days=1)
    return x


def bd_on_or_after(d, hol):
    return d if is_bd(d, hol) else next_bd_after(d, hol)


def add_bd(d, n, hol):
    x, k = d, 0
    while k < n:
        x = x + datetime.timedelta(days=1)
        if is_bd(x, hol):
            k += 1
    return x


def last_bd_of_week(d, hol):
    x = d + datetime.timedelta(days=4 - d.weekday())
    monday = d - datetime.timedelta(days=d.weekday())
    while not is_bd(x, hol) and x > monday:
        x = x - datetime.timedelta(days=1)
    return x


def attempt_date(rule, today, deadline, hol, cap):
    if rule in ('end_of_week_roll', 'end_of_week'):
        x = last_bd_of_week(today, hol)
        if rule == 'end_of_week_roll' and x <= today:
            x = last_bd_of_week(today + datetime.timedelta(days=7), hol)
        elif x < today or not is_bd(x, hol):
            x = bd_on_or_after(today, hol)
    elif rule == 'today':
        x = bd_on_or_after(today, hol)
    elif rule == 'next_business_day':
        x = next_bd_after(today, hol)
    else:
        x = deadline
    if cap and x > deadline:
        x = deadline
    return x


def spoken(d):
    return WEEKDAYS[d.weekday()] + ' ' + str(d.day) + ' ' + MONTHS[d.month - 1]


def spoken_full(d):
    return spoken(d) + ' (' + d.isoformat() + ')'


def money(x):
    s = '%.2f' % float(x)
    return s[:-3] if s.endswith('.00') else s


def num(v):
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r'[^0-9.,\-]', '', str(v or ''))
    if s.count(',') and s.count('.'):
        s = s.replace(',', '')
    elif s.count(',') == 1 and len(s.split(',')[1]) == 2:
        s = s.replace(',', '.')
    else:
        s = s.replace(',', '')
    return float(s) if s not in ('', '.', '-') else 0.0


def truthy(v):
    return str(v).strip().lower() in ('true', '1', 'yes')


def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith('['):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else []
        except ValueError:
            return []
    return []


def jget(vars, key, default):
    v = vars.get(key)
    if isinstance(v, (dict, list)):
        return v
    try:
        x = json.loads(v) if isinstance(v, str) and v.strip() else None
    except ValueError:
        x = None
    return x if isinstance(x, type(default)) else default


def jput(vars, key, value):
    vars[key] = json.dumps(value)


def _flattened_items(vars, list_field):
    """Products as flattened keys: <prefix>.data.<list>.<i>.<field>."""
    rows = dict()
    pat = re.compile(r'^(?:get_account|fetch_account|fetch_account_retry)_response\.data\.' + re.escape(list_field) + r'\.(\d+)\.(\w+)$')
    for k in list(vars.keys()):
        m = pat.match(str(k))
        if m:
            rows.setdefault(int(m.group(1)), dict())[m.group(2)] = vars.get(k)
    return [rows[i] for i in sorted(rows)]


def raw_products(vars, cfg):
    lf = cfg.get('list_field') or 'products'
    for key in ('products_raw', 'get_account_response.data.' + lf, 'fetch_account_response.data.' + lf,
                'fetch_account_retry_response.data.' + lf):
        items = as_list(vars.get(key))
        if items:
            return [x for x in items if isinstance(x, dict)]
    return _flattened_items(vars, lf)


def band_for(cfg, days):
    bands = cfg.get('bands') or []
    for b in bands:
        if int(b['min_days']) <= days <= int(b['max_days']):
            return b
    if bands and days < int(bands[0]['min_days']):
        return bands[0]
    return bands[-1] if bands else dict(name='default', deadline_business_days=5, attempts=1)


def type_key(cfg, value):
    for k, t in (cfg.get('product_types') or dict()).items():
        if str(t.get('enum')) == str(value):
            return k
    return ''


def product_rows(vars, cfg):
    """Every product, in API order, with its computed facts."""
    now = parse_now(vars.get('now'))
    today = now.date()
    hol = hol_set(cfg)
    af = cfg.get('account_fields') or dict()
    plan = cfg.get('attempt_plan') or []
    out = []
    for i, p in enumerate(raw_products(vars, cfg)[: int(cfg.get('max_products') or 3)]):
        tk = type_key(cfg, p.get(af.get('type', 'type')))
        t = (cfg.get('product_types') or dict()).get(tk) or dict()
        pid = str(p.get(af.get('product_id', 'product_id')) or str(cfg.get('product_id_format') or 'p{n}').replace('{n}', str(i + 1)))
        last4 = str(p.get(t.get('last4_field') or '') or '')
        label = str(t.get('label') or 'account').replace('{last4}', last4)
        past_due = num(p.get(af.get('past_due', 'past_due')))
        days = int(num(p.get(af.get('days_late', 'days_late'))))
        floor = num(p.get(t.get('floor_field') or '')) if t.get('floor_field') in p else past_due
        if floor <= 0 or floor > past_due:
            floor = past_due
        b = band_for(cfg, days)
        deadline = add_bd(today, int(b.get('deadline_business_days', 5)), hol)
        attempts = int(b.get('attempts', 1))
        props = []
        for k in range(attempts):
            step = plan[k] if k < len(plan) else (plan[-1] if plan else dict(date='deadline', amount='floor'))
            d = attempt_date(step.get('date', 'deadline'), today, deadline, hol, step.get('cap_at_deadline', True))
            props.append(dict(date=d.isoformat(), spoken=spoken(d), amount=step.get('amount', 'full_or_floor')))
        out.append(dict(index=i + 1, pid=pid, label=label, past_due=past_due, days=days, floor=floor,
                        band=str(b.get('name', '')), deadline=deadline.isoformat(), deadline_spoken=spoken(deadline),
                        attempts=attempts, proposals=props))
    return out


def outcome_fields(cfg, key):
    om = cfg.get('outcome_map') or dict()
    seen = set()
    k = key
    while k and k not in seen:
        seen.add(k)
        v = om.get(k)
        if v:
            return k, v[0], v[1]
        k = FALLBACK_KEY.get(k)
    return key, '', None


def final_key(vars, cfg):
    tr = str(vars.get('transfer_key') or '')
    if tr and tr != 'none':
        return 'tr_' + tr
    if str(vars.get('end_key') or '') == 'np_service_error_hard':
        return 'np_service_error'
    if str(vars.get('phase') or '') != 'products':
        return str(vars.get('end_key') or 'nr_unclear')
    pst = jget(vars, 'pstate', dict())
    order = jget(vars, 'pids', [])
    statuses = [pst.get(p, 'open') for p in order]
    if not statuses:
        return str(vars.get('end_key') or 'np_refused')
    if 'promised' in statuses:
        return 'promise'
    statuses = ['refused' if s == 'open' else s for s in statuses]
    if not cfg.get('multi') or len(statuses) == 1:
        return STATUS_KEY.get(statuses[0], 'np_refused')
    if all(s == 'paid' for s in statuses):
        return 'paid'
    rule = cfg.get('close_rule') or dict()
    if rule.get('kind') == 'priority' and rule.get('order'):
        for k in rule['order']:
            if k in statuses:
                return STATUS_KEY.get(k, 'np_refused')
    for s in statuses:
        if s != 'paid':
            return STATUS_KEY.get(s, 'np_refused')
    return 'np_refused'


def refresh_close(vars, cfg):
    key, outcome, reason = outcome_fields(cfg, final_key(vars, cfg))
    vars['close_key'] = key
    vars['close_outcome'] = outcome or ''
    vars['close_reason'] = reason or ''
    vars['close_code'] = outcome or ''
    return key


def open_pids(vars):
    pst = jget(vars, 'pstate', dict())
    return [p for p in jget(vars, 'pids', []) if pst.get(p, 'open') == 'open']


def set_status(vars, pid, status):
    pst = jget(vars, 'pstate', dict())
    if pid in jget(vars, 'pids', []) and (pst.get(pid) != 'promised' or status == 'promised'):
        pst[pid] = status  # a recorded promise is never downgraded
        jput(vars, 'pstate', pst)


def pick_products(vars, which):
    """Product ids an event concerns: '1'..'3' (order), 'all', or '' (the first open product)."""
    pids = jget(vars, 'pids', [])
    w = str(which or '').strip().lower()
    if w.isdigit() and 1 <= int(w) <= len(pids):
        return [pids[int(w) - 1]]
    if w == 'all':
        return open_pids(vars) or list(pids)
    op = open_pids(vars)
    return op[:1] if op else pids[:1]


def neg_flag(vars):
    vars['neg_state'] = 'done' if not open_pids(vars) else 'open'
    return vars['neg_state']


NUM_WORDS = {'zero': 0, 'oh': 0, 'one': 1, 'first': 1, 'two': 2, 'second': 2, 'three': 3, 'third': 3, 'four': 4,
             'fourth': 4, 'five': 5, 'fifth': 5, 'six': 6, 'sixth': 6, 'seven': 7, 'seventh': 7, 'eight': 8,
             'eighth': 8, 'nine': 9, 'ninth': 9, 'ten': 10, 'tenth': 10, 'eleven': 11, 'eleventh': 11, 'twelve': 12,
             'twelfth': 12, 'thirteen': 13, 'thirteenth': 13, 'fourteen': 14, 'fourteenth': 14, 'fifteen': 15,
             'fifteenth': 15, 'sixteen': 16, 'sixteenth': 16, 'seventeen': 17, 'seventeenth': 17, 'eighteen': 18,
             'eighteenth': 18, 'nineteen': 19, 'nineteenth': 19, 'twenty': 20, 'twentieth': 20, 'thirty': 30,
             'thirtieth': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}


def _number(vals):
    """A run of number-word values -> its digits: cardinals with hundred/thousand, or a spoken year (19 89)."""
    if 100 in vals or 1000 in vals:
        total, cur = 0, 0
        for v in vals:
            if v == 100:
                cur = (cur or 1) * 100
            elif v == 1000:
                total += (cur or 1) * 1000
                cur = 0
            else:
                cur += v
        return str(total + cur)
    groups, cur = [], 0
    for v in vals:
        if cur and not (cur >= 20 and cur % 10 == 0 and v < 10):
            groups.append(cur)
            cur = 0
        cur += v
    groups.append(cur)
    if len(groups) == 2 and 10 <= groups[0] <= 20 and groups[1] < 100:
        return str(groups[0] * 100 + groups[1])
    return ' '.join(str(g) for g in groups)


def words_to_digits(text):
    """'twenty-third of February nineteen eighty-nine' -> '23 of february 1989'. Digits stay as they are."""
    words = str(text or '').lower().replace('-', ' ').replace(',', ' , ').split()
    out, run = [], []
    for i, w in enumerate(words):
        if w in NUM_WORDS or w in ('hundred', 'thousand'):
            run.append(NUM_WORDS.get(w, 100 if w == 'hundred' else 1000))
        elif w == 'and' and run and i + 1 < len(words) and words[i + 1] in NUM_WORDS:
            continue
        else:
            if run:
                out.append(_number(run))
                run = []
            out.append(w)
    if run:
        out.append(_number(run))
    return ' '.join(out)


def to_iso(text, today):
    """A date said or written in many ways -> YYYY-MM-DD (day-first for numeric dates). '' when unreadable."""
    s = str(text or '').strip().lower()
    if not s:
        return ''
    if re.search(r'[a-z]', s) and not re.search(r'\d', s):
        s = words_to_digits(s)
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return ''
    m = re.search(r'\b(\d+)[./\-](\d+)(?:[./\-](\d+))?\b', s)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        try:
            x = datetime.date(y, mo, d)
        except ValueError:
            return ''
        if not m.group(3) and x < today:
            x = datetime.date(y + 1, mo, d)
        return x.isoformat()
    mi = -1
    for i, name in enumerate(MONTHS):
        if name.lower() in s or re.search(r'\b' + name.lower()[:3] + r'\b', s):
            mi = i
            break
    if mi >= 0:
        nums = [int(x) for x in re.findall(r'\d+', s)]
        day = next((n for n in nums if 1 <= n <= 31), 0)
        year = next((n for n in nums if n > 31), 0)
        if day:
            y = year or today.year
            try:
                x = datetime.date(y, mi + 1, day)
            except ValueError:
                return ''
            if not year and x < today:
                x = datetime.date(y + 1, mi + 1, day)
            return x.isoformat()
    return ''


def to_hhmm(text):
    s = str(text or '').strip().lower().replace('.', ':')
    m = re.search(r'(\d+)(?::(\d+))?\s*(am|pm|a\.m|p\.m)?', s)
    if not m:
        return ''
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    if m.group(2) is None and h >= 100:
        h, mi = h // 100, h % 100
    ap = m.group(3) or ''
    if ap.startswith('p') and h < 12:
        h += 12
    if ap.startswith('a') and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return ''
    return '%02d:%02d' % (h, mi)


def norm_answer(kind, text, today):
    s = str(text or '').strip()
    if kind == 'date':
        iso = to_iso(s, datetime.date(today.year, 1, 1))
        if iso:
            y = int(iso[:4])
            if y > today.year:  # a birth date has no future year; to_iso rolled it
                iso = str(y - 1) + iso[4:]
            return iso
        return s
    if kind == 'year':
        m = re.search(r'(1[89]|20)\d\d', s)
        return m.group(0) if m else re.sub(r'\D', '', s)
    if kind == 'digits':
        return re.sub(r'\D', '', s)
    if kind == 'code':
        return re.sub(r'\s+', ' ', s).upper()
    return re.sub(r'\s+', ' ', s)


def date_table(cfg, rows, today, days=21):
    hol = hol_set(cfg)
    lines = []
    for k in range(days + 1):
        d = today + datetime.timedelta(days=k)
        if is_bd(d, hol):
            ok = [r['pid'] for r in rows if d.isoformat() <= r['deadline']]
            tail = 'business day; allowed for ' + (', '.join(ok) if ok else 'no product (after every latest date)')
        else:
            tail = 'NOT a business day (next business day: ' + spoken_full(next_bd_after(d, hol)) + ')'
        lines.append('- ' + spoken_full(d) + ': ' + tail)
    return '\n'.join(lines)


def weekday_words(cfg, today):
    ww = cfg.get('weekday_words') or dict()
    monday = today - datetime.timedelta(days=today.weekday())
    out = []
    for i, name in enumerate(WEEKDAYS[:5]):
        this_d = monday + datetime.timedelta(days=i)
        if ww.get('this') == 'next_occurrence' and this_d < today:
            this_d = this_d + datetime.timedelta(days=7)
        nxt = monday + datetime.timedelta(days=7 + i)
        if ww.get('next') == 'next_occurrence':
            nxt = today + datetime.timedelta(days=(i - today.weekday()) % 7 or 7)
        out.append('"this ' + name + '" = ' + spoken_full(this_d) + '; "next ' + name + '" = ' + spoken_full(nxt))
    return '\n'.join(out)
