#!/usr/bin/env python
"""Recortador de zoom p/ a skill /ptoo.

Lê o overlay EDITÁVEL `_overlay_<name>.svg` (gerado por photo_to_outline.py com
`--inkscape`): ele já traz a foto retificada embutida (base64) E o contorno de Béziers
EMITIDO, ambos no MESMO referencial em mm (viewBox). Desenha o contorno sobre a foto e
recorta janelas de zoom nas regiões informativas (4 extremidades dos eixos + pontos de
maior curvatura/protuberância), em alta resolução, p/ inspeção visual. Se o overlay de
SEGMENTAÇÃO `_overlay_<name>.png` for passado (mesma dimensão da foto retificada), recorta
as MESMAS janelas dele lado a lado (contorno emitido | o que o tool segmentou).

Sem dependências novas: só cv2 + numpy + stdlib. Saídas em <out-dir> + manifest.json.

Uso:
  inspect.py --overlay-svg _overlay_foo.svg [--seg-overlay _overlay_foo.png] --out-dir DIR
"""
import argparse
import base64
import json
import os
import re
import sys

import cv2
import numpy as np

WIN = 360            # lado da janela de zoom (px) na resolução da foto retificada
OVERVIEW_W = 1000    # largura do overview reduzido
CONTOUR_BGR = (0, 255, 255)   # amarelo — contorno EMITIDO desenhado sobre a foto
N_CURV = 4           # nº de pontos de alta curvatura a destacar (além das 4 extremidades)


