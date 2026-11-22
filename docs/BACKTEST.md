# Teknik Puanın Geriye Dönük Testi ve Kalibrasyon

**Tarih:** 23 Kasım 2026 · **Araçlar:** `tools/backtest_teknik.py`, `tools/kalibrasyon.py`

## Yöntem
- Tema listelerindeki tüm hisseler (ABD 67, BIST 87), 5 yıllık günlük veri.
- Her ay, *o güne kadarki* veriyle teknik puan hesaplandı (ileriye bakma yok).
- Sonraki 126 işlem günündeki (~6 ay) getiri, aynı dönemdeki endeks getirisiyle karşılaştırıldı.
- Kalem bazında **bilgi katsayısı (IC)**: kalemin sinyali ile sonraki fazla getiri arasındaki Spearman sıra korelasyonu. Aylık IC, aynı ay içindeki hisseler arasında hesaplanıp ortalaması alınır (piyasa yönünün etkisini dışlar). Kabaca 0.05 üzeri anlamlı, 0.10 üzeri güçlü kabul edilir.

## Sonuçlar (tam veri)

| Piyasa | Gözlem | Zayıf (<40) fazla getiri / yenme | Güçlü (≥65) fazla getiri / yenme | Toplam puan aylık IC |
|---|---|---|---|---|
| ABD | 2.784 | +19.6% / %56.4 | +9.5% / %56.1 | **0.031** (zayıf) |
| BIST | 3.423 | −4.3% / %33.6 | +6.7% / %48.6 | **0.147** (güçlü) |

En işe yarayan kalemler (aylık IC, ABD / BIST): 52H dip AVWAP (0.063 / 0.120), RS seviyesi (0.058 / 0.118), Minervini (0.029 / 0.171), Weinstein (0.024 / 0.124).
İşe yaramayan kalemler: hacim teyidi (−0.001 / −0.020), VCP (−0.006 / 0.039), ABD'de 50 SMA uzaklığı (−0.058).

## Kalibrasyon denemesi (örneklem dışı)
Ağırlıklar verinin ilk yarısında IC'ye göre yeniden belirlendi ve ikinci yarıda sınandı:

| Piyasa | Eski ağırlıklar (test IC) | Yeni ağırlıklar (test IC) |
|---|---|---|
| ABD | 0.071 | 0.069 |
| BIST | 0.109 | 0.101 |

**Karar:** Yeni ağırlıklar örneklem dışında daha iyi değil; ABD'de kalemlerin IC'leri iki yarı arasında işaret değiştiriyor (kararsız). Ağırlıklar **değiştirilmedi**. Aşırı uyumlu bir ağırlık setine geçmek geçmişte iyi, gelecekte kötü çalışan bir puan üretirdi.

## Yorum
- **BIST:** Teknik puan hisseleri anlamlı biçimde sıralıyor; düşük puanlı hisseler belirgin şekilde endeksin gerisinde kalmış.
- **ABD:** Teknik puanın 6 aylık göreli getiriyle ilişkisi zayıf ve kararsız. ABD hisselerinde teknik puanı tek başına karar ölçütü olarak kullanmayın; arayüz bunu not olarak gösterir.

## Sınırlamalar
Hayatta kalma yanlılığı (bugünkü hisseler), işlem maliyeti yok, gözlemler birbiriyle örtüşüyor, bilanço puanı test edilemedi (Yahoo geçmişe dönük bilanço vermez; `score_history` tablosu biriktikçe bu mümkün olacak).

---

# Süper Tarayıcı Filtrelerinin Geriye Dönük Testi

**Araç:** `tools/backtest_tarayici.py` · Sonuçlar `backend/data/screen_backtest.json` dosyasına yazılır ve arayüzde her filtrenin yanında gösterilir.

Her ay, o güne kadarki veriyle teknik analiz ve para akışı skorları hesaplandı; filtrenin **teknik ve akış** koşullarını sağlayan hisselerin sonraki ~6 aylık (126 işlem günü) endekse göre fazla getirisi ölçüldü. **"Aynı ay farkı"**, sinyal veren hissenin fazla getirisinden o ay tüm hisselerin ortalamasının çıkarılmasıdır (seçicilik etkisi). Bilanço koşulları test edilemez.

| Filtre | ABD sinyal / medyan / yenme / aynı ay farkı | BIST sinyal / medyan / yenme / aynı ay farkı |
|---|---|---|
| Tüm gözlemler (evren) | 2.784 / — / %56.2 / — | 3.423 / — / %43.5 / — |
| **Göreli Güç Liderleri** | 378 / +10.5% / **%62.7** / **+8.4%** | 470 / +0.7% / **%50.9** / **+6.9%** |
| Erken Rotasyon (bilanço hariç) | 210 / +3.1% / %57.1 / +3.4% | 324 / −3.0% / %44.4 / +3.2% |
| Altın Kesişim (bilanço hariç) | 883 / +3.4% / %54.9 / −1.4% | 986 / −0.8% / %48.6 / +3.2% |
| VCP Kırılım Adayları | 251 / +6.7% / %61.0 / −0.1% | 225 / +2.1% / %54.7 / +4.6% |
| Kaliteli ve Görece Ucuz | test edilemez (yalnızca bilanço) | test edilemez |

**Yorum:** En tutarlı filtre, teknik puan testinde en iyi çalışan kalemlerden kurulan *Göreli Güç Liderleri* (her iki piyasada evreni geçti); arayüzde varsayılan filtre budur. *Altın Kesişim* ABD'de evrenden ayrışmadı. Ortalamalar uç değerlere duyarlıdır; medyan ve yenme oranı birlikte okunmalıdır.
