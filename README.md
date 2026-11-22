# HisseRöntgen — Tekno-Temel Hisse Analiz ve Para Akışı Platformu

**BIST (Borsa İstanbul)** ve **ABD / Global** hisseleri için **teknik analiz**, **bilanço/temel analiz** ve **tema bazlı para akışı rotasyonunu** tek web arayüzünde birleştiren açık kaynaklı analiz aracı.

> **Yasal Uyarı:** Bu yazılım eğitim ve araştırma amaçlıdır; herhangi bir menkul kıymete yönelik yatırım tavsiyesi niteliği taşımaz.

---

## Özellikler

### 1. Tekno-Temel Detaylı Hisse Analizi
- **4-Kadran Karar Matrisi:** Bileşik Puan (`0–100`), Teknik Puan (`0–100`) ve Bilanço Puanı (`0–100`) + otomatik güçlü yönler ve kırmızı bayraklar.
- **Teknik Analiz:**
  - **Mark Minervini 8'li Trend Şablonu** (`SMA 50 / 150 / 200`, 200 SMA eğimi, 52H zirve/dip mesafesi)
  - **Stan Weinstein Haftalık Evre Analizi** (30 haftalık SMA — Evre 1/2/3/4)
  - **Göreceli Güç (RS)** ve **Piyasa Rejimi** (`BIST 100` / `S&P 500`)
  - **Anchored VWAP** (52H Dip, 52H Zirve ve Yılbaşı kurumsal maliyet çizgileri)
  - **VCP Volatilite Daralması**, **RVOL**, **ATR(14)**, **ADR%(20)** ve yapısal stop referansları (`1 ADR`, `1.5×/2× ATR`)
  - Trend filtreli **RSI(14)** ve **MACD(12,26,9)**
  - **BIST USD Bazlı Grafik & Trend Doğrulaması** (enflasyon yanılsamasına karşı tek tıkla TL / USD geçişi)
- **Bilanço & Temel Analiz:**
  - **Piotroski F-Score (0–9)** — tüm 9 muhasebe kriteri tek tek
  - **Altman Z-Score** (finansal sıkıntı testi) ve **Beneish M-Score** (kâr manipülasyonu riski)
  - **Joel Greenblatt Sihirli Formülü** (`EBIT/EV` ve `ROC`)
  - **Esas Faaliyet Kârı Odaklı:** EBIT ve FAVÖK, yatırım satış kazancı gibi faaliyet dışı kalemleri içermeyen *esas faaliyet kârından* hesaplanır.
  - **Kârlılık & Nakit Kalitesi:** `ROIC`, `ROCE`, `ROE`, Brüt/FAVÖK/EBIT marjları, `OCF/Net Kâr`, Serbest Nakit Akışı (`FCF`) ve `FCF Getirisi`
  - **Borç & Değerleme:** `Net Borç/FAVÖK` (net borç = toplam borç − nakit ve kısa vadeli yatırımlar; kiralar ayrıca gösterilir), Cari/Asit-Test, Faiz Karşılama, `F/K`, `PD/DD`, `FD/FAVÖK`, `PEG`, Graham Çarpımı ve 4 yıllık finansal özet tablosu
  - **Akıllı Kur Hizalama:** `THYAO`, `PGSUS`, `TAVHL` gibi finansallarını USD/EUR raporlayıp TRY işlem gören BIST hisselerinde çarpanları otomatik kur düzeltmesiyle tutarlı hesaplar.
  - **Sektör & TMS 29 Farkındalığı:** Banka/Finans şirketlerinde `ROE` ve `PD/DD` odaklı puanlama; BIST hisselerinde TMS 29 farkındalığı (büyüme oranları enflasyonu dışlamak için dönem ortalama USD/TRY kuruyla **dolar bazında** ölçülür); `KOZAL → TRALT`, `KOZAA → TRMET`, `IPEKE → TRENJ` otomatik kod yönlendirmesi.

