"""Spoken texts built in code, per language. The workflow is written in English; for another language the generated
code and the fixed spoken lines go through `localize` (exact-substring pairs), so nothing is spoken in the wrong language.
Lines taken from the brief are never touched. Values (names, amounts, dates) are not part of any pair."""

from __future__ import annotations

SUPPORTED = ("tr",)

TR_WEEKDAYS = "['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']"
TR_MONTHS = ("['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', "
             "'Aralık']")

# (english, turkish): longest first at apply time. Placeholders in the English text are kept as they are.
TR = [
    # identity step
    ("'Thank you. ' + pr", "'Teşekkür ederim. ' + pr"),
    ("'Could you say that again? ' + pr", "'Rica etsem tekrar eder misiniz? ' + pr"),
    ("'Sorry, I could not read that. ' + pr", "'Pardon, bunu anlayamadım. ' + pr"),
    ("'The check did not go through. ' + pr", "'Doğrulama tamamlanamadı. ' + pr"),
    ("'That answer does not match. ' + pr", "'Bu yanıt eşleşmedi. ' + pr"),
    ("'Sorry, I did not catch that. '", "'Pardon, anlayamadım. '"),
    ("'Thank you. Could you give me the rest of that, please?'", "'Teşekkür ederim. Devamını da söyler misiniz?'"),
    ("'Let us try that once more. '", "'Bir kez daha deneyelim. '"),
    # closing and fallbacks
    ("'Goodbye.'", "'İyi günler.'"),
    ("I am sorry, I could not complete that because of a system problem.", "Özür dilerim, bir sistem sorunu nedeniyle bunu tamamlayamadım."),
    ("Thank you, we will call back then.", "Teşekkür ederim, o zaman sizi tekrar arayacağız."),
    ("I am connecting you with a colleague now.", "Şimdi sizi bir meslektaşımıza bağlıyorum."),
    ("I am connecting you with our support team now.", "Şimdi sizi destek ekibimize bağlıyorum."),
    ("Sorry for the trouble.", "Rahatsızlık için özür dilerim."),
    ("Could you tell me when {first_name} {last_name} can be reached?", "{first_name} {last_name} hangi zaman ulaşılabilir, söyler misiniz?"),
    ("Could you tell me when they can be reached?", "Hangi zaman ulaşılabilir olduklarını söyler misiniz?"),
    ("' Could you give me another time?'", "' Başka bir zaman söyler misiniz?'"),
    ("'Which day and time would suit?'", "'Hangi gün ve saat uygun olur?'"),
    ("'We can call back '", "'Şu zamanlarda tekrar arayabiliriz: '"),
    ("' or '.join(parts)", "' veya '.join(parts)"),
    ("rel = 'today' if d == today else ('tomorrow' if", "rel = 'bugün' if d == today else ('yarın' if"),
    ("', from ' + a['start'] + ' to ' + a['end']", "', ' + a['start'] + ' ile ' + a['end'] + ' arası'"),
    # promise check
    ("'On which day exactly would you like to pay it?'", "'Tam olarak hangi gün ödemek istersiniz?'"),
    ("'The date I can record is ' + spoken(datetime.date.fromisoformat(r['att1'])) + '. Could you pay on that date?'",
     "'Kaydedebileceğim tarih ' + spoken(datetime.date.fromisoformat(r['att1'])) + '. O tarihte ödeyebilir misiniz?'"),
    ("'The latest date I can record is ' + spoken(dl) + '. Could you pay on that date?'",
     "'Kaydedebileceğim en geç tarih ' + spoken(dl) + '. O tarihte ödeyebilir misiniz?'"),
    ("'Which amount would you like to pay?'", "'Hangi tutarı ödemek istersiniz?'"),
    ("'I cannot record less than ' + money(floor) + '. Could you pay that amount?'",
     "money(floor) + ' tutarından azını kaydedemiyorum. Bu tutarı ödeyebilir misiniz?'"),
    ("'The amount owed is ' + money(past) + ', so I cannot record more than that. Could you pay ' + money(past) + '?'",
     "'Borç tutarı ' + money(past) + ', bundan fazlasını kaydedemiyorum. ' + money(past) + ' ödeyebilir misiniz?'"),
    ("'I need a date from today on. The next business day is ' + spoken(bd_on_or_after(today, hol)) + '. Would that work?'",
     "'Bugünden itibaren bir tarih gerekiyor. Bir sonraki iş günü ' + spoken(bd_on_or_after(today, hol)) + '. Bu uygun olur mu?'"),
    ("'That day is not a business day. The next business day is ' + spoken(nb) + '. Would that work?'",
     "'O gün iş günü değil. Bir sonraki iş günü ' + spoken(nb) + '. Bu uygun olur mu?'"),
    ("vars['rb_text'] = money(amt) + ' on ' + spoken(d)", "vars['rb_text'] = spoken(d) + ' günü ' + money(amt)"),
    ("'So that is ' + money(amt) + ' on ' + spoken(d) + ' for ' + r['label'] + '. ' + str(CFG['lines'].get('confirm_question') or 'Shall I record that?')",
     "'Yani ' + r['label'] + ' için ' + spoken(d) + ' günü ' + money(amt) + '. ' + str(CFG['lines'].get('confirm_question') or 'Bunu kaydedeyim mi?')"),
    ("'I could not save that because of a technical problem.'", "'Teknik bir sorun nedeniyle bunu kaydedemedim.'"),
    # attempt ladder
    ("'Could you pay the minimum amount of ' + money(p['floor']) + ' on ' + pr['spoken'] + '? The rest would stay overdue.'",
     "pr['spoken'] + ' günü en az ' + money(p['floor']) + ' ödeyebilir misiniz? Kalanı gecikmiş olarak kalır.'"),
    ("'Could you pay the full amount of ' + money(p['past_due']) + ' on ' + pr['spoken'] + '?'",
     "pr['spoken'] + ' günü tutarın tamamını, ' + money(p['past_due']) + ', ödeyebilir misiniz?'"),
    # spoken debt statement
    ("'Your ' + r['label'] + ': ' + money(r['past_due']) + ' past due, ' + str(r['days']) + ' days late.'",
     "r['label'] + ': ' + money(r['past_due']) + ' gecikmiş, ' + str(r['days']) + ' gün gecikme.'"),
]


