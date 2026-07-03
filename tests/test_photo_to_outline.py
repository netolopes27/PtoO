#!/usr/bin/env python3
# =============================================================================
# test_photo_to_outline.py — suíte TDD do tooling foto → contorno
# -----------------------------------------------------------------------------
# Três níveis (ver docs/design.md):
#   A. Unidade  — funções puras de polígono/escala/homografia (sem imagem).
#   B. Sintético — cena ArUco gerada por numpy; rectify() retifica em mm/aborta.
#   C. Ponta-a-ponta — contorno tirado DIRETAMENTE de thermpro.jpg (foto na base
#      ArUco, sem referência à mão): escala via marcadores, encaixe/limpeza/curvas.
#
# Rodar: .venv/Scripts/python tests/run_image_tests.py
# =============================================================================

import math
import os
import sys
import unittest

import numpy as np

# Importa o módulo sob teste (photo_to_outline.py).
THIS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(THIS)   # raiz do projeto (pai de tests/)
sys.path.insert(0, ROOT)

import photo_to_outline as P  # noqa: E402
import calibration_target as CT  # noqa: E402

THERMPRO_JPG = os.path.join(ROOT, "thermpro.jpg")


# -----------------------------------------------------------------------------
# Helpers de teste
# -----------------------------------------------------------------------------
def regular_polygon(n, r, cx=0.0, cy=0.0):
    return [(cx + r * math.cos(2 * math.pi * k / n),
             cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def rectangle(w, h, cx=0.0, cy=0.0):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
            (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


def star_polygon(points, r_out, r_in, samples_per_edge=12):
    """Estrela de `points` pontas (forma CÔNCAVA), arestas amostradas densamente —
    o ajuste livre precisa de MUITAS cúbicas; serve p/ provar o teto rígido de curvas."""
    pts = []
    for k in range(points):
        a0 = 2 * math.pi * k / points
        a1 = 2 * math.pi * (k + 0.5) / points
        a2 = 2 * math.pi * (k + 1) / points
        for s in range(samples_per_edge):              # ponta → vale
            t = s / samples_per_edge
            a, r = a0 + (a1 - a0) * t, r_out + (r_in - r_out) * t
            pts.append((r * math.cos(a), r * math.sin(a)))
        for s in range(samples_per_edge):              # vale → ponta
            t = s / samples_per_edge
            a, r = a1 + (a2 - a1) * t, r_in + (r_out - r_in) * t
            pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def rounded_rect(w, h, r, n=60):
    """Retângulo arredondado (forma típica de um gadget: thermpro, controle, etc.) —
    cantos em arco, p/ exercitar o POCKET de encaixe por quadrante."""
    pts = []
    corners = [(w / 2 - r, h / 2 - r, 0.0), (-(w / 2 - r), h / 2 - r, math.pi / 2),
               (-(w / 2 - r), -(h / 2 - r), math.pi), (w / 2 - r, -(h / 2 - r), 3 * math.pi / 2)]
    for cx, cy, a0 in corners:
        for s in range(n):
            a = a0 + (math.pi / 2) * s / n
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def rect_with_right_bump(w=60.0, h=44.0, bump=4.0, half=5.0, step=0.4):
    """Retângulo CCW com um RESSALTO triangular no MEIO da aresta direita, projetando
    `bump` mm além de x=w/2 (largura 2*`half` em y). Modela a saliência lateral real
    (pega de borracha) que o seletor radial por quadrante ignora — a ponta em
    (w/2+bump, 0) NÃO é 'externa ao centro' como os cantos, então nunca vira âncora."""
    def seg(p, q):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        m = max(1, int(round(d / step)))
        return [(p[0] + (q[0] - p[0]) * t / m, p[1] + (q[1] - p[1]) * t / m) for t in range(m)]
    xr, yt = w / 2, h / 2
    path = []
    path += seg((-xr, -yt), (xr, -yt))        # base: esq→dir (CCW)
    path += seg((xr, -yt), (xr, -half))       # direita: sobe até a base do ressalto
    path += seg((xr, -half), (xr + bump, 0))  # sobe p/ a ponta do ressalto
    path += seg((xr + bump, 0), (xr, half))   # desce da ponta
    path += seg((xr, half), (xr, yt))         # direita: até o canto
    path += seg((xr, yt), (-xr, yt))          # topo: dir→esq
    path += seg((-xr, yt), (-xr, -yt))        # esquerda: topo→base
    return path


# =============================================================================
# A. UNIDADE — funções puras
# =============================================================================
class TestPolygonBasics(unittest.TestCase):
    def test_signed_area_ccw_positive(self):
        # Retângulo CCW → área com sinal positiva = +w*h.
        a = P.signed_area(rectangle(4, 2))
        self.assertAlmostEqual(a, 8.0, places=6)

    def test_signed_area_cw_negative(self):
        a = P.signed_area(list(reversed(rectangle(4, 2))))
        self.assertAlmostEqual(a, -8.0, places=6)

    def test_polygon_area_absolute(self):
        self.assertAlmostEqual(P.polygon_area(list(reversed(rectangle(4, 2)))), 8.0, places=6)

    def test_ensure_ccw(self):
        cw = list(reversed(rectangle(4, 2)))
        self.assertGreater(P.signed_area(P.ensure_ccw(cw)), 0)
        ccw = rectangle(4, 2)
        self.assertGreater(P.signed_area(P.ensure_ccw(ccw)), 0)

    def test_bbox_and_size(self):
        pts = rectangle(10, 4, cx=5, cy=-3)
        self.assertEqual(P.bbox(pts), (0.0, -5.0, 10.0, -1.0))
        w, h = P.size(pts)
        self.assertAlmostEqual(w, 10.0)
        self.assertAlmostEqual(h, 4.0)

    def test_is_closed_and_dedup(self):
        pts = rectangle(4, 2)
        self.assertFalse(P.is_closed(pts))
        closed = pts + [pts[0]]
        self.assertTrue(P.is_closed(closed))
        self.assertEqual(len(P.dedup_closing_point(closed)), len(pts))


class TestSimplifyAndSmooth(unittest.TestCase):
    def test_douglas_peucker_removes_colinear(self):
        # Pontos colineares extra devem sumir, preservando os cantos.
        pts = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 3), (0, 3)]
        out = P.douglas_peucker(pts, eps=0.01)
        self.assertLess(len(out), len(pts))
        # bbox preservada
        self.assertEqual(P.bbox(out), P.bbox(pts))

    def test_chaikin_reduces_max_corner_sharpness(self):
        # Quadrado tem cantos de 90°; Chaikin deve abrir o ângulo mínimo.
        sq = rectangle(10, 10)
        before = min(P.corner_angles(sq, closed=True))
        after = min(P.corner_angles(P.chaikin(sq, iterations=3, closed=True), closed=True))
        self.assertGreater(after, before)

    def test_chaikin_keeps_polygon_closed_and_ccw(self):
        sq = P.ensure_ccw(rectangle(10, 10))
        out = P.chaikin(sq, iterations=2, closed=True)
        self.assertGreater(P.signed_area(out), 0)

    def test_corner_radii_small_at_sharp_corner(self):
        # Num quadrado os 4 cantos têm raio osculador pequeno; lados ~infinito.
        sq = P.resample_uniform(rectangle(20, 20), step=2.0, closed=True)
        self.assertLess(P.min_corner_radius(sq), 2.0)

    def test_enforce_min_radius(self):
        sq = P.resample_uniform(rectangle(40, 40), step=1.0, closed=True)
        r_min = 3.0
        out = P.enforce_min_radius(sq, r_min=r_min, closed=True)
        # tolerância: a discretização do arco deixa o raio osculador ~r_min
        self.assertGreaterEqual(P.min_corner_radius(out), r_min * 0.8)

    def test_resample_uniform_spacing(self):
        out = P.resample_uniform(rectangle(10, 10), step=1.0, closed=True)
        d = []
        for i in range(len(out)):
            x0, y0 = out[i]
            x1, y1 = out[(i + 1) % len(out)]
            d.append(math.hypot(x1 - x0, y1 - y0))
        self.assertLess(max(d), 1.5)


class TestFitAndSmoothness(unittest.TestCase):
    def test_coverage_full_when_contained(self):
        outer = rectangle(20, 20)
        inner = rectangle(10, 10)
        self.assertAlmostEqual(P.coverage(outer, inner), 1.0, places=2)

    def test_coverage_partial_when_poking_out(self):
        outer = rectangle(20, 20)
        inner = rectangle(30, 4)  # transborda nas laterais
        self.assertLess(P.coverage(outer, inner), 0.8)

    def test_roughness_zero_for_smooth_circle(self):
        circ = regular_polygon(360, 20)
        self.assertLess(P.boundary_roughness(circ, win_mm=2.0), 0.05)

    def test_roughness_high_for_jagged(self):
        # Dente-de-serra sobre um círculo: aspereza deve ser claramente alta.
        jag = []
        for k in range(360):
            r = 20 + (0.8 if k % 2 else -0.8)
            ang = 2 * math.pi * k / 360
            jag.append((r * math.cos(ang), r * math.sin(ang)))
        self.assertGreater(P.boundary_roughness(jag, win_mm=2.0), 0.3)


class TestBezierFit(unittest.TestCase):
    def test_fits_circle_with_few_curves(self):
        # Um círculo cabe em poucas cúbicas e o ajuste é fiel.
        circ = regular_polygon(120, 20)
        cub = P.fit_closed_beziers(circ, tol=0.1)
        self.assertLessEqual(len(cub), 12)
        flat = P.flatten_beziers(cub, seg=16)
        # erro radial pequeno
        errs = [abs(math.hypot(x, y) - 20) for (x, y) in flat]
        self.assertLess(max(errs), 0.3)

    def test_bezier_point_endpoints(self):
        bez = ((0, 0), (1, 2), (2, 2), (3, 0))
        self.assertEqual(P.bezier_point(bez, 0.0), (0, 0))
        self.assertEqual(P.bezier_point(bez, 1.0), (3, 0))

    def test_corner_detected_on_square(self):
        rp = P.resample_uniform(rectangle(40, 40), 0.5, closed=True)
        corners = P._corner_indices(rp, angle_thresh=40, win=3)
        self.assertEqual(len(corners), 4)


class TestAnchoredFit(unittest.TestCase):
    """Ajuste ANCORADO NAS EXTREMIDADES (ideia: fixar os pontos mais distantes do
    objeto garante que ele cabe; traçar o resto suave evita viradas bruscas)."""

    def test_douglas_peucker_idx_keeps_corners(self):
        # Quadrado com pontos colineares: RDP-idx mantém só os 4 cantos.
        pts = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (3, 2), (3, 3),
               (2, 3), (1, 3), (0, 3), (0, 2), (0, 1)]
        keep = P.douglas_peucker_idx(pts, eps=0.01)
        corners = {(0, 0), (3, 0), (3, 3), (0, 3)}
        self.assertTrue(corners.issubset({pts[i] for i in keep}))
        self.assertLessEqual(len(keep), 6)

    def test_hull_anchors_are_dominant_extremities(self):
        # Retângulo amostrado: as âncoras (extremidades dominantes) ≈ 4 cantos.
        rp = P.resample_uniform(rectangle(60, 30), 0.5, closed=True)
        idx = P.hull_anchor_indices(rp, simplify_mm=2.0)
        self.assertGreaterEqual(len(idx), 4)
        self.assertLessEqual(len(idx), 8)

    def test_anchored_contains_with_few_smooth_nodes(self):
        # Forma convexa (círculo): o ajuste ancorado a contém com poucas cúbicas
        # suaves e nunca corta para dentro (a peça cabe).
        circ = regular_polygon(120, 20)
        cub = P.fit_closed_beziers_anchored(circ, smooth_mm=2.0, simplify_mm=2.0)
        self.assertGreater(len(cub), 0)
        self.assertLess(len(cub), 20)                      # poucos nós
        flat = P.flatten_beziers(cub, seg=24)
        self.assertGreaterEqual(P.coverage(flat, circ), 0.985)   # cabe
        self.assertLess(P.boundary_roughness(flat, 2.0), 0.1)    # suave

    def test_anchored_fewer_nodes_when_simplified_more(self):
        # Mais simplificação do fecho → menos âncoras → menos (ou igual) nós.
        circ = regular_polygon(160, 25)
        few = P.fit_closed_beziers_anchored(circ, smooth_mm=2.0, simplify_mm=4.0)
        many = P.fit_closed_beziers_anchored(circ, smooth_mm=2.0, simplify_mm=1.0)
        self.assertLessEqual(len(few), len(many))

    def test_anchored_all_nodes_smooth(self):
        # TODO nó (junção entre cúbicas consecutivas, incl. o fechamento) é SUAVE:
        # a tangente que chega e a que sai são colineares (sem bico/cusp).
        cub = P.fit_closed_beziers_anchored(regular_polygon(160, 25),
                                            smooth_mm=2.0, simplify_mm=2.0)
        self.assertGreater(len(cub), 2)
        m = len(cub)
        for k in range(m):
            a, b = cub[k], cub[(k + 1) % m]          # 'a' termina onde 'b' começa
            din = P._unit((a[3][0] - a[2][0], a[3][1] - a[2][1]))   # chega (p3 - c2)
            dout = P._unit((b[1][0] - b[0][0], b[1][1] - b[0][1]))  # sai  (c1 - p0)
            cross = abs(din[0] * dout[1] - din[1] * dout[0])
            dot = din[0] * dout[0] + din[1] * dout[1]
            self.assertLess(cross, 1e-3, f"nó {k} com bico (cross={cross:.4f})")
            self.assertGreater(dot, 0.0, f"nó {k} com tangente invertida")

    def test_min_dist_controls_density(self):
        # --min-dist é a ÚNICA alavanca de densidade do pocket: menor distância mínima
        # entre âncoras ⇒ MAIS cúbicas (contorno mais justo); maior ⇒ menos. Não há mais
        # teto de nós — a quantidade de curvas emerge só do espaçamento.
        star = star_polygon(5, 30, 14, samples_per_edge=12)
        dense = P.fit_closed_beziers_anchored(star, smooth_mm=1.0, min_dist_mm=2.0)
        sparse = P.fit_closed_beziers_anchored(star, smooth_mm=1.0, min_dist_mm=20.0)
        self.assertGreater(len(dense), len(sparse))    # menos distância ⇒ mais nós
        # mesmo denso, TODO nó continua suave (G1).
        m = len(dense)
        for k in range(m):
            a, b = dense[k], dense[(k + 1) % m]
            din = P._unit((a[3][0] - a[2][0], a[3][1] - a[2][1]))
            dout = P._unit((b[1][0] - b[0][0], b[1][1] - b[0][1]))
            self.assertLess(abs(din[0] * dout[1] - din[1] * dout[0]), 1e-3)

    def test_min_dist_default_is_ten(self):
        # A densidade do pocket é controlada só por --min-dist (default 10 mm); o teto de
        # nós (MAX_NODES) foi removido.
        self.assertEqual(P.ANCHOR_MIN_DIST_MM, 10.0)
        self.assertFalse(hasattr(P, "MAX_NODES"))

    def test_quadrant_anchors_one_per_quadrant_when_far(self):
        # Sem teto: a densidade vem só do min_dist. Com min_dist grande (≥ o tamanho de um
        # quadrante) cada setor cabe 1 âncora — a extremidade mais externa.
        shape = rounded_rect(50, 34, 8, n=80)
        rp = P.resample_uniform(shape, 0.4, closed=True)
        idx = P._quadrant_anchors(rp, min_dist_mm=40.0)
        self.assertEqual(len(idx), 4)
        xs = [p[0] for p in rp]; ys = [p[1] for p in rp]
        cx = 0.5 * (min(xs) + max(xs)); cy = 0.5 * (min(ys) + max(ys))
        quads = {(rp[i][0] >= cx, rp[i][1] >= cy) for i in idx}
        self.assertEqual(len(quads), 4)            # uma âncora em cada quadrante

    def test_quadrant_anchors_min_distance(self):
        # RESTRIÇÃO: âncoras do MESMO quadrante ficam a ≥ min_dist_mm (parametrizável,
        # default 10). min_dist maior → menos (ou igual) âncoras.
        self.assertEqual(P.ANCHOR_MIN_DIST_MM, 10.0)
        shape = rounded_rect(60, 40, 8, n=120)
        rp = P.resample_uniform(shape, 0.4, closed=True)
        xs = [p[0] for p in rp]; ys = [p[1] for p in rp]
        cx = 0.5 * (min(xs) + max(xs)); cy = 0.5 * (min(ys) + max(ys))
        for md in (5.0, 10.0, 20.0):
            idx = P._quadrant_anchors(rp, min_dist_mm=md)
            by_q = {}
            for i in idx:
                by_q.setdefault((rp[i][0] >= cx, rp[i][1] >= cy), []).append(rp[i])
            for q, ps in by_q.items():
                for a in range(len(ps)):
                    for b in range(a + 1, len(ps)):
                        d = math.hypot(ps[a][0] - ps[b][0], ps[a][1] - ps[b][1])
                        self.assertGreaterEqual(d, md - 1e-6, f"quad {q}: {d:.2f} < {md}")
        self.assertLessEqual(len(P._quadrant_anchors(rp, min_dist_mm=20.0)),
                             len(P._quadrant_anchors(rp, min_dist_mm=5.0)))

    def test_pocket_contains_piece(self):
        # OBJETIVO do modo encaixe: o pocket CONTÉM a peça (coverage ~1), em várias
        # densidades de min_dist. Vale p/ formas convexas e côncavas (a estrela é côncava —
        # o pocket faz a ponte sobre os vales, contendo tudo).
        for shape in (regular_polygon(120, 20), star_polygon(5, 30, 14), rounded_rect(50, 34, 8)):
            for md in (12.0, 6.0, 2.0):
                cub = P.fit_closed_beziers_anchored(shape, smooth_mm=1.0, min_dist_mm=md)
                self.assertGreaterEqual(P.coverage(P.flatten_beziers(cub, seg=40), shape), 0.99)

    def test_pocket_near_object_size(self):
        # O pocket FICA JUSTO: nunca encolhe além da tolerância de penetração
        # (`POCKET_EPS_MM` — pode TOCAR/cortar de leve, não some p/ dentro). Garante o
        # "firme": não vira um contorno muito menor que a peça. Formas arredondadas.
        margin = P.POCKET_EPS_MM + 0.15
        for shape in (regular_polygon(120, 20), rounded_rect(50, 34, 8)):
            tw, th = P.size(shape)
            for md in (12.0, 6.0, 2.0):
                flat = P.flatten_beziers(
                    P.fit_closed_beziers_anchored(shape, smooth_mm=1.0, min_dist_mm=md), seg=40)
                pw, ph = P.size(flat)
                self.assertGreaterEqual(pw, tw - margin)     # não encolhe além da tolerância
                self.assertGreaterEqual(ph, th - margin)

    def test_pocket_eps_param_default_and_tighter(self):
        # `pocket_eps` é a penetração tolerada (mm) do modo POCKET, exposta como parâmetro
        # (e flag --pocket-eps). Default = POCKET_EPS_MM; menor eps corta MENOS a peça →
        # cobertura nunca menor (contém ≥). Segue contendo a peça.
        self.assertEqual(P.POCKET_EPS_MM, 0.5)
        shape = rounded_rect(50, 34, 8)
        cov = {}
        for eps in (0.0, 0.5):
            cub = P.fit_closed_beziers_anchored(shape, smooth_mm=1.0, min_dist_mm=6.0, pocket_eps=eps)
            cov[eps] = P.coverage(P.flatten_beziers(cub, seg=40), shape)
            self.assertGreaterEqual(cov[eps], 0.99)           # ainda contém a peça
        self.assertGreaterEqual(cov[0.0], cov[0.5] - 1e-9)    # eps menor não contém menos


