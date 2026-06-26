#!/usr/bin/env python3
# =============================================================================
# make_calibration_target.py — gera o alvo de calibração SVG
# -----------------------------------------------------------------------------
# Renderiza o alvo "moldura ArUco + centro branco" como SVG vetorial
# pronto para imprimir em A4. A GEOMETRIA vem de calibration_target.py (fonte
# única da verdade, compartilhada com o detector). Aqui só desenhamos:
#   - fundo branco da folha (com margem branca para impressão sem sangria);
#   - cada marcador ArUco como retângulos pretos vetoriais (nítidos no papel);
#   - marcas de canto (cinza-claro) indicando o miolo branco do objeto;
#   - instrução de impressão a 100%.
#
# Uso:
#   .venv/Scripts/python make_calibration_target.py --out base.svg
# =============================================================================

import argparse
import sys

import cv2

import calibration_target as CT


def _marker_modules(dict_name, marker_id):
    """Matriz mods×mods (0=preto, 255=branco) do marcador, 1 px por módulo."""
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    mods = CT.DICT_MODULES.get(dict_name, 6)
    return cv2.aruco.generateImageMarker(dic, marker_id, mods)


def _fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _marker_rects(mk, dict_name):
    """Retângulos pretos (run-length por linha) de um marcador, em mm."""
    grid = _marker_modules(dict_name, mk.id)
    mods = grid.shape[0]
    cell = mk.size / mods
    out = []
    for r in range(mods):
        c = 0
        while c < mods:
            if grid[r, c] < 128:                      # módulo preto
                c0 = c
                while c < mods and grid[r, c] < 128:
                    c += 1
                x = mk.x + c0 * cell
                y = mk.y + r * cell
                w = (c - c0) * cell
                out.append((x, y, w, cell))
            else:
                c += 1
    return out


def render_svg(layout):
    W, H = layout["page"]
    x0, y0, x1, y1 = layout["inner_rect"]
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(W)}mm" height="{_fmt(H)}mm" '
        f'viewBox="0 0 {_fmt(W)} {_fmt(H)}" version="1.1">')
    parts.append(
        f'  <!-- Alvo de calibracao PtoO (moldura ArUco + centro branco). '
        f'Dict {layout["dict"]}, lado {_fmt(layout["marker_mm"])}mm, '
        f'margem {_fmt(layout["page_margin"])}mm, {len(layout["markers"])} marcadores. -->')
    # Fundo branco da folha.
    parts.append(f'  <rect x="0" y="0" width="{_fmt(W)}" height="{_fmt(H)}" fill="#ffffff"/>')

    # Marcadores ArUco (preto vetorial).
    parts.append('  <g fill="#000000" stroke="none" shape-rendering="crispEdges">')
    for mk in layout["markers"]:
        for (x, y, w, h) in _marker_rects(mk, layout["dict"]):
            parts.append(
                f'    <rect x="{_fmt(x)}" y="{_fmt(y)}" '
                f'width="{_fmt(w)}" height="{_fmt(h)}"/>')
    parts.append('  </g>')

    # Marcas de canto do miolo branco (cinza-claro, fora do retangulo do objeto).
    arm = 8.0
    ticks = []
    for (cx, cy, dx, dy) in [(x0, y0, -1, -1), (x1, y0, 1, -1),
                             (x1, y1, 1, 1), (x0, y1, -1, 1)]:
        ticks.append(f'M {_fmt(cx + dx * arm)} {_fmt(cy)} L {_fmt(cx)} {_fmt(cy)} '
                     f'L {_fmt(cx)} {_fmt(cy + dy * arm)}')
    parts.append(
        f'  <path d="{" ".join(ticks)}" fill="none" '
        f'stroke="#bbbbbb" stroke-width="0.25"/>')

    # Guia de enquadramento "nadir": anel concentrico + cruz de centragem.
    # Um circulo so aparece redondo na foto se a camera estiver a 90graus; sob
    # inclinacao vira elipse. Raio limitado pela MENOR metade do miolo (circulo
    # verdadeiro), com perimetro fora da pegada do objeto -> sobram arcos
    # visiveis ao redor para o olho julgar a roundeza. Cinza bem claro e fino:
    # fica acima de qualquer limiar de binarizacao, entao a segmentacao do
    # objeto escuro sobre branco o ignora.
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    ring_r = min(x1 - x0, y1 - y0) / 2.0 - 5.0
    cross = 12.0   # braco da cruz central
    tick = 4.0     # ticks radiais nos 4 pontos cardeais do anel
    parts.append('  <g fill="none" stroke="#cccccc" stroke-width="0.3">')
    parts.append(f'    <circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(ring_r)}"/>')
    parts.append(
        f'    <path d="M {_fmt(cx - cross)} {_fmt(cy)} L {_fmt(cx + cross)} {_fmt(cy)} '
        f'M {_fmt(cx)} {_fmt(cy - cross)} L {_fmt(cx)} {_fmt(cy + cross)}"/>')
    parts.append(
        f'    <path d="M {_fmt(cx)} {_fmt(cy - ring_r - tick)} L {_fmt(cx)} {_fmt(cy - ring_r + tick)} '
        f'M {_fmt(cx)} {_fmt(cy + ring_r - tick)} L {_fmt(cx)} {_fmt(cy + ring_r + tick)} '
        f'M {_fmt(cx - ring_r - tick)} {_fmt(cy)} L {_fmt(cx - ring_r + tick)} {_fmt(cy)} '
        f'M {_fmt(cx + ring_r - tick)} {_fmt(cy)} L {_fmt(cx + ring_r + tick)} {_fmt(cy)}"/>')
    parts.append('  </g>')

    # Instrucao de impressao no rodape (margem branca).
    parts.append(
        f'  <text x="{_fmt(W / 2)}" y="{_fmt(H - layout["page_margin"] * 0.35)}" '
        f'font-family="sans-serif" font-size="3.2" fill="#999999" '
        f'text-anchor="middle">PtoO base.svg  -  imprima em A4 a 100% '
        f'(sem "ajustar a pagina")  -  objeto no centro branco</text>')

    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gera o alvo de calibracao SVG (Opcao B).")
    ap.add_argument("--out", default="base.svg")
    ap.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    ap.add_argument("--page-margin", type=float, default=10.0)
    ap.add_argument("--marker-mm", type=float, default=16.0)
    ap.add_argument("--inner-pad", type=float, default=6.0)
    ap.add_argument("--dict", default="DICT_4X4_50")
    args = ap.parse_args(argv)

    page = CT.A4_LANDSCAPE if args.orientation == "landscape" else CT.A4_PORTRAIT
    layout = CT.target_layout(page=page, page_margin=args.page_margin,
                              marker_mm=args.marker_mm, inner_pad=args.inner_pad,
                              dict_name=args.dict)
    n = len(layout["markers"])
    if n > layout["capacity"]:
        sys.exit(f"ERRO: {n} marcadores > capacidade {layout['capacity']} de {args.dict}. "
                 f"Use um marker-mm maior ou um dicionario maior.")
    svg = render_svg(layout)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    ix = layout["inner_rect"]
    print(f"OK: {args.out}  ({n} marcadores, {args.dict})")
    print(f"    miolo branco do objeto: {_fmt(ix[2]-ix[0])} x {_fmt(ix[3]-ix[1])} mm")


if __name__ == "__main__":
    main()
