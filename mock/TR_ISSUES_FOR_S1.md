# Turkish issues from OUR self-test transcripts (local dress run 2, 5/10) — for S1
Source: out/dress2_local/build/r0/selftest/transcripts (our own scenarios, not GATE). Turn numbers = judge's "Message N" (user/assistant turns only). `scripts/failed_turns.py` prints them.

1. ST-02 identity_failed — number words read as a PARTIAL answer, so the 3rd wrong answer is never counted and the check does not end.
   #10 user "Bin iki yüz elli yedi." -> #11 assi "Teşekkür ederim. Devamını da söyler misiniz?" (asks for "the rest"); #8 user "Telefon numaramın son dört hanesi" (a field name, not a value) was taken as a DOB attempt.
   Expect: a spoken 4-digit/ year number is a complete (wrong) answer; "Bu yanıt eşleşmedi" counts toward max_wrong; after the 3rd: end + app/branch line.
2. Opening: "Mr Lindqvist ile mi görüşüyorum?" — English title in Turkish (known; yours).
3. Debt line is telegraphic and starts lowercase: "Gecikmiş bir ödeme nedeniyle tahsilat ekibinden arıyorum. taşıt kredisi: 1.100,00 TL gecikmiş, 7 gün gecikme. Bu ödemeyi bugün yapabilir misiniz?" (ST-01/06/08). Make it a sentence ("Taşıt krediniz için 1.100,00 TL tutarında, 7 gündür gecikmiş bir ödemeniz var.").
4. Fragment order, ST-07 #9: "Tam olarak hangi gün ödemek istersiniz? Anlıyorum, taşıt kredisi ödemenizi gerçekleştirebilirsiniz." (acknowledgement AFTER the question). ST-08 #11: "235,00 TL tutarından azını kaydedemiyorum. Bu tutarı ödeyebilir misiniz? Anlıyorum, ancak belirttiğiniz tutar minimum limitimizin altında kalıyor." (reason after the ask).
5. ST-06 #9: "Kısmi ödeme talebinizi not aldım ancak ... tamamının kapatılması gerekmektedir." — "not aldım" reads as accepting; the brief wants "bu tutarı kaydedemiyorum" + the floor offer.
(Not Turkish: ST-07 deadline 25 Kasım looks computed from max_days (45) instead of deadline_business_days -> logic; ST-08 hardship closes as "refused" and the floor is offered after hardship -> logic.)
