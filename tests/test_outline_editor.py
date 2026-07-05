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


def sym_hex(c=5.0):
    """Contorno PAREADO canônico (eixo vertical x=c, N=6): nós 0 e 3 no eixo, 1-2 à
    direita, 4-5 = espelhos de 2-1 — invariante i ↔ (N−i) % N (plano 011/F1)."""
    return [(c, 0.0), (c + 3.0, -1.0), (c + 4.0, -4.0),
            (c, -6.0), (c - 4.0, -4.0), (c - 3.0, -1.0)]


def sym_ring(c=10.0):
    """Contorno PAREADO maior (N=12, eixo vertical x=c): 5 nós de cada lado + 2 no eixo."""
    right = [(c + 3.0, -1.0), (c + 5.0, -3.0), (c + 5.5, -5.0),
             (c + 4.0, -7.0), (c + 2.0, -8.0)]
    left = [(2.0 * c - x, y) for (x, y) in reversed(right)]
    return [(c, 0.0)] + right + [(c, -9.0)] + left


class TestSymmetryPairing(unittest.TestCase):
    """F1 (plano 011): o pareamento é POR ÍNDICE — o par do nó i é (N−i) % N; nós 0 e
    N/2 caem no eixo (auto-pareados). Nada de matching geométrico."""

    def test_mirror_index(self):
        self.assertEqual(E.mirror_index(0, 6), 0)      # nó de eixo: auto-pareado
        self.assertEqual(E.mirror_index(3, 6), 3)      # idem (N/2)
        self.assertEqual(E.mirror_index(1, 6), 5)
        self.assertEqual(E.mirror_index(2, 6), 4)
        self.assertEqual(E.mirror_index(5, 6), 1)      # involução

    def test_mirror_point(self):
        self.assertEqual(E.mirror_point((8.0, -1.0), "vertical", 5.0), (2.0, -1.0))
        self.assertEqual(E.mirror_point((8.0, -1.0), "horizontal", -2.0), (8.0, -3.0))

    def test_check_pairing_accepts_canonical(self):
        self.assertTrue(E.sym_check_pairing(sym_hex(), "vertical", 5.0))
        self.assertTrue(E.sym_check_pairing(sym_ring(), "vertical", 10.0))

    def test_check_pairing_rejects_free_edit(self):
        nodes = E.move_node(sym_hex(), 1, (9.0, -1.0))   # edição LIVRE de um lado só
        self.assertFalse(E.sym_check_pairing(nodes, "vertical", 5.0))

    def test_check_pairing_rejects_wrong_axis(self):
        self.assertFalse(E.sym_check_pairing(sym_hex(), "vertical", 5.5))

    def test_accepts_real_symmetrize_beziers_output(self):
        # Compatibilidade com o CLI: a saída de symmetrize_beziers JÁ nasce pareada por
        # índice (hipótese validada no plano 011 — erro 0.000000 mm em thermpro.jpg).
        cub = E.cubics_through_nodes(circle_nodes(12, 4.0))
        cub = [tuple((x + 5.0, y - 6.0) for (x, y) in b) for b in cub]  # centro (5,−6)
        sym = P.symmetrize_beziers(cub, "vertical", 5.0)
        nodes = E.nodes_from_cubics(sym)
        self.assertTrue(E.sym_check_pairing(nodes, "vertical", 5.0, eps=1e-6))