class TestProtrusionAnchors(unittest.TestCase):
    """Saliência no MEIO de uma aresta (ressalto lateral): o seletor radial por
    quadrante a ignora (não é 'externa ao centro' como os cantos). Uma âncora de
    CONVEXIDADE local tem de fixá-la, senão a cúbica suave arredonda por cima dela."""

    def test_protrusion_anchor_lands_on_bump_tip(self):
        # Há ≥1 âncora de saliência e a mais próxima cai na ponta do ressalto (x≈34, y≈0).
        rp = P.resample_uniform(rect_with_right_bump(bump=4.0), 0.4, closed=True)
        idx = P._protrusion_anchors(rp, P.PROTRUSION_DEV_MM)
        self.assertGreaterEqual(len(idx), 1)
        nearest = min(math.hypot(rp[i][0] - 34.0, rp[i][1] - 0.0) for i in idx)
        self.assertLess(nearest, 2.0)

    def test_no_protrusion_on_smooth_shape(self):
        # Curvatura suave/uniforme (círculo) não gera saliências espúrias — só PICOS
        # locais (proeminência acima da vizinhança) contam, não a curvatura de fundo.
        rp = P.resample_uniform(regular_polygon(240, 25), 0.4, closed=True)
        self.assertEqual(P._protrusion_anchors(rp, P.PROTRUSION_DEV_MM), [])

    def test_pocket_captures_side_bump(self):
        # O pocket ALCANÇA o ressalto: cobertura alta e a borda direita chega à ponta
        # (x≈34), contendo a peça.
        shape = rect_with_right_bump(bump=4.0)
        cub = P.fit_closed_beziers_anchored(shape, smooth_mm=1.0, min_dist_mm=4.0)
        flat = P.flatten_beziers(cub, seg=40)
        self.assertGreaterEqual(P.coverage(flat, shape), 0.99)
        self.assertGreater(max(x for x, _ in flat), 34.0 - 1.0)

    def test_bump_pocket_all_nodes_smooth(self):
        # Mesmo com a âncora de saliência, todo nó continua G1 (sem bico/cusp).
        cub = P.fit_closed_beziers_anchored(rect_with_right_bump(bump=4.0),
                                            smooth_mm=1.0, min_dist_mm=4.0)
        m = len(cub)
        self.assertGreater(m, 2)
        for k in range(m):
            a, b = cub[k], cub[(k + 1) % m]
            din = P._unit((a[3][0] - a[2][0], a[3][1] - a[2][1]))
            dout = P._unit((b[1][0] - b[0][0], b[1][1] - b[0][1]))
            self.assertLess(abs(din[0] * dout[1] - din[1] * dout[0]), 1e-3,
                            f"nó {k} com bico")


