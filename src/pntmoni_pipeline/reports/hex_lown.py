"""Low-n hex-cell reliability marking (dotted inset ring).

Implements the ``data.lowN`` design token (pntmoni-docs
``60-brand/tokens.json`` v1.2.0; ADR 0013 Postscript 2026-07-18,
pntmoni-docs Issue #27) shared by the Product 1 (monthly_free /
monthly_pro) and Product 2 (monthly_qc) hex maps:

- every populated hex cell is rendered (the former
  minimum-stations-per-cell blank suppression is retired);
- cells backed by fewer than :data:`MIN_STATIONS_PER_CELL` distinct
  stations keep their TRUE metric fill colour and carry a dotted ring
  inset from the cell edge.

The fill is never desaturated or recoloured (on a perceptual colormap a
saturation shift reads as a different value), and the shared cell edge
is never restyled (a dotted cell edge is indistinguishable from the
white hex hairlines over dark fills, and neighbouring cells share
edges). Ring colour is picked per cell for contrast against the
*effective* fill (fill alpha-blended over the land colour).
"""
from __future__ import annotations

import numpy as np
from matplotlib import colors as mcolors
from matplotlib.collections import PolyCollection

# Reliability threshold: a cell backed by fewer distinct stations than
# this is statistically thin (a single outlier station can colour the
# whole cell) and is marked, not hidden. Methodology/config parameter
# (captured by config_hash); shared across Product 1 and Product 2 maps.
MIN_STATIONS_PER_CELL = 3

# data.lowN token values (pntmoni-docs 60-brand/tokens.json v1.2.0).
RING_INSET_RATIO = 0.8      # ring vertices at this fraction of cell radius
RING_STROKE_RATIO = 0.08    # stroke width as fraction of cell radius
RING_ON_DARK = "#FFFFFF"    # ring colour over dark effective fills
RING_ON_LIGHT = "#22273A"   # ring colour over light effective fills
_LUMINANCE_SPLIT = 0.45

_MIN_STROKE_PT = 0.7        # legibility floor at small render sizes


def _relative_luminance(rgb: np.ndarray) -> float:
    r, g, b = rgb[:3]
    return 0.2126 * float(r) + 0.7152 * float(g) + 0.0722 * float(b)


def _cell_radius_points(ax, r_data: float) -> float:
    """Approximate the cell radius in typographic points on this axes."""
    p0 = ax.transData.transform((0.0, 0.0))
    p1 = ax.transData.transform((r_data, 0.0))
    px = float(np.hypot(*(p1 - p0)))
    return px * 72.0 / ax.figure.dpi


def overlay_lown_rings(
    ax,
    hb,
    counts,
    *,
    min_stations: int = MIN_STATIONS_PER_CELL,
    background: str = "#f5f5f4",
) -> int:
    """Mark low-n cells of a drawn hexbin layer with dotted inset rings.

    ``hb`` is the rendered hexbin :class:`~matplotlib.collections
    .PolyCollection` (drawn with ``mincnt=1`` so every populated cell is
    present). ``counts`` is the per-cell distinct-station count aligned
    index-for-index with ``hb.get_array()`` (same grid parameters in the
    counting pass). ``background`` is the map's land colour, used to
    compute the effective fill under the layer's alpha for the
    ring-contrast choice.

    Returns the number of cells marked.
    """
    counts = np.asarray(counts)
    low = counts < min_stations
    n_low = int(low.sum())
    if n_low == 0:
        return 0

    offsets = np.asarray(hb.get_offsets())[low]
    values = np.asarray(hb.get_array())[low]
    fills = hb.get_cmap()(hb.norm(values))          # (n, 4) RGBA
    alpha = hb.get_alpha() if hb.get_alpha() is not None else 1.0
    bg = np.asarray(mcolors.to_rgb(background))

    edge_colors = [
        RING_ON_DARK
        if _relative_luminance(alpha * np.asarray(f[:3]) + (1.0 - alpha) * bg)
        < _LUMINANCE_SPLIT
        else RING_ON_LIGHT
        for f in fills
    ]

    # hexbin uses a single hexagon path (data-unit sized, centred at the
    # origin) positioned via offsets — scale it inward for the ring.
    unit = np.asarray(hb.get_paths()[0].vertices)
    ring = unit * RING_INSET_RATIO
    verts = ring[None, :, :] + offsets[:, None, :]

    r_pt = _cell_radius_points(ax, float(np.abs(unit).max()))
    lw = max(r_pt * RING_STROKE_RATIO, _MIN_STROKE_PT)

    ax.add_collection(PolyCollection(
        verts,
        facecolors="none",
        edgecolors=edge_colors,
        linewidths=lw,
        linestyles=(0, (1, 1)),
        zorder=hb.get_zorder() + 1,
    ))
    return n_low