class TestSymmetryOps(unittest.TestCase):
    """F1: ops-par (move/insert/delete/straighten espelhados) PRESERVAM o invariante
    i ↔ (N−i) % N; nó de eixo fica travado no eixo."""

    AX, C = "vertical", 5.0

    def assertPaired(self, nodes, c=None):
        self.assertTrue(E.sym_check_pairing(nodes, self.AX, self.C if c is None else c),
                        f"invariante quebrado: {nodes}")

    def test_move_pair(self):
        nodes = E.move_node_sym(sym_hex(), 1, (8.5, -1.5), self.AX, self.C)
        self.assertEqual(nodes[1], (8.5, -1.5))
        self.assertEqual(nodes[5], (1.5, -1.5))          # par recebeu (2c−x, y)
        self.assertPaired(nodes)

    def test_move_left_side_moves_right_pair(self):
        nodes = E.move_node_sym(sym_hex(), 4, (0.5, -4.5), self.AX, self.C)
        self.assertEqual(nodes[4], (0.5, -4.5))
        self.assertEqual(nodes[2], (9.5, -4.5))
        self.assertPaired(nodes)

    def test_move_axis_node_locked_to_axis(self):
        # nó de eixo (i=0): a coordenada do eixo TRAVA em x=c; move só ao longo dele.
        nodes = E.move_node_sym(sym_hex(), 0, (7.3, 1.0), self.AX, self.C)
        self.assertEqual(nodes[0], (5.0, 1.0))
        self.assertPaired(nodes)

    def test_move_axis_node_horizontal(self):
        # eixo HORIZONTAL: troca os papéis de x e y do sym_hex → pareado em y=−2.
        nodes = [(p[1], p[0]) for p in sym_hex(-2.0)]
        self.assertTrue(E.sym_check_pairing(nodes, "horizontal", -2.0))
        out = E.move_node_sym(nodes, 0, (1.0, 3.3), "horizontal", -2.0)
        self.assertEqual(out[0], (1.0, -2.0))            # y travado no eixo

    def assertHasPoint(self, nodes, p, tol=1e-9):
        self.assertTrue(any(math.hypot(q[0] - p[0], q[1] - p[1]) < tol for q in nodes),
                        f"{p} ausente de {nodes}")

    def test_insert_pair_right_segment(self):
        nodes0 = sym_hex()
        nodes, lines = E.insert_node_sym(nodes0, set(), 1, (8.7, -2.5), self.AX, self.C)
        self.assertEqual(len(nodes), len(nodes0) + 2)    # N+2 (o casal)
        self.assertHasPoint(nodes, (8.7, -2.5))
        self.assertHasPoint(nodes, (1.3, -2.5))          # espelho no trecho par
        self.assertPaired(nodes)
        self.assertEqual(lines, set())

    def test_insert_pair_left_segment(self):
        nodes0 = sym_hex()
        nodes, _ = E.insert_node_sym(nodes0, set(), 4, (1.3, -2.5), self.AX, self.C)
        self.assertEqual(len(nodes), len(nodes0) + 2)
        self.assertHasPoint(nodes, (8.7, -2.5))
        self.assertPaired(nodes)

    def test_insert_remaps_lines(self):
        # reta marcada no trecho 2 (nó2→nó3): inserir no trecho 1 desloca-a; a reta
        # espelhada do trecho 3 (par de 2) também sobrevive coerente.
        nodes, lines = E.insert_node_sym(sym_ring(), {2, 9}, 1, (15.2, -2.0),
                                         self.AX, 10.0)
        self.assertTrue(E.sym_check_pairing(nodes, self.AX, 10.0))
        n = len(nodes)
        for k in lines:                                  # toda reta tem o par espelhado
            self.assertIn((n - 1 - k) % n, lines)

    def test_delete_pair(self):
        nodes0 = sym_ring()
        nodes, lines = E.delete_node_sym(nodes0, set(), 2, self.AX, 10.0)
        self.assertEqual(len(nodes), len(nodes0) - 2)    # excluiu o casal
        self.assertNotIn(nodes0[2], nodes)
        self.assertNotIn(nodes0[10], nodes)
        self.assertTrue(E.sym_check_pairing(nodes, self.AX, 10.0))

    def test_delete_axis_node_alone(self):
        nodes0 = sym_ring()
        nodes, _ = E.delete_node_sym(nodes0, set(), 0, self.AX, 10.0)
        self.assertEqual(len(nodes), len(nodes0) - 1)    # nó de eixo sai sozinho
        self.assertTrue(E.sym_check_pairing(nodes, self.AX, 10.0))

    def test_delete_min_guard(self):
        nodes0 = sym_hex()                               # N=6: excluir casal → 4, ok;
        nodes, _ = E.delete_node_sym(nodes0, set(), 1, self.AX, self.C)
        self.assertEqual(len(nodes), 4)
        nodes2, _ = E.delete_node_sym(nodes, set(), 1, self.AX, self.C)
        self.assertEqual(len(nodes2), len(nodes))        # 4−2 < 3 → no-op

    def test_sequence_preserves_invariant(self):
        # inserir → mover → excluir, como no plano: o invariante sobrevive à sequência.
        nodes, lines = E.insert_node_sym(sym_ring(), set(), 3, (15.0, -6.0),
                                         self.AX, 10.0)
        nodes = E.move_node_sym(nodes, 2, (16.0, -3.5), self.AX, 10.0)
        nodes, lines = E.delete_node_sym(nodes, lines, 5, self.AX, 10.0)
        self.assertTrue(E.sym_check_pairing(nodes, self.AX, 10.0))

    def test_straighten_sym_both_sides(self):
        # Line espelhado: retifica nós 1..4 do lado direito → o lado esquerdo ganha a
        # MESMA reta espelhada; invariante preservado e as duas retas em line_segs.
        nodes, lines, seg = E.straighten_between_sym(sym_ring(), set(), 1, 4,
                                                     self.AX, 10.0)
        self.assertIsNotNone(seg)
        self.assertTrue(E.sym_check_pairing(nodes, self.AX, 10.0))
        self.assertEqual(len(lines), 2)                  # a reta e o espelho dela
        n = len(nodes)
        for k in lines:
            self.assertIn((n - 1 - k) % n, lines)