class TestCoverageTolerance(unittest.TestCase):
    """v0.6: `coverage(..., tol_mm=)` mede o contém com tolerância de PROFUNDIDADE —
    penetração rasa (≤ tol, a serrilha de ruído da referência CRUA) não conta; um corte
    profundo (feature real perdida, ex.: o gancho da trena) continua furando o gate."""

    def test_shallow_sliver_forgiven(self):
        inner = rectangle(20, 20)
        outer = rectangle(19.75, 20, cx=-0.125)     # corta 0.25 mm na borda direita
        self.assertLess(P.coverage(outer, inner, ppm=16.0), 0.995)
        self.assertGreaterEqual(P.coverage(outer, inner, ppm=16.0, tol_mm=0.3), 0.9999)

    def test_deep_cut_still_flagged(self):
        inner = rectangle(20, 20)
        outer = rectangle(16, 20, cx=-2.0)          # corta 2 mm — feature perdida
        self.assertLess(P.coverage(outer, inner, ppm=16.0, tol_mm=0.3), 0.99)

    def test_default_tol_zero_unchanged(self):
        inner = rectangle(20, 20)
        outer = rectangle(19.75, 20, cx=-0.125)
        self.assertAlmostEqual(P.coverage(outer, inner, ppm=16.0),
                               P.coverage(outer, inner, ppm=16.0, tol_mm=0.0), places=9)


class TestPreserveSpikes(unittest.TestCase):
    """Espigão convexo FINO e real (caso 'gancho da trena', v0.6): o low-pass do
    `smooth_mm` RECUA a ponta antes da seleção de âncoras — o piso de contenção nasce
    sem ela e o pocket corta o topo do espigão SEM nenhum aviso (o `contém` mal se move).
    `_preserve_spikes` reinjeta na curva suavizada os trechos crus em torno de picos com
    proeminência ≥ PROTRUSION_DEV_MM (ruído sub-mm não tem proeminência → intacto)."""

    def test_preserve_spikes_restores_thin_spike_tip(self):
        # Pino de 1 mm de largura × 5 mm (ponta em x=35): o low-pass 2.5 mm recua a
        # ponta ≥ 0.3 mm; o preserve devolve a extremidade CRUA.
        raw = P.resample_uniform(rect_with_right_bump(bump=5.0, half=0.5), 0.15, closed=True)
        sm = P.lowpass_closed(raw, win_mm=2.5, step=0.15)
        raw_tip = max(x for x, _ in raw)
        self.assertLess(max(x for x, _ in sm), raw_tip - 0.3)      # premissa: recuou
        kept = P._preserve_spikes(raw, sm, span_mm=1.5)
        self.assertGreaterEqual(max(x for x, _ in kept), raw_tip - 0.05)

    def test_preserve_spikes_noop_on_smooth_shape(self):
        # Curvatura macro uniforme (cantos arredondados): proeminência ~0 → NENHUM ponto
        # restaurado, o suavizado volta intacto (o preserve não desfaz o smooth-mm).
        raw = P.resample_uniform(rounded_rect(60, 44, 8), 0.15, closed=True)
        sm = P.lowpass_closed(raw, win_mm=8.0, step=0.15)
        self.assertEqual(P._preserve_spikes(raw, sm, span_mm=10.0), sm)

    def test_pocket_wraps_thin_spike(self):
        # Ponta-a-ponta do ajuste: o POCKET alcança a ponta CRUA do pino (x=20) em vez
        # de cortá-la pela versão recuada do low-pass — e contém a peça.
        shape = rect_with_right_bump(w=30.0, h=24.0, bump=5.0, half=0.5)
        cub = P.fit_closed_beziers_anchored(shape, smooth_mm=2.5, min_dist_mm=1.5)
        flat = P.flatten_beziers(cub, seg=40)
        self.assertGreater(max(x for x, _ in flat), 19.7)          # ponta em x=20
        self.assertGreaterEqual(P.coverage(flat, shape), 0.999)


class TestRegularizeSilhouette(unittest.TestCase):
    """Regularização da silhueta no domínio da MÁSCARA (remove ondulações da borda
    preta de baixo contraste sem arredondar os cantos macro)."""

    @staticmethod
    def _mask_from_poly(poly_px, pad=12):
        import cv2
        pts = np.array(poly_px, np.float32)
        pts = pts - pts.min(0) + pad
        w = int(math.ceil(pts[:, 0].max())) + pad
        h = int(math.ceil(pts[:, 1].max())) + pad
        m = np.zeros((h, w), np.uint8)
        cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255)
        return m

    @staticmethod
    def _sawtooth_circle(r=80.0, teeth_amp=6.0, n=720, cx=160.0, cy=160.0):
        poly = []
        for k in range(n):
            ang = 2 * math.pi * k / n
            rr = r + (teeth_amp if (k // 12) % 2 else -teeth_amp)   # dente-de-serra ~8px
            poly.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        return poly

    @staticmethod
    def _perimeter(pts):
        n = len(pts)
        return sum(math.hypot(pts[(i + 1) % n][0] - pts[i][0],
                              pts[(i + 1) % n][1] - pts[i][1]) for i in range(n))

    def test_regularize_removes_waviness(self):
        # Borda dente-de-serra (ondulação ~0.75 mm): o perímetro cru é ~2.4× o ideal; após
        # regularizar com raio 2 mm ele cai p/ perto do círculo liso, mantendo ~toda a área.
        mask = self._mask_from_poly(self._sawtooth_circle())
        ideal = 2 * math.pi * (80.0 / P.PX_PER_MM)             # círculo liso de raio 10 mm
        raw = self._perimeter(P.extract_outline(mask, 1.0 / P.PX_PER_MM))
        reg = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM)
        smo = self._perimeter(P.extract_outline(reg, 1.0 / P.PX_PER_MM))
        self.assertGreater(raw, 1.5 * ideal)                   # a borda crua é bem ondulada
        self.assertLess(smo, 1.25 * ideal)                     # regularizada ≈ círculo liso
        self.assertGreaterEqual(np.count_nonzero(reg) / np.count_nonzero(mask), 0.95)

    def test_regularize_keeps_macro_size(self):
        # Num disco liso GRANDE (raio macro ≫ raio de regularização) o encolhimento por
        # curvatura é desprezível — não rói a forma real (≈ caso do contorno do thermpro).
        disk = [(260 + 200 * math.cos(2 * math.pi * k / 720),
                 260 + 200 * math.sin(2 * math.pi * k / 720)) for k in range(720)]
        mask = self._mask_from_poly(disk)
        before = int(np.count_nonzero(mask))
        after = int(np.count_nonzero(P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM)))
        self.assertLess(abs(after - before) / before, 0.03)

    def test_regularize_noop_when_zero(self):
        mask = self._mask_from_poly([(10, 10), (120, 14), (118, 122), (14, 118)])
        out = P.regularize_silhouette(mask, 0.0, ppmm=P.PX_PER_MM)
        self.assertTrue(np.array_equal(out, mask))

    # --- Etapa B (v0.5): preservar RESSALTOS convexos -------------------------
    @staticmethod
    def _bump_and_notch():
        """Bloco macro com um RESSALTO convexo (sai do topo) e um ENTALHE côncavo
        (entra pela base), ambos de amplitude sub-raio. A regularização isotrópica
        apaga os DOIS; enviesada p/ fechamento deve apagar só o entalhe (côncavo) e
        PRESERVAR o ressalto (convexo, ex.: a aba lateral da peça)."""
        import cv2
        m = np.zeros((400, 400), np.uint8)
        cv2.rectangle(m, (100, 100), (300, 300), 255, -1)      # corpo macro
        cv2.rectangle(m, (180, 84), (210, 100), 255, -1)       # ressalto convexo (16 px p/ cima)
        cv2.rectangle(m, (140, 284), (170, 300), 0, -1)        # entalhe côncavo (16 px p/ dentro)
        return m

    def test_regularize_preserves_convex_bump(self):
        mask = self._bump_and_notch()
        iso = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM, preserve_convex=False)
        keep = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM, preserve_convex=True)
        # ponta do ressalto convexo: sobrevive SÓ no modo enviesado p/ fechamento
        self.assertGreater(int(keep[88, 195]), 0)
        self.assertEqual(int(iso[88, 195]), 0)

    def test_regularize_fills_concave_notch_either_way(self):
        mask = self._bump_and_notch()
        iso = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM, preserve_convex=False)
        keep = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM, preserve_convex=True)
        # topo (extremo FECHADO) do entalhe côncavo: preenchido nos DOIS modos — o closing
        # tampa a reentrância de amplitude < raio (a "boca" na borda fica aberta, por isso
        # amostro perto do fundo do entalhe, não na boca).
        self.assertGreater(int(iso[287, 155]), 0)
        self.assertGreater(int(keep[287, 155]), 0)

    def test_regularize_preserve_convex_default_off(self):
        # default preserve_convex=False = comportamento atual inalterado (byte-a-byte).
        mask = self._bump_and_notch()
        a = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM)
        b = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM, preserve_convex=False)
        self.assertTrue(np.array_equal(a, b))

    # --- v0.6: AVISAR quando a regularização remove saliência convexa real ---------
    @staticmethod
    def _body_with_spike():
        """Corpo macro com um ESPIGÃO fino no topo (1×5 mm a 8 px/mm — o gancho da
        trena): o modo isotrópico o apaga por inteiro, e nada no `contém` acusa."""
        import cv2
        m = np.zeros((400, 400), np.uint8)
        cv2.rectangle(m, (100, 100), (300, 300), 255, -1)      # corpo macro
        cv2.rectangle(m, (196, 60), (204, 100), 255, -1)       # espigão 8×40 px = 1×5 mm
        return m

    def test_warn_when_smoothing_removes_protrusion(self):
        # O isotrópico REMOVE o espigão (proeminência ≥ PROTRUSION_DEV_MM, área ≥ 1 mm²)
        # → o CLI tem de AVISAR (a remoção é silenciosa p/ o gate `contém`).
        import contextlib
        import io
        mask = self._body_with_spike()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM)
        self.assertEqual(int(out[70, 200]), 0)                 # espigão de fato removido
        self.assertIn("saliência", err.getvalue())

    def test_no_warn_on_subthreshold_waviness(self):
        # Serrilha de ruído (amplitude 0.5 mm < PROTRUSION_DEV_MM): remover é o TRABALHO
        # do --mask-smooth-mm — nenhum aviso.
        import contextlib
        import io
        mask = self._mask_from_poly(self._sawtooth_circle(teeth_amp=4.0))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM)
        self.assertEqual(err.getvalue(), "")

    def test_no_warn_when_keep_bumps_preserves(self):
        # Com --mask-smooth-keep-bumps o espigão sobrevive → nada removido, nada avisado.
        import contextlib
        import io
        mask = self._body_with_spike()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = P.regularize_silhouette(mask, 2.0, ppmm=P.PX_PER_MM, preserve_convex=True)
        self.assertGreater(int(out[70, 200]), 0)               # keep-bumps preservou
        self.assertEqual(err.getvalue(), "")


