# T-CC: mimari, test skorları ve durum raporu

Tarih: 10 Ekim 2026, 21:10 · Repo: `yc-hackathon-vapi` · Push edildiği yer: `yc_hackathon_first_day` (`main`), `yc_template_claude_code`

T-CC, bankanın brief'ini ve tool API'sini okuyup Freya üzerinde tahsilat (collections) telefon ajanı kuran bir **builder**. Adı "Template + Claude Code": deterministik bir şablon derleyici ile Claude Code'u (Agent SDK) birleştiriyor. Claude Code burada politika denetçisi ve yama yazan olarak çalışıyor.

---

## 1. Özet

| | |
|---|---|
| **Ana skor** (9 brief × 10 testbed personası, Freya simülasyonu, banka kaydı + Freya hakemi) | **59/90 (%66)** |
| Aynı vakalar, banka kaydı + **local judge** (Judge C / Jev) | **44/90 (%49)** |
| Kitin pratik vakalarında Brief A (sağlıklı platformda) | **8/10** (kitin örnek builder'ı: 6/10) |
| Offline test paketi | **293 test, hepsi geçiyor** |
| Build süresi / maliyeti (brief başına) | 2,5–3,5 dk, ~$0,20 (OpenRouter) + Claude Code aboneliği |
| Lint | Derlenen her workflow (9 testbed brief'i + fixture) **0 hata** |

**En zayıf aileler:** Tutarlar (3/9), İnsan talebi (4/9), Tarihler (5/9). **En güçlüsü:** Vefat (9/9).

---

## 2. Mimari

```
brief(ler) + tool API (openapi.json)
  │
  ├─ 1. EXTRACT (LLM, 2 geçiş + 1 düzeltme turu) ──► policy.raw.json
  │      policy_check: şema, API enum'ları, tatiller, bantlar, callback penceresi, brief alıntıları (deterministik)
  │      çözülemeyen değerlere muhafazakâr varsayılanlar
  │
  ├─ 2. BASELINE COMPILE (saf kod) ──► workflow.baseline.json   (her zaman bir yedek vardır)
  │
  ├─ 3. POLICY AUDIT: Claude Code, izole geçici workspace'te policy.json'ı brief'e karşı denetler
  │      → her öneri PATCH JUDGE'tan geçer (deterministik kontroller + karar modeli) → kabul edilenler uygulanır
  │
  ├─ 4. COMPILE (saf kod, deterministik) ──► workflow.json + zones.json
  │
  ├─ 5. SELF-TEST LOOP (isteğe bağlı, --self-test local)
  │      testgen: KENDİ politikamızdan vakalar (testbed verisi asla okunmaz) → train/heldout (2:1)
  │      runner: build-the-builder mock bank + LLM müşteri (DeepSeek v4.1) + local judge (Jev)
  │      unit-test kapısı: Freya unit testleri (tek turluk, politikadan üretilir) → kıran aday elenir
  │      analyzer (LLM): başarısızlıklar → genel hatalar + kanıt turları
  │      patcher = Claude Code: yalnızca kilitsiz prompt bölgelerine yama; run_sims aracıyla yamasını dener
  │      patch judge: gerekli mi / brief destekliyor mu / brief'le çelişiyor mu / vakaya özel mi / gereksiz mi / doğru yer mi
  │      kapı: heldout'ta eşleştirilmiş sign testi (p < 0,1) + hiç tam-geçen vaka bozulmayacak → tut ya da at
  │
  └─ 6. FINALIZE: lint, Freya validate (dry run), save_workflow + export_workflow, build_report.json, trace
```

### 2.1 Derlenen telefon ajanının akışı (graph)

```
start (sessiz, kodsuz) → opening (sabit açılış cümlesi, tts) → [müşterinin ilk cevabı] → setup (kod: tarih, callback penceresi, varsayılan kapanış)
  ├─ müşteri → identity (verify_identity; normalize eden pre-hook; durum yazan post-hook) → identity_explain (1 kez açıklama)
  │     └─ geçti → fetch_account (+ retry) → facts (kod: bant, son tarih, deneme önerileri, 21 günlük tarih tablosu)
  │           └─ negotiate (create_promise; okuma + açık evet; çift söz koruması)
  │                 yan yollar: hardship, dispute/zaten ödedi, yeniden yapılandırma, insan talebi, konuşmak istemiyor,
  │                 ürün başına reddetme (tool-call geçişi), transition_to_wrap (görüşmeyi bitirme)
  ├─ üçüncü kişi → third_party (schedule_callback; "bugün/yarın" isimli pencere)
  ├─ yanlış numara / vefat / belirsiz → mark_* (kapanış anahtarı)
  └─ wrap (kod: açık ürünler → reddedildi, not kuyruğu, kapanış cümlesi) → note_next ⇄ note_write → end
global: g_ai, g_scam (sabit cevap → geri dön), g_human (bir kez "ben yardım edeyim mi"), g_goodbye (döngü önleyici)
close_call: workflow seviyesinde lifecycle tool (end_of_call), pre-hook durumdan sonucu hesaplar; telefon kapansa da kayıt düşer
```

### 2.2 Yama bölgeleri (zones)
- **Kilitsiz (yama yapılabilir):** her adımın `rules` ve `examples` bölümü, system prompt `global_rules`, model-facing tool açıklamaları, `what_to_do_next` mesajları, intent açıklamaları, extraction açıklamaları.
- **Kilitli:** tüm kod, URL'ler, enum'lar, koşullar, graph, brief'in birebir cümleleri, hesaplanan facts.
- **Bütçe:** bölge başına karakter sınırı, iterasyon başına toplam metin en fazla +%15.

### 2.3 Cevap anahtarı izolasyonu
- Builder yalnızca brief + tool API okur.
- Testbed `config.json`/`cases.json`, `oracle` ve `public-test-set.json` builder'a hiç girmez; yalnızca dışarıdaki değerlendirme scriptleri kullanır.
- Claude Code oturumları repo dışında, geçici bir workspace'te çalışır. PreToolUse guard'ı yolları ve isimleri kısıtlar, yazma yalnızca `out/`'a izinli.
- No-leak testi: testbed ve Brief A/B'deki banka adları, tarihler, enum'lar ve 6+ kelimelik cümleler `builder/template_cc/**` içinde aranır; çıkmaması gerekir.

### 2.4 Dosyalar (`builder/template_cc/`)
| Dosya | Görev |
|---|---|
| `run.py` | CLI ve orkestrasyon (`python3 -m builder.template_cc.run <brief...> <tools.openapi.json>`) |
| `extract.py`, `policy_check.py`, `policy.schema.json` | Çıkarım ve deterministik doğrulama |
| `compiler/` (`graph.py`, `prompts.py`, `runtime.py`, `snippets.py`, `tools.py`) | Şablon derleyici |
| `zones.py`, `patches.py` | Yama bölgeleri, yama uygulama, büyüme bütçesi |
| `audit.py`, `patcher.py`, `session.py`, `guard.py` | Claude Code oturumları (Agent SDK), MCP araçları, guard |
| `judge.py`, `judge_agreement.py` | Patch judge (build-the-builder karar modeli Jev + yerel yedek) |
| `analyze.py`, `testgen.py`, `loop.py`, `gate.py`, `runner.py` | Self-test döngüsü |
| `vendor_runner.py`, `vendor_worker.py`, `vendor_bankd.py` | build-the-builder test altyapısı (mock bank, chat driver, local judge) |
| `unittests.py` | Freya unit test kapısı |
| `sims.py` | Zor simülasyonlar (DeepSeek müşteri), `run_sims` aracı |
| `llm.py` | Anthropic / OpenAI / OpenRouter (stdlib, `.venv310` için port) |

Değerlendirme scriptleri (`scripts/`): `tcc_eval_freya.py` (Freya sim + local judge), `tcc_eval_testbed.py` (sohbet + local judge), `tcc_shared_bank.py` (tek banka + tek tünel), `tcc_dashboard.py` (canlı dashboard, http://127.0.0.1:8900).

---

## 3. Test skorları

### 3.1 Testbed personaları: Freya simülasyonu (9 brief × 10 vaka, ailelere yayılmış örnek)

| Brief | Tür | Banka kaydı + Freya hakemi | Banka kaydı + local judge |
|---|---|---|---|
| brief-a | kit, tek ürün | **8/10** | 5/10 |
| brief-b | kit, çok ürün | **6/10** | 4/10 |
| f1-nordhavn | temiz, 3 bant | **6/10** | 5/10 |
| f2-ostral | temiz, 3 kimlik sorusu | **7/10** | 6/10 |
| f3-kestrel | çok ürün, öncelik sırası | **7/10** | 5/10 |
| f4-brightwell | kurumsal müşteri | **6/10** | 4/10 |
| f5-halden-email | ham e-posta zinciri | **4/10** | 3/10 |
| f6-corvid-memo | politika + memo değişikliği | **7/10** | 7/10 |
| f7-lumen-codes | kod listesi, close_call tek kod | **8/10** | 5/10 |
| **Toplam** | | **59/90 (%66)** | **44/90 (%49)** |

### 3.2 Aile bazında (Freya hakemi, 9 brief)

| Aile | Skor |
|---|---|
| Tutarlar (Amounts) | 3/9 |
| İnsan talebi | 4/9 |
| Tarihler (Dates) | 5/9 |
| İtiraz | 6/9 |
| Mutlu yol | 6/9 |
| Zor durum | 6/9 |
| Kimlik | 6/9 |
| Zaten ödedi | 7/9 |
| Kimliği reddetme | 7/9 |
| Vefat | 9/9 |

### 3.3 Kitin pratik vakaları (Brief A 10, Brief B 3; Freya simülasyonu)

| Koşu | Brief A | Brief B | Not |
|---|---|---|---|
| 1 (düzeltmelerden önce) | 4/10 | – | platform kod sandbox'ı kesintisi |
| 2 (6 genel düzeltme) | **8/10** | 0/3 | B'de sandbox kesintisi |
| 3 | 2/10 | **2/3** | A'da sandbox kesintisi |
| Kitin örnek builder'ı | 6/10 | – | referans |

### 3.4 Politika çıkarım doğruluğu (çıkarılan policy vs elle yazılmış config)

| Brief A | f1 | f2 | f3 | f4 | f5 | f6 | f7 |
|---|---|---|---|---|---|---|---|
| %80 | %92 | %80 | %86 | %88 | %84 | %80 | %78 |

Farkların çoğu zararsız (anahtar adları, tek ürünlü brief'te boş not tablosu). Gerçek hata: **f7 tek ürünlü olduğu halde çok ürünlü çıkarıldı.** f6'daki memo değişiklikleri (son tarih 7 → 5, aynı gün callback yok) doğru çıkarıldı.

### 3.5 Freya unit test kapısı (Brief A)
- 11 tek turluk testten **9/11** geçti. Kalan 2'si test ifadesi sorunuydu, düzeltildi; canlıda tekrar koşulmadı.

---

## 4. Bilinen sorunlar ve sıradaki işler

1. **Self-test döngüsü canlıda henüz bir tur tamamlamadı.** Kod hazır ve offline testli. Canlı denemeler Freya sohbet hattının 502/504'leri ve Cloudflare tünel limitleri (429) yüzünden skor üretemedi. Öneri: Freya simülasyonu yolunu (bugün çalışan tek yol) runner olarak ekleyip döngüyü tek bir brief'te 2–3 tur koşmak.
2. **Audit zayıf:** 7 sahte brief'in hiçbirinde düzeltme önermedi (yaklaşık 20 saniyede "her şey doğru" diyor). f7'deki tek/çok ürün hatasını kaçırdı.
3. **Tutarlar, İnsan talebi ve Tarihler aileleri zayıf** (3/9, 4/9, 5/9). Asgari tutar teklif akışı ve son tarih / hafta içi gün çözümlemesi incelenmeli.
4. **Local judge, Freya hakeminden daha katı** (44 vs 59). Farkın sebepleri vaka bazında `out/template_cc/eval/freya/*.json` içinde.
5. **Platform bağımlılığı:** ajanın tüm mantığı Freya'nın kod sandbox'ında çalışıyor. Sandbox kesintisinde neredeyse her şey düşüyor (bugün 3 koşuda görüldü).
6. **OpenRouter kredisi az kaldı** (~$3). Anahtar başka oturumla paylaşılıyor.

---

## 5. Bugün yapılan genel düzeltmeler (builder kodunda; brief'e özgü değil)
- Açılış kodsuz ve önce konuşuluyor (sohbette 37–49 sn → 1,5 sn); sessiz `start` adımı sabit açılış cümlesini garantiliyor.
- "Çok fazla" bir yeniden yapılandırma talebi değil; robot sorusu bir insan talebi değil.
- Callback penceresi "bugün / yarın" diye adlandırılıyor; kelimeyle söylenen tarihler sayıya çevriliyor.
- Görüşme bitirme yolları eklendi (`transition_to_wrap` + `g_goodbye`); "Goodbye" döngüsü yok.
- Çift `create_promise` koruması; kayıtlı söz asla düşürülmüyor.
- Söz hatası mesajlarında "recorded" kelimesi yok; son tarih teklifi tutarı değiştirmiyor.
- Ürün dışı teklif (ör. tasarruf hesabı) yasak.
- Başarısız kod adımı döngüye girmiyor, `wrap`'e gidiyor.

---

## 6. Komutlar

```bash
# build (Freya'ya kaydeder)
.venv310/bin/python -m builder.template_cc.run briefs/brief-a.md tools/openapi.json --save freya --slot tcc-brief-a
# kayıtlı bir policy'den hızlı derleme (çıkarım yok)
.venv310/bin/python -m builder.template_cc.run briefs/brief-a.md tools/openapi.json --save freya --audit off --policy out/template_cc/policy-a.json
# testbed değerlendirmesi (Freya sim + local judge, ortak banka)
.venv310/bin/python scripts/tcc_eval_freya.py --brief all --limit 10 --or-budget 3 --shared-origin <tünel-url>
# zor simülasyonlar (DeepSeek müşteri)
.venv310/bin/python -m builder.template_cc.sims --workflow out/template_cc/judge-a/workflow.json --policy out/template_cc/policy-a.json --api tools/openapi.json --n 3
# testler
.venv310/bin/python -m pytest tests/template_cc -q
# canlı dashboard
.venv310/bin/python scripts/tcc_dashboard.py   # http://127.0.0.1:8900
```

Ham sonuçlar: `out/template_cc/eval/freya/*.json` (vaka bazında sebepler) · Tasarım ayrıntısı: `builder/template_cc/DESIGN.md`
