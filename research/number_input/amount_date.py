"""Turn what a caller said into a payment amount or a payment date, and say whether it is complete enough to use.

Generic: no bank, currency amount, date or field name from any brief. Standard library only (re, datetime): paste-ready
for a Freya code node or pre-hook. Contains no double braces.

    amount_from_speech("four hundred and fifty-five")          -> (455.0, True)
    amount_from_speech("two fifty")                            -> (250.0, True)
    amount_from_speech("two pounds fifty")                     -> (2.5, True)    # currency word: pounds + pence
    amount_from_speech("four fifty-five point five")           -> (455.5, True)
    amount_from_speech("300, sorry, 350")                      -> (350.0, True)  # the caller's last version counts
    amount_from_speech("the full amount")                      -> (None, "full")
    amount_from_speech("four hundred and")                     -> (400.0, False) # incomplete: wait for the rest
    date_from_speech("the twenty-second", "2026-10-14T10:10")  -> ("2026-10-22", True)
    date_from_speech("Friday", "2026-10-14T10:10")             -> ("2026-10-16", True)
    date_from_speech("end of the month", "2026-10-14T10:10")   -> (None, False)  # vague: ask for a day

Never returns a past date.
"""
import datetime
import re

UNITS = {"zero": 0, "nought": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
DIGIT_WORDS = dict(UNITS)
DIGIT_WORDS.update(oh=0, o=0)
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
       "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
       "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                           "september", "october", "november", "december"])}
for _k, _v in list(MONTHS.items()):
    MONTHS[_k[:3]] = _v
MONTHS["sept"] = 9
WEEKDAYS = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
WEEKDAYS.update(mon=0, tue=1, tues=1, wed=2, weds=2, thu=3, thur=3, thurs=3, fri=4, sat=5, sun=6)
CURRENCY_WORDS = ("pounds", "pound", "quid", "dollars", "dollar", "bucks", "euros", "euro", "sterling")
CENT_WORDS = ("pence", "p", "cents", "cent", "penny", "pennies")
SYMBOLS = ("£", "$", "€")
NOT_MONEY_AFTER = ("day", "days", "week", "weeks", "month", "months", "year", "years", "kid", "kids", "child",
                   "children", "percent", "am", "pm", "oclock", "o", "hours", "hour", "minutes", "times", "st", "nd",
                   "rd", "th", "of")
FILLERS = ("uh", "um", "er", "erm", "like", "hmm")
FULL = re.compile(r"\b(?:full amount|full balance|full sum|the full|in full|all of it|the whole|whole amount|whole lot|"
                  r"the lot|everything|entire amount|entire balance|all of the|the total|total amount|clear it all|"
                  r"pay it all|all at once)\b")
CORRECTION = re.compile(r"\b(?:sorry|i mean|no wait|wait|actually|correction|rather|make that|scratch that|"
                        r"or rather)\b|\bno\s*,")
VAGUE_DATE = re.compile(r"\b(?:end of (?:the |this |next )?month|end of the week|next month|next week|sometime|some time|"
                        r"soon|later|when i (?:get|am) paid|payday|pay day|a few days|few weeks|beginning of|start of|"
                        r"middle of|mid month|not sure|no idea|whenever|asap|as soon as)\b")


def segments(text):
    """'300, sorry, I mean 350' -> ['300, ', ', ', ' 350']: the caller's last version is the last segment."""
    parts = CORRECTION.split((text or "").lower())
    return [p for p in parts if p and re.search(r"[a-z0-9]", p)] or [(text or "").lower()]


# --- amounts ----------------------------------------------------------------------------------------------------------

def _amount_tokens(text):
    t = (text or "").lower()
    for _ in range(3):
        t = re.sub(r"(\d),(\d{3})", r"\1\2", t)
    t = t.replace("-", " ").replace("o'clock", "oclock")
    return re.findall(r"\d+(?:\.\d+)?(?:st|nd|rd|th|k)?|[a-z]+|[£$€]", t)


def _num(tok):
    if re.fullmatch(r"\d+(?:\.\d+)?", tok or ""):
        return float(tok)
    return None


def _starts_number(toks, i):
    w = toks[i]
    if _num(w) is not None or re.fullmatch(r"\d+(?:\.\d+)?k", w):
        return True
    if w in UNITS or w in TENS:
        return True
    if w == "a" and i + 1 < len(toks) and toks[i + 1] in ("hundred", "thousand", "grand"):
        return True
    if w in SYMBOLS and i + 1 < len(toks) and (_starts_number(toks, i + 1)):
        return True
    return False


def _small(toks, k):
    """A number from 1 to 99 at toks[k] (words or digits) -> (value, next index) or (None, k)."""
    if k >= len(toks):
        return None, k
    w = toks[k]
    v = _num(w)
    if v is not None and v == int(v) and 0 < v < 100:
        return int(v), k + 1
    if w in TENS:
        v = TENS[w]
        if k + 1 < len(toks) and toks[k + 1] in UNITS and 0 < UNITS[toks[k + 1]] < 10:
            return v + UNITS[toks[k + 1]], k + 2
        return v, k + 1
    if w in UNITS and UNITS[w] > 0:
        return UNITS[w], k + 1
    return None, k


def _decimals(toks, k):
    """Digits after 'point': 'five' -> '5', 'five oh' -> '50', 'fifty' -> '50', '5' -> '5'."""
    ds = ""
    while k < len(toks):
        w = toks[k]
        if re.fullmatch(r"\d+", w):
            ds += w
        elif w in DIGIT_WORDS and DIGIT_WORDS[w] < 10:
            ds += str(DIGIT_WORDS[w])
        elif w in TENS and not ds:
            v = TENS[w]
            if k + 1 < len(toks) and toks[k + 1] in UNITS and 0 < UNITS[toks[k + 1]] < 10:
                v += UNITS[toks[k + 1]]
                k += 1
            ds += str(v)
        else:
            break
        k += 1
    return ds, k


def _parse_amount(toks, i):
    """One number phrase starting at toks[i] -> (value, end, complete, currency) or (None, end, False, False)."""
    n = len(toks)
    total, cur, dec = 0.0, 0.0, None
    last, currency, complete = None, False, True
    j = i
    if toks[j] in SYMBOLS:
        currency = True
        j += 1
    while j < n:
        w = toks[j]
        v = _num(w)
        if w.endswith("k") and _num(w[:-1]) is not None:
            if last is not None and last not in ("and",):
                break
            total += _num(w[:-1]) * 1000
            last = "thousand"
        elif v is not None:
            if last in ("num", "unit", "teen", "tens"):
                break
            cur += v
            last = "num"
        elif w in UNITS:
            u = UNITS[w]
            if last == "tens" and u < 10 and cur % 10 == 0:
                cur += u
                last = "unit2"
            elif last in ("unit", "teen") and u >= 10 and 0 < cur < 20 and total == 0:
                cur = cur * 100 + u  # 'two fifteen' = 215
                last = "unit2"
            elif last in ("num", "unit", "teen", "tens", "unit2"):
                break
            else:
                cur += u
                last = "teen" if u >= 10 else "unit"
        elif w in TENS:
            t = TENS[w]
            if last in ("unit", "teen") and 0 < cur < 20 and total == 0:
                cur = cur * 100 + t  # 'four fifty' = 450, 'twelve fifty' = 1250
                last = "tens"
            elif last in ("num", "tens", "unit2", "unit", "teen"):
                break
            else:
                cur += t
                last = "tens"
        elif w == "hundred":
            cur = (cur or 1) * 100
            last = "hundred"
        elif w in ("thousand", "grand"):
            total += (cur or 1) * 1000
            cur = 0
            last = "thousand"
        elif w == "a" and j + 1 < n and toks[j + 1] in ("hundred", "thousand", "grand"):
            pass
        elif w == "and":
            if j + 2 < n and toks[j + 1] == "a" and toks[j + 2] == "half" and last is not None:
                dec = 0.5
                j += 3
                break
            if j + 1 >= n or all(x in FILLERS or x == "and" for x in toks[j + 1:]):
                complete = False
                j += 1
                break
            if last in ("hundred", "thousand") and j + 1 < n and _starts_number(toks, j + 1):
                last = "and"
            else:
                break
        elif w == "point":
            ds, k = _decimals(toks, j + 1)
            if not ds:
                complete = False
                j += 1
                break
            dec = float("0." + ds)
            j = k
            break
        elif w in FILLERS and last is not None:
            pass
        else:
            break
        j += 1
    if last is None:
        return None, j, False, False
    value = total + cur
    if j < n and toks[j] in ORD:
        return None, j + 1, False, False  # 'twenty second' is a date
    if j < n and toks[j] in NOT_MONEY_AFTER:
        return None, j + 1, False, False
    if dec is not None:
        value += dec
    if j < n and toks[j] in CURRENCY_WORDS:
        currency = True
        j += 1
        k = j + 1 if j < n and toks[j] == "and" else j
        c, k2 = _small(toks, k)
        if c is not None and dec is None:
            value += c / 100.0
            j = k2
            if j < n and toks[j] in CENT_WORDS:
                j += 1
        elif k < n and toks[k] == "and" and k + 1 >= n:
            complete = False
    elif j < n and toks[j] in CENT_WORDS and dec is None and total == 0 and cur < 100:
        value = cur / 100.0
        currency = True
        j += 1
    return value, j, complete, currency


def _amount_in(seg):
    toks = _amount_tokens(seg)
    found, i = [], 0
    while i < len(toks):
        if _starts_number(toks, i):
            v, j, ok, cur = _parse_amount(toks, i)
            if v is not None:
                found.append((v, ok, cur))
            i = max(j, i + 1)
        else:
            i += 1
    if not found:
        return None
    with_cur = [f for f in found if f[2]]
    v, ok, _ = (with_cur or found)[-1]
    return round(v, 2), ok


def amount_from_speech(text):
    """Return (amount or None, complete). complete is 'full' when the caller means the whole amount."""
    try:
        for seg in reversed(segments(text)):
            r = _amount_in(seg)
            if r is not None:
                return r
            if FULL.search(seg):
                return None, "full"
        if FULL.search((text or "").lower()):
            return None, "full"
    except Exception:
        pass
    return None, False


# --- dates ------------------------------------------------------------------------------------------------------------

def _today(now_iso):
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(now_iso or ""))
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return datetime.date.today()


