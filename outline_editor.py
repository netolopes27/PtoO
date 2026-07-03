#!/usr/bin/env python3
# =============================================================================
# outline_editor.py — editor manual dos NÓS do contorno (GUI tkinter)
# -----------------------------------------------------------------------------
# Etapa interativa OPCIONAL entre a detecção e a saída do photo_to_outline.py.
# A CLI detecta o contorno como hoje (rectify ArUco → segment → extract → pocket
# Béziers) e, com `--edit`, abre uma janela mostrando a FOTO RETIFICADA de fundo
# e os NÓS on-curve da curva final como alças arrastáveis. O usuário MOVE/INCLUI/
# EXCLUI nós; qualquer edição RE-TRAÇA a curva suave (G1) que passa pelos nós
# (`cubics_through_nodes`). WYSIWYG: ao "Finalize" a CLI grava as MESMAS saídas de
# hoje a partir de EXATAMENTE a curva exibida (sem recalcular). A DETECÇÃO continua
# sendo da ferramenta — o usuário só ajusta os nós.
#
# Duas camadas:
#   • NÚCLEO PURO (sem tkinter, testável): geometria do "re-traçar", ops de edição
#     dos nós e os transforms mm↔pixel-da-foto.
#   • VIEW tkinter (glue fino, não unit-testado): a janela. tkinter é stdlib; a foto
#     entra via cv2.imencode(PNG)→base64→tk.PhotoImage (Tk 8.6 lê PNG, sem PIL).
#
# Roda no mesmo venv do photo_to_outline.py (numpy + opencv-python).
# =============================================================================

import math

import photo_to_outline as P


# =============================================================================
# NÚCLEO PURO — geometria do "re-traçar" + edição dos nós + transforms
# =============================================================================
def nodes_from_cubics(cubics):
    """Nós on-curve (os pontos por onde a curva passa) de uma lista de cúbicas
    `(p0,c1,c2,p3)` ENCADEADAS e FECHADAS: o `p0` de cada cúbica (o `p3` de uma é o
    `p0` da próxima). É a lista inicial de alças que o editor mostra."""
    return [(float(c[0][0]), float(c[0][1])) for c in cubics]


def cubics_through_nodes(nodes, line_segs=frozenset()):
    """RE-TRAÇAR: dado o polígono fechado de nós on-curve, devolve cúbicas G1 que
    PASSAM por cada nó (spline cardinal / Catmull-Rom → Bézier). A tangente em cada
    nó = corda pelos vizinhos imediatos (mesma ideia de P._anchor_tangents) e os
    handles ficam a ~1/3 da corda ao longo dela. Como a MESMA tangente serve aos dois
    trechos que se encontram num nó, todo nó é SUAVE (G1, sem bico) — igual à saída
    automática. Reaproveita P._cap_handles (teto anti-laço) e P._repair_self_intersections
    (de-loop) p/ garantir um contorno fechado SIMPLES.

    `line_segs` (v0.10): índices dos trechos RETOS (trecho k = nó k → nó k+1). Um trecho
    reto vira cúbica DEGENERADA na corda; o vizinho curvo sai TANGENTE à reta (G1).
    EXCEÇÃO ao G1: dois trechos retos consecutivos formam CANTO legítimo — é o que o
    usuário pediu ao retificar os dois. Se o polígono for invertido p/ CCW, os índices
    são REMAPEADOS junto (a reta segue entre os MESMOS dois nós)."""
    pts = P.dedup_closing_point(nodes)
    n = len(pts)
    if n < 3:
        return []
    lines = {k % n for k in line_segs}
    if P.signed_area(pts) < 0:                   # ensure_ccw inverteria: remapeia junto
        pts = pts[::-1]
        lines = {(n - 2 - k) % n for k in lines}
    pts = [(float(p[0]), float(p[1])) for p in pts]

    def chord(i, j):
        return P._unit((pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]))

    seg_dir = [chord(i, (i + 1) % n) for i in range(n)]
    catmull = [chord((i - 1) % n, (i + 1) % n) for i in range(n)]
    cubics = []
    for i in range(n):
        p0 = pts[i]
        p3 = pts[(i + 1) % n]
        if i in lines:                           # RETA: handles na própria corda
            t0 = t1 = seg_dir[i]
        else:                                    # curva: tangente do vizinho RETO manda
            t0 = seg_dir[(i - 1) % n] if ((i - 1) % n) in lines else catmull[i]
            t1 = seg_dir[(i + 1) % n] if ((i + 1) % n) in lines else catmull[(i + 1) % n]
        L = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
        a = L / 3.0
        c1 = (p0[0] + t0[0] * a, p0[1] + t0[1] * a)
        c2 = (p3[0] - t1[0] * a, p3[1] - t1[1] * a)
        cubics.append(P._cap_handles((p0, c1, c2, p3)))
    return P._repair_self_intersections(cubics)


