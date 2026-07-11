# Analysis: automating Figure 6 (accuracy-degradation cause classification)

Source: Shiono & Kubo (2026, NAVIGATION), Figure 6 —
"Flowchart for classifying primary causes of accuracy degradation events".
Goal (founder, 2026-07-11): automate this decision process to drive the
Pro report §5 今月のイベント. Flagged by the founder as hard / needing
study — this doc is the study.

## 1. What the flowchart actually is

A per-(compact-network, day) decision tree. It first asks whether the day
is a *degradation event*, then walks a sequence of tests to assign ONE
primary cause. Decoded from the figure:

```
Start
└─ Daily 95% Err > PS ?               (H or V, static or kinematic)
   ├─ No  → NORMAL
   └─ Yes → Dst < −150 nT ?
            ├─ Yes → GEOMAGNETIC STORM
            └─ No  → Ionospheric disturbance (dTEC/ROTI map) ?
                     ├─ Yes (ionospheric branch)
                     │   ├─ Wave-like pattern (dTEC) ?
                     │   │   ├─ Yes → spatiotemporal aligned ? → MSTID / (fall through)
                     │   │   └─ No  → (fall through)
                     │   └─ # Cycle slips > 100 ?
                     │       ├─ Yes → spatiotemporal aligned ? → PBs / OTHER-COMPLEX
                     │       └─ No  → OTHER-COMPLEX
                     └─ No (non-ionospheric branch)
                         ├─ Tropospheric divergence (CSSR) ?
                         │   ├─ Yes → spatiotemporal aligned ? → TROPOSPHERIC / (fall through)
                         │   └─ No  → (fall through)
                         └─ Other corrections spliced/discontinued ?
                             ├─ Yes → spatiotemporal aligned ? → OTHER-CORRECTIONS / UNIDENTIFIED
                             └─ No  → UNIDENTIFIED
```

Terminal classes (8): Normal, Geomagnetic Storm, MSTID, PBs,
Other/Complex, Tropospheric Divergence, Other Corrections, Unidentified.

**Critical caveat from the caption itself:** "Although the flowchart
depicts a sequential decision tree, in practice, all available data
sources … were comprehensively examined for each event … Cases in which
multiple indicators were present simultaneously were resolved through
spatiotemporal alignment analysis to determine the dominant mechanism."
→ The published classification was **expert-in-the-loop**, not a pure
algorithm. The "Check Spatiotemporal Alignment" boxes are where human
judgment entered. Any automation must decide how to handle those.

## 2. Per-node data inventory (what we have TODAY)

| Node | Signal needed | Pipeline source | Status |
|---|---|---|---|
| Daily 95% > PS | per-network daily H95/V95 vs PS-QZSS | `epoch_errors` (per-day) → new daily network rollup; PS thresholds already encoded | ✅ HAVE (one aggregation away; monthly network cube exists, daily does not yet) |
| Dst < −150 nT | hourly Dst index | — (external: WDC Kyoto) | ⚠️ EASY FETCH — single hourly scalar series, small acquisition module |
| # Cycle slips > 100 | Σ mean daily CS/station across networks | `qc_summary` `*_slps` bins (ION, MP12/21/15/51, …) — same definition as the QC report's `dist_slips` | ✅ HAVE |
| Ionospheric disturbance (dTEC/ROTI) | dTEC / ROTI maps | — (external: NICT / GEONET-derived) | ❌ MISSING — spatial map ingest, heavy |
| Wave-like pattern → MSTID | MSTID wave-signature detection on dTEC | dTEC maps + detector | ❌ HARD — needs the dTEC ingest above + a detection algorithm |
| Tropospheric divergence (CSSR) | CSSR troposphere-correction anomaly | L6 archive — but we only decode **Alert flags** (`l6_alerts` = date/prn/tow/time_utc), NOT the CSSR correction payload | ❌ CSSR payload not decoded |
| Other corrections spliced/discontinued | CSSR correction continuity | same as above | ❌ CSSR payload not decoded |
| Check spatiotemporal alignment | degradation timing/location vs disturbance map | multiple | ❌ HARD / expert judgment |

## 3. Difficulty tiers

- **Deterministic & automatable now** — event trigger (daily per-network
  95% > PS), Geomagnetic-Storm branch (once Dst is fetched), and the
  high-CS gate (CS > 100 from `qc_summary`). These cover the *entry* of
  the tree and 1–2 terminal classes outright.
- **New acquisition, still deterministic** — Dst module (small); a dTEC/
  ROTI ingest (large, and only *then* can MSTID detection begin).
- **Needs new decoding** — CSSR troposphere / correction-continuity → a
  proper CSSR payload decoder on the L6 archive (we have the bytes, not
  the parsed corrections).
- **Irreducibly judgment-heavy** — every "spatiotemporal alignment" box.
  The authors resolved these by eye across all sources; a v1 automation
  should *surface the evidence* and let a reviewer confirm, not fake it.

## 4. Proposed phased approach

**Phase A — Event detection + evidence dossier (automatable now).**
Build `analysis/event_detection.py`: daily per-network 95% H/V vs PS →
degradation-event flags (this IS the paper's event definition and also
feeds §9 要注意局). For each event, auto-attach the cheap evidence we
already hold: CS totals (qc_summary), which mode/metric tripped, and the
inside/outside split. Deterministically resolve **Normal** (no exceedance)
and set up the two easy gates. No external data yet. High value on its own
— it's the §5 events table and the §9 watch-list source.