def _date_tokens(text):
    t = (text or "").lower().replace("-", " ")
    t = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1 #ord", t)
    return re.findall(r"#ord|[a-z]+|\d+", t)


def _day_at(toks, k, need_marker):
    """A day of month at toks[k] -> (day, next index) or (None, k). need_marker: only clear ordinals count."""
    if k >= len(toks):
        return None, k
    w = toks[k]
    nxt = toks[k + 1] if k + 1 < len(toks) else ""
    if re.fullmatch(r"\d{1,2}", w):
        d = int(w)
        if nxt == "#ord":
            return (d, k + 2) if 1 <= d <= 31 else (None, k)
        if need_marker:
            return None, k
        return (d, k + 1) if 1 <= d <= 31 else (None, k)
    if w in TENS and nxt in ORD and ORD[nxt] < 10:
        return TENS[w] + ORD[nxt], k + 2
    if w in ORD:
        return ORD[w], k + 1
    if need_marker:
        return None, k
    if w in TENS:
        v = TENS[w]
        if nxt in UNITS and 0 < UNITS[nxt] < 10:
            v += UNITS[nxt]
            return (v, k + 2) if v <= 31 else (None, k)
        return (v, k + 1) if v <= 31 else (None, k)
    if w in UNITS and UNITS[w] > 0:
        return UNITS[w], k + 1
    return None, k