# --- edição dos nós (polígono fechado, sem ponto de fechamento duplicado) -----
def move_node(nodes, i, xy):
    """Move o nó `i` p/ a posição `xy` (mm). Devolve uma NOVA lista."""
    out = list(nodes)
    out[i % len(out)] = (float(xy[0]), float(xy[1]))
    return out


def insert_node(nodes, i, xy):
    """Insere `xy` LOGO APÓS o nó `i` (entre `i` e `i+1`) — usado ao clicar no trecho
    que sai do nó `i`. Devolve uma NOVA lista."""
    out = list(nodes)
    out.insert((i % len(out)) + 1, (float(xy[0]), float(xy[1])))
    return out


def delete_node(nodes, i):
    """Exclui o nó `i`, mantendo no mínimo 3 nós (abaixo disso não há contorno).
    Devolve uma NOVA lista (a original se já estiver no mínimo)."""
    if len(nodes) <= 3:
        return list(nodes)
    out = list(nodes)
    del out[i % len(out)]
    return out


def remap_lines_insert(line_segs, i):
    """Remapeia os trechos RETOS após inserir um nó DENTRO do trecho `i`: o trecho
    dividido vira DOIS retos (visual inalterado — o nó novo cai na reta; arrastá-lo
    depois cria um canto de duas retas); os seguintes deslocam +1."""
    out = set()
    for k in line_segs:
        if k < i:
            out.add(k)
        elif k == i:
            out.update((i, i + 1))
        else:
            out.add(k + 1)
    return out


def remap_lines_delete(line_segs, i, m):
    """Remapeia os trechos RETOS após excluir o nó `i` (de `m` nós): os dois trechos
    vizinhos fundem num só — RETO somente se AMBOS eram retos (reta+curva = curva);
    os seguintes deslocam -1."""
    i %= m
    prev = (i - 1) % m
    out = set()
    for k in line_segs:
        if k == prev or k == i:
            continue                             # par fundido: tratado abaixo
        if i == 0:
            out.add(k - 1)                       # apagou o nó 0: tudo desloca
        else:
            out.add(k if k < prev else k - 1)
    if prev in line_segs and i in line_segs:
        out.add(prev if i > 0 else m - 2)
    return out


def straighten_between(nodes, line_segs, i, j):
    """Botão LINE: remove os nós INTERIORES do caminho MAIS CURTO (em comprimento)
    entre os nós `i` e `j` e marca o trecho resultante como RETA. Devolve
    `(nós, retas, índice_do_trecho_reto)` — ou `(cópias, None)` no índice se a
    operação for inválida (nós iguais ou resultado < 3 nós)."""
    n = len(nodes)
    if n < 3:
        return list(nodes), set(line_segs), None
    i %= n
    j %= n
    if i == j:
        return list(nodes), set(line_segs), None
    # comprimento ANDANDO ADIANTE i→j vs o caminho reverso (j→i adiante)
    def fwd_len(a, b):
        total, k = 0.0, a
        while k != b:
            nk = (k + 1) % n
            total += math.hypot(nodes[nk][0] - nodes[k][0], nodes[nk][1] - nodes[k][1])
            k = nk
        return total
    a, b = (i, j) if fwd_len(i, j) <= fwd_len(j, i) else (j, i)
    interior = ((b - a) % n) - 1
    if n - interior < 3:
        return list(nodes), set(line_segs), None
    out = list(nodes)
    lines = {k % n for k in line_segs}
    for _ in range(interior):                    # apaga sempre o SUCESSOR de `a`
        m = len(out)
        idx = (a + 1) % m
        lines = remap_lines_delete(lines, idx, m)
        del out[idx]
        if idx < a:
            a -= 1                               # apagou antes de `a` (wrap): desloca
    seg = a % len(out)
    lines.add(seg)
    return out, lines, seg


