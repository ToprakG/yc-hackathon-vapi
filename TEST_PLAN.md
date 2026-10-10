# Test Planı ve Karar Kuralları — Collections Builder

> **Güncelleme (10 Ekim, kit sonrası):** Agent modeli sabit (T1.1 model taraması iptal), skorlama metin (ses deneyleri iptal), çıktı Freya workflow'u olmalı. Builder mimarisi karşılaştırması (A1 / agentic / hybrid) ve güncel öncelikler için **HACKATHON_PLAN.md** esas alınır. İstatistik kuralları, kabul kapısı ve yargıç kalibrasyonu bu dosyada geçerlidir.

Takip için: `Test_Plani.xlsx` (aynı içerik + Durum / Gerçek sonuç / Not sütunları).

## Ön koşul: collections domain klasörü (kickoff'tan önce)

Bu olmadan hiçbir test koşamaz. Gerçek brief 13:00'te gelince sadece bir klasör daha olur; sahte olanlar genelleme seti olur.

- **5+ sahte collections brief'i:** farklı limitler, farklı disclosure kuralları; en az bir **katı** brief, bir **Türkçe** brief, bir **"plan yok"** bankası. Format da farklı olsun (alan isimleri, tool isimleri, eksik bölümler) ki builder'ın format sağlamlığı test edilsin.
- Tool'lar: `verify_identity`, `get_account`, `log_promise_to_pay`, `log_dispute`, `schedule_callback`, `mark_do_not_call`, `transfer_to_human` + mock veri
- Persona kütüphanesi: 16 collections case tipi, her birinde o brief'in policy'sinden doldurulmuş `successCriteria`
- Dört kritik an için unit testler: üçüncü şahıs, belirsiz söz, "beni aramayın", limit dışı plan

## Gürültü ve karar istatistiği

**Aggregate 2×SD kuralı kullanılmaz.** 30 case'te iki konfigürasyonun aggregate farkı için dürüst eşik ~±12–13 puan; tek değişikliklerin çoğu bunu geçemez. Bunun yerine:

1. **Eşleştirilmiş case bazında test.** İki konfigürasyon aynı case'lerde koşar. Her case için A ve B'nin 3 run'daki geçme sayısı (0–3) alınır; case bazında farklara **sign test veya Wilcoxon** uygulanır. Ortak case zorluğu sıfırlanır, efektif gürültü kabaca yarıya iner.
2. **Ayrıştırmayan case'ler karşılaştırma setinden çıkar, ama regresyon kontrolünden çıkmaz.** Her konfigürasyonda 3/3 geçen veya 0/3 kalan case'ler A/B istatistiğine gürültü ekler; karşılaştırma ayrıştıran case'lerde yapılır. Ancak **her iddia edilen kazançta** doymuş case'ler üzerinde (en azından kritik tiplerde: üçüncü şahıs, doğrulama, söz verme) ucuz bir regresyon koşusu yapılır; bir değişiklik hep geçen bir case'i kırabilir.
3. **Gürültü varsayılmaz, ölçülür.** Baseline × 3, case başına gerçek run-to-run varyansı verir. Collections case'leri çoğu zaman neredeyse deterministiktir; gerçek gürültü binom tahmininin altında olabilir.
4. **Az ve cesur deney.** Değişiklikler paket halinde test edilir (Tier 1 paketi, P1). Paket kaybederse bölünür.
5. **Büyük suite en son ve sadece lokalde.** Lokal yargıç kalibrasyonu geçerse brief başına 60–90 lokal varyant. Geçmezse hassasiyet hacimden değil, eşleştirilmiş test + ayrıştıran case'lerden alınır.

6. **Çoklu test düzeltmesi: her kazanç bir kez yeniden koşulur.** 15–20 testte p < 0.1 ile 1–2 sahte kazanç beklenir. Bu yüzden her kazanç, kilitlenmeden önce **taze run'larla bir kez daha** koşulur; özellikle prompt'u büyüten değişikliklerde zorunlu.

**Tanımlar (tüm tablolarda bunlar kastedilir):**
- **Karşılaştırma her zaman *mevcut en iyi* konfigürasyona karşı yapılır, baseline'a karşı değil.** "Baseline'dan kötü değil" kuralı, kabul edilen değişiklikler boyunca küçük regresyonların birikmesine izin verir.
- **Kazanç ("gürültünün üstünde önde")** ⇔ mevcut en iyiye karşı eşleştirilmiş testte p < 0.1 **ve** taze run'larla tekrarında yön korunuyor **ve** hiçbir kritik case tipinde düşüş yok.
- **Düşüş** ⇔ aynı eşleştirilmiş testte, o case tipinde p < 0.1 ile kötüleşme. (Tek bir run'da bir case'in kalması "düşüş" değildir; gürültü iyi değişiklikleri veto etmesin.)
- **Eşit** ⇔ eşleştirilmiş testte anlamlı fark yok.