class TestMirrorContour(unittest.TestCase):
    """F1b (plano 011): Mirror constrói o pareamento a partir de QUALQUER contorno —
    nó de emenda na interseção exata com o eixo, lado-mestre + espelho em ordem
    reversa (invariante por construção); recusa se cruza o eixo mais de 2×."""

    # assimétrico, cruza o eixo x=5 exatamente 2× (trechos 0 e 3)
    FREE = [(2.0, 0.0), (8.0, 0.5), (9.0, -3.0), (7.5, -6.0), (1.0, -5.0), (0.0, -2.0)]

    def test_mirror_high_builds_pairing(self):
        nodes, lines = E.mirror_contour(self.FREE, set(), "vertical", 5.0, keep="high")
        self.assertIsNotNone(nodes)
        self.assertTrue(E.sym_check_pairing(nodes, "vertical", 5.0))
        # lado-mestre (direita) sobrevive intacto
        for p in [(8.0, 0.5), (9.0, -3.0), (7.5, -6.0)]:
            self.assertIn(p, nodes)
        self.assertEqual(lines, set())

    def test_seam_nodes_at_exact_intersection(self):
        # emenda = interseção exata trecho×eixo: (2,0)→(8,0.5) cruza x=5 em y=0.25;
        # (7.5,−6)→(1,−5) cruza em y=−6+ (2.5/6.5)·1.
        nodes, _ = E.mirror_contour(self.FREE, set(), "vertical", 5.0, keep="high")
        seams = [p for p in nodes if abs(p[0] - 5.0) < 1e-9]
        self.assertEqual(len(seams), 2)
        ys = sorted(p[1] for p in seams)
        self.assertAlmostEqual(ys[1], 0.25, places=9)
        self.assertAlmostEqual(ys[0], -6.0 + 2.5 / 6.5, places=9)

    def test_mirror_low_uses_other_side(self):
        nodes, _ = E.mirror_contour(self.FREE, set(), "vertical", 5.0, keep="low")
        self.assertIsNotNone(nodes)
        self.assertTrue(E.sym_check_pairing(nodes, "vertical", 5.0))
        for p in [(1.0, -5.0), (0.0, -2.0), (2.0, 0.0)]:  # esquerda = mestre
            self.assertIn(p, nodes)
        self.assertNotIn((9.0, -3.0), nodes)             # direita foi regenerada

    def test_refuses_more_than_two_crossings(self):
        # forma em "C" atravessando o eixo 4×: espelho fecharia laços separados.
        w = [(0.0, 0.0), (10.0, 0.0), (10.0, -2.0), (4.0, -2.0),
             (4.0, -4.0), (10.0, -4.0), (10.0, -6.0), (0.0, -6.0)]
        nodes, lines = E.mirror_contour(w, set(), "vertical", 5.0, keep="high")
        self.assertIsNone(nodes)
        self.assertIsNone(lines)

    def test_master_lines_survive_mirrored(self):
        # reta no lado-mestre (trecho 1→2, todo à direita) sobrevive E ganha o espelho;
        # retas do lado regenerado são descartadas.
        nodes, lines = E.mirror_contour(self.FREE, {1, 4}, "vertical", 5.0, keep="high")
        self.assertTrue(E.sym_check_pairing(nodes, "vertical", 5.0))
        self.assertEqual(len(lines), 2)
        n = len(nodes)
        for k in lines:
            self.assertIn((n - 1 - k) % n, lines)

    def test_axis_move_snap_no_step(self):
        # Caso particular do F1b: pareamento válido em c, eixo movido p/ c′ — os nós de
        # emenda ENCOSTAM no eixo novo (y inalterado) e o Mirror não deixa degrau.
        nodes0 = sym_ring(10.0)
        moved = E.snap_seam_nodes(nodes0, "vertical", 10.0, 10.5)
        self.assertEqual(moved[0], (10.5, 0.0))          # x=c′, y inalterado
        self.assertEqual(moved[6], (10.5, -9.0))
        nodes, _ = E.mirror_contour(moved, set(), "vertical", 10.5, keep="high")
        self.assertIsNotNone(nodes)
        self.assertTrue(E.sym_check_pairing(nodes, "vertical", 10.5))
        # sem degrau: as emendas continuam nos MESMOS y (0 e −9)
        seam_ys = sorted(p[1] for p in nodes if abs(p[0] - 10.5) < 1e-9)
        self.assertAlmostEqual(seam_ys[0], -9.0, places=9)
        self.assertAlmostEqual(seam_ys[1], 0.0, places=9)

    def test_horizontal_axis(self):
        free = [(p[1], p[0]) for p in self.FREE]         # troca x↔y → eixo horizontal
        nodes, _ = E.mirror_contour(free, set(), "horizontal", 5.0, keep="high")
        self.assertIsNotNone(nodes)
        self.assertTrue(E.sym_check_pairing(nodes, "horizontal", 5.0))


