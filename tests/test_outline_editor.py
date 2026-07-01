#!/usr/bin/env python3
# =============================================================================
# test_outline_editor.py — TDD do núcleo PURO do editor de nós (outline_editor.py)
# -----------------------------------------------------------------------------
# Só o núcleo (geometria do "re-traçar", ops de edição, transforms). A view tkinter
# é glue fino e NÃO é instanciada aqui (sem display num runner headless).
#
# Rodar: .venv/Scripts/python tests/run_image_tests.py
# =============================================================================

import math
import os
import sys
import unittest

THIS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(THIS)
sys.path.insert(0, ROOT)

import outline_editor as E  # noqa: E402
import photo_to_outline as P  # noqa: E402


def square_nodes(s=10.0):
    """4 nós de um quadrado em mm (Y p/ cima, como a silhueta: y ≤ 0)."""
    return [(0.0, 0.0), (s, 0.0), (s, -s), (0.0, -s)]


def circle_nodes(n=12, r=10.0):
    return [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


class TestRetrace(unittest.TestCase):
    """cubics_through_nodes: curva G1 que passa pelos nós."""

    def test_passes_through_each_node(self):
        nodes = square_nodes()
        cub = E.cubics_through_nodes(nodes)
        self.assertEqual(len(cub), len(nodes))     # 1 cúbica por trecho, fechado
        starts = E.nodes_from_cubics(cub)
        # cada p0 coincide com um nó de entrada (a menos da orientação CCW/rotação)
        for s in starts:
            self.assertTrue(any(math.hypot(s[0] - q[0], s[1] - q[1]) < 1e-6 for q in nodes))

    def test_chained_and_closed(self):
        cub = E.cubics_through_nodes(circle_nodes())
        for k in range(len(cub)):
            p3 = cub[k][3]
            p0_next = cub[(k + 1) % len(cub)][0]
            self.assertAlmostEqual(p3[0], p0_next[0], places=6)
            self.assertAlmostEqual(p3[1], p0_next[1], places=6)

    def test_g1_smooth_nodes(self):
        """Tangente de saída de um trecho == tangente de entrada do próximo (nó G1)."""
        cub = E.cubics_through_nodes(circle_nodes())
        for k in range(len(cub)):
            _p0, _c1, c2, p3 = cub[k]
            p0n, c1n, _c2n, _p3n = cub[(k + 1) % len(cub)]
            t_in = P._unit((p3[0] - c2[0], p3[1] - c2[1]))     # chegada no nó
            t_out = P._unit((c1n[0] - p0n[0], c1n[1] - p0n[1]))  # saída do nó
            self.assertAlmostEqual(t_in[0], t_out[0], places=3)
            self.assertAlmostEqual(t_in[1], t_out[1], places=3)

    def test_circle_is_simple(self):
        """Um anel de nós vira contorno fechado SEM auto-cruzar (cada cúbica simples)."""
        cub = E.cubics_through_nodes(circle_nodes(16, 12.0))
        for bez in cub:
            self.assertTrue(P._cubic_is_simple(bez))

    def test_too_few_nodes(self):
        self.assertEqual(E.cubics_through_nodes([(0.0, 0.0), (1.0, 0.0)]), [])

    def test_roundtrip_nodes_from_cubics(self):
        nodes = square_nodes()
        cub = E.cubics_through_nodes(nodes)
        self.assertEqual(len(E.nodes_from_cubics(cub)), len(nodes))


class TestEditOps(unittest.TestCase):
    def test_move_node(self):
        nodes = square_nodes()
        out = E.move_node(nodes, 1, (99.0, -7.0))
        self.assertEqual(out[1], (99.0, -7.0))
        self.assertEqual(nodes[1], (10.0, 0.0))    # original intacto (cópia)

    def test_insert_after(self):
        nodes = square_nodes()
        out = E.insert_node(nodes, 0, (5.0, 0.0))
        self.assertEqual(len(out), len(nodes) + 1)
        self.assertEqual(out[1], (5.0, 0.0))       # logo após o nó 0

    def test_delete_keeps_min_three(self):
        nodes = square_nodes()
        out = E.delete_node(nodes, 0)
        self.assertEqual(len(out), 3)
        out2 = E.delete_node(out, 0)               # já no mínimo → no-op
        self.assertEqual(len(out2), 3)

    def test_nearest_node(self):
        nodes = square_nodes()
        self.assertEqual(E.nearest_node(nodes, (9.6, 0.2)), 1)
        self.assertIsNone(E.nearest_node(nodes, (100.0, 100.0), max_dist=1.0))
        self.assertIsNone(E.nearest_node([], (0.0, 0.0)))

    def test_nearest_segment(self):
        nodes = square_nodes()                     # trecho 0:(0,0)→1:(10,0)
        self.assertEqual(E.nearest_segment(nodes, (5.0, 0.3)), 0)
        self.assertIsNone(E.nearest_segment([(0.0, 0.0)], (1.0, 1.0)))


class TestTransforms(unittest.TestCase):
    def test_roundtrip(self):
        mmpp_x, mmpp_y = 0.125, 0.130
        for pt in [(0.0, 0.0), (37.5, -22.1), (5.0, -100.0)]:
            px = E.mm_to_px(pt, mmpp_x, mmpp_y)
            back = E.px_to_mm(px, mmpp_x, mmpp_y)
            self.assertAlmostEqual(back[0], pt[0], places=9)
            self.assertAlmostEqual(back[1], pt[1], places=9)

    def test_orientation(self):
        # mm Y p/ cima (y ≤ 0) → pixel Y p/ baixo (py ≥ 0)
        px = E.mm_to_px((10.0, -10.0), 0.1, 0.1)
        self.assertGreater(px[0], 0)
        self.assertGreater(px[1], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