### 2. Para Akışı & Tema Rotasyonu (Günlük / Haftalık / Aylık / 3 Aylık)
- **15 BIST Teması** (87 hisse) ve **12 ABD / Global Teması** (67 lider hisse; ETF yok, sadece hisse senedi). Ortalama günlük işlem hacmi eşiğin altındaki sığ hisseler akış hesabından çıkarılır; tema skoru işlem hacmiyle ağırlıklandırılır.
- Her tema ve hisse için **1G · 1H · 1A · 3A** bazında **Para Akışı Skoru (`-100`..`+100`)**, **Chaikin Money Flow (CMF)** alım/satım baskısı, **RVOL**, **RS Farkı** ve **Rotasyon Etiketleri** (*Rotasyon Başlangıcı*, *Erken Para Girişi*, *Ana Lider Tema*, *Kâr Satışı / Çıkış*).
- Çift yönlü tema akış çubukları, 4 dönemlik ısı haritası, **Top 10 Giriş / Çıkış** tabloları ve tek tıkla hissenin tam Tekno-Temel analizine geçiş.

### 3. İzleme Listesi, Çoklu Kıyaslama ve PDF Rapor
- Kendi BIST + ABD izleme listeni oluştur, tüm hisseleri paralel tarayıp sıralanabilir tabloda kıyasla.
- Yazdırmaya özel açık renkli şablonla tek tıkla **PDF / Yazdır** dışa aktarımı.

### 4. Analist Hedefleri, Riskler ve Uyarılar
- **ABD hisseleri için analist hedef fiyatları:** konsensüs, ortalama/medyan/en yüksek/en düşük hedef ve potansiyel getiri; son 6 ayda not veya hedef değiştiren kurumların listesi. (Aracı kurum tahminleridir; uygulamanın önerisi değildir.)
- **Bilanço takvimi:** sıradaki bilanço tarihi; 7 gün içindeyse uyarı.
- **Finansman riski:** zarar eden şirketlerde nakit ömrü (ay), pay sayısı artışı (seyrelme), hisse bazlı ödeme yükü, 24 ay içinde vadesi gelen borç.
- **Döngüsel sektörler:** faaliyet marjı tarihsel ortalamanın çok üstündeyse "zirve kâr riski" uyarısı; değerleme ortalama marjla normalize edilir.
- **Sektör içi kıyas:** değerleme ve marj, aynı tema/sektördeki hisselerin yüzdelik sırasıyla dengelenir (arka plan görevi günde bir kez kıyas verisini toplar).
- **Puan geçmişi:** her analiz günlük olarak yerel veritabanına (`.cache/hisse_rontgen.sqlite3`) kaydedilir.
- **İzleme listesi uyarıları:** evre değişimi, ±15 puan değişimi ve yaklaşan bilanço; sunucu açıkken 30 dakikada bir kontrol edilir (🔔 Uyarılar).

### 5. Şeffaf Puanlama
- Her puanın **kalem kalem dökümü** gösterilir (ör. "ROIC: 15/15, Değerleme: 7/15").
- **ABD bilançosu SEC EDGAR'dan** (resmi XBRL verisi) alınır; Yahoo yalnızca yedek kaynaktır ve iki kaynak %5'ten fazla farklıysa uyarı gösterilir. SEC istekleri için `SEC_USER_AGENT` ortam değişkeniyle kendi uygulama adınızı ve e-postanızı verebilirsiniz.
- Bilanço puanı **yalnızca mevcut verilerle** hesaplanır: eksik bir kalem puan kazandırmaz ya da kaybettirmez; puanın yanında **veri kapsamı (%)** ve eksik kalemler gösterilir.
- **Beneish M-Score** bilgi amaçlıdır, puandan düşülmez (yüksek satış büyümesi skoru tek başına eşiğin üzerine taşıyabilir). En az 6/8 bileşen gerçek veriye dayanmıyorsa hesaplanmaz.
- **RS Tahmini**, IBD'nin yüzdelik RS sıralaması değildir; hissenin endekse göre ağırlıklı fazla getirisinden türetilir.
- **Para akışı tahminidir**: fiyat, hacim ve gün içi kapanış konumundan (Chaikin) türetilir; gerçek takas / AKD verisi değildir.

---

## Kurulum ve Çalıştırma

**Gereksinimler:** Python 3.10+

```bash
git clone https://github.com/cagatayyakyildizz-cloud/hisse-rontgen.git
cd hisse-rontgen
pip install -r requirements.txt
```

**Başlatma (Windows):**
- `Baslat.cmd` dosyasına çift tıkla (sunucuyu başlatır ve tarayıcıyı açar).

