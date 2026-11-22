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