def localize(code: str, lang: str) -> str:
    """Code or data text -> the language's spoken texts. Unknown language: unchanged."""
    if lang not in SUPPORTED:
        return code
    for en, tr in sorted(TR, key=lambda p: -len(p[0])):
        code = code.replace(en, tr)
    code = code.replace("WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']",
                        "WEEKDAYS = " + TR_WEEKDAYS)
    a = code.find("MONTHS = ['January'")
    if a >= 0:
        b = code.index("]", a) + 1
        code = code[:a] + "MONTHS = " + TR_MONTHS + code[b:]
    return code


SYSTEM_RULE = {"tr": "Always speak Turkish, in a natural and polite way, addressing the customer with the formal 'siz' form. "
                     "Say dates and amounts the Turkish way, for example '22 Ekim Perşembe'. Never answer in English."}


# Fallback lines, used only when the brief does not state the line (a stated line is always kept as it is).
TR_LINES = {
    "condolence": "Başınız sağ olsun.",
    "debt_intro": "Geciken bir ödeme nedeniyle arıyorum.",
    "first_ask": "Bu tutarı bugün ödeyebilir misiniz?",
    "first_ask_multi": "Bunların hepsini bugün ödeyebilir misiniz?",
    "confirm_question": "Onaylıyor musunuz?",
    "ai": "Ben dijital bir asistanım.",
    "scam": "Bu aramayı doğrulamak için bankayı arayabilirsiniz.",
    "failed_id": "Doğrulama olmadan devam edemiyorum.",
    "paid_reply": "Teşekkür ederim. Bir ödemenin hesapta görünmesi biraz zaman alabilir.",
    "change_promise": "Kaydedilmiş bir söz bu görüşmede değiştirilemez.",
    "cannot_record": "Üzgünüm, bunu kaydedemedim.",
    "no_info": "Bu bilgiye sahip değilim.",
    "id_reason": "Bu sorular hesabınızı korumak içindir.",
    "hardship_sympathy": "Bunu duyduğuma üzüldüm.",
    "hint_retry": "Rica etsem bir seferde bir parça olacak şekilde tekrar eder misiniz?",
    "goodbye": "Zaman ayırdığınız için teşekkür ederim. İyi günler.",
    "promise_confirmation": "Sözünüz kaydedildi.",
}
TR_LINES_ADDR = {"right_party_question": "{addr} ile mi görüşüyorum?", "right_party_question_none": "Hesap sahibi ile mi görüşüyorum?",
                 "opening": "Merhaba, {opening}", "opening_none": "Merhaba."}
TR_NO_DISCOUNT = "Tutarı düşüremem."
TR_HARDSHIP_OFFER = "Sizi destek ekibine bağlamamı ister misiniz?"