class TestScaleAndHomography(unittest.TestCase):
    def test_px_per_mm(self):
        self.assertAlmostEqual(P.px_per_mm(45.0, 10.0), 4.5, places=6)
        self.assertAlmostEqual(P.mm_per_px(45.0, 10.0), 10.0 / 45.0, places=6)

    def test_homography_recovers_corners(self):
        src = [(0, 0), (100, 0), (100, 50), (0, 50)]
        dst = [(10, 5), (210, 8), (205, 110), (8, 95)]
        H = P.homography_from_corners(src, dst)
        got = P.apply_homography(H, src)
        for (gx, gy), (dx, dy) in zip(got, dst):
            self.assertAlmostEqual(gx, dx, places=3)
            self.assertAlmostEqual(gy, dy, places=3)


# =============================================================================
# B. SINTÉTICO — cena ArUco gerada por numpy; rectify retifica em mm / aborta
# -----------------------------------------------------------------------------
# Renderiza uma "foto" da base (marcadores ArUco nas posições nominais) com um
# objeto escuro de tamanho CONHECIDO no centro, opcionalmente sob perspectiva. O
# rectify deve devolver o miolo branco num canvas métrico de escala uniforme, e o
# pipeline deve recuperar o tamanho real do objeto, mesmo com keystone.
# =============================================================================
def _aruco_scene(layout, ppmm_img=6.0, warp=0.0, obj_mm=(40.0, 30.0)):
    import cv2
    W, H = layout["page"]
    iw, ih = int(round(W * ppmm_img)), int(round(H * ppmm_img))
    img = np.full((ih, iw, 3), 255, np.uint8)
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, layout["dict"]))
    mods = layout["modules"]
    for mk in layout["markers"]:
        side = int(round(mk.size * ppmm_img))
        tile = cv2.aruco.generateImageMarker(dic, mk.id, side)
        tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
        x = int(round(mk.x * ppmm_img))
        y = int(round(mk.y * ppmm_img))
        img[y:y + side, x:x + side] = tile[:ih - y, :iw - x]
    # Objeto escuro centrado no miolo (cor saturada p/ exercitar a segmentação).
    x0, y0, x1, y1 = layout["inner_rect"]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ow, oh = obj_mm
    p0 = (int(round((cx - ow / 2) * ppmm_img)), int(round((cy - oh / 2) * ppmm_img)))
    p1 = (int(round((cx + ow / 2) * ppmm_img)), int(round((cy + oh / 2) * ppmm_img)))
    cv2.rectangle(img, p0, p1, (30, 60, 200), -1)   # BGR: laranja/vermelho saturado
    if warp:
        d = warp * iw
        src = np.float32([[0, 0], [iw, 0], [iw, ih], [0, ih]])
        dst = np.float32([[d, 1.4 * d], [iw - 0.5 * d, 0.3 * d],
                          [iw - 0.2 * d, ih - 1.1 * d], [0.6 * d, ih - 0.2 * d]])
        Hm = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, Hm, (iw, ih), borderValue=(255, 255, 255))
    return img


class TestRectifyAruco(unittest.TestCase):
    def test_canvas_is_metric_and_uniform(self):
        layout = CT.default_layout()
        img = _aruco_scene(layout)
        rect, mmpp_x, mmpp_y, conf = P.rectify(img)
        self.assertAlmostEqual(conf, 1.0, places=6)          # todos os marcadores
        self.assertAlmostEqual(mmpp_x, mmpp_y, places=9)     # escala uniforme
        self.assertAlmostEqual(mmpp_x, 1.0 / P.PX_PER_MM, places=9)
        x0, y0, x1, y1 = layout["inner_rect"]
        self.assertEqual(rect.shape[1], int(round((x1 - x0) * P.PX_PER_MM)))
        self.assertEqual(rect.shape[0], int(round((y1 - y0) * P.PX_PER_MM)))

    def test_object_size_recovered_flat(self):
        layout = CT.default_layout()
        img = _aruco_scene(layout, obj_mm=(40.0, 30.0))
        rect, mx, my, _ = P.rectify(img)
        sil = P.extract_outline(P.segment_tool(rect), mx, my)
        w, h = P.size(sil)
        self.assertAlmostEqual(w, 40.0, delta=1.0)
        self.assertAlmostEqual(h, 30.0, delta=1.0)

    def test_object_size_recovered_under_perspective(self):
        # Mesmo com keystone, a homografia ArUco devolve o tamanho real (≤ ~1 mm).
        layout = CT.default_layout()
        img = _aruco_scene(layout, warp=0.05, obj_mm=(40.0, 30.0))
        rect, mx, my, _ = P.rectify(img)
        sil = P.extract_outline(P.segment_tool(rect), mx, my)
        w, h = P.size(sil)
        self.assertAlmostEqual(w, 40.0, delta=1.5)
        self.assertAlmostEqual(h, 30.0, delta=1.5)

    def test_aborts_without_markers(self):
        blank = np.full((400, 600, 3), 255, np.uint8)
        with self.assertRaises(P.GridDetectionError):
            P.rectify(blank)

    def test_tilt_zero_when_flat_positive_when_warped(self):
        import cv2
        layout = CT.default_layout()

        def tilt(warp):
            gray = cv2.cvtColor(_aruco_scene(layout, warp=warp), cv2.COLOR_BGR2GRAY)
            c, ids = P.detect_markers(gray, layout["dict"])
            ip, mp = P.aruco_correspondences(c, ids, layout)
            # Mesmo contrato do rectify: a homografia imagem→mm já resolvida é
            # INVERTIDA e passada (sem um segundo RANSAC dentro da estimativa).
            Hmat, _ = cv2.findHomography(ip, mp, cv2.RANSAC, 3.0)
            return P.estimate_tilt_deg(np.linalg.inv(Hmat), gray.shape)

        flat, warped = tilt(0.0), tilt(0.06)
        self.assertLess(flat, 3.0)                 # cena frontal ≈ nadir
        self.assertGreater(warped, flat + 3.0)     # keystone → inclinação aparente


# =============================================================================
# B2. HISTERESE DE SOMBRA (--shadow remove): recupera o TOPO PRETO, rejeita a
#     SOMBRA DE CONTATO cinza. O separador é a SATURAÇÃO (SEG_WEAK_SAT_MIN):
#     bisel preto do topo tem croma → entra; sombra de contato é cinza → barrada.
# =============================================================================
def _shadow_scene():
    """Canvas retificado sintético p/ exercitar a histerese de `segment_tool`. Fundo
    branco; objeto central com (de cima p/ baixo): um BISEL escuro-mas-cromático
    (S=40) que o corte único NÃO pega, um NÚCLEO preto (semente da histerese) e,
    embaixo, uma faixa de SOMBRA DE CONTATO escura-mas-CINZA (S=20). A histerese com
    piso de saturação deve crescer p/ o bisel (topo) e NÃO p/ a sombra (base)."""
    import cv2
    H, W = 480, 400
    hsv = np.zeros((H, W, 3), np.uint8)
    hsv[:, :, 0] = 15                              # matiz único (perto do fundo → não cromático)
    hsv[:, :, 2] = 235                             # fundo branco (V alto, S=0)
    x0, x1 = 150, 250
    bands = {"bevel": (100, 116, 40, 110),         # (r0, r1, S, V) — cromático fraco: cresce
             "core":  (116, 300, 40, 40),          # núcleo escuro: semente (V ≤ 0.30·fundo)
             "shadow": (300, 316, 20, 110)}        # cinza fraco: sombra de contato → barrada
    for r0, r1, s, v in bands.values():
        hsv[r0:r1, x0:x1, 1] = s
        hsv[r0:r1, x0:x1, 2] = v
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), bands


