# Test Planı ve Karar Kuralları — Collections Builder

"Gürültü" = baseline'ı 3 kez koşturunca ölçülen 2×SD değeri. Bu eşiğin altındaki farka kazanç denmez.
Takip için: `Test_Plani.xlsx` (aynı içerik + Durum / Gerçek sonuç / Not sütunları).

## 0. Önce ölçülecekler (diğer her şey bunlara bağlı)

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **Baseline × 3** | 2×SD = gürültü eşiği | Bu eşiğin altındaki hiçbir farka "kazanç" denmez. |
| **Lokal yargıç ile Freya verdict uyumu** | ≥ %85 | Lokal simülatör iç döngü olur, Freya yalnızca onaylar. GEPA açılır. |
| | %70–85 | Lokal yalnızca bariz kötüleri eler; sıralama Freya'da yapılır. |
| | < %70 | Lokal yargıç bırakılır, yalnızca Freya verdict'i kullanılır. GEPA iptal. |
| **Unit test skoru ile Freya skoru sıralaması** (5 varyantta) | Spearman ≥ 0.6 | Unit testler varyant eleme ve best-of-K puanlaması için kullanılır. |
| | < 0.6 | Unit testler yalnızca regresyon kontrolü olarak kalır. |

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
| **Best-of-K, unit testlerle puanlanan** (yalnızca Spearman ≥ 0.6 ise) | Self-check'e göre gürültünün üstünde önde | Builder'a eklenir, değerlendirme süre sınırına uyuyorsa. |
| | Eşit | Eklenmez; basit olan kalır. |
| **Best-of-K, simülasyon + yargıçla puanlanan** (yalnızca yargıç ≥ %85 ve builder değerlendirmede simülasyon çalıştırabiliyorsa) | Önde | Eklenir; ardından bir onarım turu denenir. |
| | Eşit | Eklenmez. |

**Genel kural:** En iyiye gürültü içinde yakın olan en basit varyant seçilir.

## 4. Arama ve optimizasyon

| Test | Sonuç | Ne yapılır |
|---|---|---|
| **GEPA-lite agent template'i üzerinde** (yalnızca yargıç ≥ %85 ise; Pareto: brief ve case tipi başına en iyi aday) | En iyi 3 aday Freya'da gürültünün üstünde önde ve sahte brief'lerde düşüş yok | Kurallar template'e birleştirilir. |
| | Lokal skor artıyor ama Freya skoru artmıyor | Yargıç ile Freya uyuşmuyor demektir. GEPA bırakılır. |
| **AFlow-lite** (yalnızca workflow kazandıysa): 3–4 elle yapılmış graf şekli + bir tur LLM düzenlemesi | Bir şekil gürültünün üstünde önde | O graf seçilir. |
| | Eşit | Basit graf kalır. |

**Her durumda yapılır:** Practice'te tekrarlayan hatalar genel kurallara dönüştürülüp builder template'ine eklenir (dersler kütüphanesi).

## 5. Her değişiklik için kabul kapısı

Bir değişiklik ancak üç koşul birlikte sağlanırsa kalıcı olur:
1. Practice'te baseline'dan kötü değil.
2. En az 3 sahte brief'te düşüş yok.
3. Builder tüm sahte brief'lerde hatasız agent üretiyor.

Yalnızca practice brief'te işe yarayan değişiklik reddedilir.