def _year_at(toks, k):
    seq = [t for t in toks[k:k + 5] if t not in ("of", "the", "in", "and", "#ord")]
    if not seq:
        return None
    if re.fullmatch(r"(19|20)\d\d", seq[0]):
        return int(seq[0])
    if seq[0] == "two" and len(seq) > 1 and seq[1] == "thousand":
        rest = seq[2:]
        v, _ = _small(rest, 0)
        return 2000 + (v or 0)
    if seq[0] in ("twenty", "nineteen") and len(seq) > 1:
        hi = 20 if seq[0] == "twenty" else 19
        v, _ = _small(seq, 1)
        if v is not None and v >= 10:
            return hi * 100 + v
    return None


def _resolve(y, m, d, today):
    if y is not None:
        try:
            dt = datetime.date(y, m, d)
        except ValueError:
            return None, False
        return (dt.isoformat(), True) if dt >= today else (None, False)
    for yy in (today.year, today.year + 1):
        try:
            dt = datetime.date(yy, m, d)
        except ValueError:
            continue
        if dt >= today:
            return dt.isoformat(), True
    return None, False


def _next_day_of_month(d, today):
    y, m = today.year, today.month
    for _ in range(13):
        try:
            dt = datetime.date(y, m, d)
            if dt >= today:
                return dt.isoformat(), True
        except ValueError:
            pass
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return None, False