class TestDeshadowHysteresis(unittest.TestCase):
    def setUp(self):
        self.scene, self.b = _shadow_scene()
        self.off = P.segment_tool(self.scene, deshadow=False)
        self.on = P.segment_tool(self.scene, deshadow=True)

    @staticmethod
    def _top_bot(mask):
        ys, _ = np.where(mask > 0)
        return ys.min(), ys.max()

    def test_off_misses_bevel(self):
        # SEM histerese o corte único só pega o núcleo: o bisel cromático fraco fica de fora.
        top, _ = self._top_bot(self.off)
        self.assertGreaterEqual(top, self.b["core"][0] - 4)   # topo ≈ núcleo (não subiu p/ o bisel)

    def test_deshadow_recovers_dark_bevel(self):
        # COM histerese o núcleo cresce pelo bisel cromático → o topo sobe ≥ 1 mm (8 px).
        top_off, _ = self._top_bot(self.off)
        top_on, _ = self._top_bot(self.on)
        self.assertLessEqual(top_on, top_off - 8)

    def test_deshadow_rejects_gray_shadow(self):
        # A SOMBRA DE CONTATO cinza (S baixa) NÃO é absorvida: a base fica no núcleo,
        # não desce p/ a faixa de sombra (auto-limitação pela saturação).
        _, bot_off = self._top_bot(self.off)
        _, bot_on = self._top_bot(self.on)
        self.assertLessEqual(bot_on, bot_off + 4)
        self.assertLess(bot_on, self.b["shadow"][0] + 4)      # não invadiu a sombra

    def test_saturation_floor_is_the_separator(self):
        # Documenta o contrato: derrubar o piso de saturação faria a sombra cinza
        # voltar a inflar a base — é ele que separa bisel (croma) de sombra (cinza).
        self.assertEqual(P.SEG_WEAK_SAT_MIN, 35)
        orig = P.SEG_WEAK_SAT_MIN
        try:
            P.SEG_WEAK_SAT_MIN = 0                             # sem piso → cinza S=20 entra
            no_floor = P.segment_tool(self.scene, deshadow=True)
        finally:
            P.SEG_WEAK_SAT_MIN = orig
        _, bot_no_floor = self._top_bot(no_floor)
        _, bot_on = self._top_bot(self.on)
        self.assertGreater(bot_no_floor, bot_on + 4)          # sem piso a base inflaria


def _rim_scene():
    """Espelho cromático da cena do bisel: a borda do fundo NÃO é preta, é a borda
    LARANJA arredondada. Ao virar p/ a mesa ela DESSATURA e escurece (S cai), caindo
    no VÃO entre `colored` e `dark` — o corte único a perde, igual o bisel preto no
    topo. De cima p/ baixo: um CORPO colorido (S=120, semente cromática), um TOE
    laranja-fraco (S=40: ≥ piso 35 mas < corte de `colored` → só a histerese pega) e,
    embaixo, a SOMBRA DE CONTATO cinza (S=20 < piso). A mesma histerese com piso de
    saturação deve crescer p/ o TOE (recupera a borda real) e parar na SOMBRA."""
    import cv2
    H, W = 480, 400
    hsv = np.zeros((H, W, 3), np.uint8)
    hsv[:, :, 0] = 15
    hsv[:, :, 2] = 235                              # fundo branco (V alto, S=0)
    x0, x1 = 150, 250
    bands = {"body":   (100, 300, 120, 120),       # (r0, r1, S, V) — colorido: semente
             "toe":    (300, 316, 40, 110),        # laranja dessaturado: cresce (recupera)
             "shadow": (316, 340, 20, 110)}        # cinza: sombra de contato → barrada
    for r0, r1, s, v in bands.values():
        hsv[r0:r1, x0:x1, 1] = s
        hsv[r0:r1, x0:x1, 2] = v
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), bands


class TestRimToeHysteresis(unittest.TestCase):
    """Recuperação da BORDA COLORIDA (toe) no fundo — simétrica ao bisel preto do topo.
    A mesma histerese, semeada também pelo núcleo `colored`, cresce pelo toe laranja
    dessaturado e para na sombra cinza (mesmo piso de croma SEG_WEAK_SAT_MIN)."""
    def setUp(self):
        self.scene, self.b = _rim_scene()
        self.off = P.segment_tool(self.scene, deshadow=False)
        self.on = P.segment_tool(self.scene, deshadow=True)

    @staticmethod
    def _top_bot(mask):
        ys, _ = np.where(mask > 0)
        return ys.min(), ys.max()

    def test_off_misses_rim_toe(self):
        # SEM histerese o toe laranja-fraco (não `colored`, não `dark`) fica de fora:
        # a base para no corpo, sem descer p/ o toe.
        _, bot = self._top_bot(self.off)
        self.assertLess(bot, self.b["toe"][0] + 6)            # base ≈ corpo (não desceu p/ o toe)

    def test_deshadow_recovers_colored_rim(self):
        # COM histerese o núcleo colorido cresce pelo toe → a base desce ≥ 1 mm (8 px).
        _, bot_off = self._top_bot(self.off)
        _, bot_on = self._top_bot(self.on)
        self.assertGreaterEqual(bot_on, bot_off + 8)

    def test_deshadow_rejects_gray_shadow_below_rim(self):
        # A SOMBRA cinza (S baixa) abaixo do toe NÃO entra: a base para no fim do toe,
        # não invade a faixa de sombra (auto-limitação pelo piso de saturação).
        _, bot_on = self._top_bot(self.on)
        self.assertLess(bot_on, self.b["shadow"][0] + 4)