def parse_overlay_svg(path):
    """Devolve (img_bgr, canvas_w_mm, canvas_h_mm, pts_mm) do overlay editável.
    `pts_mm` é a polilinha (achatada dos Béziers) no frame da foto (Y p/ baixo, em mm)."""
    with open(path, "r", encoding="utf-8") as fh:
        svg = fh.read()
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not m:
        raise ValueError("viewBox não encontrado no overlay SVG")
    cw, ch = float(m.group(1)), float(m.group(2))
    m = re.search(r"base64,([A-Za-z0-9+/=]+)", svg)
    if not m:
        raise ValueError("imagem embutida (base64) não encontrada no overlay SVG")
    buf = np.frombuffer(base64.b64decode(m.group(1)), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    m = re.search(r'<path d="([^"]+)"', svg)
    if not m:
        raise ValueError("path do contorno não encontrado no overlay SVG")
    pts = flatten_path(m.group(1))
    return img, cw, ch, pts


def flatten_path(d, steps=20):
    """Achata um path SVG (só M/L/C/Z absolutos, como o writer emite) numa lista de
    pontos (x,y) em mm. Cada cúbica vira `steps` segmentos."""
    toks = re.findall(r"[MLCZ]|-?\d*\.?\d+", d)
    pts, i, cur, start = [], 0, None, None
    while i < len(toks):
        c = toks[i]; i += 1
        if c == "M":
            cur = (float(toks[i]), float(toks[i + 1])); i += 2
            start = cur; pts.append(cur)
        elif c == "L":
            cur = (float(toks[i]), float(toks[i + 1])); i += 2
            pts.append(cur)
        elif c == "C":
            c1 = (float(toks[i]), float(toks[i + 1]))
            c2 = (float(toks[i + 2]), float(toks[i + 3]))
            p3 = (float(toks[i + 4]), float(toks[i + 5])); i += 6
            for s in range(1, steps + 1):
                t = s / steps; u = 1 - t
                x = (u**3 * cur[0] + 3 * u * u * t * c1[0]
                     + 3 * u * t * t * c2[0] + t**3 * p3[0])
                y = (u**3 * cur[1] + 3 * u * u * t * c1[1]
                     + 3 * u * t * t * c2[1] + t**3 * p3[1])
                pts.append((x, y))
            cur = p3
        elif c == "Z":
            if start is not None:
                pts.append(start)
    return pts


def curvature_points(px_pts, k=N_CURV):
    """Índices dos pontos de maior mudança de direção (cantos/protuberâncias), espaçados."""
    n = len(px_pts)
    if n < 8:
        return []
    P = np.asarray(px_pts, dtype=float)
    step = max(2, n // 120)             # vizinhança p/ medir o ângulo (robusto a ruído)
    score = np.zeros(n)
    for i in range(n):
        a = P[(i - step) % n]; b = P[i]; c = P[(i + step) % n]
        v1, v2 = b - a, c - b
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cosang = np.clip(np.dot(v1, v2) / (n1 * n2), -1, 1)
        score[i] = np.arccos(cosang)   # 0 = reto; maior = canto mais fechado
    chosen, guard = [], max(6, n // (k + 2))   # espaçamento mínimo em índices (não px)
    for idx in np.argsort(-score):
        if all(min(abs(idx - j), n - abs(idx - j)) > guard for j in chosen):
            chosen.append(int(idx))
        if len(chosen) >= k:
            break
    return chosen


def crop(img, cx, cy, win=WIN):
    h, w = img.shape[:2]
    half = win // 2
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(w, cx + half), min(h, cy + half)
    return img[y0:y1, x0:x1]


def label(img, text):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(out, text, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    return out


def side_by_side(a, b):
    h = max(a.shape[0], b.shape[0])
    def pad(im):
        p = np.zeros((h, im.shape[1], 3), np.uint8)
        p[:im.shape[0], :im.shape[1]] = im
        return p
    sep = np.full((h, 4, 3), (60, 60, 60), np.uint8)
    return np.hstack([pad(a), sep, pad(b)])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay-svg", required=True)
    ap.add_argument("--seg-overlay", default=None)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--win", type=int, default=WIN)
    args = ap.parse_args(argv)

    img, cw, ch, pts_mm = parse_overlay_svg(args.overlay_svg)
    h, w = img.shape[:2]
    sx, sy = w / cw, h / ch
    px_pts = [(int(round(x * sx)), int(round(y * sy))) for (x, y) in pts_mm]

    emitted = img.copy()
    cv2.polylines(emitted, [np.array(px_pts, np.int32)], True, CONTOUR_BGR, 2, cv2.LINE_AA)

    seg = None
    if args.seg_overlay and os.path.exists(args.seg_overlay):
        s = cv2.imread(args.seg_overlay)
        if s is not None and s.shape[:2] == (h, w):
            seg = s

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = {}

    # Overview (contorno emitido, reduzido).
    ow = OVERVIEW_W
    oh = int(h * ow / w)
    over = cv2.resize(emitted, (ow, oh), interpolation=cv2.INTER_AREA)
    op = os.path.join(args.out_dir, "overview.png")
    cv2.imwrite(op, label(over, "OVERVIEW  contorno emitido (amarelo) sobre a foto"))
    manifest["overview"] = op

    # Regiões: 4 extremidades dos eixos + pontos de alta curvatura.
    P = np.array(px_pts)
    ext = {
        "esq":   tuple(P[np.argmin(P[:, 0])]),
        "dir":   tuple(P[np.argmax(P[:, 0])]),
        "topo":  tuple(P[np.argmin(P[:, 1])]),
        "baixo": tuple(P[np.argmax(P[:, 1])]),
    }
    regions = [(f"ext_{k}", int(c[0]), int(c[1])) for k, c in ext.items()]
    for n, idx in enumerate(curvature_points(px_pts)):
        cx, cy = px_pts[idx]
        regions.append((f"curv_{n}", cx, cy))

    for name, cx, cy in regions:
        ce = label(crop(emitted, cx, cy, args.win), f"{name}  EMITIDO")
        tile = ce if seg is None else side_by_side(
            ce, label(crop(seg, cx, cy, args.win), "SEGMENTADO"))
        tp = os.path.join(args.out_dir, f"zoom_{name}.png")
        cv2.imwrite(tp, tile)
        manifest[name] = tp

    with open(os.path.join(args.out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(json.dumps(manifest, indent=2))
    print(f"foto retificada: {w}x{h}px  |  objeto frame: {cw:.2f}x{ch:.2f}mm  "
          f"|  px/mm ~ {sx:.2f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