def _count_word(w):
    if re.fullmatch(r"\d+", w or ""):
        return int(w)
    if w in ("a", "an", "one"):
        return 1
    if w == "couple":
        return 2
    return UNITS.get(w) if w in UNITS else None


def _date(seg, today):
    t = seg.lower()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _resolve(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else None
        if y is not None and y < 100:
            y += 2000
        if mo > 12 and d <= 12:
            d, mo = mo, d
        if 1 <= mo <= 12:
            return _resolve(y, mo, d, today)
    toks = _date_tokens(t)
    words = set(toks)
    if "day" in words and "after" in words and "tomorrow" in words:
        return (today + datetime.timedelta(days=2)).isoformat(), True
    if "tomorrow" in words:
        return (today + datetime.timedelta(days=1)).isoformat(), True
    if "today" in words or "tonight" in words:
        return today.isoformat(), True
    # 'in two weeks', 'in 3 days', 'a week from today', 'in a fortnight'
    for i, w in enumerate(toks):
        if w not in ("day", "days", "week", "weeks", "fortnight") or i == 0:
            continue
        if not ("in" in toks[max(0, i - 4):i] or toks[i + 1:i + 2] in (["from"], ["time"])):
            continue
        if w == "fortnight":
            days = 14
        else:
            c = _count_word(toks[i - 1])
            if toks[i - 1] == "of" and i > 1 and toks[i - 2] == "couple":
                c = 2
            if not c:
                continue
            days = c * (7 if w.startswith("week") else 1)
        return (today + datetime.timedelta(days=days)).isoformat(), True
    # month name with a day next to it
    for i, w in enumerate(toks):
        if w not in MONTHS:
            continue
        mo = MONTHS[w]
        d, k = None, i + 1
        # '22nd of October', 'the twenty second of October', 'twenty two October'
        pre = toks[max(0, i - 5):i]
        while pre and pre[-1] in ("of", "the"):
            pre.pop()
        for start in range(max(0, len(pre) - 3), len(pre)):
            dd, end = _day_at(pre, start, False)
            if dd is not None and end == len(pre):
                d = dd
                break
        if d is None:
            k2 = i + 1
            while k2 < len(toks) and toks[k2] in ("the", "of"):
                k2 += 1
            dd, end = _day_at(toks, k2, False)
            if dd is not None:
                d, k = dd, end
        if d is None:
            if w == "may" or len(w) == 3:
                continue
            return None, False  # 'sometime in October': ask for the day
        return _resolve(_year_at(toks, k), mo, d, today)
    # a day of month alone: 'the twenty-second', 'on the 22nd'
    for i, w in enumerate(toks):
        marker = i > 0 and toks[i - 1] == "the"
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if marker and not (re.fullmatch(r"\d{1,2}", w) or w in ORD or (w in TENS and nxt in ORD)):
            continue  # 'the one I said' is not a day
        dd, _ = _day_at(toks, i, not marker)
        if dd is not None and (marker or (i + 1 < len(toks) and toks[i + 1] == "#ord")):
            return _next_day_of_month(dd, today)
    for w in toks:
        if w in WEEKDAYS:
            delta = (WEEKDAYS[w] - today.weekday()) % 7 or 7
            return (today + datetime.timedelta(days=delta)).isoformat(), True
    if VAGUE_DATE.search(t):
        return None, False
    return None


def date_from_speech(text, now_iso):
    """Return (ISO date or None, complete). None + False means: ask the caller for a specific day."""
    try:
        today = _today(now_iso)
        for seg in reversed(segments(text)):
            r = _date(seg, today)
            if r is not None:
                return r
    except Exception:
        pass
    return None, False