**Phase B — Deterministic causes (small acquisition).**
Add a Dst acquisition module (WDC Kyoto) → auto-label **Geomagnetic
Storm** (Dst < −150 nT). Add a CS-threshold gate → mark **PB-candidate**
(CS > 100, pending alignment). After B the tree deterministically yields
Normal / Geomagnetic Storm / PB-candidate / "needs ionosphere data", with
every event carrying its CS + Dst evidence.

**Phase C — Ionosphere ingest + MSTID classifier (large, separate project).**
dTEC/ROTI ingest (NICT) → wave-like-pattern (MSTID) detection +
spatiotemporal alignment scoring. This is the bulk of the remaining
classes (MSTID, PB confirmation, Other/Complex) and is a data-engineering
project in its own right. Scope independently; do not block Phases A/B.

*ML angle (founder, 2026-07-11):* the MSTID call in the paper is made by
**looking at the dTEC/ROTI images**, and MSTID signatures are visually
very distinctive — extended wave-like banded structures with a
characteristic ~100–500 km wavelength / 15–60 min period, NW–SE aligned
phase fronts, and a clear summer-night / winter-day seasonal pattern. That
is a strong fit for **image-based classification**, and it likely raises
the automatable fraction of the tree well beyond the deterministic Dst/CS
gates. Two framings, cheapest first:

1. **Spectral-feature classifier (interpretable, low data need).** 2D-FFT
   each dTEC/ROTI map tile; read off dominant wavelength, orientation, and
   band-power in the MSTID band. Threshold or a shallow classifier
   (logistic / gradient-boost) on those features. Physically interpretable,
   needs few labels, and the features double as the "wave-like pattern"
   test the flowchart already names.
2. **CNN image classifier (higher ceiling, more data need).** Multi-class
   on map tiles: MSTID / PB / geomagnetic-storm / quiet. PBs (localized
   plume/depletion + high scintillation & CS) vs MSTID (extended
   wavefronts) are visually separable, so a classifier could also help
   resolve part of the MSTID-vs-PB "spatiotemporal alignment" judgment,
   not just the wave-like gate.

**Training data.** The paper already hand-labeled ~89 events (2021–2025)
by primary cause — a ready seed set, and per-network-per-day granularity
multiplies the samples. 89 is small for a CNN from scratch, so favor the
spectral-feature route and/or transfer learning + augmentation; the
spectral classifier can also *bootstrap labels* to grow the CNN set.

**Boundaries.** ML replaces the *detector*, not the *data* — the dTEC/
ROTI ingest is still the prerequisite. And the model output should feed
the Phase E reviewer step as a **confidence-scored suggestion**, never an
unreviewed authoritative cause label, until it is validated against the
paper's labels on held-out years.

**Phase D — CSSR decode (parallel, separate).**
Decode the CSSR correction payload from the L6 archive → tropospheric-
divergence + correction-continuity gates. Enables the non-ionospheric
branch. Independent of C.

**Phase E — Reviewer-assisted resolution.**
For events the deterministic gates can't close, render an "event dossier"
(error time series, CS map, Dst, whatever ionosphere/CSSR indicators
exist) and let a human assign the terminal class; persist the label. This
mirrors how the paper actually produced Figure 6/7 and is the honest v1
for MSTID-vs-PB-vs-Other and every alignment box.

## 5. Recommendation

Do **not** attempt full auto-classification for the monthly Pro report
now. The tree's leaves depend on data we don't yet ingest (dTEC/ROTI,
decoded CSSR) and on alignment judgments the authors made by hand.

Instead, **build Phase A now** (event detection + evidence dossier) — it
is fully automatable from data on disk, directly populates §5 events and
§9 watch-list, and establishes the schema every later phase writes into.
Then **Phase B** (Dst) for the one clean external label. Treat C
(ionosphere) and D (CSSR) as scoped follow-on data projects, and ship the
classifier as reviewer-assisted (Phase E) until they land.

This keeps the report honest: deterministic where the data supports it,
explicitly "under review" where the paper itself relied on expert
judgment — never a fabricated cause label.

## 6. Open questions for the founder

1. For the monthly report, is **event detection + evidence (Phase A)**
   enough to start, with causes shown as "candidate / under review"?
2. PS thresholds for the **daily** exceedance test — reuse the same
   PS-QZSS H/V values the report already cites? (paper uses static AND
   kinematic; our pipeline is kinematic-primary — confirm whether to
   detect on kinematic only or add a static run.)
3. Priority order for the follow-on ingests: **Dst (cheap) → dTEC/ROTI
   (MSTID) → CSSR decode** — agree?
4. Is a dTEC/ROTI ingest even in scope for Phase 0/1, or deferred? (It is
   a substantial new acquisition + detection subsystem.)
5. MSTID via ML on dTEC/ROTI images (founder's proposal): start with the
   interpretable spectral-feature classifier, or go straight to a CNN?
   Either way, first secure the dTEC/ROTI ingest and a labeled seed set
   (the paper's ~89 events).
