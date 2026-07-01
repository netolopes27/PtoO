#!/usr/bin/env python3
# =============================================================================
# test_calibration_target.py — suíte TDD do alvo de calibração
# -----------------------------------------------------------------------------
# Alvo "moldura ArUco + centro branco". Dois níveis:
#   A. Layout puro — geometria em mm (calibration_target.py), sem OpenCV.
#   B. Detecção sintética — renderiza os marcadores num "foto" numpy, roda o
#      detector ArUco do OpenCV e recupera a homografia imagem→mm. Prova que o
#      alvo é detectável e métrico ANTES de imprimir, inclusive sob perspectiva.
#
# Rodar: .venv/Scripts/python tests/run_image_tests.py
# =============================================================================

import os
import sys
import unittest

THIS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(THIS)
sys.path.insert(0, TOOLS)

import calibration_target as CT  # noqa: E402

try:
    import numpy as np
    import cv2
    _HAS_CV = True
except ImportError:  # pragma: no cover
    _HAS_CV = False


# =============================================================================
# A. LAYOUT PURO
# =============================================================================
class TestTargetLayout(unittest.TestCase):
    def setUp(self):
        self.L = CT.target_layout()

    def test_deterministic(self):
        a = CT.target_layout()
        b = CT.target_layout()
        self.assertEqual([m.corners_mm() for m in a["markers"]],
                         [m.corners_mm() for m in b["markers"]])

    def test_ids_unique_and_sequential(self):
        ids = [m.id for m in self.L["markers"]]
        self.assertEqual(ids, list(range(len(ids))))
        self.assertEqual(len(set(ids)), len(ids))

    def test_count_within_dictionary_and_enough_for_homography(self):
        n = len(self.L["markers"])
        self.assertLessEqual(n, self.L["capacity"])
        self.assertGreaterEqual(n, 8)  # robustez de homografia

    def test_markers_inside_printable_area(self):
        # Tudo dentro da margem branca (impressão sem sangria).
        W, H = self.L["page"]
        m = self.L["page_margin"]
        s = self.L["marker_mm"]
        for mk in self.L["markers"]:
            self.assertGreaterEqual(mk.x, m - 1e-6)
            self.assertGreaterEqual(mk.y, m - 1e-6)
            self.assertLessEqual(mk.x + s, W - m + 1e-6)
            self.assertLessEqual(mk.y + s, H - m + 1e-6)

    def test_markers_do_not_invade_inner_white(self):
        # Moldura só: nenhum marcador cruza o miolo branco do objeto.
        x0, y0, x1, y1 = self.L["inner_rect"]
        s = self.L["marker_mm"]
        for mk in self.L["markers"]:
            overlaps = (mk.x < x1 and mk.x + s > x0 and
                        mk.y < y1 and mk.y + s > y0)
            self.assertFalse(overlaps, f"marcador {mk.id} invade o miolo")

    def test_inner_rect_fits_thermpro(self):
        # Campo do thermpro ~117x107mm; o miolo precisa acomodar com folga.
        x0, y0, x1, y1 = self.L["inner_rect"]
        self.assertGreaterEqual(x1 - x0, 130.0)
        self.assertGreaterEqual(y1 - y0, 120.0)

    def test_corner_order_is_aruco(self):
        m = CT.Marker(0, 10.0, 20.0, 6.0)
        self.assertEqual(m.corners_mm(),
                         [(10, 20), (16, 20), (16, 26), (10, 26)])

    def test_edge_positions_single_when_two_would_violate_gap(self):
        # Span curto (não cabem 2 marcadores com o vão mínimo): devolve UM, centrado,
        # em vez de dois quase-sobrepostos (indetectáveis e fora do contrato min_gap).
        pos = CT._edge_positions(0.0, 20.0, 16.0, 9.6)   # span útil = 4 mm < 16+9.6
        self.assertEqual(len(pos), 1)
        self.assertAlmostEqual(pos[0], 2.0)              # centrado em [0, 20-16]

    def test_tight_page_yields_single_marker_rows_without_overlap(self):
        # Página apertada (1 marcador por borda): layout ainda válido, nenhum par de
        # marcadores se sobrepõe.
        L = CT.target_layout(page=(95.0, 95.0), marker_mm=30.0)
        s = L["marker_mm"]
        ms = L["markers"]
        self.assertGreaterEqual(len(ms), 2)
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                a, b = ms[i], ms[j]
                self.assertFalse(a.x < b.x + s and a.x + s > b.x and
                                 a.y < b.y + s and a.y + s > b.y,
                                 f"marcadores {a.id} e {b.id} sobrepostos")

    def test_degenerate_inner_rect_raises(self):
        # Página pequena demais p/ o marcador: as bordas de marcadores colidiriam e o
        # miolo branco degenera — erro claro em vez de um alvo impresso inválido.
        with self.assertRaises(ValueError):
            CT.target_layout(page=(60.0, 60.0), marker_mm=30.0)

    def test_unknown_dict_raises_value_error(self):
        # Dicionário fora da tabela DICT_CAPACITY/DICT_MODULES: erro CLARO na hora, em vez
        # do fallback silencioso (capacity=50 inventada) + AttributeError cru lá na frente.
        with self.assertRaises(ValueError):
            CT.target_layout(dict_name="DICT_BOGUS")


