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


class TestStraightSegments(unittest.TestCase):
    """v0.10: trechos RETOS no editor — shift+clique seleciona 2 nós e o botão Line
    remove os nós intermediários do caminho MAIS CURTO e marca o trecho como reta.
    O re-traçar honra as retas: cúbica degenerada na corda, vizinhos tangentes à reta
    (G1); dois trechos retos consecutivos formam CANTO legítimo (exceção ao G1)."""

    def wiggly(self):
        # aresta inferior ruidosa (nós 1..3) + volta limpa; CCW (y p/ cima)
        return [(0.0, 0.0), (2.0, 0.4), (5.0, -0.3), (8.0, 0.2), (10.0, 0.0),
                (10.0, 8.0), (0.0, 8.0)]

    def test_straighten_removes_shorter_path(self):
        nodes, lines, seg = E.straighten_between(self.wiggly(), set(), 0, 4)
        self.assertEqual(nodes, [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)])
        self.assertEqual(seg, 0)                   # reta = trecho nó0→nó1
        self.assertEqual(lines, {0})

    def test_straighten_wraps_across_closure(self):
        # caminho mais curto de 4 até 0 atravessa o fechamento? Não: 4→5→6→0 (26 mm)
        # vs 4→3→2→1→0 (~10 mm) — remove 3,2,1 (o mais curto em COMPRIMENTO).
        nodes, lines, seg = E.straighten_between(self.wiggly(), set(), 4, 0)
        self.assertEqual(len(nodes), 4)
        self.assertIn((0.0, 0.0), nodes)
        self.assertIn((10.0, 0.0), nodes)
        self.assertEqual(lines, {seg})

    def test_straighten_remaps_existing_lines(self):
        # uma reta já marcada ANTES do trecho apagado mantém o índice; DEPOIS, desloca.
        nodes0 = self.wiggly()
        n0, l0, s0 = E.straighten_between(nodes0, set(), 5, 6)   # reta no topo (5→6)
        self.assertEqual(l0, {s0})
        n1, l1, s1 = E.straighten_between(n0, l0, 0, 4)          # apaga nós 1..3
        self.assertEqual(len(n1), 4)
        self.assertEqual(len(l1), 2)                             # a do topo sobreviveu
        self.assertIn(s1, l1)

    def test_line_segment_is_straight(self):
        nodes = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]   # CCW
        cub = E.cubics_through_nodes(nodes, line_segs={0})
        bez = next(b for b in cub
                   if math.hypot(b[0][0], b[0][1]) < 1e-6 and
                      math.hypot(b[3][0] - 10.0, b[3][1]) < 1e-6)
        for t in (0.25, 0.5, 0.75):                # a curva fica NA corda
            pt = P.bezier_point(bez, t)
            self.assertLess(abs(pt[1]), 1e-6)
            self.assertGreater(pt[0], 0.0)
            self.assertLess(pt[0], 10.0)

    def test_line_survives_ccw_reversal(self):
        # nós em sentido HORÁRIO (como square_nodes): ensure_ccw inverte a ordem e o
        # índice do trecho reto é REMAPEADO — a reta continua entre os MESMOS dois nós.
        nodes = square_nodes()                     # CW: (0,0)→(10,0)→(10,-10)→(0,-10)
        cub = E.cubics_through_nodes(nodes, line_segs={0})       # reta (0,0)↔(10,0)
        bez = next(b for b in cub if {tuple(map(round, b[0])), tuple(map(round, b[3]))}
                   == {(0, 0), (10, 0)})
        for t in (0.25, 0.5, 0.75):
            self.assertLess(abs(P.bezier_point(bez, t)[1]), 1e-6)

    def test_neighbors_leave_tangent_to_line(self):
        # G1 na junção reta↔curva: o trecho vizinho SAI na direção da reta.
        nodes = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        cub = E.cubics_through_nodes(nodes, line_segs={0})
        nxt = next(b for b in cub if math.hypot(b[0][0] - 10.0, b[0][1]) < 1e-6)
        t_out = P._unit((nxt[1][0] - nxt[0][0], nxt[1][1] - nxt[0][1]))
        self.assertAlmostEqual(t_out[0], 1.0, places=6)          # sai ao longo da reta
        self.assertAlmostEqual(t_out[1], 0.0, places=6)

    def test_two_lines_make_corner(self):
        # retas consecutivas = canto G0 legítimo: cada uma exatamente na sua corda.
        nodes = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        cub = E.cubics_through_nodes(nodes, line_segs={0, 1})
        for want0, want3, axis, val in (((0.0, 0.0), (10.0, 0.0), 1, 0.0),
                                        ((10.0, 0.0), (10.0, 10.0), 0, 10.0)):
            bez = next(b for b in cub
                       if math.hypot(b[0][0] - want0[0], b[0][1] - want0[1]) < 1e-6 and
                          math.hypot(b[3][0] - want3[0], b[3][1] - want3[1]) < 1e-6)
            for t in (0.3, 0.7):
                self.assertLess(abs(P.bezier_point(bez, t)[axis] - val), 1e-6)

    def test_remap_insert(self):
        # inserir DENTRO de uma reta divide em duas retas; índices seguintes deslocam.
        self.assertEqual(E.remap_lines_insert({0, 2}, 0), {0, 1, 3})
        self.assertEqual(E.remap_lines_insert({0, 2}, 1), {0, 3})

    def test_remap_delete(self):
        # apagar o nó entre duas retas funde numa reta; entre reta e curva, vira curva.
        self.assertEqual(E.remap_lines_delete({0, 1}, 1, 4), {0})
        self.assertEqual(E.remap_lines_delete({0}, 1, 4), set())
        self.assertEqual(E.remap_lines_delete({2}, 1, 4), {1})   # só desloca


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
