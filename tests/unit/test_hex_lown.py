"""Tests for the low-n hex-cell reliability marking (dotted inset ring).

ADR 0013 Postscript 2026-07-18 (pntmoni-docs Issue #27): blank
suppression retired — every populated cell renders, and cells backed by
fewer than MIN_STATIONS_PER_CELL distinct stations carry a dotted ring
inset from the cell edge over their TRUE fill colour.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.collections import PolyCollection

from pntmoni_pipeline.reports.hex_lown import (
    MIN_STATIONS_PER_CELL,
    RING_INSET_RATIO,
    RING_ON_DARK,
    RING_ON_LIGHT,
    overlay_lown_rings,
)


def _render_hexbin(values_by_cluster, alpha=0.5):
    """Two well-separated point clusters → two hexbin cells.

    Each cluster's points share one C value so the cell colour is exact.
    Returns (fig, ax, hb, counts) with counts = points per cell (one
    point per synthetic station).
    """
    xs, ys, cs = [], [], []
    centers = [(0.0, 0.0), (100.0, 0.0)]
    for (cx, cy), (value, n_pts) in zip(centers, values_by_cluster):
        for i in range(n_pts):
            xs.append(cx + 0.01 * i)
            ys.append(cy)
            cs.append(value)
    fig, ax = plt.subplots(figsize=(6, 4))
    ext = (-10.0, 110.0, -10.0, 10.0)
    cnt = ax.hexbin(xs, ys, C=cs, reduce_C_function=len,
                    gridsize=5, extent=ext, mincnt=1)
    counts = np.asarray(cnt.get_array())
    cnt.remove()
    hb = ax.hexbin(xs, ys, C=cs, reduce_C_function=np.median,
                   gridsize=5, extent=ext, cmap="plasma", mincnt=1,
                   alpha=alpha)
    return fig, ax, hb, counts


def _ring_collections(ax):
    return [c for c in ax.collections
            if isinstance(c, PolyCollection)
            and np.all(np.asarray(c.get_facecolor()).size == 0
                       or np.asarray(c.get_facecolor())[:, 3] == 0.0)
            and c.get_linestyle()[0][1] is not None]


def test_low_cell_gets_ring_and_populated_cells_all_survive():
    fig, ax, hb, counts = _render_hexbin([(0.1, 1), (0.5, 5)])
    n_cells_before = len(np.asarray(hb.get_array()))
    marked = overlay_lown_rings(ax, hb, counts)
    assert marked == int((counts < MIN_STATIONS_PER_CELL).sum()) == 1
    # No suppression: the drawn layer still holds every populated cell.
    assert len(np.asarray(hb.get_array())) == n_cells_before
    rings = _ring_collections(ax)
    assert len(rings) == 1 and len(rings[0].get_paths()) == 1
    plt.close(fig)


def test_no_low_cells_adds_nothing():
    fig, ax, hb, counts = _render_hexbin([(0.1, 4), (0.5, 5)])
    n_coll = len(ax.collections)
    assert overlay_lown_rings(ax, hb, counts) == 0
    assert len(ax.collections) == n_coll
    plt.close(fig)


def test_ring_is_inset_from_cell_edge():
    fig, ax, hb, counts = _render_hexbin([(0.1, 1), (0.5, 5)])
    overlay_lown_rings(ax, hb, counts)
    (ring,) = _ring_collections(ax)
    cell = np.asarray(hb.get_paths()[0].vertices)
    ring_verts = np.asarray(ring.get_paths()[0].vertices)
    low_offset = np.asarray(hb.get_offsets())[counts < MIN_STATIONS_PER_CELL][0]
    rel = ring_verts - low_offset
    cell_r = np.abs(cell).max(axis=0)
    ring_r = np.abs(rel).max(axis=0)
    assert np.allclose(ring_r, cell_r * RING_INSET_RATIO, rtol=1e-6)
    plt.close(fig)


@pytest.mark.parametrize(
    ("value", "alpha", "expected"),
    [
        # At the reports' 0.5 display alpha over light land, even the
        # plasma dark end blends light → ink ring on both extremes.
        (0.02, 0.5, RING_ON_LIGHT),
        (0.98, 0.5, RING_ON_LIGHT),
        # Fully opaque dark fill → white ring (the contrast switch).
        (0.02, 1.0, RING_ON_DARK),
    ],
)
def test_ring_color_picked_for_contrast(value, alpha, expected):
    fig, ax, hb, counts = _render_hexbin([(value, 1), (value, 5)], alpha=alpha)
    hb.norm.vmin, hb.norm.vmax = 0.0, 1.0
    overlay_lown_rings(ax, hb, counts)
    (ring,) = _ring_collections(ax)
    edge = np.asarray(ring.get_edgecolor())[0]
    expected_rgba = matplotlib.colors.to_rgba(expected)
    assert np.allclose(edge, expected_rgba, atol=1e-6)
    plt.close(fig)


def test_fill_colors_untouched():
    fig, ax, hb, counts = _render_hexbin([(0.1, 1), (0.5, 5)])
    before = np.asarray(hb.get_array()).copy()
    cmap_before = hb.get_cmap().name
    overlay_lown_rings(ax, hb, counts)
    assert np.array_equal(np.asarray(hb.get_array()), before)
    assert hb.get_cmap().name == cmap_before
    plt.close(fig)