# =============================================================================
# B. DETECÇÃO SINTÉTICA (precisa OpenCV)
# =============================================================================
@unittest.skipUnless(_HAS_CV, "OpenCV ausente")
class TestTargetDetection(unittest.TestCase):
    SCALE = 6.0  # px por mm na "foto" sintética

    @staticmethod
    def _render(layout, scale):
        """Renderiza o alvo numa imagem numpy (fundo branco) no dado px/mm."""
        W, H = layout["page"]
        img = np.full((int(round(H * scale)), int(round(W * scale))), 255, np.uint8)
        dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, layout["dict"]))
        mods = layout["modules"]
        for mk in layout["markers"]:
            k = max(1, int(round(mk.size * scale / mods)))
            side = mods * k
            bm = cv2.aruco.generateImageMarker(dic, mk.id, side)
            x0 = int(round(mk.x * scale))
            y0 = int(round(mk.y * scale))
            img[y0:y0 + side, x0:x0 + side] = bm
        return img

    @staticmethod
    def _detect(img, dict_name):
        dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
        det = cv2.aruco.ArucoDetector(dic, cv2.aruco.DetectorParameters())
        corners, ids, _ = det.detectMarkers(img)
        return corners, ids

    def _correspondences(self, layout, corners, ids):
        """Casa cantos detectados (px) com cantos do layout (mm)."""
        lut = {m.id: m.corners_mm() for m in layout["markers"]}
        src, dst = [], []
        for c, i in zip(corners, ids.flatten()):
            for (px, mm) in zip(c.reshape(-1, 2), lut[int(i)]):
                src.append(px)
                dst.append(mm)
        return np.array(src, np.float64), np.array(dst, np.float64)

    def test_all_markers_detected_flat(self):
        L = CT.target_layout()
        img = self._render(L, self.SCALE)
        corners, ids = self._detect(img, L["dict"])
        self.assertIsNotNone(ids)
        found = set(int(i) for i in ids.flatten())
        self.assertEqual(found, set(m.id for m in L["markers"]))

    def test_homography_recovers_mm_flat(self):
        L = CT.target_layout()
        img = self._render(L, self.SCALE)
        corners, ids = self._detect(img, L["dict"])
        src, dst = self._correspondences(L, corners, ids)
        Hmat, _ = cv2.findHomography(src, dst, cv2.RANSAC, 2.0)
        # Projeta cantos px→mm e confere o lado de CADA marcador ≈ marker_mm.
        s = L["marker_mm"]
        for c in corners:
            pts = c.reshape(-1, 1, 2).astype(np.float64)
            mm = cv2.perspectiveTransform(pts, Hmat).reshape(-1, 2)
            for a, b in [(0, 1), (1, 2), (2, 3), (3, 0)]:
                side = float(np.hypot(*(mm[a] - mm[b])))
                self.assertAlmostEqual(side, s, delta=0.4)

    def test_homography_removes_perspective(self):
        # Aplica perspectiva conhecida; o detector + homografia devem devolver
        # marcadores de lado uniforme = marker_mm em TODO o campo (análogo ao
        # teste dos 4 quadrantes, agora no alvo real).
        L = CT.target_layout()
        flat = self._render(L, self.SCALE)
        h, w = flat.shape
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        d = 0.12
        dstq = np.float32([[w * 0.05, h * 0.02], [w * 0.98, h * 0.10],
                           [w * (1 - d * 0.3), h * 0.97], [w * 0.02, h * 0.90]])
        Wp = cv2.getPerspectiveTransform(src, dstq)
        warped = cv2.warpPerspective(flat, Wp, (w, h), borderValue=255)
        corners, ids = self._detect(warped, L["dict"])
        self.assertIsNotNone(ids)
        # Maioria esmagadora dos marcadores deve sobreviver à perspectiva.
        self.assertGreaterEqual(len(ids), int(0.8 * len(L["markers"])))
        s = L["marker_mm"]
        src2, dst2 = self._correspondences(L, corners, ids)
        Hmat, _ = cv2.findHomography(src2, dst2, cv2.RANSAC, 2.0)
        sides = []
        for c in corners:
            pts = c.reshape(-1, 1, 2).astype(np.float64)
            mm = cv2.perspectiveTransform(pts, Hmat).reshape(-1, 2)
            for a, b in [(0, 1), (1, 2), (2, 3), (3, 0)]:
                sides.append(float(np.hypot(*(mm[a] - mm[b]))))
        sides = np.array(sides)
        self.assertAlmostEqual(float(sides.mean()), s, delta=0.3)
        self.assertLess(float(sides.std()), 0.5)  # uniforme em todo o campo


@unittest.skipUnless(_HAS_CV, "OpenCV ausente")
class TestMakeTargetCli(unittest.TestCase):
    def test_unknown_dict_rejected_at_parse(self):
        # --dict inválido é rejeitado pelo argparse (choices) antes de renderizar qualquer coisa.
        import io
        from contextlib import redirect_stderr
        import make_calibration_target as MCT
        with self.assertRaises(SystemExit) as cm, redirect_stderr(io.StringIO()):
            MCT.main(["--dict", "DICT_BOGUS", "--out", os.devnull])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