**Başlatma (Komut Satırı):**
```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```
Ardından tarayıcıda `http://127.0.0.1:8765` adresini aç.

> Sunucu yalnızca kendi bilgisayarında (`127.0.0.1`) çalışacak şekilde ayarlıdır. İzleme listesi uç noktalarında kimlik doğrulama yoktur; `--host 0.0.0.0` ile ağa açmayın.

---

## Testler

Testler ağ erişimi gerektirmez (Yahoo'ya istek atılmaz) ve her `push`'ta GitHub Actions'ta otomatik çalışır.

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Puanların Geriye Dönük Testi

Teknik puanın gerçekten işe yarayıp yaramadığını görmek için: geçmişte her ay, *o güne kadarki* veriyle teknik puan hesaplanır ve sonraki 6 aydaki endekse göre getiriyle karşılaştırılır.

```bash
python tools/backtest_teknik.py --market us
python tools/backtest_teknik.py --market bist --horizon 63
```

Kalem bazında bilgi katsayısı ve örneklem dışı kalibrasyon için `--components --csv` ve `tools/kalibrasyon.py`. Son sonuçlar ve ağırlıkların neden değiştirilmediği: [docs/BACKTEST.md](docs/BACKTEST.md). Özetle: teknik puan BIST'te anlamlı (aylık IC 0.15), ABD'de zayıf (0.03).

> Yalnızca teknik puan test edilebilir (Yahoo geçmişe dönük bilanço vermez). Tema listeleri bugünkü hisselerden oluştuğu için hayatta kalma yanlılığı vardır; sonuçları kesin kanıt olarak değil, eşikleri sorgulamak için kullanın.

## Referans Verilerini Güncelleme

BIST kod değişiklikleri (örn. `KOZAL → TRALT`) ve tema listeleri koda gömülü değildir:
- `backend/data/bist_symbols.json` — eski→yeni kod yönlendirmeleri ve bilinen BIST kodları
- `backend/data/themes.json` — para akışı temaları (yalnızca hisse senedi, ETF eklemeyin)

---

## Proje Yapısı

```text
hisse-rontgen/
├── backend/
│   ├── app.py           # FastAPI sunucusu ve REST uç noktaları
│   ├── data_fetcher.py  # Yahoo Finance veri, önbellek ve kur hizalama
│   ├── technical.py     # Minervini, Weinstein, RS, AVWAP, VCP, ATR/ADR, USD grafik
│   ├── fundamental.py   # Piotroski, Altman, Beneish, ROIC, FCF, değerleme
│   ├── analyzer.py      # Tekno-Temel bileşik skor ve 4-kadran karar motoru
│   ├── money_flow.py    # 15 BIST + 12 ABD teması para akışı & rotasyon motoru
│   ├── cache.py         # Boyut sınırlı (LRU) ve süreli önbellek
│   ├── reference_data.py# JSON referans verilerini yükler
│   ├── scoring.py       # Ortak puan kartı (kalem dökümü, veri kapsamı)
│   ├── sec_data.py      # SEC EDGAR XBRL bilanço özeti (ABD)
│   ├── market_info.py   # Analist hedefleri, bilanço takvimi, finansman riski
│   ├── storage.py       # SQLite: puan geçmişi, sektör kıyası, uyarılar, önbellek
│   ├── scheduler.py     # Arka plan: uyarılar ve günlük sektör kıyas verisi
│   └── data/            # bist_symbols.json, themes.json
├── tests/               # Ağ erişimsiz birim ve API testleri (pytest)
├── tools/
│   ├── backtest_teknik.py  # Teknik puanın geriye dönük testi
│   └── kalibrasyon.py      # Ağırlık kalibrasyonu (örneklem dışı doğrulamalı)
├── docs/BACKTEST.md     # Geriye dönük test sonuçları
├── static/
│   ├── index.html       # Arayüz (Detaylı Analiz, Para Akışı, İzleme Listesi)
│   ├── styles.css       # Koyu finans teması + PDF/yazdırma stilleri
│   └── app.js           # TradingView Lightweight Charts ve etkileşim katmanı
├── Baslat.cmd           # Tek tıkla Windows başlatıcı
├── requirements.txt     # Çalışma bağımlılıkları (yfinance sabit sürüm)
└── requirements-dev.txt # Test bağımlılıkları
```
