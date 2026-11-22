(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    market: "auto",
    currentData: null,
    chartCurrency: "primary",
    chartDays: 252,
    chartObj: null,
    chartSeries: {},
    watchlist: [],
    wlRows: [],
    wlSortKey: "composite_score",
    wlSortDir: -1,
    flowMarket: "bist",
    flowPeriod: "1w",
    flowData: { bist: null, us: null },
    flowThemeFilter: "ALL",
    flowSearch: "",
    flowSortKey: "flow_score",
    flowSortDir: -1,
    scanMarket: "bist",
    scanPreset: "rs_liderleri",
    scanPresets: [],
    positionPlan: null,
    positionLines: [],
  };

  // --- Formatting helpers ---
  function fmtNum(v, dec = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return Number(v).toLocaleString("tr-TR", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function fmtPct(v, dec = 2, signed = false) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const s = signed && v > 0 ? "+" : "";
    return `${s}%${fmtNum(v, dec)}`;
  }
  function fmtBig(v, curr = "") {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const abs = Math.abs(v);
    const sign = v < 0 ? "-" : "";
    let out;
    if (abs >= 1e12) out = `${(abs / 1e12).toFixed(2)} T`;
    else if (abs >= 1e9) out = `${(abs / 1e9).toFixed(2)} Mr`;
    else if (abs >= 1e6) out = `${(abs / 1e6).toFixed(1)} Mn`;
    else if (abs >= 1e3) out = `${(abs / 1e3).toFixed(1)} B`;
    else out = abs.toFixed(0);
    return `${sign}${out}${curr ? " " + curr : ""}`;
  }
  function scoreColor(s) {
    if (s >= 65) return "#22c55e";
    if (s >= 45) return "#f59e0b";
    return "#ef4444";
  }
  function scoreClass(s) {
    if (s >= 65) return "high";
    if (s >= 45) return "mid";
    return "low";
  }
  function setGauge(circleId, textId, value) {
    const c = $(circleId);
    const t = $(textId);
    const v = Math.max(0, Math.min(100, Number(value) || 0));
    const circ = 263.89;
    c.style.strokeDashoffset = String(circ * (1 - v / 100));
    c.style.stroke = scoreColor(v);
    t.textContent = String(v);
    t.style.color = scoreColor(v);
  }

  function showError(msg) {
    const box = $("errorBox");
    if (!msg) {
      box.classList.add("hidden");
      box.textContent = "";
      return;
    }
    box.textContent = msg;
    box.classList.remove("hidden");
  }
  function setLoading(on, text = "Piyasa verileri ve finansal tablolar analiz ediliyor…") {
    $("loadingText").textContent = text;
    $("loadingBox").classList.toggle("hidden", !on);
    $("analyzeBtn").disabled = on;
  }

  function switchView(view) {
    const isAna = view === "analysis";
    const isFlow = view === "flow";
    const isWl = view === "watchlist";
    const isScan = view === "scan";
    $("tabScan").classList.toggle("active", isScan);
    $("scanView").classList.toggle("hidden", !isScan);
    $("tabAnalysis").classList.toggle("active", isAna);
    $("tabFlow").classList.toggle("active", isFlow);
    $("tabWatchlist").classList.toggle("active", isWl);
    $("flowView").classList.toggle("hidden", !isFlow);
    $("watchlistView").classList.toggle("hidden", !isWl);
    if (isAna) {
      $("welcomeView").classList.toggle("hidden", !!state.currentData);
      $("analysisView").classList.toggle("hidden", !state.currentData);
    } else {
      $("welcomeView").classList.add("hidden");
      $("analysisView").classList.add("hidden");
      if (isFlow) {
        if (!state.flowData[state.flowMarket]) loadMoneyFlow(state.flowMarket, false);
        else renderMoneyFlow();
      } else if (isWl && state.wlRows.length === 0 && state.watchlist.length > 0) {
        scanWatchlist();
      } else if (isScan) {
        initScanner();
      }
    }
  }

  // --- Rendering helpers ---
  function renderChecklist(containerId, items) {
    const el = $(containerId);
    el.innerHTML = "";
    const iconMap = { pass: "✓", warn: "!", fail: "✕", na: "–" };
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "chk-row";
      const st = item.status || (item.available === false ? "na" : item.passed ? "pass" : "fail");
      row.innerHTML = `
        <div class="chk-left">
          <span class="chk-icon ${st}">${iconMap[st] || "•"}</span>
          <span>${escapeHtml(item.label || item.name)}</span>
        </div>
        <span class="chk-val">${escapeHtml(item.value ?? item.detail ?? (st === "pass" ? "Evet" : st === "na" ? "Veri Yok" : "Hayır"))}</span>
      `;
      el.appendChild(row);
    }
  }

  function renderKV(containerId, rows) {
    const el = $(containerId);
    el.innerHTML = "";
    for (const r of rows) {
      const div = document.createElement("div");
      div.className = "kv-row";
      div.innerHTML = `<span class="kv-k">${escapeHtml(r.k)}</span><span class="kv-v ${r.cls || ""}">${escapeHtml(String(r.v))}</span>`;
      el.appendChild(div);
    }
  }

  // --- Puan dokumu: her kalemin puani / agirligi ---
  function renderBreakdown(containerId, items, total, opts = {}) {
    const el = $(containerId);
    el.innerHTML = "";
    for (const it of items || []) {
      const row = document.createElement("div");
      const missing = it.points === null || it.points === undefined;
      row.className = `bd-row${missing ? " missing" : ""}`;
      const ratio = missing ? 0 : (it.max ? it.points / it.max : 0);
      const cls = ratio >= 0.67 ? "good" : ratio >= 0.34 ? "mid" : "bad";
      row.innerHTML = `
        <div class="bd-label">
          <span class="bd-name" title="${escapeHtml(it.label)}">${escapeHtml(it.label)}${it.detail ? `<span class="muted">${escapeHtml(it.detail)}</span>` : ""}</span>
          <div class="bd-bar"><div class="bd-fill ${cls}" style="width:${Math.round(ratio * 100)}%"></div></div>
        </div>
        <span class="bd-val">${missing ? "veri yok" : `${fmtNum(it.points, 1)}/${fmtNum(it.max, 0)}`}</span>`;
      el.appendChild(row);
    }
    const foot = document.createElement("div");
    foot.className = "bd-total";
    const parts = [`Puan: ${total}/100 (mevcut kalemlerin ağırlıklı ortalaması)`];
    if (opts.coverage !== undefined && opts.coverage !== null) parts.push(`Veri kapsamı: %${opts.coverage}`);
    if (opts.penalty) parts.push(`Ceza: −${fmtNum(opts.penalty, 0)}`);
    foot.textContent = parts.join(" · ");
    el.appendChild(foot);
    if (opts.note) {
      const n = document.createElement("div");
      n.className = "bd-total";
      n.textContent = `Geriye dönük test: ${opts.note}`;
      el.appendChild(n);
    }
  }

  function renderAnalyst(a, meta) {
    const card = $("analystCard");
    const body = $("analystActionsBody");
    body.innerHTML = "";
    if (meta.is_bist) {
      renderKV("analystBox", [{ k: "Durum", v: "Analist hedef fiyatları yalnızca ABD / global hisseler için gösterilir." }]);
      $("analystNote").textContent = "";
      card.classList.add("muted-card");
      return;
    }
    card.classList.remove("muted-card");
    if (!a || !a.available) {
      renderKV("analystBox", [{ k: "Durum", v: (a && a.note) || "Analist verisi bulunamadı." }]);
      $("analystNote").textContent = "";
      return;
    }
    const cur = a.currency || meta.currency;
    const up = (v) => (v === null || v === undefined ? "" : ` (${fmtPct(v, 1, true)})`);
    const cls = (v) => (v === null || v === undefined ? "" : v >= 0 ? "pos" : "neg");
    renderKV("analystBox", [
      { k: "Konsensüs", v: `${a.recommendation || "—"}${a.analyst_count ? ` · ${a.analyst_count} analist` : ""}` },
      { k: "Ortalama hedef", v: a.target_mean !== null ? `${fmtNum(a.target_mean)} ${cur}${up(a.upside_mean_pct)}` : "—", cls: cls(a.upside_mean_pct) },
      { k: "Medyan hedef", v: a.target_median !== null ? `${fmtNum(a.target_median)} ${cur}${up(a.upside_median_pct)}` : "—", cls: cls(a.upside_median_pct) },
      { k: "En yüksek / en düşük", v: `${fmtNum(a.target_high)} / ${fmtNum(a.target_low)} ${cur}` },
    ]);
    for (const x of a.recent_actions || []) {
      const tr = document.createElement("tr");
      const tgt = x.target ? fmtNum(x.target) : "—";
      const prior = x.prior_target && x.prior_target !== x.target ? ` <span class="muted">(${fmtNum(x.prior_target)})</span>` : "";
      tr.innerHTML = `<td class="mono">${escapeHtml(x.date)}</td><td>${escapeHtml(x.firm)}</td>
        <td title="${escapeHtml(x.action)}">${escapeHtml(x.to_grade || x.action)}</td><td class="num">${tgt}${prior}</td>`;
      body.appendChild(tr);
    }
    if (!(a.recent_actions || []).length) body.innerHTML = `<tr><td colspan="4" class="muted">Son 6 ayda not değişikliği yok.</td></tr>`;
    $("analystNote").textContent = a.note || "";
  }

  function renderRisk(e, fin, f) {
    const lvl = { low: "Düşük", medium: "Orta", high: "Yüksek" };
    const rows = [
      {
        k: "Sıradaki bilanço",
        v: e && e.next_date ? `${e.next_date} (${e.days_until} gün)${e.is_estimate ? " · tahmini" : ""}` : "Tarih bilinmiyor",
        cls: e && e.warning ? "warn" : "",
      },
      { k: "Son bilanço", v: (e && e.last_date) || "—" },
    ];
    if (e && e.eps_estimate !== null && e.eps_estimate !== undefined) rows.push({ k: "Beklenen HBK", v: fmtNum(e.eps_estimate, 2) });
    rows.push(
      { k: "Finansman riski", v: lvl[fin.level] || fin.level, cls: fin.level === "high" ? "neg" : fin.level === "medium" ? "warn" : "pos" },
      { k: "Nakit ömrü", v: fin.runway_months !== null ? `${fmtNum(fin.runway_months, 0)} ay` : (fin.fcf_ttm !== null && fin.fcf_ttm >= 0 ? "Nakit üretiyor" : "—"), cls: fin.runway_months !== null && fin.runway_months < 24 ? "warn" : "" },
      { k: "Aylık nakit yakımı", v: fin.monthly_burn ? fmtBig(fin.monthly_burn, f.financial_currency) : "—" },
      { k: "Pay sayısı değişimi (1 yıl)", v: fmtPct(fin.share_growth_1y_pct, 1, true), cls: (fin.share_growth_1y_pct || 0) > 10 ? "neg" : "" },
      { k: "Hisse bazlı ödeme / ciro", v: fin.sbc_pct_revenue !== null ? fmtPct(fin.sbc_pct_revenue, 1) : "—" },
      { k: "Dönüştürülebilir borç", v: fin.convertible_debt ? fmtBig(fin.convertible_debt, "USD") : "—" },
      { k: "Vadesi 24 ay içinde gelen borç", v: fin.debt_due_24m !== null && fin.debt_due_24m !== undefined ? fmtBig(fin.debt_due_24m, "USD") : "—" },
    );
    renderKV("riskBox", rows);
  }

  function renderHistory(hist) {
    const el = $("historyChart");
    const pts = (hist || []).filter((h) => h.composite !== null && h.composite !== undefined);
    if (pts.length < 2) {
      el.innerHTML = "";
      $("historyNote").textContent = pts.length
        ? "Puan geçmişi her analizde günlük olarak kaydedilir; grafik ikinci günden itibaren oluşur."
        : "Henüz kayıt yok.";
      return;
    }
    const W = 320, H = 110, pad = 6;
    const x = (i) => pad + (i * (W - 2 * pad)) / (pts.length - 1);
    const y = (v) => H - pad - (v / 100) * (H - 2 * pad);
    const line = (key) => pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key] ?? 0).toFixed(1)}`).join(" ");
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Puan geçmişi">
      <line x1="0" x2="${W}" y1="${y(65)}" y2="${y(65)}" stroke="rgba(148,163,184,.25)" stroke-dasharray="3 3"/>
      <path d="${line("tech")}" fill="none" stroke="#38bdf8" stroke-width="1.3" opacity=".7"/>
      <path d="${line("fund")}" fill="none" stroke="#f59e0b" stroke-width="1.3" opacity=".7"/>
      <path d="${line("composite")}" fill="none" stroke="#22c55e" stroke-width="2"/>
    </svg>`;
    const first = pts[0], last = pts[pts.length - 1];
    $("historyNote").textContent = `${first.date} → ${last.date} · Bileşik (yeşil) ${first.composite} → ${last.composite} · Teknik (mavi) · Bilanço (turuncu) · kesikli çizgi: 65`;
  }

  function renderSourceChecks(f) {
    $("dataSourceLbl").textContent = f.data_source || "—";
    const body = $("sourceCheckBody");
    body.innerHTML = "";
    const checks = f.source_checks || [];
    if (!checks.length) {
      body.innerHTML = `<tr><td colspan="4" class="muted">SEC karşılaştırması yalnızca SEC'e rapor veren ABD şirketlerinde yapılır.</td></tr>`;
      return;
    }
    for (const c of checks) {
      const tr = document.createElement("tr");
      const big = c.diff_pct !== null && Math.abs(c.diff_pct) > 5;
      tr.innerHTML = `<td>${escapeHtml(c.item)}</td><td class="num">${fmtBig(c.sec)}</td><td class="num">${fmtBig(c.yahoo)}</td>
        <td class="num" style="color:${big ? "#f59e0b" : "inherit"}">${c.diff_pct !== null ? fmtPct(c.diff_pct, 1, true) : "—"}</td>`;
      body.appendChild(tr);
    }
  }

  function renderPeers(f) {
    const p = f.peers || {};
    const pc = p.percentiles || {};
    const names = { ev_ebitda: "FD/FAVÖK (ucuzluk)", pe: "F/K (ucuzluk)", fcf_yield: "FCF getirisi", roic: "ROIC", ebit_margin: "Faaliyet marjı", rev_growth: "Büyüme" };
    const rows = [{ k: "Kıyas grubu", v: `${(p.group || "—").replace(/^(us|bist):/, "")} · ${p.count || 0} hisse` }];
    if (!p.used) {
      rows.push({ k: "Durum", v: `Kıyas için en az ${p.min_count || 5} hissenin güncel verisi gerekir; arka plan görevi günde bir toplar.` });
    } else {
      for (const [k, label] of Object.entries(names)) {
        const v = pc[k];
        rows.push({ k: `${label} — sektör içi sıra`, v: v === null || v === undefined ? "—" : `%${v} (100 = en iyi)`, cls: v >= 67 ? "pos" : v !== null && v <= 33 ? "neg" : "" });
      }
    }
    const c = f.cyclical || {};
    rows.push({ k: "Döngüsel sektör", v: c.is_cyclical_industry ? "Evet" : "Hayır" });
    rows.push({ k: "Faaliyet marjı: güncel / ort.", v: `${fmtPct(c.current_ebit_margin_pct, 1)} / ${fmtPct(c.avg_ebit_margin_pct, 1)} (${c.years_in_average || 0} yıl)`, cls: c.peak_margin ? "warn" : "" });
    if (c.peak_margin && c.normalized_pe) rows.push({ k: "Normalize F/K (ort. marjla)", v: fmtNum(c.normalized_pe, 1), cls: "warn" });
    renderKV("peerBox", rows);
  }

  // --- Pozisyon boyutu ---
  function lsGet(k, d) {
    try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; }
  }
  function lsSet(k, v) {
    try { localStorage.setItem(k, v); } catch { /* yoksay */ }
  }

  function setupPositionCard(data) {
    const pos = data.position || {};
    const cur = data.meta.currency;
    const capKey = `hr_capital_${data.meta.is_bist ? "bist" : "us"}`;
    $("posCapital").value = lsGet(capKey, data.meta.is_bist ? "200000" : "10000");
    $("posRisk").value = lsGet("hr_risk", "1");
    $("posMaxPct").value = lsGet("hr_maxpct", "25");
    const sel = $("posStopSel");
    sel.innerHTML = "";
    for (const o of pos.stop_options || []) {
      const opt = document.createElement("option");
      opt.value = String(o.price);
      opt.textContent = `${o.label}: ${fmtNum(o.price)} ${cur} (−%${fmtNum(o.distance_pct, 1)})`;
      sel.appendChild(opt);
    }
    const custom = document.createElement("option");
    custom.value = "custom";
    custom.textContent = "Özel stop fiyatı…";
    sel.appendChild(custom);
    $("posCustomWrap").classList.toggle("hidden", sel.value !== "custom");
    state.positionPlan = null;
    $("positionBox").innerHTML = "";
    $("positionWarn").innerHTML = "";
    $("positionNote").textContent = "Sermaye ve risk yüzdesini girip Hesapla'ya basın. Değerler bu tarayıcıda hatırlanır.";
  }

  async function calcPosition() {
    const data = state.currentData;
    if (!data) return;
    const sel = $("posStopSel").value;
    const stop = sel === "custom" ? Number($("posCustomStop").value) : Number(sel);
    const body = {
      entry: data.technical.price,
      stop,
      capital: Number($("posCapital").value),
      risk_pct: Number($("posRisk").value),
      max_position_pct: Number($("posMaxPct").value) || 100,
      lot_size: (data.position && data.position.lot_size) || 1,
      avg_turnover: (data.position && data.position.avg_turnover_20d) || null,
    };
    lsSet(`hr_capital_${data.meta.is_bist ? "bist" : "us"}`, String(body.capital));
    lsSet("hr_risk", String(body.risk_pct));
    lsSet("hr_maxpct", String(body.max_position_pct));
    let plan;
    try {
      plan = await fetchJson("/api/position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      $("positionWarn").innerHTML = `<li>${escapeHtml(err.message)}</li>`;
      return;
    }
    state.positionPlan = plan;
    const cur = data.meta.currency;
    renderKV("positionBox", [
      { k: "Alınacak adet", v: `${plan.shares.toLocaleString("tr-TR")} adet`, cls: plan.shares ? "pos" : "neg" },
      { k: "Giriş / Stop", v: `${fmtNum(plan.entry)} / ${fmtNum(plan.stop)} ${cur} (−%${fmtNum(plan.stop_distance_pct, 2)})` },
      { k: "Pozisyon tutarı", v: `${fmtNum(plan.position_value)} ${cur} (sermayenin %${fmtNum(plan.position_pct_of_capital, 1)})` },
      { k: "Stop olursa en fazla zarar", v: `${fmtNum(plan.max_loss)} ${cur} (%${fmtNum(plan.actual_risk_pct, 2)})`, cls: "neg" },
      ...plan.targets.map((t) => ({ k: `${t.r}R kâr al`, v: `${fmtNum(t.price)} ${cur} (+%${fmtNum(t.pct, 1)} · +${fmtNum(t.gain)} ${cur})`, cls: "pos" })),
      { k: "Sınırlayan", v: plan.limited_by === "risk" ? "Risk bütçesi" : "Sermaye üst sınırı" },
    ]);
    $("positionWarn").innerHTML = (plan.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");
    $("positionNote").textContent = plan.note || "";
    drawPositionLines(state.chartCurrency === "usd");
  }

  function drawPositionLines(useUsd) {
    const candles = state.chartSeries && state.chartSeries.candles;
    if (!candles) return;
    for (const l of state.positionLines) {
      try { candles.removePriceLine(l); } catch { /* yoksay */ }
    }
    state.positionLines = [];
    const plan = state.positionPlan;
    if (!plan || useUsd) return; // USD grafikte fiyatlar farkli birimde
    const mk = (price, color, title, style = 2) =>
      candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    state.positionLines.push(mk(plan.entry, "#94a3b8", "Giriş", 0));
    state.positionLines.push(mk(plan.stop, "#ef4444", "Stop"));
    for (const t of plan.targets) state.positionLines.push(mk(t.price, "#22c55e", `${t.r}R`));
  }

  // --- Super Tarayici ---
  async function initScanner() {
    if (!state.scanPresets.length) {
      try {
        const data = await fetchJson("/api/scan/presets");
        state.scanPresets = data.presets || [];
      } catch (err) {
        $("scanStatus").textContent = `Filtreler yüklenemedi: ${err.message}`;
        return;
      }
    }
    renderPresetButtons();
    runScan();
  }

  function evidenceTag(ev) {
    if (!ev) return { cls: "neutral", text: "test sonucu yok" };
    if (ev.testable === false) return { cls: "neutral", text: "bilanço filtresi · test edilemez" };
    const v = ev.verdict || "";
    const cls = v.startsWith("endeksi ve evreni") ? "good" : v.startsWith("evrenin gerisinde") ? "bad" : "neutral";
    return { cls, text: `geçmiş: ${v}` };
  }

  function renderPresetButtons() {
    const box = $("scanPresets");
    box.innerHTML = "";
    const all = [...state.scanPresets, { key: "ozel", name: "Özel Filtre", description: "Kendi eşiklerin", evidence: {} }];
    for (const p of all) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `scan-preset${p.key === state.scanPreset ? " active" : ""}`;
      const tag = p.key === "ozel" ? { cls: "neutral", text: "kendi eşiklerin" } : evidenceTag((p.evidence || {})[state.scanMarket]);
      b.innerHTML = `${escapeHtml(p.name)}<span class="sp-tag ${tag.cls}">${escapeHtml(tag.text)}</span>`;
      b.title = p.description || "";
      b.addEventListener("click", () => {
        state.scanPreset = p.key;
        renderPresetButtons();
        $("scanCustomForm").classList.toggle("hidden", p.key !== "ozel");
        if (p.key !== "ozel") runScan();
      });
      box.appendChild(b);
    }
  }

  function renderEvidence(res) {
    const el = $("scanEvidence");
    const p = res.preset;
    const ev = res.evidence;
    const conds = (p.conditions || []).map((c) => escapeHtml(c.label)).join(" · ");
    let html = `<strong>${escapeHtml(p.name)}</strong> — ${escapeHtml(p.description || "")}<div class="muted" style="margin-top:4px">${conds}</div>`;
    if (ev && ev.testable && ev.signals) {
      const b = ev.baseline || {};
      html += `<div class="ev-grid">
        <span>Geçmiş sinyal: <strong>${ev.signals}</strong></span>
        <span>6 ay sonra endekse göre medyan: <strong>${fmtPct(ev.median, 1, true)}</strong> (evren ${fmtPct(b.median, 1, true)})</span>
        <span>Endeksi yenme: <strong>%${fmtNum(ev.hit_pct, 1)}</strong> (evren %${fmtNum(b.hit_pct, 1)})</span>
        <span>Aynı ay ortalamasına göre: <strong>${fmtPct(ev.vs_month_mean, 1, true)}</strong></span>
        <span>Sonuç: <strong>${escapeHtml(ev.verdict)}</strong></span>
      </div>`;
      if ((ev.untested || []).length) html += `<div class="muted" style="font-size:12px;margin-top:4px">Test edilmeyen koşullar: ${escapeHtml(ev.untested.join(", "))}</div>`;
    } else if (ev && ev.testable === false) {
      html += `<div class="muted" style="font-size:12px;margin-top:4px">${escapeHtml(ev.note || "Geriye dönük test edilemez.")}</div>`;
    } else if (p.key !== "ozel") {
      html += `<div class="muted" style="font-size:12px;margin-top:4px">Bu piyasa için geriye dönük test sonucu yok.</div>`;
    }
    el.innerHTML = html;
  }

  async function runScan() {
    const params = new URLSearchParams({ market: state.scanMarket, preset: state.scanPreset });
    if (state.scanPreset === "ozel") {
      for (const [id, key] of [["scMinComp", "min_composite"], ["scMinTech", "min_tech"], ["scMinFund", "min_fund"], ["scMinFlow", "min_flow_1w"]]) {
        const v = $(id).value;
        if (v !== "") params.set(key, v);
      }
    }
    $("scanStatus").textContent = "Taranıyor… (para akışı verisi ilk seferde 10–20 sn sürebilir)";
    $("scanBody").innerHTML = "";
    let res;
    try {
      res = await fetchJson(`/api/scan?${params}`);
    } catch (err) {
      $("scanStatus").textContent = `Tarama hatası: ${err.message}`;
      return;
    }
    renderEvidence(res);
    const parts = [`${res.matches.length} hisse filtreyi geçti · taranan ${res.scanned}/${res.universe}`];
    if (res.data_dates) parts.push(`veri: ${res.data_dates[0]} – ${res.data_dates[1]}`);
    if (res.undecided) parts.push(`${res.undecided} hissede veri eksikliğinden karar verilemedi`);
    if (!res.flow_available) parts.push("para akışı verisi alınamadı (akış koşulları değerlendirilemedi)");
    if (res.scanned < res.universe * 0.8) parts.push("bazı hisselerin güncel analizi yok — arka plan görevi günde bir tamamlar");
    $("scanStatus").textContent = parts.join(" · ");
    const body = $("scanBody");
    if (!res.matches.length) {
      body.innerHTML = `<tr><td colspan="14" class="muted">Bu filtreyi şu an geçen hisse yok.</td></tr>`;
      return;
    }
    for (const r of res.matches) {
      const tr = document.createElement("tr");
      const flow = (v) => (v === null || v === undefined ? "—" : `<span style="color:${v >= 0 ? "#22c55e" : "#ef4444"}">${v > 0 ? "+" : ""}${v}</span>`);
      tr.innerHTML = `
        <td><strong class="mono">${escapeHtml(r.display_symbol)}</strong><div class="muted" style="font-size:11px;max-width:160px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(r.name || "")}</div></td>
        <td class="muted" style="font-size:12px">${escapeHtml(r.theme || r.sector || "—")}</td>
        <td class="num"><span class="score-chip ${scoreClass(r.composite_score)}">${r.composite_score}</span></td>
        <td class="num"><span class="score-chip ${scoreClass(r.tech_score)}">${r.tech_score}</span></td>
        <td class="num"><span class="score-chip ${scoreClass(r.fund_score)}">${r.fund_score}</span></td>
        <td class="num">${flow(r.flow_1w)}</td>
        <td class="num">${flow(r.flow_1m)}</td>
        <td class="num">${r.rs ?? "—"}</td>
        <td class="mono">${escapeHtml(r.minervini || "—")}</td>
        <td class="num">${fmtPct(r.roic_pct, 1)}</td>
        <td class="mono">${escapeHtml(r.piotroski || "—")}</td>
        <td class="num">${r.earnings_days !== null && r.earnings_days !== undefined ? r.earnings_days + " g" : "—"}</td>
        <td class="num">${r.analyst_upside_pct !== null && r.analyst_upside_pct !== undefined ? fmtPct(r.analyst_upside_pct, 0, true) : "—"}</td>
        <td class="num muted" style="font-size:11px">${escapeHtml(r._date || "")}</td>`;
      tr.addEventListener("click", () => runAnalyze(r.symbol, r.is_bist ? "bist" : "us"));
      body.appendChild(tr);
    }
  }

  // --- Uyarilar ---
  async function loadAlerts() {
    try {
      const data = await fetchJson("/api/alerts?limit=50");
      renderAlerts(data.items || [], data.unseen || 0);
    } catch {
      /* uyarilar kritik degil */
    }
  }

  function renderAlerts(items, unseen) {
    const badge = $("alertsCount");
    badge.textContent = String(unseen);
    badge.classList.toggle("hidden", !unseen);
    const list = $("alertsList");
    list.innerHTML = items.length ? "" : `<li class="muted">Henüz uyarı yok.</li>`;
    for (const a of items) {
      const li = document.createElement("li");
      if (!a.seen) li.className = "unseen";
      li.innerHTML = `${escapeHtml(a.message)}<span class="al-date">${escapeHtml(a.created_at.replace("T", " "))}</span>`;
      list.appendChild(li);
    }
  }

  // Tum API cagrilari icin guvenli yardimci: sunucu JSON yerine HTML hata sayfasi donerse
  // anlamsiz "JSON parse" hatasi yerine anlasilir bir mesaj uretir; res.ok kontrolunu tek yerde yapar.
  async function fetchJson(url, options = {}) {
    let res;
    try {
      res = await fetch(url, options);
    } catch (err) {
      throw new Error("Sunucuya ulaşılamadı. Uygulamanın çalıştığından emin olun.");
    }
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(`Sunucu beklenmeyen bir yanıt döndürdü (HTTP ${res.status}).`);
    }
    if (!res.ok) {
      let detail = data && data.detail;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg || String(d)).join("; ");
      throw new Error(detail || `İstek başarısız (HTTP ${res.status}).`);
    }
    return data;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  // --- Chart (TradingView Lightweight Charts) ---
  function renderChart() {
    const data = state.currentData;
    if (!data || !data.technical || !data.technical.charts) return;
    const container = $("chartContainer");
    const useUsd = state.chartCurrency === "usd" && data.technical.charts.usd;
    const src = useUsd ? data.technical.charts.usd : data.technical.charts.primary;
    if (!src || !src.candles || !src.candles.length) return;

    if (state.chartObj) {
      state.chartObj.remove();
      state.chartObj = null;
    }
    container.innerHTML = "";

    const chart = LightweightCharts.createChart(container, {
      layout: {
        background: { type: "solid", color: "#0f141e" },
        textColor: "#94a3b8",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.07)" },
        horzLines: { color: "rgba(148, 163, 184, 0.07)" },
      },
      rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.16)" },
      timeScale: { borderColor: "rgba(148, 163, 184, 0.16)", timeVisible: false },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      width: container.clientWidth,
      height: 420,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const sliceCount = state.chartDays;
    const candles = sliceCount < src.candles.length ? src.candles.slice(-sliceCount) : src.candles;
    const minTime = candles[0].time;
    const filterByTime = (arr) => (arr || []).filter((p) => p.time >= minTime);

    candleSeries.setData(candles);

    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volSeries.setData(filterByTime(src.volumes));

    const overlaySpec = {
      sma50: { color: "#f59e0b", lineWidth: 1.8, lineStyle: 0 },
      sma150: { color: "#a855f7", lineWidth: 1.6, lineStyle: 0 },
      sma200: { color: "#38bdf8", lineWidth: 2, lineStyle: 0 },
      avwap_low: { color: "#22c55e", lineWidth: 1.6, lineStyle: 2 },
      avwap_high: { color: "#fb7185", lineWidth: 1.6, lineStyle: 2 },
    };

    state.chartSeries = { candles: candleSeries };
    document.querySelectorAll("#overlayToggles input[type=checkbox]").forEach((cb) => {
      const key = cb.dataset.ov;
      const spec = overlaySpec[key];
      const line = chart.addLineSeries({
        color: spec.color,
        lineWidth: spec.lineWidth,
        lineStyle: spec.lineStyle,
        priceLineVisible: false,
        lastValueVisible: false,
        visible: cb.checked,
      });
      line.setData(filterByTime(src[key]));
      state.chartSeries[key] = line;
    });

    const currLabel = useUsd ? "USD" : data.meta.currency;
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) return;
      const c = param.seriesData.get(candleSeries);
      if (c) {
        $("chartReadout").textContent =
          `${param.time}  |  A: ${fmtNum(c.open)}  Y: ${fmtNum(c.high)}  D: ${fmtNum(c.low)}  K: ${fmtNum(c.close)} ${currLabel}`;
      }
    });

    chart.timeScale().fitContent();
    state.chartObj = chart;
    drawPositionLines(useUsd);
  }

  window.addEventListener("resize", () => {
    if (state.chartObj && $("chartContainer").clientWidth > 0) {
      state.chartObj.applyOptions({ width: $("chartContainer").clientWidth });
    }
  });

  // --- Render Full Analysis ---
  function renderAnalysis(data) {
    state.currentData = data;
    state.chartCurrency = "primary";
    const { meta, verdict, technical: t, fundamental: f } = data;

    $("welcomeView").classList.add("hidden");
    $("flowView").classList.add("hidden");
    $("watchlistView").classList.add("hidden");
    $("scanView").classList.add("hidden");
    $("tabScan").classList.remove("active");
    $("analysisView").classList.remove("hidden");
    $("tabAnalysis").classList.add("active");
    $("tabFlow").classList.remove("active");
    $("tabWatchlist").classList.remove("active");
    $("printBtn").disabled = false;
    $("toggleWatchBtn").disabled = false;
    updateWatchButtonState();

    // Hero
    $("heroSymbol").textContent = meta.display_symbol;
    $("heroMarket").textContent = meta.market_label;
    $("heroSector").textContent = `${meta.sector} · ${meta.industry}`;
    $("heroName").textContent = meta.name;
    $("heroPrice").textContent = `${fmtNum(t.price)} ${meta.currency}`;
    const chgEl = $("heroChange");
    chgEl.textContent = fmtPct(t.daily_change_pct, 2, true);
    chgEl.className = `hero-change mono ${t.daily_change_pct >= 0 ? "up" : "down"}`;

    if (meta.is_bist && t.usd_analysis) {
      $("heroUsdPrice").textContent = `USD Bazlı: $${fmtNum(t.usd_analysis.price_usd, 3)} (Kur: ${fmtNum(t.usd_analysis.usdtry_last, 2)})`;
      $("heroUsdPrice").classList.remove("hidden");
    } else {
      $("heroUsdPrice").classList.add("hidden");
    }
    $("heroMeta").textContent = `Son işlem günü: ${t.last_date} · Piyasa Değeri: ${fmtBig(f.market_cap_trade, meta.currency_major || meta.currency)} · Güncelleme: ${meta.fetched_at}`;

    setGauge("gaugeComp", "scoreComp", verdict.composite_score);
    setGauge("gaugeTech", "scoreTech", t.score);
    setGauge("gaugeFund", "scoreFund", f.score);

    const vb = $("verdictBar");
    vb.className = `verdict-bar ${verdict.tone}`;
    $("verdictBadge").textContent = verdict.badge;
    $("verdictSummary").textContent = verdict.summary;
    $("verdictHighlights").innerHTML = (verdict.highlights || [])
      .map((h) => `<span class="hl-pill mono">${escapeHtml(h)}</span>`)
      .join("");

    // Flags
    const goodFlags = [...(t.flags_good || []), ...(f.flags_good || [])];
    const warnFlags = [...(t.flags_warn || []), ...(f.flags_warn || [])];
    $("flagsGoodList").innerHTML = goodFlags.length
      ? goodFlags.map((x) => `<li>${escapeHtml(x)}</li>`).join("")
      : `<li class="muted">Belirgin pozitif sinyal saptanmadı.</li>`;
    $("flagsWarnList").innerHTML = warnFlags.length
      ? warnFlags.map((x) => `<li>${escapeHtml(x)}</li>`).join("")
      : `<li class="muted">Kritik kırmızı bayrak saptanmadı.</li>`;

    const notesEl = $("specialNotes");
    if (f.notes && f.notes.length) {
      notesEl.innerHTML = f.notes.map((n) => `<div><strong>Not:</strong> ${escapeHtml(n)}</div>`).join("");
      notesEl.classList.remove("hidden");
    } else {
      notesEl.classList.add("hidden");
    }

    setupPositionCard(data);
    renderBreakdown("techBreakdown", t.score_breakdown, t.score, { note: t.backtest_evidence && t.backtest_evidence.note });
    renderBreakdown("fundBreakdown", f.score_breakdown, f.score, { coverage: f.data_coverage_pct, penalty: f.score_penalty });
    renderAnalyst(data.analysts, meta);
    renderRisk(data.earnings || {}, data.financing || {}, f);
    renderHistory(data.score_history);
    renderSourceChecks(f);
    renderPeers(f);

    // Chart currency toggle (only BIST)
    const currTog = $("currencyToggle");
    if (meta.is_bist && t.charts && t.charts.usd) {
      currTog.classList.remove("hidden");
      currTog.querySelectorAll(".mini-btn").forEach((b) => b.classList.toggle("active", b.dataset.curr === "primary"));
    } else {
      currTog.classList.add("hidden");
    }
    renderChart();

    // Technical section
    renderChecklist("techChecklist", t.checklist);
    $("minerviniBadge").textContent = `${t.minervini.passed}/${t.minervini.total}`;
    renderChecklist("minerviniList", t.minervini.checks);

    renderKV("stageRsBox", [
      { k: "Weinstein Evresi", v: t.weinstein.label, cls: t.weinstein.stage === 2 ? "pos" : t.weinstein.stage === 4 ? "neg" : "warn" },
      { k: "30 Haftalık SMA", v: t.weinstein.w_sma30 !== null ? `${fmtNum(t.weinstein.w_sma30)} ${meta.currency}` : "—" },
      { k: `Piyasa (${t.benchmark_regime.name})`, v: t.benchmark_regime.status },
      { k: "RS Tahmini (1–99, yüzdelik sıra değil)", v: t.relative_strength.rs_score_est ?? "—", cls: (t.relative_strength.rs_score_est || 0) >= 70 ? "pos" : (t.relative_strength.rs_score_est || 0) < 40 ? "neg" : "" },
      { k: "3A / 1Y Endeks Farkı", v: `${fmtPct(t.relative_strength.excess_3m, 1, true)} / ${fmtPct(t.relative_strength.excess_1y, 1, true)}` },
      { k: "Hisse Getiri (1A / 3A / 1Y)", v: `${fmtPct(t.returns["1m"], 1, true)} / ${fmtPct(t.returns["3m"], 1, true)} / ${fmtPct(t.returns["1y"], 1, true)}` },
      ...(t.usd_analysis ? [{ k: "1Y USD Bazlı Getiri", v: fmtPct(t.usd_analysis.ret_1y_usd, 1, true), cls: (t.usd_analysis.ret_1y_usd || 0) >= 0 ? "pos" : "neg" }] : []),
    ]);

    const vr = t.volatility_risk;
    renderKV("volRiskBox", [
      { k: "ATR (14) — Fiyat / %", v: vr.atr14 ? `${fmtNum(vr.atr14)} (${fmtPct(vr.atr_pct, 2)})` : "—" },
      { k: "ADR% (20 Gün — Qullamaggie)", v: fmtPct(vr.adr20_pct, 2) },
      { k: "VCP Daralma (10G / 50G ADR)", v: vr.vcp_ratio ? `${vr.vcp_ratio}x ${vr.vcp_tight ? "(Sıkışma)" : ""}` : "—", cls: vr.vcp_tight ? "pos" : "" },
      { k: "RVOL (Göreli Hacim) / 5G Kuruma", v: `${vr.rvol ?? "—"}x / ${vr.vol_dryup_ratio ?? "—"}x` },
      { k: "20G Ort. İşlem Hacmi", v: fmtBig(vr.avg_turnover_20d, meta.currency) },
      { k: "Yapısal Stop — 1 ADR", v: vr.stop_1adr ? `${fmtNum(vr.stop_1adr)} ${meta.currency}` : "—", cls: "warn" },
      { k: "Yapısal Stop — 1.5× / 2× ATR", v: vr.stop_15atr ? `${fmtNum(vr.stop_15atr)} / ${fmtNum(vr.stop_2atr)}` : "—" },
    ]);

    const ma = t.moving_averages;
    const av = t.avwap;
    const osc = t.oscillators;
    renderKV("avwapOscBox", [
      { k: "52H Dip AVWAP", v: av.low_52w ? `${fmtNum(av.low_52w)} (${av.above_low ? "Üstü" : "Altı"})` : "—", cls: av.above_low ? "pos" : "neg" },
      { k: "52H Zirve AVWAP", v: av.high_52w ? `${fmtNum(av.high_52w)} (${av.above_high ? "Üstü" : "Altı"})` : "—", cls: av.above_high ? "pos" : "warn" },
      { k: "Yılbaşı (YTD) AVWAP", v: av.ytd ? `${fmtNum(av.ytd)} (${av.above_ytd ? "Üstü" : "Altı"})` : "—", cls: av.above_ytd ? "pos" : "neg" },
      { k: "SMA 10 / 20 / 50", v: `${fmtNum(ma.sma10)} / ${fmtNum(ma.sma20)} / ${fmtNum(ma.sma50)}` },
      { k: "SMA 150 / 200", v: `${fmtNum(ma.sma150)} / ${fmtNum(ma.sma200)}` },
      { k: "50 SMA'dan Uzama", v: fmtPct(ma.ext_sma50_pct, 1, true), cls: (ma.ext_sma50_pct || 0) > 25 ? "warn" : "" },
      { k: "RSI (14) / MACD", v: `${fmtNum(osc.rsi14, 1)} / ${osc.macd_bullish ? "Pozitif" : "Negatif"}` },
    ]);

    // Fundamental section
    const pio = f.scores.piotroski;
    $("piotroskiBadge").textContent = pio.score !== null ? `${pio.score} / ${pio.available}` : "—";
    renderChecklist("piotroskiList", pio.items);
    renderChecklist("fundChecklist", f.checklist);

    const alt = f.scores.altman;
    const ben = f.scores.beneish;
    renderKV("altmanBeneishBox", [
      { k: "Altman Z-Score", v: alt.score !== null ? `${alt.score}` : "—", cls: alt.score > 2.99 ? "pos" : alt.score !== null && alt.score < 1.81 ? "neg" : "warn" },
      { k: "Altman Bölgesi", v: alt.zone },
      { k: "Beneish M-Score", v: ben.score !== null ? `${ben.score}` : "—", cls: ben.score !== null && ben.score < -1.78 ? "pos" : ben.score !== null ? "neg" : "" },
      { k: "Beneish Yorumu", v: ben.status },
    ]);
    renderKV("magicBox", [
      { k: "Kazanç Getirisi (EBIT / EV)", v: fmtPct(f.valuation.magic_ey_pct, 2), cls: (f.valuation.magic_ey_pct || 0) >= 8 ? "pos" : "" },
      { k: "Sermaye Getirisi (ROC)", v: fmtPct(f.valuation.magic_roc_pct, 2), cls: (f.valuation.magic_roc_pct || 0) >= 15 ? "pos" : "" },
    ]);

    const pr = f.profitability;
    renderKV("profitBox", [
      { k: "Brüt Kâr Marjı", v: fmtPct(pr.gross_margin_pct) },
      { k: "FAVÖK (EBITDA) Marjı", v: fmtPct(pr.ebitda_margin_pct) },
      { k: "Esas Faaliyet Kâr (EBIT) Marjı", v: fmtPct(pr.ebit_margin_pct) },
      { k: "Net Kâr Marjı", v: fmtPct(pr.net_margin_pct) },
      { k: "ROIC (Yatırılan Sermaye Getirisi)", v: fmtPct(pr.roic_pct), cls: (pr.roic_pct || 0) >= 15 ? "pos" : (pr.roic_pct !== null && pr.roic_pct < 6 ? "neg" : "") },
      { k: "ROCE (Kullanılan Sermaye Getirisi)", v: fmtPct(pr.roce_pct) },
      { k: "ROE (Özsermaye Kârlılığı)", v: fmtPct(pr.roe_pct), cls: (pr.roe_pct || 0) >= 18 ? "pos" : "" },
      { k: "ROA (Aktif Kârlılığı)", v: fmtPct(pr.roa_pct) },
    ]);

    const cq = f.cash_quality;
    renderKV("cashBox", [
      { k: "Faaliyet Nakit Akışı (OCF — TTM)", v: fmtBig(cq.ocf_ttm, f.financial_currency), cls: (cq.ocf_ttm || 0) > 0 ? "pos" : cq.ocf_ttm !== null ? "neg" : "" },
      { k: "Serbest Nakit Akışı (FCF — TTM)", v: fmtBig(cq.fcf_ttm, f.financial_currency), cls: (cq.fcf_ttm || 0) > 0 ? "pos" : cq.fcf_ttm !== null ? "neg" : "" },
      { k: "OCF / Net Kâr (Nakit Kalitesi)", v: cq.ocf_to_ni !== null ? `${fmtNum(cq.ocf_to_ni)}x` : "—", cls: (cq.ocf_to_ni || 0) >= 0.9 ? "pos" : (cq.ocf_to_ni !== null && cq.ocf_to_ni < 0.5 ? "neg" : "") },
      { k: "Nakit Dönüşümü (OCF / EBIT)", v: fmtPct(cq.cash_conv_ebit_pct, 1) },
      { k: "Serbest Nakit Akışı (FCF) Marjı", v: fmtPct(cq.fcf_margin_pct) },
      { k: "FCF Getirisi (FCF / EV)", v: fmtPct(cq.fcf_yield_pct), cls: (cq.fcf_yield_pct || 0) >= 5 ? "pos" : "" },
    ]);

    const bh = f.balance_health;
    renderKV("debtBox", [
      { k: "Nakit + Kısa Vadeli Yatırımlar", v: fmtBig(bh.cash, f.financial_currency) },
      { k: "Toplam Finansal Borç (kiralar dahil)", v: fmtBig(bh.total_debt, f.financial_currency) },
      { k: "— Kira (Leasing) Yükümlülüğü", v: fmtBig(bh.lease_liabilities, f.financial_currency) },
      { k: "Net Borç", v: bh.net_debt !== null ? (bh.net_debt < 0 ? `Net Nakit (${fmtBig(Math.abs(bh.net_debt), f.financial_currency)})` : fmtBig(bh.net_debt, f.financial_currency)) : "—", cls: bh.net_debt !== null && bh.net_debt < 0 ? "pos" : "" },
      { k: "Net Borç / FAVÖK", v: bh.net_debt_to_ebitda !== null ? `${fmtNum(bh.net_debt_to_ebitda)}x` : "—", cls: bh.net_debt_to_ebitda !== null && bh.net_debt_to_ebitda > 3.5 ? "neg" : (bh.net_debt_to_ebitda !== null && bh.net_debt_to_ebitda <= 1.5 ? "pos" : "") },
      { k: "Cari Oran", v: fmtNum(bh.current_ratio) },
      { k: "Asit-Test (Likidite) Oranı", v: fmtNum(bh.quick_ratio) },
      { k: "Faiz Karşılama (EBIT / Faiz)", v: bh.interest_coverage !== null ? `${fmtNum(bh.interest_coverage)}x` : "—", cls: (bh.interest_coverage || 0) >= 5 ? "pos" : (bh.interest_coverage !== null && bh.interest_coverage < 2 ? "neg" : "") },
      { k: "Toplam Borç / Özkaynak", v: bh.debt_to_equity !== null ? `${fmtNum(bh.debt_to_equity)}x` : "—" },
    ]);

    const val = f.valuation;
    const gr = f.growth;
    renderKV("valGrowthBox", [
      { k: "F/K (P/E) / İleri F/K", v: `${fmtNum(val.pe)} / ${fmtNum(val.forward_pe)}` },
      { k: "PD/DD (P/B) / Graham (F/K×PD/DD)", v: `${fmtNum(val.pb)} / ${fmtNum(val.graham_product)}` },
      { k: "FD/FAVÖK (EV/EBITDA)", v: val.ev_ebitda !== null ? `${fmtNum(val.ev_ebitda)}x` : "—" },
      { k: "FD/Satışlar / PEG Oranı", v: `${val.ev_sales !== null ? fmtNum(val.ev_sales) + "x" : "—"} / ${fmtNum(val.peg)}` },
      { k: f.growth_basis === "USD" ? "Yıllık Ciro / EBIT Büyümesi (USD bazlı)" : "Yıllık Ciro / EBIT Büyümesi", v: `${fmtPct(gr.rev_yoy_pct, 1, true)} / ${fmtPct(gr.ebit_yoy_pct, 1, true)}` },
      { k: "Çeyreklik (YoY) Ciro / Net Kâr", v: `${fmtPct(gr.q_rev_yoy_pct, 1, true)} / ${fmtPct(gr.q_ni_yoy_pct, 1, true)}` },
      { k: "Stok / Ticari Alacak Artışı (YoY)", v: `${fmtPct(gr.inv_yoy_pct, 1, true)} / ${fmtPct(gr.rec_yoy_pct, 1, true)}` },
      { k: "Hisse Seyreltme (Pay Artışı YoY)", v: fmtPct(gr.dilution_pct, 1, true), cls: (gr.dilution_pct || 0) > 10 ? "neg" : "" },
    ]);

    // Financial history table
    const asOf = f.data_as_of || {};
    $("finCurrNote").textContent = `Para birimi: ${f.financial_currency}` +
      (asOf.income_ttm_through ? ` · Son 12 ay: ${asOf.income_ttm_through} itibarıyla` : "") +
      (asOf.balance_sheet ? ` · Bilanço: ${asOf.balance_sheet}` : "");
    const body = $("finHistoryBody");
    body.innerHTML = "";
    if (!f.history_table || !f.history_table.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted">Yıllık finansal tablo verisi bulunamadı.</td></tr>`;
    } else {
      for (const row of f.history_table) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="mono"><strong>${escapeHtml(row.year)}</strong></td>
          <td class="num">${fmtBig(row.revenue)}</td>
          <td class="num">${fmtBig(row.ebitda)}</td>
          <td class="num">${fmtBig(row.ebit)}</td>
          <td class="num">${fmtBig(row.net_income)}</td>
          <td class="num">${fmtBig(row.ocf)}</td>
          <td class="num">${fmtBig(row.fcf)}</td>
          <td class="num">${fmtBig(row.net_debt)}</td>
        `;
        body.appendChild(tr);
      }
    }
  }

  // --- API Actions ---
  async function runAnalyze(rawSymbol, marketOverride = null, refresh = false) {
    const sym = (rawSymbol || "").trim();
    if (!sym) return;
    const mkt = marketOverride || state.market;
    $("symbolInput").value = sym.toUpperCase();
    showError("");
    setLoading(true, `${sym.toUpperCase()} analiz ediliyor…`);
    try {
      const payload = await fetchJson(`/api/analyze/${encodeURIComponent(sym)}?market=${encodeURIComponent(mkt)}&refresh=${refresh}`);
      renderAnalysis(payload);
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  // --- Watchlist ---
  async function loadWatchlistMeta() {
    try {
      const data = await fetchJson("/api/watchlist");
      state.watchlist = data.items || [];
      $("watchlistCount").textContent = String(state.watchlist.length);
      updateWatchButtonState();
    } catch (err) {
      showError(`İzleme listesi yüklenemedi: ${err.message}`);
    }
  }

  function isInWatchlist(sym) {
    if (!sym) return false;
    const up = sym.toUpperCase();
    return state.watchlist.some((x) => x.symbol.toUpperCase() === up);
  }

  function updateWatchButtonState() {
    const btn = $("toggleWatchBtn");
    if (!state.currentData) {
      btn.disabled = true;
      btn.textContent = "☆ İzle";
      return;
    }
    const inList = isInWatchlist(state.currentData.meta.symbol);
    btn.textContent = inList ? "★ İzleniyor" : "☆ İzle";
  }

  async function toggleCurrentWatchlist() {
    if (!state.currentData) return;
    const sym = state.currentData.meta.symbol;
    const mkt = state.currentData.meta.is_bist ? "bist" : "us";
    try {
      if (isInWatchlist(sym)) {
        const data = await fetchJson(`/api/watchlist/${encodeURIComponent(sym)}`, { method: "DELETE" });
        state.watchlist = data.items || [];
      } else {
        const data = await fetchJson("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: sym, market: mkt }),
        });
        state.watchlist = data.items || [];
      }
    } catch (err) {
      showError(`İzleme listesi güncellenemedi: ${err.message}`);
      return;
    }
    $("watchlistCount").textContent = String(state.watchlist.length);
    updateWatchButtonState();
    state.wlRows = []; // sonraki geciste yenilensin
  }

  async function scanWatchlist() {
    if (!state.watchlist.length) {
      $("wlTableBody").innerHTML = `<tr><td colspan="18" class="muted">İzleme listeniz boş. Yukarıdan hisse ekleyin.</td></tr>`;
      $("wlStatus").textContent = "";
      return;
    }
    $("wlStatus").textContent = `${state.watchlist.length} hisse paralel olarak taranıyor…`;
    $("wlRefreshBtn").disabled = true;
    try {
      const data = await fetchJson("/api/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: state.watchlist }),
      });
      state.wlRows = data.rows || [];
      const parts = [`${state.wlRows.length} hisse güncellendi.`];
      if (data.errors && data.errors.length) {
        parts.push(`Analiz edilemeyen: ${data.errors.map((e) => `${e.symbol} (${e.error})`).join(", ")}.`);
      }
      if (data.skipped && data.skipped.length) {
        parts.push(`Tek seferde en fazla ${data.limit} hisse taranır; atlanan: ${data.skipped.join(", ")}.`);
      }
      $("wlStatus").textContent = parts.join(" ");
      renderWatchlistTable();
    } catch (err) {
      $("wlStatus").textContent = `Tarama hatası: ${err.message}`;
    } finally {
      $("wlRefreshBtn").disabled = false;
    }
  }

  function renderWatchlistTable() {
    const rows = [...state.wlRows];
    const key = state.wlSortKey;
    const dir = state.wlSortDir;
    rows.sort((a, b) => {
      const va = a[key];
      const vb = b[key];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "string") return va.localeCompare(vb, "tr") * dir;
      return (va - vb) * dir;
    });

    const body = $("wlTableBody");
    body.innerHTML = "";
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <strong class="mono">${escapeHtml(r.display_symbol)}</strong>
          <div class="muted" style="font-size:11px;max-width:160px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(r.name)}</div>
        </td>
        <td class="num">${fmtNum(r.price)} ${escapeHtml(r.currency)}</td>
        <td class="num" style="color:${r.daily_change_pct >= 0 ? "#22c55e" : "#ef4444"}">${fmtPct(r.daily_change_pct, 2, true)}</td>
        <td class="num" style="color:${(r.ret_1y || 0) >= 0 ? "#22c55e" : "#ef4444"}">${fmtPct(r.ret_1y, 1, true)}</td>
        <td class="num"><span class="score-chip ${scoreClass(r.composite_score)}">${r.composite_score}</span></td>
        <td class="num"><span class="score-chip ${scoreClass(r.tech_score)}">${r.tech_score}</span></td>
        <td class="num"><span class="score-chip ${scoreClass(r.fund_score)}">${r.fund_score}</span></td>
        <td class="num">Evre ${r.stage || "—"}</td>
        <td class="mono">${escapeHtml(r.minervini)}</td>
        <td class="num">${r.rs ?? "—"}</td>
        <td class="mono">${escapeHtml(r.piotroski)}</td>
        <td class="num">${fmtPct(r.roic_pct, 1)}</td>
        <td class="num">${r.ev_ebitda !== null ? fmtNum(r.ev_ebitda, 1) + "x" : "—"}</td>
        <td class="num">${r.pe !== null ? fmtNum(r.pe, 1) : "—"}</td>
        <td class="num" style="color:${r.earnings_days !== null && r.earnings_days <= 7 ? "#f59e0b" : "inherit"}">${r.earnings_days !== null && r.earnings_days !== undefined ? r.earnings_days + " g" : "—"}</td>
        <td class="num" style="color:${(r.analyst_upside_pct || 0) >= 0 ? "#22c55e" : "#ef4444"}">${r.analyst_upside_pct !== null && r.analyst_upside_pct !== undefined ? fmtPct(r.analyst_upside_pct, 0, true) : "—"}</td>
        <td><span class="hl-pill">${escapeHtml(r.badge)}</span></td>
        <td class="no-print"><button type="button" class="del-btn" title="Listeden çıkar">×</button></td>
      `;
      tr.addEventListener("click", (e) => {
        if (e.target.closest(".del-btn")) return;
        runAnalyze(r.symbol, r.is_bist ? "bist" : "us");
      });
      tr.querySelector(".del-btn").addEventListener("click", async (e) => {
        e.stopPropagation();
        let data;
        try {
          data = await fetchJson(`/api/watchlist/${encodeURIComponent(r.symbol)}`, { method: "DELETE" });
        } catch (err) {
          $("wlStatus").textContent = `Silinemedi: ${err.message}`;
          return;
        }
        state.watchlist = data.items || [];
        state.wlRows = state.wlRows.filter((x) => x.symbol !== r.symbol);
        $("watchlistCount").textContent = String(state.watchlist.length);
        updateWatchButtonState();
        renderWatchlistTable();
      });
      body.appendChild(tr);
    }
  }

  // --- Money Flow & Theme Rotation ---
  const PERIOD_NAMES = { "1d": "Günlük (1G)", "1w": "Haftalık (1H)", "1m": "Aylık (1A)", "3m": "3 Aylık (3A)" };

  function flowClass(score) {
    if (score >= 30) return "strong-in";
    if (score >= 10) return "mild-in";
    if (score <= -30) return "strong-out";
    if (score <= -10) return "mild-out";
    return "neutral";
  }

  function heatStyle(score) {
    const s = Math.max(-100, Math.min(100, Number(score) || 0));
    if (s >= 10) {
      const a = (0.12 + (s / 100) * 0.34).toFixed(2);
      return `background:rgba(34,197,94,${a});color:#bbf7d0`;
    }
    if (s <= -10) {
      const a = (0.12 + (Math.abs(s) / 100) * 0.34).toFixed(2);
      return `background:rgba(239,68,68,${a});color:#fecaca`;
    }
    return `background:rgba(148,163,184,0.12);color:#cbd5e1`;
  }

  function rotTagClass(tag) {
    if (!tag) return "";
    if (tag.includes("Lider") || tag.includes("Erken") || tag.includes("Başlangıç")) return "pos";
    if (tag.includes("Çıkış") || tag.includes("Kâr")) return "warn";
    return "neg";
  }

  async function loadMoneyFlow(market = state.flowMarket, refresh = false) {
    state.flowMarket = market;
    $("flowLoading").classList.remove("hidden");
    $("flowContent").classList.add("hidden");
    $("flowRefreshBtn").disabled = true;
    $("flowLoadingText").textContent = `${market === "bist" ? "BIST" : "ABD / Global"} tema ve hisse para akışı hesaplanıyor…`;
    try {
      const data = await fetchJson(`/api/money-flow?market=${encodeURIComponent(market)}&refresh=${refresh}`);
      state.flowData[market] = data;
      state.flowThemeFilter = "ALL";
      const ex = data.excluded || {};
      const exParts = [];
      if ((ex.illiquid || []).length) exParts.push(`Düşük hacim nedeniyle hariç: ${ex.illiquid.map((s) => s.replace(".IS", "")).join(", ")}`);
      if ((ex.stale || []).length) exParts.push(`Güncel verisi olmayan: ${ex.stale.map((s) => s.replace(".IS", "")).join(", ")}`);
      $("flowSubtitle").textContent = [data.note, ...exParts].filter(Boolean).join(" · ");
      populateThemeFilter(data);
      renderMoneyFlow();
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      $("flowLoading").classList.add("hidden");
      $("flowRefreshBtn").disabled = false;
    }
  }

  function populateThemeFilter(data) {
    const sel = $("flowThemeFilter");
    sel.innerHTML = `<option value="ALL">Tüm Temalar (${data.stocks.length} Hisse)</option>`;
    for (const th of data.themes) {
      const opt = document.createElement("option");
      opt.value = th.name;
      opt.textContent = `${th.name} (${th.stock_count})`;
      sel.appendChild(opt);
    }
    sel.value = state.flowThemeFilter;
  }

  function renderMoneyFlow() {
    const data = state.flowData[state.flowMarket];
    if (!data) return;
    const pk = state.flowPeriod;
    const pName = PERIOD_NAMES[pk] || pk;

    $("flowContent").classList.remove("hidden");
    $("flowSubtitle").textContent = `${data.market_label} · ${data.themes.length} tema, ${data.stocks.length} likit hisse · Son veri: ${data.last_date}`;
    $("inflowPeriodLbl").textContent = pName;
    $("outflowPeriodLbl").textContent = pName;

    const themesSorted = [...data.themes].sort((a, b) => b.periods[pk].flow_score - a.periods[pk].flow_score);
    const bestTheme = themesSorted[0];
    const worstTheme = themesSorted[themesSorted.length - 1];
    const br = data.breadth[pk];
    const bRet = data.benchmark_returns[pk];

    // 4 KPI Cards
    $("flowKpis").innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">${escapeHtml(data.benchmark_name)} (${pName})</div>
        <div class="kpi-val mono" style="color:${(bRet || 0) >= 0 ? "#22c55e" : "#ef4444"}">${fmtPct(bRet, 2, true)}</div>
        <div class="kpi-sub mono">1G: ${fmtPct(data.benchmark_returns["1d"], 1, true)} · 1A: ${fmtPct(data.benchmark_returns["1m"], 1, true)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Piyasa Genişliği (Breadth)</div>
        <div class="kpi-val mono" style="color:${br.positive_pct >= 50 ? "#22c55e" : "#f59e0b"}">%${br.positive_pct} Pozitif</div>
        <div class="kpi-sub">${br.positive}/${br.total} yükselen · <span style="color:#4ade80">${br.inflow} giriş</span> · <span style="color:#f87171">${br.outflow} çıkış</span></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">En Güçlü Tema (${pName})</div>
        <div class="kpi-val" style="font-size:15px;color:#4ade80">${bestTheme ? escapeHtml(bestTheme.name) : "—"}</div>
        <div class="kpi-sub mono">${bestTheme ? `Skor: ${bestTheme.periods[pk].flow_score > 0 ? "+" : ""}${bestTheme.periods[pk].flow_score} · ${fmtPct(bestTheme.periods[pk].ret_pct, 2, true)} · RVOL ${bestTheme.periods[pk].rvol}x` : ""}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">En Zayıf Tema (${pName})</div>
        <div class="kpi-val" style="font-size:15px;color:#f87171">${worstTheme ? escapeHtml(worstTheme.name) : "—"}</div>
        <div class="kpi-sub mono">${worstTheme ? `Skor: ${worstTheme.periods[pk].flow_score > 0 ? "+" : ""}${worstTheme.periods[pk].flow_score} · ${fmtPct(worstTheme.periods[pk].ret_pct, 2, true)} · RVOL ${worstTheme.periods[pk].rvol}x` : ""}</div>
      </div>
    `;

    // Theme Flow Heatmap Rows
    const listEl = $("themeFlowList");
    listEl.innerHTML = "";
    for (const th of themesSorted) {
      const tp = th.periods[pk];
      const sc = tp.flow_score;
      const halfW = Math.min(50, Math.abs(sc) / 2);
      const isActive = state.flowThemeFilter === th.name;
      const row = document.createElement("div");
      row.className = `theme-row ${isActive ? "active-theme" : ""}`;
      row.innerHTML = `
        <div>
          <div class="theme-name">${escapeHtml(th.name)}</div>
          <div class="theme-meta">
            <span>Lider: <strong class="mono">${escapeHtml(th.top_stock)}</strong></span>
            <span>· ${tp.pos_count}/${tp.total} pozitif</span>
            ${th.rotation_tag ? `<span class="rot-tag ${rotTagClass(th.rotation_tag)}">${escapeHtml(th.rotation_tag)}</span>` : ""}
          </div>
        </div>
        <div class="bi-bar-wrap">
          <div class="bi-bar">
            <div class="bi-fill ${sc >= 0 ? "pos" : "neg"}" style="width:${halfW}%"></div>
          </div>
          <span class="bi-score mono" style="color:${sc >= 10 ? "#4ade80" : sc <= -10 ? "#f87171" : "#cbd5e1"}">${sc > 0 ? "+" : ""}${sc}</span>
        </div>
        <div class="theme-stats">
          <div class="st-item"><span class="st-lbl">Getiri</span><span style="color:${(tp.ret_pct || 0) >= 0 ? "#4ade80" : "#f87171"}">${fmtPct(tp.ret_pct, 1, true)}</span></div>
          <div class="st-item"><span class="st-lbl">RS Fark</span><span style="color:${(tp.rs_pct || 0) >= 0 ? "#38bdf8" : "#94a3b8"}">${fmtPct(tp.rs_pct, 1, true)}</span></div>
          <div class="st-item"><span class="st-lbl">RVOL</span><span>${tp.rvol ?? "—"}x</span></div>
          <div class="st-item"><span class="st-lbl">CMF</span><span>${tp.cmf !== null ? (tp.cmf > 0 ? "+" : "") + fmtNum(tp.cmf, 2) : "—"}</span></div>
        </div>
        <div class="heat-strip" title="1G / 1H / 1A / 3A Para Akışı Skorları">
          <div class="heat-cell" style="${heatStyle(th.periods["1d"].flow_score)}"><span>1G</span>${th.periods["1d"].flow_score > 0 ? "+" : ""}${th.periods["1d"].flow_score}</div>
          <div class="heat-cell" style="${heatStyle(th.periods["1w"].flow_score)}"><span>1H</span>${th.periods["1w"].flow_score > 0 ? "+" : ""}${th.periods["1w"].flow_score}</div>
          <div class="heat-cell" style="${heatStyle(th.periods["1m"].flow_score)}"><span>1A</span>${th.periods["1m"].flow_score > 0 ? "+" : ""}${th.periods["1m"].flow_score}</div>
          <div class="heat-cell" style="${heatStyle(th.periods["3m"].flow_score)}"><span>3A</span>${th.periods["3m"].flow_score > 0 ? "+" : ""}${th.periods["3m"].flow_score}</div>
        </div>
      `;
      row.addEventListener("click", () => {
        state.flowThemeFilter = state.flowThemeFilter === th.name ? "ALL" : th.name;
        $("flowThemeFilter").value = state.flowThemeFilter;
        renderMoneyFlow();
      });
      listEl.appendChild(row);
    }

    // Top 10 Inflow & Top 10 Outflow
    const byFlow = [...data.stocks].sort((a, b) => b.periods[pk].flow_score - a.periods[pk].flow_score);
    const renderTop = (tbodyId, arr) => {
      const tb = $(tbodyId);
      tb.innerHTML = "";
      for (const s of arr) {
        const sp = s.periods[pk];
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong class="mono">${escapeHtml(s.display_symbol)}</strong></td>
          <td class="muted" style="font-size:12px">${escapeHtml(s.theme)}</td>
          <td class="num" style="color:${(sp.ret_pct || 0) >= 0 ? "#4ade80" : "#f87171"}">${fmtPct(sp.ret_pct, 2, true)}</td>
          <td class="num">${sp.rvol ?? "—"}x</td>
          <td class="num">${sp.cmf !== null ? (sp.cmf > 0 ? "+" : "") + fmtNum(sp.cmf, 2) : "—"}</td>
          <td class="num"><span class="flow-pill ${flowClass(sp.flow_score)}">${sp.flow_score > 0 ? "+" : ""}${sp.flow_score}</span></td>
        `;
        tr.addEventListener("click", () => runAnalyze(s.symbol, s.is_bist ? "bist" : "us"));
        tb.appendChild(tr);
      }
    };
    renderTop("topInflowBody", byFlow.slice(0, 10));
    renderTop("topOutflowBody", [...byFlow].reverse().slice(0, 10));

    renderFlowStockTable();
  }

  function renderFlowStockTable() {
    const data = state.flowData[state.flowMarket];
    if (!data) return;
    const pk = state.flowPeriod;
    const q = state.flowSearch.trim().toUpperCase();

    let rows = data.stocks.filter((s) => {
      if (state.flowThemeFilter !== "ALL" && s.theme !== state.flowThemeFilter) return false;
      if (q && !s.display_symbol.toUpperCase().includes(q) && !s.theme.toUpperCase().includes(q)) return false;
      return true;
    });

    const getVal = (s, k) => {
      if (k === "display_symbol" || k === "theme" || k === "price") return s[k];
      if (k === "ret_1d") return s.periods["1d"].ret_pct;
      if (k === "ret_1w") return s.periods["1w"].ret_pct;
      if (k === "ret_1m") return s.periods["1m"].ret_pct;
      if (k === "ret_3m") return s.periods["3m"].ret_pct;
      return s.periods[pk][k];
    };

    const sk = state.flowSortKey;
    const dir = state.flowSortDir;
    rows.sort((a, b) => {
      const va = getVal(a, sk);
      const vb = getVal(b, sk);
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "string") return va.localeCompare(vb, "tr") * dir;
      return (va - vb) * dir;
    });

    const tb = $("flowStockBody");
    tb.innerHTML = "";
    for (const s of rows) {
      const sp = s.periods[pk];
      const tr = document.createElement("tr");
      const retCell = (v) => `<td class="num" style="color:${(v || 0) >= 0 ? "#4ade80" : "#f87171"}">${fmtPct(v, 1, true)}</td>`;
      tr.innerHTML = `
        <td><strong class="mono">${escapeHtml(s.display_symbol)}</strong></td>
        <td class="muted" style="font-size:12px">${escapeHtml(s.theme)}</td>
        <td class="num">${fmtNum(s.price)} ${escapeHtml(s.currency)}</td>
        ${retCell(s.periods["1d"].ret_pct)}
        ${retCell(s.periods["1w"].ret_pct)}
        ${retCell(s.periods["1m"].ret_pct)}
        ${retCell(s.periods["3m"].ret_pct)}
        <td class="num">${sp.rvol ?? "—"}x</td>
        <td class="num" style="color:${(sp.cmf || 0) >= 0 ? "#4ade80" : "#f87171"}">${sp.cmf !== null ? (sp.cmf > 0 ? "+" : "") + fmtNum(sp.cmf, 2) : "—"}</td>
        <td class="num">${fmtBig(sp.turnover, s.currency)}</td>
        <td class="num"><span class="flow-pill ${flowClass(sp.flow_score)}">${sp.flow_score > 0 ? "+" : ""}${sp.flow_score}</span></td>
        <td>
          <span class="hl-pill">${escapeHtml(sp.label)}</span>
          ${s.rotation_tag ? `<span class="rot-tag ${rotTagClass(s.rotation_tag)}" style="margin-left:4px">${escapeHtml(s.rotation_tag)}</span>` : ""}
        </td>
      `;
      tr.addEventListener("click", () => runAnalyze(s.symbol, s.is_bist ? "bist" : "us"));
      tb.appendChild(tr);
    }
  }

  // --- Event Listeners ---
  $("marketPills").addEventListener("click", (e) => {
    const btn = e.target.closest(".pill");
    if (!btn) return;
    state.market = btn.dataset.market;
    $("marketPills").querySelectorAll(".pill").forEach((b) => b.classList.toggle("active", b === btn));
  });

  $("searchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    runAnalyze($("symbolInput").value);
  });

  $("quickChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    runAnalyze(chip.dataset.sym, chip.dataset.market);
  });

  $("brandHome").addEventListener("click", () => switchView("analysis"));
  $("tabAnalysis").addEventListener("click", () => switchView("analysis"));
  $("tabFlow").addEventListener("click", () => switchView("flow"));
  $("tabWatchlist").addEventListener("click", () => switchView("watchlist"));
  $("tabScan").addEventListener("click", () => switchView("scan"));
  document.querySelectorAll("#scanMarketToggle .mini-btn").forEach((b) => {
    b.addEventListener("click", () => {
      state.scanMarket = b.dataset.mkt;
      document.querySelectorAll("#scanMarketToggle .mini-btn").forEach((x) => x.classList.toggle("active", x === b));
      renderPresetButtons();
      runScan();
    });
  });
  $("scanCustomForm").addEventListener("submit", (e) => {
    e.preventDefault();
    runScan();
  });
  $("positionForm").addEventListener("submit", (e) => {
    e.preventDefault();
    calcPosition();
  });
  $("posStopSel").addEventListener("change", () => {
    $("posCustomWrap").classList.toggle("hidden", $("posStopSel").value !== "custom");
  });
  $("posClear").addEventListener("click", () => {
    state.positionPlan = null;
    drawPositionLines(false);
  });
  $("toggleWatchBtn").addEventListener("click", toggleCurrentWatchlist);
  $("printBtn").addEventListener("click", () => window.print());

  $("flowMarketToggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".mini-btn");
    if (!btn) return;
    const mkt = btn.dataset.fmkt;
    $("flowMarketToggle").querySelectorAll(".mini-btn").forEach((b) => b.classList.toggle("active", b === btn));
    if (state.flowData[mkt]) {
      state.flowMarket = mkt;
      state.flowThemeFilter = "ALL";
      populateThemeFilter(state.flowData[mkt]);
      renderMoneyFlow();
    } else {
      loadMoneyFlow(mkt, false);
    }
  });

  $("flowPeriodToggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".mini-btn");
    if (!btn) return;
    state.flowPeriod = btn.dataset.fp;
    $("flowPeriodToggle").querySelectorAll(".mini-btn").forEach((b) => b.classList.toggle("active", b === btn));
    renderMoneyFlow();
  });

  $("flowRefreshBtn").addEventListener("click", () => loadMoneyFlow(state.flowMarket, true));
  $("flowThemeFilter").addEventListener("change", (e) => {
    state.flowThemeFilter = e.target.value;
    renderMoneyFlow();
  });
  $("flowSearchInput").addEventListener("input", (e) => {
    state.flowSearch = e.target.value;
    renderFlowStockTable();
  });
  document.querySelectorAll("#flowStockTable th[data-fsort]").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.fsort;
      if (state.flowSortKey === k) state.flowSortDir *= -1;
      else {
        state.flowSortKey = k;
        state.flowSortDir = (k === "display_symbol" || k === "theme") ? 1 : -1;
      }
      renderFlowStockTable();
    });
  });

  $("currencyToggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".mini-btn");
    if (!btn) return;
    state.chartCurrency = btn.dataset.curr;
    $("currencyToggle").querySelectorAll(".mini-btn").forEach((b) => b.classList.toggle("active", b === btn));
    renderChart();
  });

  $("rangeToggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".mini-btn");
    if (!btn) return;
    state.chartDays = Number(btn.dataset.days);
    $("rangeToggle").querySelectorAll(".mini-btn").forEach((b) => b.classList.toggle("active", b === btn));
    renderChart();
  });

  $("overlayToggles").addEventListener("change", (e) => {
    const cb = e.target;
    if (cb.type !== "checkbox") return;
    const s = state.chartSeries[cb.dataset.ov];
    if (s) s.applyOptions({ visible: cb.checked });
  });

  $("wlAddForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const sym = $("wlInput").value.trim();
    const mkt = $("wlMarket").value;
    if (!sym) return;
    $("wlStatus").textContent = `${sym.toUpperCase()} ekleniyor…`;
    let data;
    try {
      data = await fetchJson("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, market: mkt }),
      });
    } catch (err) {
      $("wlStatus").textContent = `Eklenemedi: ${err.message}`;
      return;
    }
    $("wlInput").value = "";
    state.watchlist = data.items || [];
    $("watchlistCount").textContent = String(state.watchlist.length);
    updateWatchButtonState();
    scanWatchlist();
  });

  $("wlRefreshBtn").addEventListener("click", scanWatchlist);

  document.querySelectorAll("#wlTable th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (state.wlSortKey === k) state.wlSortDir *= -1;
      else {
        state.wlSortKey = k;
        state.wlSortDir = k === "display_symbol" ? 1 : -1;
      }
      renderWatchlistTable();
    });
  });

  $("alertsBtn").addEventListener("click", async (e) => {
    e.stopPropagation();
    const panel = $("alertsPanel");
    const opening = panel.classList.contains("hidden");
    panel.classList.toggle("hidden");
    if (opening) {
      await loadAlerts();
      try {
        await fetchJson("/api/alerts/seen", { method: "POST" });
        $("alertsCount").classList.add("hidden");
      } catch { /* yoksay */ }
    }
  });
  $("alertsCheckBtn").addEventListener("click", async (e) => {
    e.stopPropagation();
    const btn = $("alertsCheckBtn");
    btn.disabled = true;
    btn.textContent = "Kontrol ediliyor…";
    try {
      const data = await fetchJson("/api/alerts/check", { method: "POST" });
      renderAlerts(data.items || [], 0);
    } catch (err) {
      showError(`Uyarı kontrolü başarısız: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Şimdi kontrol et";
    }
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".alerts-wrap")) $("alertsPanel").classList.add("hidden");
  });

  // Init
  loadWatchlistMeta();
  loadAlerts();
  setInterval(loadAlerts, 5 * 60 * 1000);
})();
