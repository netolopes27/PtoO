#!/usr/bin/env python3
# =============================================================================
# calibration_target.py — layout do alvo de calibração
# -----------------------------------------------------------------------------
# Define a GEOMETRIA do alvo "moldura ArUco + centro branco": uma faixa de
# marcadores ArUco ao redor da borda de uma folha A4, com miolo branco liso
# onde o objeto é apoiado e fotografado.
#
# Este módulo é PURO (sem OpenCV): só descreve onde cada marcador fica, em mm.
# É a ÚNICA fonte da verdade do layout — tanto o renderizador SVG
# (make_calibration_target.py) quanto o detector (photo_to_outline.py)
# importam daqui, garantindo que "o que é impresso == o que o detector assume".
#
# Convenção de coordenadas: mm, origem no canto superior-esquerdo da folha,
# eixo Y para BAIXO (igual SVG e imagem). Cantos de marcador na ordem do
# OpenCV ArUco: top-left, top-right, bottom-right, bottom-left (horário).
# =============================================================================

from dataclasses import dataclass

# A4 em mm (paisagem é o padrão — foi o que o usuário já imprimiu).
A4_LANDSCAPE = (297.0, 210.0)
A4_PORTRAIT = (210.0, 297.0)

# Capacidade de cada dicionário ArUco predefinido (nº de IDs distintos).
# Mantido aqui para validar a contagem SEM importar o OpenCV.
DICT_CAPACITY = {
    "DICT_4X4_50": 50,
    "DICT_4X4_100": 100,
    "DICT_4X4_250": 250,
    "DICT_5X5_50": 50,
    "DICT_5X5_100": 100,
    "DICT_6X6_50": 50,
    "DICT_6X6_100": 100,
}

# Lado do marcador em módulos (dados + 1 módulo de borda em cada lado).
DICT_MODULES = {
    "DICT_4X4_50": 6, "DICT_4X4_100": 6, "DICT_4X4_250": 6,
    "DICT_5X5_50": 7, "DICT_5X5_100": 7,
    "DICT_6X6_50": 8, "DICT_6X6_100": 8,
}


@dataclass(frozen=True)
class Marker:
    id: int
    x: float   # canto superior-esquerdo, mm
    y: float
    size: float  # lado, mm

    def corners_mm(self):
        """4 cantos em mm na ordem ArUco (tl, tr, br, bl), Y para baixo."""
        s = self.size
        return [(self.x, self.y), (self.x + s, self.y),
                (self.x + s, self.y + s), (self.x, self.y + s)]


def _edge_positions(start, end, size, min_gap):
    """Posições do canto-de-início (top-left) de marcadores de lado `size`
    distribuídos uniformemente no intervalo [start, end] de uma borda. Os
    marcadores ficam dentro de [start, end] (o último começa em end-size)."""
    span = (end - size) - start
    if span <= 1e-9:
        return [start]
    n = int(span // (size + min_gap)) + 1
    n = max(2, n)
    step = span / (n - 1)
    return [start + i * step for i in range(n)]


def target_layout(page=A4_LANDSCAPE, page_margin=10.0, marker_mm=16.0,
                  inner_pad=6.0, min_gap=None, dict_name="DICT_4X4_50"):
    """Calcula o layout do alvo.

    page         (W,H) da folha em mm.
    page_margin  margem branca da folha (impressoras não imprimem até a borda).
    marker_mm    lado de cada marcador ArUco.
    inner_pad    folga entre a moldura de marcadores e o miolo branco do objeto.
    min_gap      vão mínimo entre marcadores numa borda (default 0.6*marker_mm).
    dict_name    dicionário ArUco predefinido.

    Retorna dict com: page, page_margin, marker_mm, dict, capacity,
    inner_rect (x0,y0,x1,y1) = retângulo branco do objeto, e markers = lista de
    Marker com IDs únicos sequenciais. Marcadores formam uma moldura de UMA
    espessura; o miolo (inner_rect) fica livre de marcadores.
    """
    W, H = page
    if min_gap is None:
        min_gap = 0.6 * marker_mm
    s = marker_mm

    px0, py0 = page_margin, page_margin
    px1, py1 = W - page_margin, H - page_margin

    xs = _edge_positions(px0, px1, s, min_gap)        # colunas (top-left x)
    ys = _edge_positions(py0, py1, s, min_gap)        # linhas (top-left y)
    ys_interior = ys[1:-1]                            # exclui cantos (já cobertos)

    markers = []
    nid = 0

    def add(x, y):
        nonlocal nid
        markers.append(Marker(nid, x, y, s))
        nid += 1

    # Ordem determinística: topo (E→D), direita (cima→baixo interior),
    # base (E→D), esquerda (cima→baixo interior).
    for x in xs:                 # borda superior
        add(x, py0)
    for y in ys_interior:        # borda direita
        add(px1 - s, y)
    for x in xs:                 # borda inferior
        add(x, py1 - s)
    for y in ys_interior:        # borda esquerda
        add(px0, y)

    inner = (px0 + s + inner_pad, py0 + s + inner_pad,
             px1 - s - inner_pad, py1 - s - inner_pad)

    return {
        "page": (W, H),
        "page_margin": page_margin,
        "marker_mm": s,
        "dict": dict_name,
        "capacity": DICT_CAPACITY.get(dict_name, 50),
        "modules": DICT_MODULES.get(dict_name, 6),
        "inner_rect": inner,
        "markers": markers,
    }


def homography_correspondences(layout):
    """Lista [(id, [4 cantos mm na ordem ArUco]), ...] para casar com os cantos
    detectados na imagem e resolver a homografia imagem→mm. É o contrato que o
    detector (photo_to_outline.py) consome."""
    return [(m.id, m.corners_mm()) for m in layout["markers"]]


def default_layout():
    return target_layout()