class TestTranslateNodes(unittest.TestCase):
    """Modo Pan (extensão do 011/F4): translação 2D pura dos nós — desloca o contorno
    inteiro (corrige viés LATERAL da detecção) e o eixo de simetria acompanha."""

    def test_translates_and_keeps_original(self):
        nodes = sym_hex()
        out = E.translate_nodes(nodes, (0.4, -0.2))
        self.assertEqual(len(out), len(nodes))
        for p, q in zip(nodes, out):
            self.assertAlmostEqual(q[0], p[0] + 0.4, places=12)
            self.assertAlmostEqual(q[1], p[1] - 0.2, places=12)
        self.assertEqual(nodes, sym_hex())              # original intacto (cópia)

    def test_preserves_shape(self):
        nodes = sym_ring()
        out = E.translate_nodes(nodes, (1.3, 0.0))
        self.assertAlmostEqual(P.signed_area(nodes), P.signed_area(out), places=9)

    def test_pairing_survives_with_shifted_axis(self):
        # deslocar TODOS os nós + o eixo pelo MESMO dx mantém o invariante — é o que
        # permite o modo Pan não desligar a simetria (diferente do Rotate).
        nodes = E.translate_nodes(sym_ring(10.0), (0.7, 0.0))
        self.assertTrue(E.sym_check_pairing(nodes, "vertical", 10.7))
        self.assertFalse(E.sym_check_pairing(nodes, "vertical", 10.0))
        # eixo HORIZONTAL: deslocamento em x não mexe no eixo (y) — pareamento segue
        nodes_h = [(p[1], p[0]) for p in sym_ring(-3.0)]
        moved = E.translate_nodes(nodes_h, (0.7, 0.0))
        self.assertTrue(E.sym_check_pairing(moved, "horizontal", -3.0))

    def test_zero_is_identity(self):
        nodes = sym_hex()
        self.assertEqual(E.translate_nodes(nodes, (0.0, 0.0)), nodes)


class TestRotateNodes(unittest.TestCase):
    """F4 (plano 011): rotação 2D pura dos nós — preserva distâncias e área."""

    def test_preserves_distances_and_area(self):
        nodes = sym_ring()
        rot = E.rotate_nodes(nodes, 3.7, (10.0, -4.5))
        n = len(nodes)
        for i in range(n):
            a, b = nodes[i], nodes[(i + 1) % n]
            ra, rb = rot[i], rot[(i + 1) % n]
            self.assertAlmostEqual(math.hypot(b[0] - a[0], b[1] - a[1]),
                                   math.hypot(rb[0] - ra[0], rb[1] - ra[1]), places=9)
        self.assertAlmostEqual(P.signed_area(nodes), P.signed_area(rot), places=6)

    def test_center_fixed_and_roundtrip(self):
        nodes = sym_hex()
        c = (5.0, -3.0)
        rot = E.rotate_nodes([c], 30.0, c)
        self.assertAlmostEqual(rot[0][0], c[0], places=12)
        self.assertAlmostEqual(rot[0][1], c[1], places=12)
        back = E.rotate_nodes(E.rotate_nodes(nodes, 12.3, c), -12.3, c)
        for p, q in zip(nodes, back):
            self.assertAlmostEqual(p[0], q[0], places=9)
            self.assertAlmostEqual(p[1], q[1], places=9)

    def test_zero_is_identity(self):
        nodes = sym_hex()
        self.assertEqual(E.rotate_nodes(nodes, 0.0, (0.0, 0.0)), nodes)


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