def nearest_node(nodes, xy, max_dist=None):
    """Índice do nó mais próximo de `xy` (mesmo referencial). `None` se a lista for
    vazia ou se o mais próximo estiver além de `max_dist`."""
    if not nodes:
        return None
    best_i, best_d2 = None, float("inf")
    for i, (x, y) in enumerate(nodes):
        d2 = (x - xy[0]) ** 2 + (y - xy[1]) ** 2
        if d2 < best_d2:
            best_i, best_d2 = i, d2
    if max_dist is not None and best_d2 > max_dist * max_dist:
        return None
    return best_i


def nearest_segment(nodes, xy):
    """Índice `i` do trecho [nó i → nó i+1] mais próximo de `xy` (referencial mm/px),
    p/ inserir um nó ali. `None` se houver menos de 2 nós."""
    n = len(nodes)
    if n < 2:
        return None
    best_i, best_d = None, float("inf")
    for i in range(n):
        d = P._dist_point_seg(xy, nodes[i], nodes[(i + 1) % n])
        if d < best_d:
            best_i, best_d = i, d
    return best_i


# --- transforms mm ↔ pixel da foto retificada --------------------------------
# Convenção idêntica à de P.write_overlay_svg: a silhueta/cúbicas estão em mm com
# Y p/ CIMA (x ≥ 0, y ≤ 0, pois P.extract_outline faz y = -py·mmpp); a foto tem o
# pixel (0,0) no topo-esquerdo. Logo px = x/mmpp_x, py = -y/mmpp_y (e o inverso).
def mm_to_px(pt, mmpp_x, mmpp_y):
    """Ponto em mm (Y p/ cima) → pixel da foto retificada (Y p/ baixo)."""
    return (pt[0] / mmpp_x, -pt[1] / mmpp_y)


def px_to_mm(pt, mmpp_x, mmpp_y):
    """Pixel da foto retificada (Y p/ baixo) → ponto em mm (Y p/ cima)."""
    return (pt[0] * mmpp_x, -pt[1] * mmpp_y)


# =============================================================================
# VIEW tkinter (glue fino) — importa tkinter SÓ aqui dentro p/ o núcleo puro
# continuar importável num runner headless (testes) sem display.
# =============================================================================
HANDLE_R = 5          # raio (px de tela) das alças dos nós
HIT_TOL = 10          # tolerância de clique (px de tela) p/ pegar uma alça
ZOOM_STEP = 1.25      # fator de zoom por passo da rodinha
ZOOM_MIN = 0.05
ZOOM_MAX = 40.0