# =============================================================================
# B3. SUBTRATOR DE SOMBRA POR TEXTURA (--shadow texture, v0.5): corpo CINZA-NEUTRO
#     sem croma. VALOR pega o corpo (inclusive liso); a TEXTURA (limiar Otsu
#     adaptativo) RECORTA as regiões LISAS-E-mais-CLARAS = sombra PROJETADA, que o
#     corte de valor sozinho englobaria. Discriminador = textura (std local de V),
#     não croma nem valor. Doc: docs/historico.md (v0.5).
# =============================================================================
def _texture_shadow_scene():
    """Fundo branco (V=200). CORPO cinza-neutro ESCURO e TEXTURADO (colunas
    alternadas 60/140 → desvio-padrão local alto) encostado, à direita, numa
    SOMBRA projetada cinza-neutra LISA e mais clara (V=150, sem textura). Os dois
    caem sob o corte de valor (V < 0.80·fundo = 160) — então o valor sozinho UNE
    corpo+sombra. Só a textura separa: o corpo acende, a sombra lisa é recortada."""
    import cv2
    H, W = 480, 440
    hsv = np.zeros((H, W, 3), np.uint8)
    hsv[:, :, 0] = 15
    hsv[:, :, 1] = 0
    hsv[:, :, 2] = 200                                  # fundo branco neutro
    # corpo texturado (colunas de 3 px alternando 60/140; amplitude > sigmaColor do
    # bilateral → a textura sobrevive ao denoise)
    for c in range(120, 220):
        hsv[100:300, c, 2] = 60 if (c // 3) % 2 == 0 else 140
    hsv[100:300, 220:320, 2] = 150                      # sombra projetada LISA, mais clara
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


class TestTextureShadowSubtractor(unittest.TestCase):
    """`--shadow texture`: valor pega o corpo cinza, textura recorta a sombra lisa."""
    BODY = (200, 170)      # (linha, coluna) no meio do corpo texturado
    SHADOW = (200, 270)    # no meio da sombra projetada lisa

    def setUp(self):
        self.scene = _texture_shadow_scene()

    def test_texture_keeps_body(self):
        tex = P.segment_tool(self.scene, deshadow="texture")
        self.assertGreater(int(tex[self.BODY]), 0)        # corpo cinza é segmentado

    def test_texture_subtracts_smooth_light_shadow(self):
        # O corte de VALOR sozinho (sem textura) engloba a sombra lisa mais clara;
        # o modo textura a RECORTA. É o ganho central da v0.5.
        val = P.segment_tool(self.scene, deshadow=False, val_frac=0.80)
        tex = P.segment_tool(self.scene, deshadow="texture")
        self.assertGreater(int(val[self.SHADOW]), 0)      # valor sozinho VAZA a sombra
        self.assertEqual(int(tex[self.SHADOW]), 0)        # textura REJEITA a sombra

    def test_texture_is_opt_in(self):
        # default (deshadow=False) não roda o caminho de textura: a sombra lisa
        # continua vazando — prova que 'texture' é opcional e não regride os modos atuais.
        off = P.segment_tool(self.scene, deshadow=False, val_frac=0.80)
        self.assertGreater(int(off[self.SHADOW]), 0)


class TestWatershedEdgeRefine(unittest.TestCase):
    """v0.8 — refino de borda do modo texture: a UMBRA (sombra de contato, LISA e
    ESCURA — passa pelo recorte liso-E-mais-claro) é re-decidida pelo GRADIENTE
    (watershed): a inundação do papel entra pela rampa suave; a da peça esbarra no
    degrau físico. Numa cena sintética a corrida de inundação é mais frágil que em
    foto real (regiões planas = vencedor leva tudo), então o teste fixa as
    INVARIANTES: a borda avança PARA DENTRO da umbra (ganho mínimo), sem comer o
    corpo, e a guarda sem-marcador é no-op."""
    BODY_EDGE = 220        # última coluna do corpo texturado

    @staticmethod
    def _umbra_scene():
        # Corpo texturado (colunas 60/140) + UMBRA lisa escura (V=120, 5 mm)
        # decaindo em RAMPA suave (120→200 em 40 px) até o papel; ruído gaussiano
        # leve (σ=4, seed fixa) reproduz o grão da foto real — sem ele, a inundação
        # em região perfeitamente plana degenera (quem encosta primeiro leva tudo).
        import cv2
        rng = np.random.default_rng(7)
        H, W = 480, 440
        hsv = np.zeros((H, W, 3), np.uint8)
        hsv[:, :, 0] = 15
        V = np.full((H, W), 200, np.int16)                  # papel neutro
        for c in range(120, 220):                           # corpo texturado
            V[100:300, c] = 60 if (c // 3) % 2 == 0 else 140
        V[100:300, 220:260] = 120                           # umbra: lisa E escura
        for i, c in enumerate(range(260, 300)):             # rampa suave umbra→papel
            V[100:300, c] = 120 + int(80 * (i + 1) / 40)
        hsv[:, :, 2] = np.clip(V + rng.normal(0, 4, (H, W)), 0, 255).astype(np.uint8)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    @staticmethod
    def _right_edge(mask):
        # Borda direita TÍPICA (mediana por linha): a fronteira do watershed é
        # irregular no ruído — uma linha atípica não deve decidir o teste.
        band = mask[150:250] > 0
        per_row = [int(np.where(r)[0].max()) for r in band if r.any()]
        return float(np.median(per_row))

    def test_watershed_tightens_umbra_without_eating_body(self):
        scene = self._umbra_scene()
        val = P.segment_tool(scene, deshadow=False, val_frac=0.80)  # corte de valor puro
        tex = P.segment_tool(scene, deshadow="texture")             # + refino watershed
        self.assertGreater(int(val[200, 240]), 0)       # valor puro ENGOLE a umbra
        self.assertGreater(int(tex[200, 170]), 0)       # corpo continua segmentado
        # ganho: a borda re-decidida entra ≥ 2 mm (16 px) na umbra que o valor mantinha…
        self.assertLessEqual(self._right_edge(tex), self._right_edge(val) - 16)
        # …sem recuar p/ dentro do corpo (não come a peça)
        self.assertGreaterEqual(self._right_edge(tex), self.BODY_EDGE - 1)

    def test_refine_noop_without_fg_marker(self):
        # Corpo LISO e meio-claro inteiro (tudo cai no recorte de umbra provável):
        # sem marcador FG restante, a guarda devolve a máscara intacta.
        import cv2
        img = np.full((200, 200, 3), 200, np.uint8)
        img[60:140, 60:140] = 130
        mask = np.zeros((200, 200), np.uint8)
        mask[60:140, 60:140] = 255
        Vd = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        smooth = np.ones((200, 200), bool)
        out = P._refine_edge_watershed(img, mask, Vd, smooth, 200.0)
        self.assertTrue(bool((out == mask).all()))


class TestFaintMetal(unittest.TestCase):
    """Predicado faint-metal (ligado pelo modo 2 fotos): recupera METAL CLARO liso
    (S fraca ~fundo+10, V ≈ papel) que nenhum predicado normal pega — caso real:
    topos de conectores do Raspberry Pi em luz difusa (V = 1.005×fundo)."""
    METAL = (200, 250)

    @staticmethod
    def _metal_scene():
        import cv2
        H, W = 400, 400
        hsv = np.zeros((H, W, 3), np.uint8)
        hsv[:, :, 0] = 15
        hsv[:, :, 1] = 8                                    # papel: S fraca de JPEG
        hsv[:, :, 2] = 235
        hsv[150:250, 150:220, 1] = 8                        # corpo escuro (predicado dark)
        hsv[150:250, 150:220, 2] = 40
        hsv[150:250, 220:280, 1] = 8 + P.FUSE_FAINT_SAT_MARGIN + 8   # "conector": S fraca
        hsv[150:250, 220:280, 2] = 235                               # V = papel
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def test_default_misses_faint_metal(self):
        # Sem o predicado, o metal claro é invisível (V=papel, S abaixo de colored).
        m = P.segment_tool(self._metal_scene())
        self.assertEqual(int(m[self.METAL]), 0)

    def test_faint_metal_recovers_bright_connector(self):
        m = P.segment_tool(self._metal_scene(), faint_metal=True)
        self.assertGreater(int(m[self.METAL]), 0)


class TestFuseMasks(unittest.TestCase):
    """Fusão direcional 2-fotos (--in2): registro rígido + cada foto soberana no
    seu lado iluminado (a sombra de cada uma cai; a peça comum fica)."""
    PPMM = 4.0
    SHAPE = (320, 320)

    @classmethod
    def _piece(cls):
        # Peça em L (assimétrica sob 90/180/270°) — o registro não pode ter empate.
        m = np.zeros(cls.SHAPE, np.uint8)
        m[120:200, 80:240] = 255                            # corpo 160×80
        m[200:260, 80:130] = 255                            # aba inferior-esquerda
        return m

    @staticmethod
    def _iou(a, b):
        A, B = a > 0, b > 0
        return np.count_nonzero(A & B) / float(np.count_nonzero(A | B))

    def test_identical_masks_pass_through(self):
        m = self._piece()
        fused, reg = P.fuse_masks(m, m.copy(), ppmm=self.PPMM)
        self.assertEqual(reg["angle"] % 360.0, 0.0)
        self.assertEqual((reg["dx"], reg["dy"]), (0.0, 0.0))
        self.assertGreater(self._iou(fused, m), 0.99)

    def test_opposite_shadows_both_removed(self):
        piece = self._piece()
        m1, m2 = piece.copy(), piece.copy()
        m1[130:190, 40:80] = 255                            # sombra da foto 1 → esquerda
        m2[130:190, 240:270] = 255                          # sombra da foto 2 → direita
        fused, reg = P.fuse_masks(m1, m2, ppmm=self.PPMM)
        self.assertGreater(int(fused[160, 160]), 0)         # peça fica
        self.assertEqual(int(fused[160, 60]), 0)            # sombra 1 cai
        self.assertEqual(int(fused[160, 255]), 0)           # sombra 2 cai
        # lóbulo maior = foto de PIOR luz (o caller usa isto p/ escolher o overlay)
        self.assertGreater(reg["lobe1_px"], reg["lobe2_px"])

    def test_registration_recovers_180_rotation_and_shift(self):
        import cv2
        m1 = self._piece()
        mm = cv2.moments(m1, binaryImage=True)
        c = (mm["m10"] / mm["m00"], mm["m01"] / mm["m00"])
        M = cv2.getRotationMatrix2D(c, 180.0, 1.0)
        M[0, 2] += 12; M[1, 2] -= 8                        # peça girada E deslocada (3/2 mm)
        m2 = cv2.warpAffine(m1, M, (m1.shape[1], m1.shape[0]), flags=cv2.INTER_NEAREST)
        fused, reg = P.fuse_masks(m1, m2, ppmm=self.PPMM)
        self.assertLessEqual(abs(reg["angle"] - 180.0), P.FUSE_ANGLE_DEG)
        self.assertGreater(self._iou(fused, m1), 0.97)      # registro desfaz rot+shift


# =============================================================================
# C. PONTA-A-PONTA — contorno direto de thermpro.jpg (foto na base ArUco)
# =============================================================================
@unittest.skipUnless(os.path.exists(THERMPRO_JPG), "thermpro.jpg ausente")
class TestEndToEndThermpro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Etapa 1 SEM GANHO: clearance=0 → o contorno sai no tamanho REAL da peça
        # (a folga é aplicada depois, a jusante no OpenSCAD ou à mão).
        cls.out, cls.sil = P.generate_outline(THERMPRO_JPG, min_radius=1.5,
                                              smooth_mm=8.0, clearance=0.0,
                                              return_silhouette=True)
        # Contorno EMITIDO de fato: Béziers ancoradas nas extremidades, bbox fixada
        # na dimensão real medida pelos marcadores (silhueta crua). A INVARIANTE de
        # contenção (a peça cabe, ≥0.99) é verificada no modo FIEL (faithful=True): é a
        # qualidade do algoritmo quando ancora em todas as extremidades do fecho convexo.
        # O pocket por --min-dist é testado à parte (TestAnchoredFit/test_pocket_*).
        cls.cubics = P.fit_closed_beziers_anchored(cls.sil, smooth_mm=8.0, faithful=True)
        tw, th = P.size(cls.sil)
        cls.cubics = P._scale_cubics_to_bbox(cls.cubics, tw, th)
        cls.flat = P.flatten_beziers(cls.cubics, seg=24)

    def test_all_markers_detected(self):
        # A base inteira é reconhecida na foto real (32/32 → confiança máxima).
        import cv2
        img = P.load_image(THERMPRO_JPG)
        _, _, _, conf = P.rectify(img)
        self.assertAlmostEqual(conf, 1.0, places=6)

    def test_scale_plausible(self):
        # Escala vem dos MARCADORES (mm verdadeiros): o ThermoPro é um disco de
        # ~70 mm → dimensões em faixa física plausível.
        w, h = P.size(self.sil)
        self.assertTrue(55.0 <= w <= 90.0, f"largura {w:.1f} mm fora do plausível")
        self.assertTrue(55.0 <= h <= 90.0, f"altura {h:.1f} mm fora do plausível")

    def test_fit_contains_tool(self):
        # REQUISITO-CHAVE: a peça cabe — a silhueta está contida no contorno EMITIDO
        # (pocket ⊇ ferramenta). Extremidades ancoradas no fecho convexo; ruído sub-mm
        # de borda (sombra denoisada) é coberto pela folga aplicada depois.
        self.assertGreaterEqual(P.coverage(self.flat, self.sil), 0.99)

    def test_clean_line_no_serrilhado(self):
        # REQUISITO-CHAVE: linha limpa p/ impressão — sem serrilhado de alta freq.
        self.assertLess(P.boundary_roughness(self.flat, win_mm=2.0), 0.15)

    def test_print_rule_min_radius(self):
        # Sem cantos afiados: o low-pass arredonda os cantos (raio ≳ 1 mm).
        self.assertGreaterEqual(P.min_corner_radius(self.flat), 1.0)

    def test_single_closed_contour(self):
        self.assertGreater(len(self.out), 8)
        self.assertGreater(P.signed_area(self.out), 0)

    def test_few_nodes(self):
        # MENOS NÓS POSSÍVEIS: o ajuste ancorado economiza nós vs o polyline cru.
        self.assertLess(len(self.cubics), len(self.out) // 2)
        self.assertLessEqual(len(self.cubics), 45)

    def test_svg_bbox_equals_measured_object(self):
        # REQUISITO-CHAVE: a dimensão do SVG (Béziers) = dimensão REAL medida pelos
        # marcadores (silhueta). O "snap" fixa a bbox por eixo no objeto.
        ow, oh = P.size(self.flat)
        tw, th = P.size(self.sil)
        self.assertAlmostEqual(ow, tw, delta=0.05)           # largura = objeto
        self.assertAlmostEqual(oh, th, delta=0.05)           # altura = objeto

    def test_default_pocket_contains(self):
        # DEFAULT na foto real = POCKET de encaixe (âncoras por quadrante a ≥ --min-dist,
        # default 10 mm): o pocket CONTÉM a peça (coverage ~1) e fica ≥ objeto (SEM snap →
        # a peça cabe no case). A quantidade de nós emerge do espaçamento, sem teto.
        cub = P.fit_closed_beziers_anchored(self.sil, smooth_mm=8.0)   # default = pocket
        self.assertGreater(len(cub), 0)
        flat = P.flatten_beziers(cub, seg=40)
        self.assertGreaterEqual(P.coverage(flat, self.sil), 0.99)      # a peça cabe (encaixe)
        pw, ph = P.size(flat)
        tw, th = P.size(self.sil)
        # pocket ≈ tamanho do objeto: com --min-dist folgado (default 10) + smooth 8 a bbox
        # pode ficar levemente sob a crua (Béziers curtas estufam pouco) — a contenção real
        # é o coverage acima; aqui só garantimos que não colapsou nem inflou muito.
        self.assertLess(abs(pw - tw), 2.0)
        self.assertLess(abs(ph - th), 2.0)

    def test_dense_pocket_contour_is_simple(self):
        # REGRESSÃO v0.4 (de-loop): com âncoras DENSAS (--min-dist pequeno) os handles
        # estufados se ultrapassavam → o contorno emitido cruzava a si mesmo (8 cruzamentos
        # medidos). O contorno fechado tem de ser SIMPLES (dentro/fora bem definido p/ o
        # boolean a jusante). Aqui a foto real, antes quebrada, sai sem auto-interseção.
        cub = P.fit_closed_beziers_anchored(self.sil, smooth_mm=2.0, min_dist_mm=0.6)
        self.assertGreater(len(cub), 50)                       # de fato densa
        self.assertEqual(P._self_intersecting_indices(cub), set())
        # E a peça continua contida (de-loop só encurta handles → não expõe a peça).
        self.assertGreaterEqual(P.coverage(P.flatten_beziers(cub, seg=40), self.sil), 0.99)


class TestSilhouetteRef(unittest.TestCase):
    """v0.6 (P1): `return_silhouettes=True` devolve, além da silhueta REGULARIZADA (a que
    gera o SVG), a silhueta de REFERÊNCIA pré `--mask-smooth-mm` — é contra ela que o CLI
    mede o `contém` (senão o gate valida uma silhueta já mutilada pela regularização)."""

    @unittest.skipUnless(os.path.exists(THERMPRO_JPG), "thermpro.jpg ausente")
    def test_returns_raw_reference_silhouette(self):
        out, sil, ref = P.generate_outline(THERMPRO_JPG, mask_smooth_mm=2.0,
                                           return_silhouettes=True)
        self.assertGreater(len(out), 8)
        self.assertGreater(len(ref), 8)
        # A referência é a silhueta CRUA: mais serrilhada (perímetro ≥ o da regularizada)
        # e com ~a mesma área (a regularização alisa, não rói).
        self.assertGreaterEqual(P._perimeter(ref), P._perimeter(sil) - 1e-6)
        self.assertLess(abs(abs(P.signed_area(ref)) - abs(P.signed_area(sil)))
                        / abs(P.signed_area(sil)), 0.05)


class TestSelfIntersectionGuard(unittest.TestCase):
    """v0.4 Etapa 0 — contorno SIMPLES (sem auto-sobreposição). Um caminho fechado que se
    cruza tem dentro/fora ambíguo → pocket inválido p/ o boolean a jusante."""
    LOOP = ((0.0, 0.0), (6.0, 2.0), (-4.0, 2.0), (2.0, 0.0))   # handles cruzados → laço
    ARC = ((0.0, 0.0), (1.0, 2.0), (3.0, 2.0), (4.0, 0.0))     # arco simples

    def test_cubic_is_simple_detects_loop(self):
        self.assertFalse(P._cubic_is_simple(self.LOOP))
        self.assertTrue(P._cubic_is_simple(self.ARC))

    def test_cap_handles_removes_loop(self):
        # Limitar o handle a 0.40·corda já desfaz o laço do ajuste base.
        self.assertTrue(P._cubic_is_simple(P._cap_handles(self.LOOP)))

    def test_shrink_keeps_endpoints_and_tangent_direction(self):
        # Encurtar handles preserva pontas (p0,p3) e a DIREÇÃO da tangente (mantém G1).
        b = P._shrink_handles(self.ARC, 0.5)
        self.assertEqual((b[0], b[3]), (self.ARC[0], self.ARC[3]))
        v0 = (self.ARC[1][0] - self.ARC[0][0], self.ARC[1][1] - self.ARC[0][1])
        v1 = (b[1][0] - b[0][0], b[1][1] - b[0][1])
        self.assertAlmostEqual(v0[0] * v1[1] - v0[1] * v1[0], 0.0, places=9)  # colineares
        self.assertLess(math.hypot(*v1), math.hypot(*v0))                     # mais curto

    def test_repair_removes_crossings(self):
        # Contorno fechado CONECTADO (pontas encadeadas) com um trecho laçado fica SIMPLES
        # após o reparo global — os demais lados são retas e não se cruzam.
        def lin(p0, p3):
            return (p0, (p0[0] + (p3[0] - p0[0]) / 3, p0[1] + (p3[1] - p0[1]) / 3),
                    (p0[0] + 2 * (p3[0] - p0[0]) / 3, p0[1] + 2 * (p3[1] - p0[1]) / 3), p3)
        cubics = [self.LOOP, lin((2, 0), (2, -4)), lin((2, -4), (0, -4)), lin((0, -4), (0, 0))]
        self.assertIn(0, P._self_intersecting_indices(cubics))   # laço presente antes
        fixed = P._repair_self_intersections(cubics)
        self.assertEqual(P._self_intersecting_indices(fixed), set())


class TestValFrac(unittest.TestCase):
    """v0.4 Etapa 1 — --val-frac captura CORPO CINZA-NEUTRO de baixo contraste."""
    @staticmethod
    def _gray_body_scene():
        # Fundo branco; corpo cinza neutro grande (V≈0.67·fundo, sem croma) e um NÚCLEO
        # escuro pequeno (V baixo) no meio — réplica do caso da trena (carcaça cinza + botão).
        import cv2
        H, W = 480, 400
        hsv = np.zeros((H, W, 3), np.uint8)
        hsv[:, :, 0] = 15
        hsv[:, :, 2] = 240                                  # fundo branco
        hsv[140:340, 120:280, 1] = 12                       # corpo: cinza dessaturado
        hsv[140:340, 120:280, 2] = 160                      #        V ≈ 0.67·fundo
        hsv[220:260, 180:220, 1] = 12                       # núcleo escuro (botão)
        hsv[220:260, 180:220, 2] = 40
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def test_default_misses_gray_body_high_captures_it(self):
        scene = self._gray_body_scene()
        lo = int((P.segment_tool(scene, val_frac=0.30) > 0).sum())   # só o núcleo
        hi = int((P.segment_tool(scene, val_frac=0.75) > 0).sum())   # corpo inteiro
        self.assertGreater(hi, 5 * lo)

    def test_default_param_is_seg_val_frac(self):
        # Default inalterado → zero regressão nas peças cromáticas (thermpro).
        scene = self._gray_body_scene()
        a = P.segment_tool(scene)
        b = P.segment_tool(scene, val_frac=P.SEG_VAL_FRAC)
        self.assertTrue(bool((a == b).all()))


class TestOutputFitSourceOfTruth(unittest.TestCase):
    """Fonte ÚNICA do ajuste emitido (`_fit_for_output`): .svg final, overlay Inkscape e
    métricas do CLI usam os MESMOS Béziers — inclusive a simetria (--symmetry).
    Regressão: o overlay omitia `symmetry` e mostrava uma curva diferente do .svg."""

    @staticmethod
    def _synthetic_rect_scene():
        # "Foto retificada" sintética: retângulo escuro sobre miolo branco (50×50 mm a 8 px/mm).
        import cv2
        img = np.full((400, 400, 3), 255, np.uint8)
        cv2.rectangle(img, (120, 80), (280, 320), (30, 30, 30), -1)
        return img

    def test_fit_for_output_snaps_bbox_only_when_faithful(self):
        # Modo FIEL: bbox das cúbicas = bbox do objeto (snap). Modo POCKET: sem snap,
        # o contorno fica ≥ objeto (menos a tolerância de penetração).
        shape = rounded_rect(50, 34, 8)
        tw, th = P.size(shape)
        fiel = P._fit_for_output(shape, smooth_mm=1.0, min_dist_mm=6.0, faithful=True)
        fw, fh = P.size(P.flatten_beziers(fiel))
        self.assertAlmostEqual(fw, tw, places=6)
        self.assertAlmostEqual(fh, th, places=6)
        pocket = P._fit_for_output(shape, smooth_mm=1.0, min_dist_mm=6.0)
        pw, ph = P.size(P.flatten_beziers(pocket))
        self.assertGreaterEqual(pw, tw - P.POCKET_EPS_MM - 0.15)
        self.assertGreaterEqual(ph, th - P.POCKET_EPS_MM - 0.15)

    def test_overlay_svg_fit_receives_symmetry(self):
        # generate_outline(..., symmetry=..., overlay_svg_path=...) tem de ajustar o overlay
        # com a MESMA symmetry que o .svg final usa (mesma chave de cache → mesma curva).
        import tempfile
        from unittest import mock
        rect = self._synthetic_rect_scene()
        seen = []
        real = P.fit_anchored_cached

        def spy(sil, **kw):
            seen.append(kw.get("symmetry", "none"))
            return real(sil, **kw)

        with tempfile.TemporaryDirectory() as td:
            ov = os.path.join(td, "_overlay_x.svg")
            with mock.patch.object(P, "load_image", return_value=rect), \
                 mock.patch.object(P, "rectify", return_value=(rect, 0.125, 0.125, 1.0)), \
                 mock.patch.object(P, "fit_anchored_cached", side_effect=spy):
                P.generate_outline("dummy.jpg", symmetry="vertical", overlay_svg_path=ov)
            self.assertTrue(os.path.exists(ov))
        self.assertEqual(seen, ["vertical"])


class TestSvgNameEscaping(unittest.TestCase):
    """`name` (derivado do arquivo de entrada ou de --name) entra no SVG ESCAPADO: um nome
    hostil não pode injetar markup (um SVG aberto no navegador executa <script>) nem
    quebrar o XML ('--' é proibido dentro de comentário)."""
    EVIL = 'peca--><script>alert(1)</script><g a="'

    def test_final_svg_stays_well_formed(self):
        import xml.etree.ElementTree as ET
        svg = P.polygon_to_svg(rectangle(10, 6), name=self.EVIL, curves=False)
        self.assertNotIn("<script>", svg)
        ET.fromstring(svg)                       # parse OK = XML bem-formado

    def test_overlay_svg_label_stays_well_formed(self):
        import tempfile
        import xml.etree.ElementTree as ET
        rect = np.full((16, 16, 3), 255, np.uint8)
        cub = [((0.0, 0.0), (0.5, -0.2), (1.0, -0.2), (1.5, 0.0)),
               ((1.5, 0.0), (1.0, -0.8), (0.5, -0.8), (0.0, 0.0))]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ov.svg")
            P.write_overlay_svg(rect, cub, 0.125, 0.125, path, name=self.EVIL)
            with open(path, encoding="utf-8") as fh:
                svg = fh.read()
        self.assertNotIn("<script>", svg)
        ET.fromstring(svg)


def _line_cubic(p0, p3):
    """Cúbica RETA (controles colineares a 1/3 e 2/3) — p/ montar anéis de teste."""
    return (p0, (p0[0] + (p3[0] - p0[0]) / 3, p0[1] + (p3[1] - p0[1]) / 3),
            (p0[0] + 2 * (p3[0] - p0[0]) / 3, p0[1] + 2 * (p3[1] - p0[1]) / 3), p3)


def _ring_from_polygon(pts):
    """Anel fechado de cúbicas retas ligando os vértices consecutivos de `pts`."""
    n = len(pts)
    return [_line_cubic(pts[i], pts[(i + 1) % n]) for i in range(n)]


class TestSymmetrizeBeziers(unittest.TestCase):
    """Espelhamento de Béziers no eixo de simetria. Com >2 cruzamentos do eixo o lado
    mantido tem 2+ arcos e cada arco+espelho fecharia um LAÇO separado (multi-contorno:
    furo/componentes) — não existe caminho único fiel. O correto é RECUSAR (devolver o
    contorno original intacto, com aviso), não descartar arcos silenciosamente."""

    def test_two_crossings_still_mirrored_and_closed(self):
        # Regressão do caminho feliz: quadrado (2 cruzamentos) → resultado fechado,
        # simétrico e com a área preservada.
        ring = _ring_from_polygon([(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])
        out = P.symmetrize_beziers(ring, "vertical", 0.0)
        self.assertGreater(len(out), 0)
        m = len(out)
        for k in range(m):                       # encadeado e fechado (p3 == próximo p0)
            a, b = out[k], out[(k + 1) % m]
            self.assertAlmostEqual(a[3][0], b[0][0], places=6)
            self.assertAlmostEqual(a[3][1], b[0][1], places=6)
        flat = P.flatten_beziers(out, seg=8)
        mirror = [(-x, y) for (x, y) in flat]
        self.assertGreaterEqual(P.coverage(flat, mirror, ppm=16.0), 0.99)   # simétrico
        self.assertAlmostEqual(P.polygon_area(flat), 100.0, delta=2.0)      # área mantida

    def test_four_crossings_falls_back_to_original(self):
        # Retângulo com FENDA pela esquerda atravessando o eixo (x=0 cruzado 4 vezes:
        # y=±10 e y=±2): o lado direito tem 2 arcos (externo + fenda). Antes, só o 1º
        # arco sobrevivia e o resto era DESCARTADO (contorno mutilado); agora devolve o
        # contorno ORIGINAL intacto (fallback com aviso).
        slot = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0),
                (-10.0, 2.0), (4.0, 2.0), (4.0, -2.0), (-10.0, -2.0)]
        ring = _ring_from_polygon(slot)
        out = P.symmetrize_beziers(ring, "vertical", 0.0)
        self.assertEqual(out, ring)              # intacto — nada descartado


class TestEditFlowGuards(unittest.TestCase):
    """--edit com detecção/edição degenerada: aborta com erro amigável em vez de
    crashar em `_svg_from_cubics([])` (min() de lista vazia) na hora de gravar."""

    @staticmethod
    def _cli_args():
        import argparse
        return argparse.Namespace(
            in_path="dummy.jpg", dict_name=P.DICT_NAME, min_radius=P.MIN_RADIUS_MM,
            smooth_mm=P.SMOOTH_MM, clearance=P.CLEARANCE_MM, symmetry="none",
            shadow="off", simplify=P.ANCHOR_SIMPLIFY_MM, faithful=False,
            min_dist=P.ANCHOR_MIN_DIST_MM, pocket_eps=P.POCKET_EPS_MM,
            mask_smooth_mm=P.MASK_SMOOTH_MM, mask_smooth_keep_bumps=False,
            val_frac=P.SEG_VAL_FRAC, debug_dir=None)

    def _run(self, fit_result, editor_result):
        """Roda `_edit_flow` com o pipeline e o editor MOCKADOS (sem foto nem GUI):
        `fit_result` = cúbicas detectadas (cub0); `editor_result` = retorno do editor.
        Devolve (código de saída, out_path foi escrito?, editor foi aberto?)."""
        import io
        import tempfile
        from contextlib import redirect_stderr
        from unittest import mock
        import outline_editor as OE
        rect = np.full((16, 16, 3), 255, np.uint8)
        sil = [(0.0, 0.0), (2.0, 0.0), (2.0, -2.0), (0.0, -2.0)]
        gen = (sil, sil, rect, 0.125, 0.125)
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "x.svg")
            with mock.patch.object(P, "generate_outline", return_value=gen), \
                 mock.patch.object(P, "_fit_for_output", return_value=fit_result), \
                 mock.patch.object(OE, "run_editor", return_value=editor_result) as run_ed, \
                 redirect_stderr(io.StringIO()):
                code = P._edit_flow(self._cli_args(), out, "x",
                                    os.path.join(td, "_overlay_x.png"), None)
            return code, os.path.exists(out), run_ed.called

    def test_empty_detection_aborts_before_editor(self):
        # cub0 vazio (silhueta degenerada): erro ANTES de abrir o editor — um editor
        # sem nós é beco sem saída (não dá nem p/ inserir: nearest_segment exige ≥ 2).
        code, wrote, editor_opened = self._run([], None)
        self.assertNotEqual(code, 0)
        self.assertFalse(wrote)
        self.assertFalse(editor_opened)

    def test_editor_returning_empty_writes_nothing(self):
        # Editor devolvendo lista vazia (≠ None de cancelar): nada é gravado e o código
        # de saída acusa o erro — antes crashava em min() de bbox vazia.
        tri = [((0.0, 0.0), (0.5, 0.5), (1.5, 0.5), (2.0, 0.0)),
               ((2.0, 0.0), (1.5, -1.5), (1.0, -2.0), (0.0, -2.0)),
               ((0.0, -2.0), (0.0, -1.0), (0.0, -0.5), (0.0, 0.0))]
        code, wrote, _ = self._run(tri, [])
        self.assertNotEqual(code, 0)
        self.assertFalse(wrote)


class TestCubicRoots(unittest.TestCase):
    def test_double_root_found_despite_float_rounding(self):
        # (t−1/3)²·(t−0.8): o det do cúbico deprimido é 0 MATEMATICAMENTE, mas o float
        # arredonda p/ ±2e-19. A comparação exata `det == 0` caía no ramo de raiz única
        # quando o erro dava positivo e PERDIA a raiz dupla (medido: só 0.8 voltava) —
        # em symmetrize_beziers isso pulava um cruzamento tangente do eixo. Com
        # tolerância relativa, as duas raízes distintas saem sempre.
        r_dbl, r_simple = 1.0 / 3.0, 0.8
        B = -(2 * r_dbl + r_simple)
        C = r_dbl * r_dbl + 2 * r_dbl * r_simple
        D = -r_dbl * r_dbl * r_simple
        roots = P.cubic_roots(1.0, B, C, D)
        self.assertTrue(any(abs(t - r_dbl) < 1e-6 for t in roots), f"raiz dupla ausente: {roots}")
        self.assertTrue(any(abs(t - r_simple) < 1e-6 for t in roots), f"raiz simples ausente: {roots}")

    def test_three_distinct_roots_unchanged(self):
        # Regressão do ramo trigonométrico: 3 raízes reais distintas em [0,1].
        rr = (0.2, 0.5, 0.9)
        B = -(rr[0] + rr[1] + rr[2])
        C = rr[0] * rr[1] + rr[0] * rr[2] + rr[1] * rr[2]
        D = -rr[0] * rr[1] * rr[2]
        roots = sorted(P.cubic_roots(1.0, B, C, D))
        self.assertEqual(len(roots), 3)
        for got, want in zip(roots, rr):
            self.assertAlmostEqual(got, want, places=9)


class TestCliDictValidation(unittest.TestCase):
    def test_unknown_dict_rejected_at_parse(self):
        # --dict inválido é rejeitado pelo argparse (choices da tabela DICT_CAPACITY) com
        # mensagem amigável — antes o getattr(cv2.aruco, ...) estourava AttributeError cru.
        import io
        from contextlib import redirect_stderr
        with self.assertRaises(SystemExit) as cm, redirect_stderr(io.StringIO()):
            P.main(["--in", THERMPRO_JPG, "--dict", "DICT_INEXISTENTE"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
