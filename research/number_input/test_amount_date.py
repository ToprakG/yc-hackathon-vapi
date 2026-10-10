"""F9 check: every amount and promise date in the testbed, rendered the ways the kit's simulated customers say them.

    .venv310/bin/python research/number_input/test_amount_date.py
"""
import collections
import datetime
import glob
import json
import pathlib
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from amount_date import amount_from_speech, date_from_speech  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
TB = ROOT / "testbed"
W = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
     "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENW = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}
ORDW = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth",
        10: "tenth", 11: "eleventh", 12: "twelfth", 13: "thirteenth", 14: "fourteenth", 15: "fifteenth",
        16: "sixteenth", 17: "seventeenth", 18: "eighteenth", 19: "nineteenth", 20: "twentieth", 30: "thirtieth"}
MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
       "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def below100(n):
    if n < 20:
        return W[n]
    return TENW[n // 10] + ("" if n % 10 == 0 else "-" + W[n % 10])


def words(n):
    """1591 -> 'one thousand five hundred and ninety-one'."""
    n = int(n)
    if n == 0:
        return "zero"
    out = []
    if n >= 1000:
        out.append(words(n // 1000) + " thousand")
        n %= 1000
        if 0 < n < 100:
            out.append("and " + below100(n))
            return " ".join(out)
    if n >= 100:
        out.append(W[n // 100] + " hundred")
        n %= 100
        if n:
            out.append("and " + below100(n))
        return " ".join(out)
    if n:
        out.append(below100(n))
    return " ".join(out)


def ordinal(d):
    return ORDW[d] if d in ORDW else TENW[d // 10] + "-" + ORDW[d % 10]


def suffix(d):
    return str(d) + ("th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th"))


def year_words(y):
    return "twenty " + below100(y % 100) if y >= 2010 else words(y)


def amount_renderings(v):
    n, frac = int(v), round(v - int(v), 2)
    cents = int(round(frac * 100))
    digits = (str(n) if not cents else "%.2f" % v)
    R = [("digits", digits), ("digits_symbol", "£" + ("{:,}".format(n) if not cents else "{:,.2f}".format(v))),
         ("words", words(n) + (" point " + " ".join(W[int(c)] for c in str(cents).rstrip("0")) if cents else "")),
         ("words_currency", words(n) + " pounds" + (" " + below100(cents) if cents else "")),
         ("mixed", "{:,}".format(n) + (" pounds " + below100(cents) if cents else " pounds")),
         ("mixed_half", "%d and a half" % n) if cents == 50 else ("mixed_words_digits", words(n) + (" pounds %d" % cents if cents else ""))]
    if 100 <= n < 2000 and n % 100 >= 10 and not cents:
        R.append(("pairs", below100(n // 100) + " " + below100(n % 100)))
    other = n - 50 if n > 60 else n + 20
    R.append(("corrects", "%s, sorry, I mean %s" % (words(other), words(n) + (" pounds " + below100(cents) if cents else ""))))
    R.append(("corrects_digits", "%d, no wait, %s" % (other, digits)))
    return R


def date_renderings(iso, today):
    d = datetime.date.fromisoformat(iso)
    other = d - datetime.timedelta(days=2) if d.day > 3 else d + datetime.timedelta(days=2)
    R = [("digits_iso", iso), ("digits_dmy", d.strftime("%d/%m/%Y")),
         ("words", "the %s of %s" % (ordinal(d.day), MON[d.month - 1])),
         ("words_year", "the %s of %s, %s" % (ordinal(d.day), MON[d.month - 1], year_words(d.year))),
         ("mixed", "%s %s" % (MON[d.month - 1], suffix(d.day))),
         ("mixed_year", "%d %s %d" % (d.day, MON[d.month - 1], d.year)),
         ("corrects", "the %s of %s, sorry, I mean the %s of %s" % (ordinal(other.day), MON[other.month - 1],
                                                                  ordinal(d.day), MON[d.month - 1]))]
    # the day alone, only when the next such day of the month is that date
    nxt = today
    while nxt.day != d.day:
        nxt += datetime.timedelta(days=1)
    if nxt == d:
        R += [("day_only_words", "on the " + ordinal(d.day)), ("day_only_digits", "the " + suffix(d.day))]
    delta = (d - today).days
    if 1 <= delta <= 7:
        R.append(("weekday", "%s works for me" % DAYS[d.weekday()]))
    if delta == 1:
        R.append(("tomorrow", "tomorrow"))
    return R


HARD_AMOUNTS = [
    ("four hundred and fifty-five", 455.0, True), ("two fifty", 250.0, True), ("four fifty-five point five", 455.5, True),
    ("the full amount", None, "full"), ("all of it", None, "full"), ("300, sorry, 350", 350.0, True),
    ("two pounds fifty", 2.5, True), ("£1,591.50", 1591.5, True),
    ("one thousand five hundred and ninety-one pounds and fifty pence", 1591.5, True),
    ("a hundred and twenty", 120.0, True), ("twelve fifty", 1250.0, True), ("four hundred and", 400.0, False),
    ("I've got two kids, but I can do about 300 quid", 300.0, True),
]
NOW = "2026-10-14T10:10"  # a Wednesday
HARD_DATES = [
    ("the twenty-second", "2026-10-22", True), ("Friday", "2026-10-16", True), ("next Friday", "2026-10-16", True),
    ("the twenty-second of October", "2026-10-22", True), ("tomorrow", "2026-10-15", True),
    ("end of the month", None, False), ("the tenth", "2026-11-10", True), ("the 3rd of November", "2026-11-03", True),
    ("22/10/2026", "2026-10-22", True), ("the 20th, sorry, I mean the 22nd", "2026-10-22", True),
    ("in two weeks", "2026-10-28", True), ("sometime next month", None, False), ("2025-01-01", None, False),
]


def main():
    files = sorted(glob.glob(str(TB / "fake_briefs" / "*" / "cases.json"))) + sorted(glob.glob(str(TB / "personas" / "*.cases.json")))
    stats, fails = collections.Counter(), []
    n_amounts = n_dates = 0
    for f in files:
        for c in json.load(open(f)):
            now = c["variables"]["now"]
            today = datetime.date.fromisoformat(now[:10])
            amounts = [p["amount"] for p in c["expected"]["promises"] if isinstance(p.get("amount"), (int, float))]
            for p in c["products"]:
                amounts += [v for k, v in p.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
                            and "day" not in k and "card" not in k and "last4" not in k and v > 0]
            for v in amounts:
                n_amounts += 1
                for label, text in amount_renderings(float(v)):
                    got, ok = amount_from_speech(text)
                    good = ok is True and got == round(float(v), 2)
                    stats[("amount", label, good)] += 1
                    if not good and len(fails) < 30:
                        fails.append((c["id"], "amount", label, text, v, got, ok))
            for p in c["expected"]["promises"]:
                if not p.get("date"):
                    continue
                n_dates += 1
                for label, text in date_renderings(p["date"], today):
                    got, ok = date_from_speech(text, now)
                    good = ok is True and got == p["date"]
                    stats[("date", label, good)] += 1
                    if not good and len(fails) < 30:
                        fails.append((c["id"], "date", label, text, p["date"], got, ok, now))
    hard_ok = 0
    for text, exp, exp_ok in HARD_AMOUNTS:
        got = amount_from_speech(text)
        hard_ok += got == (exp, exp_ok)
        if got != (exp, exp_ok):
            fails.append(("HARD", "amount", text, exp, exp_ok, got))
    for text, exp, exp_ok in HARD_DATES:
        got = date_from_speech(text, NOW)
        hard_ok += got == (exp, exp_ok)
        if got != (exp, exp_ok):
            fails.append(("HARD", "date", text, exp, exp_ok, got))
    tot = sum(stats.values())
    good = sum(v for (k, l, ok), v in stats.items() if ok)
    print("%d amounts and %d promise dates from %d case files" % (n_amounts, n_dates, len(files)))
    print("\n%d/%d renderings handled correctly" % (good, tot))
    by = collections.defaultdict(lambda: [0, 0])
    for (k, l, ok), v in stats.items():
        by[(k, l)][0 if ok else 1] += v
    for key in sorted(by):
        print(key, "ok", by[key][0], "bad", by[key][1])
    print("hard forms: %d/%d" % (hard_ok, len(HARD_AMOUNTS) + len(HARD_DATES)))
    src = (pathlib.Path(__file__).parent / "amount_date.py").read_text()
    braces_ok = "{" + "{" not in src and "}" + "}" not in src
    print("no double braces in amount_date.py:", braces_ok)
    for x in fails:
        print("FAIL", x)
    return 0 if good == tot and hard_ok == len(HARD_AMOUNTS) + len(HARD_DATES) and braces_ok else 1


def test_amount_date_all():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