class EditorApp:
    """Janela de ajuste: foto retificada de fundo + nós arrastáveis + curva traçada.

    Interações: ARRASTAR alça = mover nó; CLIQUE no trecho da curva = inserir nó;
    BOTÃO-DIREITO na alça = excluir; SHIFT+CLIQUE na alça = selecionar (até 2, alça
    vermelha) p/ o botão "Line": remove os nós entre os dois selecionados (caminho
    mais curto) e traça uma RETA entre eles — os vizinhos saem tangentes à reta (G1) e
    as retas sobrevivem a mover/inserir/excluir (remap). Rodinha = zoom NO CURSOR (o
    ponto sob o mouse fica parado); CTRL + arrasto do botão esquerdo = pan. Botões (em
    inglês na GUI): Re-trace (spline Catmull-Rom G1 pelos nós), Undo, Reset (volta aos
    nós detectados, sem retas manuais), Line e Finalize. WYSIWYG: Finalize grava
    EXATAMENTE a curva que está na tela (a mesma do último Re-trace) — nada é
    recalculado.

    Modelo de coordenadas: mm (nós) → pixel-da-foto (mm_to_px) → pixel-de-TELA por uma
    transformada afim própria `tela = px·zoom + off` (não usa scrollregion do Canvas). O fundo
    é renderizado por RECORTE do VIEWPORT (só a parte visível é redimensionada/codificada),
    então o custo não explode com o zoom — o polimento pedido."""

    def __init__(self, root, rect, nodes0, mmpp_x, mmpp_y):
        import tkinter as tk
        self.tk = tk
        self.root = root
        self.rect = rect
        self.mmpp_x = mmpp_x
        self.mmpp_y = mmpp_y
        self.nodes0 = list(nodes0)          # nós detectados (p/ Reset)
        self.nodes = list(nodes0)           # nós atuais (em mm)
        self.lines = set()                  # trechos RETOS manuais (índices de trecho)
        self.sel = []                       # nós selecionados via shift+clique (≤ 2)
        self.cubics = cubics_through_nodes(self.nodes)
        self.history = []                   # pilha p/ Desfazer (snapshots de nodes+lines)
        self.result = None                  # cúbicas finais ao Finalizar; None = cancelado
        self.zoom = 1.0
        self.off_x = 0.0                    # posição (px de tela) do pixel (0,0) da foto
        self.off_y = 0.0
        self.drag_idx = None
        self._pan = None                    # (x0, y0, off_x0, off_y0) durante o pan
        self._fitted = False               # 1º <Configure> ajusta a foto à janela
        self._photo = None                 # ref. viva do PhotoImage (evita GC)
        self._photo_xy = (0.0, 0.0)        # canto (nw) do fundo em px de tela

        root.title("PtoO — node editor (Re-trace / Finalize)")
        bar = tk.Frame(root)
        bar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(bar, text="Re-trace", command=self.retrace).pack(side=tk.LEFT)
        tk.Button(bar, text="Undo", command=self.undo).pack(side=tk.LEFT)
        tk.Button(bar, text="Reset", command=self.reset).pack(side=tk.LEFT)
        tk.Button(bar, text="Line", command=self.make_line).pack(side=tk.LEFT)
        tk.Button(bar, text="Finalize", command=self.finish).pack(side=tk.RIGHT)
        self.status = tk.Label(bar, text="", anchor="w")
        self.status.pack(side=tk.LEFT, padx=8)

        h, w = rect.shape[:2]
        self.canvas = tk.Canvas(root, bg="#202020", highlightthickness=0,
                                width=min(1200, w), height=min(800, h))
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self.on_configure)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_right)                    # excluir nó
        # seleção p/ o botão Line = Shift + clique esquerdo na alça (binding com
        # modificador tem precedência sobre o <Button-1> simples, como o pan)
        self.canvas.bind("<Shift-ButtonPress-1>", self.on_shift_press)
        # pan = Ctrl + arrasto do botão esquerdo (o binding com modificador tem precedência
        # sobre o <Button-1> simples, então não conflita com mover/inserir nó)
        self.canvas.bind("<Control-ButtonPress-1>", self.on_pan_start)
        self.canvas.bind("<Control-B1-Motion>", self.on_pan_move)
        self.canvas.bind("<Control-ButtonRelease-1>", self.on_pan_end)
        self.canvas.bind("<MouseWheel>", self.on_wheel)                  # zoom (Windows/Mac)
        self.canvas.bind("<Button-4>", self.on_wheel)                    # zoom (Linux up)
        self.canvas.bind("<Button-5>", self.on_wheel)                    # zoom (Linux down)

    # --- transformada de VIEW: pixel-da-foto ↔ tela (tela = px·zoom + offset) --
    def _photo_px_to_screen(self, px, py):
        return (px * self.zoom + self.off_x, py * self.zoom + self.off_y)

    def _screen_to_photo_px(self, sx, sy):
        return ((sx - self.off_x) / self.zoom, (sy - self.off_y) / self.zoom)

    def _refresh(self):
        """Re-renderiza o fundo (recorte do viewport) e redesenha o vetor."""
        self._render_bg()
        self.redraw()

    # --- fundo por RECORTE do viewport (custo independente do zoom) -----------
    def _render_bg(self):
        import cv2
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        h, w = self.rect.shape[:2]
        z = self.zoom
        # retângulo VISÍVEL, em pixels da foto (recorta ao tamanho da foto)
        px0, py0 = self._screen_to_photo_px(0, 0)
        px1, py1 = self._screen_to_photo_px(cw, ch)
        ix0 = max(0, int(math.floor(px0)))
        iy0 = max(0, int(math.floor(py0)))
        ix1 = min(w, int(math.ceil(px1)))
        iy1 = min(h, int(math.ceil(py1)))
        if ix1 <= ix0 or iy1 <= iy0:
            self._photo = None
            return
        crop = self.rect[iy0:iy1, ix0:ix1]
        dw = max(1, int(round((ix1 - ix0) * z)))
        dh = max(1, int(round((iy1 - iy0) * z)))
        interp = cv2.INTER_AREA if z < 1 else cv2.INTER_LINEAR
        img = cv2.resize(crop, (dw, dh), interpolation=interp)
        self._photo = self.tk.PhotoImage(data=P.encode_png_b64(img))
        self._photo_xy = self._photo_px_to_screen(ix0, iy0)

    def _fit_view(self):
        """Enquadra a foto inteira na janela (centralizada) — estado inicial."""
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        h, w = self.rect.shape[:2]
        if not (w and h and cw > 1 and ch > 1):
            return
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, min(cw / w, ch / h)))
        self.off_x = (cw - w * self.zoom) / 2
        self.off_y = (ch - h * self.zoom) / 2
        self._refresh()

    # --- conversões mm ↔ tela (compõe mm↔px-da-foto com a transformada de view) -
    def _mm_to_screen(self, pt):
        return self._photo_px_to_screen(*mm_to_px(pt, self.mmpp_x, self.mmpp_y))

    def _screen_to_mm(self, sx, sy):
        return px_to_mm(self._screen_to_photo_px(sx, sy), self.mmpp_x, self.mmpp_y)

    # --- desenho (vetor apenas; o fundo já está em self._photo) ---------------
    def redraw(self):
        c = self.canvas
        c.delete("all")
        if self._photo is not None:
            c.create_image(self._photo_xy[0], self._photo_xy[1], anchor="nw", image=self._photo)
        # curva (achatada) sobre a foto, na cor de saída
        if self.cubics:
            flat = P.flatten_beziers(self.cubics) + [self.cubics[0][0]]
            coords = []
            for pt in flat:
                sx, sy = self._mm_to_screen(pt)
                coords += [sx, sy]
            if len(coords) >= 4:
                c.create_line(*coords, fill=P.OUTLINE_COLOR, width=2)
        # alças dos nós (selecionadas p/ o Line: vermelhas)
        for i, pt in enumerate(self.nodes):
            sx, sy = self._mm_to_screen(pt)
            fill = "#ff4040" if i in self.sel else "#ffe000"
            c.create_oval(sx - HANDLE_R, sy - HANDLE_R, sx + HANDLE_R, sy + HANDLE_R,
                          fill=fill, outline="#000000", tags=f"node{i}")
        self.status.config(
            text=f"{len(self.nodes)} nodes · {len(self.lines)} lines · zoom {self.zoom:.2f}× · "
                 f"drag=move · click curve=insert · right-click=delete · "
                 f"shift+click=select (2) then Line · wheel=zoom · Ctrl+drag=pan")

    def _push_history(self):
        self.history.append((list(self.nodes), set(self.lines)))
        if len(self.history) > 100:
            self.history.pop(0)

    def _hit_tol_mm(self):
        """Tolerância de clique HIT_TOL (px de tela) convertida p/ mm no zoom atual."""
        return HIT_TOL * self.mmpp_x / self.zoom

    # --- eventos -------------------------------------------------------------
    def on_configure(self, _e):
        if not self._fitted:                     # 1ª exibição: enquadra a foto
            self._fitted = True
            self._fit_view()
        else:                                    # redimensionou a janela: re-renderiza o fundo
            self._refresh()

    def on_press(self, e):
        mm = self._screen_to_mm(e.x, e.y)
        i = nearest_node(self.nodes, mm, max_dist=self._hit_tol_mm())
        if i is not None:
            self._push_history()
            self.drag_idx = i
        else:                                    # clique fora de alça = inserir no trecho
            j = nearest_segment(self.nodes, mm)
            if j is not None:
                self._push_history()
                self.nodes = insert_node(self.nodes, j, mm)
                self.lines = remap_lines_insert(self.lines, j)
                self.sel = []                    # índices mudaram: seleção caduca
                self.retrace()                   # curva na tela segue os nós (WYSIWYG)

    def on_drag(self, e):
        if self.drag_idx is not None:
            self.nodes = move_node(self.nodes, self.drag_idx, self._screen_to_mm(e.x, e.y))
            self.redraw()                        # alça segue o mouse; curva atualiza ao soltar

    def on_release(self, _e):
        if self.drag_idx is not None:
            self.drag_idx = None
            self.retrace()                       # re-traça a curva pelos nós na posição final

    def on_right(self, e):
        mm = self._screen_to_mm(e.x, e.y)
        i = nearest_node(self.nodes, mm, max_dist=self._hit_tol_mm())
        if i is not None and len(self.nodes) > 3:    # delete_node guarda o mínimo de 3
            self._push_history()
            self.lines = remap_lines_delete(self.lines, i, len(self.nodes))
            self.nodes = delete_node(self.nodes, i)
            self.sel = []                        # índices mudaram: seleção caduca
            self.retrace()                       # curva na tela segue os nós (WYSIWYG)

    def on_shift_press(self, e):
        """Shift+clique na alça: alterna a seleção do nó (mantém no máximo 2 — os dois
        extremos da futura reta do botão Line)."""
        mm = self._screen_to_mm(e.x, e.y)
        i = nearest_node(self.nodes, mm, max_dist=self._hit_tol_mm())
        if i is None:
            return
        if i in self.sel:
            self.sel.remove(i)
        else:
            self.sel.append(i)
            if len(self.sel) > 2:
                self.sel.pop(0)                  # o mais antigo sai
        self.redraw()

    def make_line(self):
        """Botão Line: reta entre os 2 nós selecionados — remove os nós intermediários
        do caminho mais curto e marca o trecho como RETO (ver straighten_between)."""
        if len(self.sel) != 2:
            self.status.config(text="Line: shift+click TWO nodes first")
            return
        self._push_history()
        nodes, lines, seg = straighten_between(self.nodes, self.lines, *self.sel)
        if seg is None:
            self.history.pop()                   # nada mudou
            self.status.config(text="Line: invalid selection (too few nodes left)")
            return
        self.nodes, self.lines, self.sel = nodes, lines, []
        self.retrace()

    def on_pan_start(self, e):
        self._pan = (e.x, e.y, self.off_x, self.off_y)

    def on_pan_move(self, e):
        if self._pan is not None:
            x0, y0, ox, oy = self._pan
            self.off_x = ox + (e.x - x0)
            self.off_y = oy + (e.y - y0)
            self._refresh()

    def on_pan_end(self, _e):
        self._pan = None

    def on_wheel(self, e):
        up = getattr(e, "delta", 0) > 0 or getattr(e, "num", None) == 4
        factor = ZOOM_STEP if up else 1.0 / ZOOM_STEP
        new = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * factor))
        if abs(new - self.zoom) < 1e-9:
            return
        # ZOOM NO CURSOR: mantém o pixel-da-foto sob o mouse parado na tela
        ipx, ipy = self._screen_to_photo_px(e.x, e.y)   # antes de trocar o zoom
        self.zoom = new
        self.off_x = e.x - ipx * new
        self.off_y = e.y - ipy * new
        self._refresh()

    # --- botões --------------------------------------------------------------
    def retrace(self):                           # traça a curva G1 pelos nós (retas incl.)
        self.cubics = cubics_through_nodes(self.nodes, self.lines)
        self.redraw()

    def undo(self):
        if self.history:
            self.nodes, self.lines = self.history.pop()
            self.sel = []
            self.retrace()

    def reset(self):
        self._push_history()
        self.nodes = list(self.nodes0)
        self.lines = set()                       # retas manuais também voltam ao zero
        self.sel = []
        self.retrace()

    def finish(self):
        # WYSIWYG: grava EXATAMENTE a curva que está na tela (o último Re-traçar), sem recalcular.
        self.result = self.cubics
        self.root.destroy()


def run_editor(rect, nodes0, mmpp_x, mmpp_y):
    """Abre o editor e BLOQUEIA até o usuário Finalizar ou fechar a janela. Devolve as
    CÚBICAS finais — EXATAMENTE a curva exibida (Catmull-Rom G1 pelos nós, o mesmo do
    Re-traçar) — ao Finalizar, ou `None` se a janela for fechada/cancelada."""
    import tkinter as tk
    root = tk.Tk()
    app = EditorApp(root, rect, nodes0, mmpp_x, mmpp_y)
    root.mainloop()
    return app.result
