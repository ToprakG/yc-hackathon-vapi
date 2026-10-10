# Claude Code Builder (A-agent) — Durum Raporu

**Tarih:** 10 Ekim 2026, 21:05 · **Hackathon:** Freya × YC "Build the Builder" · **Kod:** `~/yc-hackathon-vapi` (dal `main`)

**Repo'lar (hepsi private):**
- Sadece Claude Code builder: https://github.com/alinebidal10-afk/yc_claude_code
- Sadece T-CC: https://github.com/alinebidal10-afk/yc_template_claude_code
- Her şey, tam geçmiş: https://github.com/alinebidal10-afk/yc_hackathon_first_day

**Canlı dashboard:** `python3 builder/eval/dashboard.py` (`.venv310` Python'u ile) → http://localhost:8765

---

## 1. Özet

| Ölçüm | Sonuç |
|---|---|
| Freya, Brief A pratik seti, katı skor (3 tekrarın 3'ü de geçmeli) | **8/10** (run 8; run 6: 5/10, run 7: 7/10) |
| Freya, Brief B pratik seti, katı skor | **2/3** (run 7 ve run 8) |
| Freya, testbed örneklemi, 12 case, tek tekrar | Brief A **5/12**, Brief B **7/12** |
| Lokal simülasyon, Brief B testbed (60 case, zor stiller) | **32/60** |
| Lokal simülasyon, Brief A pratik seti (10 case) | 7/10 (Freya ile aynı skor, 2 hatanın 2'si aynı yerde) |
| Fake brief'lerde extraction doğruluğu (policy alanları) | **%77–89** (7 fake brief) |
| Lokal hakem (Jev) ile Freya hakeminin uyumu | **35/39 çağrı (%90)** |
| Bir build'in süresi / maliyeti | ~12–15 dk (limit 30) / ~$6 Claude |
| Offline testler | **192 geçiyor** |

**Hâlâ koşanlar (21:05):**
- Run 9: tam self-repair döngüsüyle A ve B build'i.
- Lokal: Brief A testbed (100 case), sonra 7 fake brief (350 case).
- Freya'da fake brief'ler: Cloudflare tunnel rate-limit'i (429) yüzünden bekliyor.

---

## 2. Mimari

```
python3 builder/build.py <brief dosyaları...> <tools.openapi.json> [--save freya|none]
```

Tool API dosyası, JSON'unda `openapi` anahtarı olan argüman. Diğerleri brief materyali; sırası önemli, sonraki öncekini geçersiz kılıyor (Brief B = `brief-a.md brief-b.md`).

### 2.1 Bir build'in akışı (≈ 29 dakikalık bütçe)

1. **İzole workspace.** Repo dışında bir temp klasöre şunlar kopyalanır:
   - yeniden adlandırılmış brief'ler, tool API, kit dokümanları;
   - uydurma değerlerle örnek workflow (`pattern_demo`);
   - skill (`build-collections-agent`).

   Test cevapları, testbed ve `config.json` yoktur.
2. **Build (≤15 dk).** Claude Code (Claude Agent SDK, Opus 5.5) skill'i izler:
   - Brief'i okur; `policy.json` (yapılandırılmış extraction) ve `rules.json` (her kural, alıntısı ve workflow'daki yeri) yazar.
   - `workflow.json` (Freya workflow) ve `unit_tests.json` yazar.
   - Araçlarıyla döngü yapar: `lint_workflow`, `run_snippet`, `check_coverage`, `policy_unit_suite`, `check_unit_tests`, `run_local_sims`, `validate_workflow`, `time_left`.
   - Bash, web ve subagent yoktur. Guard hook dosya erişimini workspace ile, yazmayı `out/` ile sınırlar.
3. **Paralel kontroller (~5 dk, kod yürütür):**
   - **Bağımsız reviewer:** ayrı bir Claude oturumu. Brief'i ve workflow'u görür, builder'ın `rules.json`'unu görmez. Kendi kural listesini çıkarır; kod iki listeyi karşılaştırıp bulgu üretir.
   - **Unit test'ler, Freya'nın gerçek motorunda** (`-unit` kopyası üzerinde): builder'ın testleri, policy'den gelen zorunlu şablonlar ve lokal simülasyondan türetilen regresyon testleri.
   - **Lokal zor simülasyonlar:** builder'ın kendi `policy.json`'undan üretilen 10 case, builder'ın kendi denemelerinden farklı bir seed ile.
4. **Fix turu (≤6 dk):** builder kendi oturumuna devam eder. Bulgular sırayla gelir: unit-test hataları → düşen simülasyon çağrıları → reviewer. Talimat: "tek konuşmayı yamalama, workflow'daki sebebi bul".
5. **Regresyon kontrolü:** unit test'ler ve lokal simülasyonlar tekrar koşar. Biri bile kötüleşirse fix geri alınır (rollback).
6. **Finalize (deterministik kod):**
   - lint'i temiz workflow'u seçer (yoksa son temiz olanı);
   - `agent_config`'i atar;
   - Freya dry-run validate;
   - `freya.save_workflow` + `export_workflow` (aynı slot hep aynı workflow'u günceller);
   - `build_report.json` ve trace (`traces/<slot>-<zaman>/messages.jsonl` + `trace.txt`).

### 2.2 Skill: `builder/agentic/skill/build-collections-agent/`

| Dosya | İçerik |
|---|---|
| `SKILL.md` | Zaman kutulu prosedür: oku → extract → tasarla → build → kontrol/fix → bitir |
| `reference/call-architecture.md` | Bir tahsilat çağrısının aşamaları. Temel ilke: sayılar, tarihler, sınırlar ve kapanış sonucu kodda; model sadece konuşur |
| `reference/freya-cookbook.md` | Kit dokümanlarında doğrulanmış Freya kalıpları ve tuzaklar |
| `reference/platform-facts.md` | Pratik koşulardan öğrenilen 10 platform gerçeği; kontrol edilebilenler lint kuralı |
| `reference/policy-schema.md` | `policy.json` şeması (testbed config'leriyle aynı anahtarlar) |
| `reference/unit-tests.md` | Unit test formatı, zorunlu şablonlar, türetilmiş regresyon testleri |
| `reference/self-check.md` | Bitirmeden önceki kontrol listesi |
| `templates/calendar.py` | İş günü, tarih kelimeleri ("Monday the 26th", "the thirtieth"), para/cent, `list_from_vars` |
| `templates/fragments/*.json` | 15 hazır workflow parçası: offer loop, agreement, read-back, engine-run write, stage node… |

Skill'deki tüm örnek değerler uydurmadır ("Example Bank", 2031 tarihleri, `outcome_x`). `test_no_leak.py`, Brief A/B'den ve fake brief'lerden hiçbir değerin skill'e girmediğini kontrol ediyor.

### 2.3 Builder'ın ürettiği çağrı mimarisi (kalıp)

- **setup** (kod): `now`'dan takvim ve geri arama penceresi; kötümser kapanış varsayılanları.
- **opening** (sabit tts cümlesi + "kim cevap verdi" extraction'ı) → **üçüncü kişi / yanlış numara / vefat** dalları.
- **identity** (`verify_identity`; post-hook'tan `what_to_do_next` ve string durum) → **load_account** (`api_request`).
- **facts** (kod): ürün başına bant, son tarih, deneme tarihleri, taban, tarih tablosu, teklif cümleleri.
- **Offer loop:**
  1. `next_offer` (kod) sıradaki teklifi seçer;
  2. `offer` teklifi sabit cümle olarak söyler ve sadece cevabı extract eder;
  3. `store_agreement` (kod) tarih ve tutarı kurallara göre kontrol eder, ya kaydeder ya düzeltme cümlesi üretir;
  4. `confirm`, kodun ürettiği read-back'i okur;
  5. `record_one` (engine-run `create_promise`, değerler koddan) ve `note_one` (engine-run `add_note`).
- **Yan rotalar:** sabit cümleyle başlayan stage node'lar (maddi zorluk, insan isteği…), global node'lar (robot ve dolandırıcılık soruları).
- **close_call:** workflow seviyesinde `end_of_call` lifecycle tool. Değerler koddan, küçük bir pre-hook öncelik kuralını uygular.

### 2.4 Test ve ölçüm altyapısı

| Araç | Ne yapar |
|---|---|
| `builder/agentic/tools/lint.py` | Kit dokümanlarına dayalı statik kontroller; `base-agent.json` 0 hata ile kalibre |
| `builder/agentic/tools/unit_tests.py` | Unit test doğrulama, Freya formatına çevirme, sync/run (kit `freya.api` ile) |
| `builder/agentic/tools/policy_suite.py` | Policy'den zorunlu unit-test şablonları (15'e kadar) |
| `builder/agentic/localsim/` | **Lokal Freya motoru**: `workflow.json`'u platform gibi çalıştırır, DeepSeek v4.1 Flash ajan modeli (OpenRouter) + teammate'in mock bankası + zor stilde LLM müşteri + kit ledger skorlayıcısı + Jev hakemi. Freya yok |
| `builder/eval/local_run.py` | Freya chat API üzerinden lokal mock bankla koşu (uzun turlarda 504 aldığı için yedek) |
| `builder/eval/score_policy.py` | Extraction'ı testbed config'iyle alan alan karşılaştırır |
| `builder/eval/dashboard.py` | Canlı dashboard |
| `out/freya_all.py`, `out/freya_fakes.py` | Bizim ajanlarla gerçek Freya simülasyonları, testbed ve fake brief'ler (mock banka + tunnel) |

---

## 3. Skor geçmişi

### 3.1 Freya, kit pratik seti (Brief A 10 case, Brief B 3 case)

| Run | Builder sürümünde ne değişti | Brief A | Brief B | Not |
|---|---|---|---|---|
| 1 | ilk sürüm | 2/10 | – | mapped list değişkeni platformda boş kalıyordu → 8 çağrı `service_error` |
| 2 | `list_from_vars` | 8/10 | 0/3 | B: goodbye döngüsü, fazla deneme |
| 3 | denemeler kodda, `end_call` güvenlik ağı | (geçersiz) | (geçersiz) | platform yükü: ilk cevap 60 sn'de gelmedi |
| 4 | reviewer + fix turu, platform gerçekleri | 10/10 | 2/3 | yavaş platform; B'nin tekrarında Freya sandbox kesintisi |
| 5 | offer loop v1 | 8/10 | 1/3 | ilk temiz (hızlı) ölçüm, tek tekrar |
| 6 | agreement capture + engine-run write'lar, 3 tekrar | **5/10** | **1/3** | tarih yardımcısında 2 hata |
| 7 | tarih düzeltmesi | **7/10** | **2/3** | |
| 8 | unit-test onarım döngüsü | **8/10** | **2/3** | A unit test: 4/16 → 16/16; B: 2/4 → 3/4 |
| 9 | tam self-repair (lokal sim + unit + reviewer) | koşuyor | koşuyor | |

Run 6'dan itibaren skorlar katı: bir case ancak 3 tekrarın 3'ünü de geçerse sayılıyor (final puanlama böyle).

**Run 8'in kalan hataları:**
- A, PUB-04: müşteri açılışta "robot mu?" diye geri soruyor.
- A, PUB-10: araç hatasından sonra "kaydedildi" kelimesinin zamanlaması.
- B, PUB-12: ortak onay adımında kilitlenme, ajan kendini tekrarlıyor.

### 3.2 Freya, testbed örneklemi (aile dengeli 12 case, tek tekrar)

| Brief | Skor | Düşen case'ler |
|---|---|---|
| Brief A | 5/12 | A-001 ve A-003 (doğum tarihi parça parça verilince "reddetti" sayılıyor), A-004 (tarih), A-008 (tekrar sorma 2 kez), A-009 (kimlik tekrarı), A-018 (ikinci anlaşılmaz cevapta bitirmedi), A-020 (ikinci retten sonra bitirmedi) |
| Brief B | 7/12 | ayrıntı `out/freya_all/brief-b.log`'da |
| f1–f7 | bekliyor | Cloudflare quick-tunnel rate-limit (429); script tek tunnel ile bekleyip tekrar deniyor |

Ortak tema: "N kez sor / ikinci seferde bitir" türü sınırların açılış, üçüncü kişi, kimlik ve ret adımlarında hâlâ modele bırakılması. Karar: skill'e case'e özel kural **eklenmedi**. Builder bu türleri kendi lokal simülasyonlarında (Belirsiz, Ret, Üçüncü kişi, Kimlik aileleri, zor stiller) görüp kendisi düzeltmeli. Run 9 bunu ölçüyor.

### 3.3 Lokal simülasyon (DeepSeek ajan, Jev hakem, Freya yok)

| Set | Skor | Kayıt doğru | Hakem geçti |
|---|---|---|---|
| Brief A pratik seti (10) | 7/10 | | |
| Brief B testbed (60) | 32/60 | 43/60 | ~32/60 |
| Brief A testbed (100) | koşuyor | | |
| 7 fake brief (350) | sırada | | |

### 3.4 Fake brief'ler, offline build (Freya'ya kaydedilmedi)

| Fake brief | Ne değişiyor | Extraction doğruluğu | Reviewer bulgusu | Build |
|---|---|---|---|---|
| f1-nordhavn | 3 bant, yeniden adlandırılmış alanlar | %81.8 | 18 | lint 0 |
| f2-ostral | 3 kimlik sorusu, 2 yanlışta bitiş | %81.0 | 17 | lint 0 |
| f3-kestrel | çok ürün, cent tutar, öncelikli kapanış | %85.9 | 16 | lint 0 |
| f4-brightwell | kurumsal müşteri, farklı kimlik alanları | %89.3 | 16 | lint 0 |
| f5-halden-email | ham e-posta zinciri, tek datetime alanı | %78.3 | 23 | lint 0 |
| f6-corvid-memo | 2 kuralı değiştiren memo | %77.4 (iki override da doğru uygulandı) | 11 | lint 0 |
| f7-lumen-codes | dialer export, tek kodlu close_call | %79.3 | 35 | lint 0 |

Kaçırılan alanların çoğu yazım farkı. Örnek: ürün tipleri kanonik kısa anahtar yerine API adıyla yazılmış. Bantlar, tatiller, kimlik, kapanış kodları ve kuyruklar doğru.

**Hold-out:** f1, f4 ve f7 sadece ölçüm için koşuluyor; builder onların sonuçlarına bakılarak düzeltilmiyor.

---

## 4. Pratik koşulardan öğrenilen platform gerçekleri

Kit dokümanlarında yazmayan, gerçek Freya'da görülen davranışlar (`reference/platform-facts.md`):

1. Node seviyesinde bir **liste** mapping'i değişkeni boş bırakıyor; liste sadece `<node>_response.data.<liste>.<i>.<alan>` anahtarlarında. **(lint: hata)**
2. Bitişe giden bir extraction, onu tetikleyen mesajın kendisinde değerlendiriliyor. Ajan brief'in gerektirdiği cümleyi söyleyemeden çağrı bitiyor.
3. Model teklifleri yeniden kelimelerle söylüyor ve zorunlu ekleri düşürüyor.
4. Model aynı tool'u tek mesajda birkaç kez çağırıyor; `<tool>_args` sadece birinin değerlerini tutuyor. **(lint: uyarı)**
5. Hiç true olmayan bir tamamlama bayrağı, sonsuz "hoşça kalın" döngüsü yaratıyor. **(lint: uyarı, `end_call` güvenlik ağı)**
6. Sadece metinde yazan sınırlar (deneme sayısı vb.) model tarafından aşılıyor.
7. Model meşgulken tur süresi 8 sn'den 24–60 sn'ye çıkıyor ve skorlar bozuluyor (kit `--rerun-if-slow`).
8. Kod ve hook'ları çalıştıran sandbox ("snekbox") çökebiliyor; o anda hook'lu bir tool'un çağrısı tamamen düşüyor.
9. Sınırlar sadece metinde olunca model her ürün için açılış sorusunu tekrar soruyor.
10. Girişte modele tool çağırtan bir node, platformun kendi dolgu cümlesini başka dilde söyletti ("Bir saniye lütfen."). **(lint: uyarı)**

Ayrıca:
- Freya'nın chat API'si uzun turlarda **504** veriyor (bizim derin engine zincirleri). Bu yüzden lokal motor yazıldı.
- Cloudflare quick tunnel'ları rate-limit'li.
- Kit'in mock bankası (Cloudflare Worker) bir süre çöktü.

---

## 5. Kararlar ve ilkeler

- **Overfitting'e karşı:** builder kendi testlerini kendi `policy.json`'undan üretiyor, testbed cevaplarını hiç görmüyor. Skill'e sadece genel yetenek ve platform gerçeği giriyor. Ölçüm builder'ın görmediği setlerle yapılıyor.
- **Determinizm:** tarih, tutar, sayaç, teklif sırası, read-back ve kapanış sonucu kodda; model sadece konuşuyor.
- **Engine-run write'lar:** değerleri kodun belirlediği kayıtlar (söz, not) `api_request` node'larından gidiyor, model tool çağrısıyla değil.
- **Kendi kendini onarma:** build → kontroller (lokal sim + unit + reviewer) → tek fix → regresyon kontrolü. Kötüleşen fix geri alınıyor.

---

## 6. Açık işler ve riskler

1. **Run 9 sonucu:** builder testbed'deki "ikinci retten sonra bitir" ve "parçalı cevap" türü hataları kendi testlerinde görüp düzeltebiliyor mu?
2. **Varyans:** her build farklı bir workflow üretiyor. Tek build'in skoru gürültülü; best-of-N (paralel build, lokal testle seçim) 30 dakikaya sığar.
3. **Freya'da fake brief'ler:** tunnel rate-limit'i kalkınca 7 × 12 case koşacak.
4. **Lokal motor ≠ Freya'nın ajan modeli:** yapısal hatalar taşınıyor, ifade davranışı farklı olabilir. Lokal ve Freya sonuçları birlikte okunmalı.
5. **Kurulum bağımlılıkları:**
   - `vendor/build-the-builder` (teammate repo'su, git-ignore'lu) lokal simülasyon ve hakem için gerekli.
   - OpenRouter key ortamda olmalı.
   - FastAPI, `.venv310`'a kuruldu.
6. **Final makinesi:** Python 3.10 (`.venv310` ile test edildi), `claude-agent-sdk` 0.2.165, `FREYA_API_KEY` staging, `FREYA_BANK_TEAM_KEY` `.env`'de.

---

## 7. Dosya yerleri

| Ne | Nerede |
|---|---|
| Builder kodu | `~/yc-hackathon-vapi/builder/` |
| Skill | `~/yc-hackathon-vapi/builder/agentic/skill/build-collections-agent/` |
| Offline testler (192) | `~/yc-hackathon-vapi/tests/agentic/` (`.venv310/bin/python -m pytest tests/agentic`) |
| Build çıktıları (workflow, policy, kurallar, raporlar) | `~/yc-hackathon-vapi/out/agentic/<slot>/` |
| Build trace'leri | `~/yc-hackathon-vapi/traces/agentic-*` |
| Freya pratik sonuçları | `~/yc-hackathon-vapi/results/agentic_{A,B}_run*.json` |
| Freya testbed/fake sonuçları | `~/yc-hackathon-vapi/out/freya_all/` |
| Lokal simülasyon sonuçları | `~/yc-hackathon-vapi/out/localsim_all/` |
| SDK notları | `~/yc-hackathon-vapi/builder/agentic/SDK_NOTES.md` |
| Builder README | `~/yc-hackathon-vapi/builder/agentic/README.md` |
