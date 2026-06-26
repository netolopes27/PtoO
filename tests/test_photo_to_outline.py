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
            return P.estimate_tilt_deg(ip, mp, gray.shape)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
