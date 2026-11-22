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
  - **Kârlılık & Nakit Kalitesi:** `ROIC`, `ROCE`, `ROE`, Brüt/FAVÖK/EBIT marjları, `OCF/Net Kâr`, Serbest Nakit Akışı (`FCF`) ve `FCF Getirisi`
  - **Borç & Değerleme:** `Net Borç/FAVÖK`, Cari/Asit-Test, Faiz Karşılama, `F/K`, `PD/DD`, `FD/FAVÖK`, `PEG`, Graham Çarpımı ve 4 yıllık finansal özet tablosu
  - **Akıllı Kur Hizalama:** `THYAO`, `PGSUS`, `TAVHL` gibi finansallarını USD/EUR raporlayıp TRY işlem gören BIST hisselerinde çarpanları otomatik kur düzeltmesiyle tutarlı hesaplar.
  - **Sektör & TMS 29 Farkındalığı:** Banka/Finans şirketlerinde `ROE` ve `PD/DD` odaklı puanlama; BIST hisselerinde TMS 29 enflasyon muhasebesi notları; `KOZAL → TRALT`, `KOZAA → TRMET`, `IPEKE → TRENJ` otomatik kod yönlendirmesi.

### 2. Para Akışı & Tema Rotasyonu (Günlük / Haftalık / Aylık / 3 Aylık)
- **14 BIST Teması** (87 likit hisse) ve **12 ABD / Global Teması** (66 lider hisse, sıfır ETF çifte sayımı).
- Her tema ve hisse için **1G · 1H · 1A · 3A** bazında **Para Akışı Skoru (`-100`..`+100`)**, **Chaikin Money Flow (CMF)** alım/satım baskısı, **RVOL**, **RS Farkı** ve **Rotasyon Etiketleri** (*Rotasyon Başlangıcı*, *Erken Para Girişi*, *Ana Lider Tema*, *Kâr Satışı / Çıkış*).
- Çift yönlü tema akış çubukları, 4 dönemlik ısı haritası, **Top 10 Giriş / Çıkış** tabloları ve tek tıkla hissenin tam Tekno-Temel analizine geçiş.

### 3. İzleme Listesi, Çoklu Kıyaslama ve PDF Rapor
- Kendi BIST + ABD izleme listeni oluştur, tüm hisseleri paralel tarayıp sıralanabilir tabloda kıyasla.
- Yazdırmaya özel açık renkli şablonla tek tıkla **PDF / Yazdır** dışa aktarımı.

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
│   └── money_flow.py    # 14 BIST + 12 ABD teması para akışı & rotasyon motoru
├── static/
│   ├── index.html       # Arayüz (Detaylı Analiz, Para Akışı, İzleme Listesi)
│   ├── styles.css       # Koyu finans teması + PDF/yazdırma stilleri
│   └── app.js           # TradingView Lightweight Charts ve etkileşim katmanı
├── Baslat.cmd           # Tek tıkla Windows başlatıcı
└── requirements.txt
```
