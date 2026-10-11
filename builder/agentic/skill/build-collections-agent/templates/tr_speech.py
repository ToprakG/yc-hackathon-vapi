# Turkish customer speech -> digits and English month / weekday words, for the date and amount parsers of calendar.py.
# Paste above your snippet when the brief is Turkish (`import re` first), call it on the customer's words BEFORE parsing:
#   text = tr_norm(vars.get('offer_date_text'))        # 'on dördüncü Mart bin dokuz yüz seksen sekiz' -> '14th march 1988'
# Handles number words (additive: 'yüz elli' = 150, digit runs 'dört dört yedi bir' = 4 4 7 1), suffixes with or without an
# apostrophe ('yirmisinde', 'Kasımda', 'Cumaya'), ordinals ('on dördüncü'), 'ayın X' as a day, 'buçuk' / 'yarım', decimal comma and
# thousands dot ('1.234,50'), 'bugün' / 'yarın'. Never use it on free text answers (names, codes). No double braces.
def tr_norm(text):
    t = str(text or '').replace('İ', 'i').replace('I', 'ı').lower()
    t = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", '', t)
    t = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", '.', t)
    t = re.sub(r"(?<=\w)['’][^\W\d_]+", '', t)
    units = {'sıfır': 0, 'bir': 1, 'iki': 2, 'üç': 3, 'dört': 4, 'beş': 5, 'altı': 6, 'yedi': 7, 'sekiz': 8, 'dokuz': 9}
    tens = {'on': 10, 'yirmi': 20, 'otuz': 30, 'kırk': 40, 'elli': 50, 'altmış': 60, 'yetmiş': 70, 'seksen': 80, 'doksan': 90}
    words = {'ocak': 'january', 'şubat': 'february', 'subat': 'february', 'mart': 'march', 'nisan': 'april', 'mayıs': 'may',
             'mayis': 'may', 'haziran': 'june', 'temmuz': 'july', 'ağustos': 'august', 'agustos': 'august', 'eylül': 'september',
             'eylul': 'september', 'ekim': 'october', 'kasım': 'november', 'kasim': 'november', 'aralık': 'december',
             'aralik': 'december', 'pazartesi': 'monday', 'salı': 'tuesday', 'çarşamba': 'wednesday',
             'perşembe': 'thursday', 'cuma': 'friday', 'cumartesi': 'saturday', 'pazar': 'sunday', 'bugün': 'today',
             'yarın': 'tomorrow', 'lira': 'pounds', 'tl': 'pounds', '₺': '£', 'kuruş': 'pence',
             'tamamı': 'the full amount', 'tamamını': 'the full amount', 'hepsini': 'the full amount',
             'haftaya': 'next week'}
    known = set(units) | set(tens) | set(words) | {'yüz', 'bin', 'milyon'}
    ords = ('inci', 'ıncı', 'uncu', 'üncü', 'nci', 'ncı', 'ncu', 'ncü')
    sufs = ('sinde', 'sında', 'sunda', 'sünde', 'inde', 'ında', 'unda', 'ünde', 'nde', 'nda', 'ini', 'ını', 'unu', 'ünü', 'ine',
            'ına', 'una', 'üne', 'nin', 'nın', 'nun', 'nün', 'den', 'dan', 'ten', 'tan', 'si', 'sı', 'su', 'sü', 'ye', 'ya',
            'yi', 'yı', 'yu', 'yü', 'de', 'da', 'te', 'ta', 'in', 'ın', 'un', 'ün', 'le', 'la', 'e', 'a', 'i', 'ı', 'u', 'ü')

    def stem(w):
        if w in known:
            return w, False
        # a suffixed number is a day ("yirmisinde")
        for suf, ordinal in [(o, True) for o in ords] + [(x, True) for x in sufs]:
            if w.endswith(suf) and len(w) > len(suf):
                st = w[:-len(suf)]
                for cand in (st, st[:-1] + 't' if st.endswith('d') else '', st[:-1] + 'k' if st.endswith('ğ') else ''):
                    if cand in known:
                        return cand, ordinal
        return w, False

    t = re.sub(r"(?<=\d)(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|sinde|sında|sunda|sünde|inde|ında|unda|ünde|nde|nda|si|sı|su|sü|de|da|e|a|i|ı|u|ü)\b", '', t)
    out, total, grp, last, have, ordf, after_ay = [], 0, 0, '', False, False, False

    def osuf(n):
        return 'th' if 10 <= n % 100 <= 20 or n % 10 not in (1, 2, 3) else {1: 'st', 2: 'nd', 3: 'rd'}[n % 10]

    for w0 in re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+|[^\w\s]", t):
        w, isord = stem(w0)
        kind = 'u' if w in units else 't' if w in tens else 'h' if w == 'yüz' else 'b' if w in ('bin', 'milyon') else ''
        if kind:
            if have and ((kind == 'u' and last == 'u') or (kind == 't' and last in ('u', 't'))):
                n = total + grp
                out.append(str(n) + (osuf(n) if ordf and n <= 31 else ''))
                total, grp, ordf = 0, 0, False
            if kind in ('u', 't'):
                grp += units.get(w, tens.get(w, 0))
            elif kind == 'h':
                grp = (grp or 1) * 100
            else:
                total += (grp or 1) * (1000 if w == 'bin' else 1000000)
                grp = 0
            have, last = True, kind
            ordf = ordf or isord or after_ay
            continue
        if have:
            n = total + grp
            out.append(str(n) + (osuf(n) if ordf and n <= 31 else ''))
            total, grp, have, last, ordf = 0, 0, False, '', False
        if w0 == 'buçuk' and out and re.fullmatch(r"\d+", out[-1]):
            out[-1] += '.5'
            continue
        if w0 in ('yarım', 'buçuk'):
            out.append('0.5')
            continue
        if after_ay and w0.isdigit() and int(w0) <= 31:
            out.append(w0 + osuf(int(w0)))
            after_ay = False
            continue
        after_ay = w0 in ('ayın', 'ayının')
        if after_ay:
            continue  # "ayın X" = day X of the month: the number carries the day mark, the word is dropped
        out.append(words.get(w, w0))
    if have:
        n = total + grp
        out.append(str(n) + (osuf(n) if ordf and n <= 31 else ''))
    return ' '.join(out)