## 0. Önce ölçülecekler (diğer her şey bunlara bağlı)

Sıra: practice baseline × 3 → **yargıç uyum kontrolü** → dal seçimi. Uyum ancak ilk collections practice run'ları Freya verdict'iyle döndükten sonra ölçülebilir.

### Lokal yargıç = decision model

Lokal yargıç olarak **decision model** kullanılır: her kontrol, tek bir transcript hakkında tek bir evet/hayır kararı ("Doğrulama tamamlanmadan tutar söylendi mi?", "Müşteri belirli bir tarih ve tutar üzerinde anlaştı mı?").
- Serbest metin gerekçe yazan bir LLM yargıcından **daha tutarlı** karar verir → daha az gürültü → A/B ve best-of-K daha az run'la gerçek farkı gösterir.
- Ucuz ve hızlı → aynı sürede çok daha fazla karşılaştırma.
- Phrase-matching / regex kontrollerinin **tamamının yerini alır**.
- Bir case'in sonucu = o case'in tüm kontrollerinin AND'i (Freya'nın successCriteria + assertion mantığıyla aynı).
- **Kısıt:** Teslim edilen builder, kurallar değerlendirme sırasında dış API çağrısına izin verdiğini teyit etmedikçe decision model'e bağımlı olmaz. Aksi halde decision model sadece dev'de (yargıç, best-of-K puanlama dev'de) kullanılır.
- **Agent içinde:** sadece Freya workflow'ları dallanma kararını bir modele bıraktırıyorsa ("kimlik geçti mi?", "anlaştılar mı?") — o noktalarda decision model vs varsayılan LLM ayrıca karşılaştırılır.

**Uyum ölçülmeden önce yargıç düzeltilir** (bilinen sebepten fail etmesin; dünkü yargıç agent'ın kendi eylemleri konusunda fazla gevşekti):
- Decision model'e transcript'le birlikte **tool-call log** verilir.
- Agent'ın **eylemleri** sözlerinden ayrı sorulur: "`log_promise_to_pay` tarih ve tutarla çağrıldı mı?", "Doğrulama başarılı olmadan herhangi bir tutar söylendi mi?"
- Her kontrol için tek bir evet/hayır kararı, sıcaklık 0, serbest metin verdict yok.
- Kontrol soruları her brief için Policy'den üretilir (case tipi × kural).
- Uyum **case tipi bazında** raporlanır; aggregate %85 olup üçüncü şahıs case'leri %60'ta kalabilir.
- **Uyum < %85 ise** decision model sadece dev triage için kalır, karar Freya verdict'iyle verilir (aşağıdaki fallback dalı).

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **Baseline × 3** | Case başına run-to-run varyansı | Ayrıştıran case seti ve eşleştirilmiş test için temel. Cache'lenir, ortam değişmedikçe tekrar koşmaz. |
| **Lokal yargıç ile Freya verdict uyumu** | ≥ %85 genelde **ve** üçüncü şahıs / doğrulama / söz verme case'lerinde | Lokal simülatör iç döngü olur, Freya yalnızca onaylar. Bölüm 3–4'ün tamamı açılır. |
| | Bunun altında | **Fallback dalı:** bölüm 3'ün simülasyonlu kısımları (best-of-K, onarım turu) ve bölüm 4'ün tamamı düşer. Sadece Freya: builder-prompt düzeltmeleri + dersler kütüphanesi + ayrıştıran case'lerde eşleştirilmiş test. Lokal yargıç sadece dev triage için kalır. |
| **Unit test skoru Freya ile aynı kazananı seçiyor mu?** (A/B çiftlerinde ikili sıralama uyumu, ≥ 8 çift; 5 varyantlık Spearman anlamsız) | Çiftlerin ≥ %80'inde aynı kazanan | Unit testler varyant eleme ve best-of-K puanlaması için kullanılır. |
| | Bunun altında | Unit testler yalnızca regresyon kontrolü olarak kalır. |

## 1. Büyük kaldıraçlar

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **Agent modeli taraması** (seçilebiliyorsa) | En iyi model gürültünün üstünde önde | O model kilitlenir, tüm testler onunla sürer. |
| | Fark gürültü içinde | Daha düşük gecikmeli ya da ucuz olan seçilir. |
| **Tek çağrılık builder mi, extract → template mi** | Template ≥ tek çağrı (eşit bile olsa) | Template seçilir; final başka bir bankanın brief'i olacak. |
| | Tek çağrı practice'te kazanıyor ama sahte brief'lerde kaybediyor | Yine template. |
| | Tek çağrı her yerde kazanıyor | Tek çağrı tutulur; template onun çıktısından öğrenilerek yeniden yazılır. |
| **Sabit uyumlu açılış mı, generic açılış mı** | Disclosure ve üçüncü şahıs case'leri iyileşiyor, genel skor düşmüyor | Sabit açılış kalıcı olur. |
| | Genel skor düşüyor | Açılış kısaltılır, yalnızca brief'in zorunlu kıldığı ifadeler bırakılır. |
| **Kimlik doğrulama: prompt kuralı mı, yapısal adım mı** (üçüncü şahıs, yanlış kişi ve doğrulayamayan case'leri ayrı ölçülür) | Bu grupta yapısal adım daha iyi, genel skor düşmüyor | Yapısal adım seçilir. |
| | Yapısal adım doğru kişiyle akışı bozuyor | Prompt kuralı tutulur, kritik an unit testle korunur. |
| **Tool açıklamaları: ham mı, yeniden yazılmış mı** | Unit testler iyileşiyor, simülasyon düşmüyor | Yeniden yazılmış açıklamalar kalıcı olur. |
| | Değişiklik yok | Yeniden yazılmış kalır; zararsız ve sahte brief'lerde koruyucu. |
| **Müşteri verisi: prompt'a sabit mi, tool ile mi** | Yanlış tutar/tarih hatası azalan taraf | O seçilir. |
| | Eşit | Sabitleme seçilir, ama yalnızca kimlik testi üçüncü şahsa sızıntı göstermiyorsa. |
| **Tek prompt mu, workflow mu** (API varsa, 2 saatlik zaman kutusu) | Workflow gürültünün üstünde önde | Workflow seçilir, AFlow-lite açılır. |
| | Eşit | Tek prompt kalır, daha az hata noktası. |
| | Deploy ya da routing hatalı (flaky) | Workflow tamamen bırakılır. |

**Test edilmeyenler:** Builder'da en iyi frontier model kullanılır, agent sıcaklığı 0–0.3'e sabitlenir. Bunlara run harcanmaz.

## 2. Davranış paketi (tek tek değil, paket halinde)

Önce practice'teki yargıç gerekçeleri kümelenir. En sık 5–8 başarısızlık tipi paketin içeriğini belirler.

**P1 paketi:** yaptığını yüksek sesle söyleyip kapatmadan önce loglamak, kapanış kontrol listesi, söz verme anında tekrar edip tool çağırmak, zorluk/itiraz/aramama talebinde yönlendirip bitirmek, 1–2 cümlelik turlar, kuralların çağrı sırasında olması, tool hatasında onay uydurmamak, konu değişse de doğrulama durumunu korumak.

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **P1 mi, mevcut en iyi mi** | P1 gürültünün üstünde önde | P1 kilitlenir. Yalnızca prompt'u %30'dan fazla uzatan maddeler tek tek çıkarılıp test edilir. |
| | Eşit | Paket ikiye bölünür, hangi yarının zarar verdiği bulunur (ikili arama). |
| | P1 geride | İkili aramayla bir şeyi kıran madde bulunup çıkarılır. |

**Paketten sonra, run kaldıysa tek tek test edilir:**

| Test | Ne yapılır |
|---|---|
| **Müzakere sırası: önce tam ödeme mi, direkt plan mı** | İlgili case'lerde kazanan sıra builder kuralı olur. |
| **Plan limitleri: tablo mu, cümle mi** | Yanlış tutar hatasını azaltan seçilir. |
| **Örnek diyaloglar mı, hiç örnek yok mu** | Kazanç gürültünün altındaysa örnekler çıkarılır; prompt kısa kalır. |
| **Türkçe brief'e İngilizce talimat mı, Türkçe talimat mı** | Kazanan dil builder'ın varsayılanı olur. |
| **Belirsiz kurala muhafazakâr okuma mı, serbest okuma mı** | Kazanan okuma builder'ın genel kuralı olur. |

## 3. Builder süreci

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **Self-check** (kural kural kontrol + onarım, simülasyonsuz) | Practice'te ve sahte brief'lerde düşüş yok | Kalıcı olur. |
| | Düşüş var | Onarım adımı kapatılır, yalnızca eksik raporu bırakılır. |
| **Best-of-K, unit testlerle puanlanan** (yalnızca ikili sıralama uyumu ≥ %80 ise ve değerlendirme süre sınırı izin veriyorsa) | Self-check'e göre gürültünün üstünde önde | Builder'a eklenir, değerlendirme süre sınırına uyuyorsa. |
| | Eşit | Eklenmez; basit olan kalır. |
| **Best-of-K, simülasyon + yargıçla puanlanan** (yalnızca yargıç ≥ %85 ve builder değerlendirmede simülasyon çalıştırabiliyorsa) | Önde | Eklenir; ardından bir onarım turu denenir. |
| | Eşit | Eklenmez. |

**Genel kural:** En iyiye gürültü içinde yakın olan en basit varyant seçilir.

## 4. Arama ve optimizasyon

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **GEPA-lite agent template'i üzerinde** (yalnızca yargıç uyumu **≥ %90** ise — binlerce run yapan bir optimizer yargıcın kaçırdığı her şeyi bulur, bu yüzden %85 yetmez; Pareto: brief ve case tipi başına en iyi aday) | En iyi 3 aday Freya'da gürültünün üstünde önde ve sahte brief'lerde düşüş yok | Kurallar template'e birleştirilir. |
| | Lokal skor artıyor ama Freya skoru artmıyor | Yargıç ile Freya uyuşmuyor demektir. GEPA bırakılır. |
| **AFlow-lite** (yalnızca workflow kazandıysa): 3–4 elle yapılmış graf şekli + bir tur LLM düzenlemesi | Bir şekil gürültünün üstünde önde | O graf seçilir. |
| | Eşit | Basit graf kalır. |

**Her durumda yapılır:** Practice'te tekrarlayan hatalar genel kurallara dönüştürülüp builder template'ine eklenir (dersler kütüphanesi).

## 5. Her değişiklik için kabul kapısı

Bir değişiklik ancak dört koşul birlikte sağlanırsa kalıcı olur:
1. Practice'te **mevcut en iyiden** kötü değil (yukarıdaki "düşüş" tanımıyla) ve taze run'larla tekrarında da öyle.
2. **En az 3 sahte brief'te** düşüş yok (5+ brief'ten).
3. Doymuş case'lerin kritik tiplerinde regresyon koşusu temiz.
4. Builder tüm sahte brief'lerde hatasız agent üretiyor.

Yalnızca practice brief'te işe yarayan değişiklik reddedilir.

## 6. Değerlendirme anı kısıtları (Faz 0'da öğrenilir, bölüm 3'ü belirler)

| Soru | Cevaba göre |
|---|---|
| Builder'ın değerlendirmede süre sınırı ne? | Best-of-K ve onarım turu bu süreye sığmıyorsa bölüm 3'ün o satırları düşer. |
| Builder değerlendirmede Freya simülasyonu / dış API çağırabilir mi? | Hayırsa: simülasyonla puanlanan best-of-K ve decision model sadece dev'de. |
| Builder kaç kez çağrılıyor, her brief için ayrı mı? | Maliyet ve timeout bütçesini belirler. |

## 7. Sağlamlık ve teslim (deney değil, skoru korur)

- **Tuhaf brief'ler:** eksik alan, çelişkili kural, açıklamasız tool, farklı alan/tool isimleri → builder makul ve muhafazakâr varsayılanla doldurur, çökmez.
- **Timeout + retry** her API çağrısında; builder herhangi bir adımda patlarsa **fallback agent** (son bilinen iyi template, brief'ten minimum extraction) deploy edilir.
- Pinned bağımlılıklar, tek komutla çalışma.
- **Temiz klon testi:** diğer kişinin makinesinde sıfırdan kurulum + tüm sahte brief'lerde koşu.
- **Erken submit:** çalışan bir versiyon ilk gün sonunda / ikinci gün öğlene kadar submit edilir; sonrası sadece kabul kapısını geçen iyileştirmeler.

## 8. Bölüm başına zaman bütçesi (bölüm 4 ikinci günü yemesin)

| Bölüm | Bütçe | Aşılırsa |
|---|---|---|
| Ön koşul + 0 (altyapı, baseline, yargıç kalibrasyonu) | ~4 saat | Kalibrasyon bitmediyse fallback dalına geç, beklemeyi bırak. |
| 1 (büyük kaldıraçlar) | ~5 saat | Kalan testleri paketle tek seferde koş. |
| 2 (davranış paketi) | ~4 saat | Tek tek testleri atla. |
| 3 (builder süreci) | ~3 saat | Self-check'te dur. |
| 4 (arama) | **Sadece gece koşusu + sabah ~2 saat onay** | Gün içinde zaman almaz; sabah onayı geçmeyen sonuç atılır. |
| 7 (sağlamlık + teslim) | ~4 saat, **ikinci gün öğleden önce başlar** | Kesilmez. |
