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


# --- simetria espelhada (F1/F1b, plano 011) -----------------------------------
# O pareamento é POR ÍNDICE: o par do nó i é (N−i) % N (nós 0 e N/2 caem no eixo e
# são auto-pareados) — estrutura herdada de P.symmetrize_beziers, validada exata em
# float. Nada de matching geométrico nem mapa de pares armazenado.
def mirror_index(i, n):
    """Índice do nó PAR de `i` no invariante canônico i ↔ (N−i) % N."""
    return (n - i) % n


def mirror_point(pt, axis, c):
    """Espelho de `pt` em torno do eixo ('vertical' = reta x=c; 'horizontal' = y=c)."""
    if axis == "vertical":
        return (2.0 * c - pt[0], pt[1])
    return (pt[0], 2.0 * c - pt[1])


def sym_check_pairing(nodes, axis, c, eps=1e-6):
    """Verifica o invariante canônico: max_i |nó_i − espelho(nó_{(N−i)%N})| < eps.
    Também valida os nós de eixo (i == (N−i)%N exige o nó SOBRE o eixo)."""
    n = len(nodes)
    if n < 3:
        return False
    for i in range(n):
        m = mirror_point(nodes[mirror_index(i, n)], axis, c)
        if math.hypot(nodes[i][0] - m[0], nodes[i][1] - m[1]) >= eps:
            return False
    return True


def _canonicalize_pairing(nodes, lines, axis, c):
    """Devolve o invariante à forma canônica ROTACIONANDO a lista (o pareamento pode
    sobreviver a uma exclusão com um deslocamento de índice — ex.: excluir o nó de
    eixo 0). Os índices das retas giram junto. Sem deslocamento válido, devolve como
    veio (o chamador decide se avisa)."""
    n = len(nodes)
    for r in range(n):
        rot = nodes[r:] + nodes[:r]
        if sym_check_pairing(rot, axis, c):
            if r == 0:
                return list(nodes), set(lines)
            return rot, {(k - r) % n for k in lines}
    return list(nodes), set(lines)


def move_node_sym(nodes, i, xy, axis, c):
    """Op-par de mover: o par j=(N−i)%N recebe o espelho de `xy`. Nó DE EIXO (i==j):
    trava a coordenada do eixo (x=c no vertical) e move só ao longo dele."""
    n = len(nodes)
    i %= n
    j = mirror_index(i, n)
    ai = 0 if axis == "vertical" else 1
    if j == i:
        pt = [float(xy[0]), float(xy[1])]
        pt[ai] = float(c)
        return move_node(nodes, i, tuple(pt))
    out = move_node(nodes, i, xy)
    return move_node(out, j, mirror_point((float(xy[0]), float(xy[1])), axis, c))


def insert_node_sym(nodes, lines, k, xy, axis, c):
    """Op-par de inserir: `xy` entra no trecho `k` E o espelho entra no trecho par
    `(N−1−k)%N`; após o casal, N'=N+2 e o invariante canônico se mantém (as posições
    de inserção são calculadas p/ isso — provado nos testes E). Devolve (nós, retas)."""
    n = len(nodes)
    k %= n
    j = (n - 1 - k) % n
    xy = (float(xy[0]), float(xy[1]))
    mxy = mirror_point(xy, axis, c)
    if k == j:
        # trecho AUTO-espelhado (cruza o eixo): os dois pontos entram no mesmo trecho,
        # ordenados ao longo dele (o mais próximo do nó k primeiro).
        a, b = nodes[k], nodes[(k + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]

        def t_of(p):
            return (p[0] - a[0]) * dx + (p[1] - a[1]) * dy

        first, second = (xy, mxy) if t_of(xy) <= t_of(mxy) else (mxy, xy)
        out = insert_node(nodes, k, first)
        lines2 = remap_lines_insert(lines, k)
        out = insert_node(out, k + 1, second)
        return out, remap_lines_insert(lines2, k + 1)
    out = insert_node(nodes, k, xy)
    lines2 = remap_lines_insert(lines, k)
    jj = j + 1 if k < j else j                   # o 1º insert deslocou (ou não) o trecho par
    out = insert_node(out, jj, mxy)
    return out, remap_lines_insert(lines2, jj)


def delete_node_sym(nodes, lines, i, axis, c):
    """Op-par de excluir: sai o nó `i` E o par (2 por vez); nó DE EIXO sai sozinho.
    Mantém o mínimo de 3 nós (no-op abaixo disso). Devolve (nós, retas)."""
    n = len(nodes)
    i %= n
    j = mirror_index(i, n)
    if j == i:                                   # nó de eixo: exclui sozinho
        if n <= 3:
            return list(nodes), set(lines)
        lines2 = remap_lines_delete(lines, i, n)
        out = list(nodes)
        del out[i]
        # excluir o nó 0 desloca o pareamento: re-canonicaliza (rotação da lista)
        return _canonicalize_pairing(out, lines2, axis, c)
    if n - 2 < 3:
        return list(nodes), set(lines)
    hi, lo = max(i, j), min(i, j)
    lines2 = remap_lines_delete(lines, hi, n)
    out = list(nodes)
    del out[hi]
    lines2 = remap_lines_delete(lines2, lo, n - 1)
    del out[lo]
    return out, lines2


def straighten_between_sym(nodes, lines, i, j, axis, c):
    """Op-par do botão Line: aplica `straighten_between` em (i,j) e repete no par
    espelhado (localizado por POSIÇÃO — os índices mudam após a 1ª retificação).
    Devolve (nós, retas, seg) — seg None = operação inválida."""
    n = len(nodes)
    i %= n
    j %= n
    mi, mj = mirror_index(i, n), mirror_index(j, n)
    pmi = mirror_point(nodes[i], axis, c)        # posição do par ANTES de editar
    pmj = mirror_point(nodes[j], axis, c)
    out, lines2, seg = straighten_between(nodes, lines, i, j)
    if seg is None:
        return list(nodes), set(lines), None
    if {mi, mj} == {i, j}:                       # a seleção É o próprio par (nós de eixo)
        out, lines2 = _canonicalize_pairing(out, lines2, axis, c)
        return out, lines2, seg

    def find(pts, p):
        for k, q in enumerate(pts):
            if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6:
                return k
        return None

    a, b = find(out, pmi), find(out, pmj)
    if a is None or b is None:                   # par sumiu (contorno não pareado)
        return out, lines2, seg
    out2, lines3, seg2 = straighten_between(out, lines2, a, b)
    if seg2 is None:
        return out, lines2, seg
    out2, lines3 = _canonicalize_pairing(out2, lines3, axis, c)
    return out2, lines3, seg2


def snap_seam_nodes(nodes, axis, c_old, c_new, eps=1e-6):
    """F1b, caso 'eixo movido com pareamento ainda válido': encosta os nós de emenda
    (os que estão SOBRE o eixo antigo `c_old`) no eixo novo `c_new`, mantendo a outra
    coordenada — sem isso o Mirror deixaria um degrau de 2(c_new−c_old) na emenda."""
    ai = 0 if axis == "vertical" else 1
    out = []
    for p in nodes:
        q = [float(p[0]), float(p[1])]
        if abs(q[ai] - c_old) <= eps:
            q[ai] = float(c_new)
        out.append(tuple(q))
    return out


def mirror_contour(nodes, lines, axis, c, keep="high", eps=1e-7):
    """F1b — botão Mirror: reconstrói um lado como ESPELHO do outro em torno do eixo.
    `keep`: 'high' mantém o lado de coordenada ≥ c (direita no eixo vertical; topo no
    horizontal), 'low' o oposto. Onde um trecho cruza o eixo entra um NÓ DE EMENDA na
    interseção exata (coordenada do eixo == c); lista final = metade-mestre + espelho
    em ordem reversa → invariante canônico POR CONSTRUÇÃO (mesma estrutura da saída
    do CLI). Retas do lado-mestre são espelhadas junto; as do lado regenerado,
    descartadas. Devolve (nós, retas), ou (None, None) se o contorno cruza o eixo mais
    de 2× (o espelho fecharia laços separados — mesma limitação/critério do CLI em
    P.symmetrize_beziers)."""
    n = len(nodes)
    if n < 3:
        return None, None
    ai = 0 if axis == "vertical" else 1
    pts = []
    for p in nodes:                              # snap dos nós que JÁ estão no eixo
        q = [float(p[0]), float(p[1])]
        if abs(q[ai] - c) <= eps:
            q[ai] = float(c)
        pts.append(tuple(q))
    crossings = []                               # (trecho original, nó de emenda)
    for k in range(n):
        a, b = pts[k], pts[(k + 1) % n]
        da, db = a[ai] - c, b[ai] - c
        if da * db < 0.0:                        # cruzamento estrito do eixo
            t = da / (da - db)
            q = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
            q[ai] = float(c)                     # interseção EXATA no eixo
            crossings.append((k, tuple(q)))
    out, lines2 = pts, set(lines)
    for k, q in reversed(crossings):             # de trás p/ frente: índices anteriores valem
        out = insert_node(out, k, q)
        lines2 = remap_lines_insert(lines2, k)
    m = len(out)
    seams = [k for k, p in enumerate(out) if p[ai] == c]
    if len(seams) != 2:                          # > 2 cruzamentos (ou tangência): recusa
        return None, None
    sgn = 1.0 if keep == "high" else -1.0

    def side_ok(i0, i1):                         # arco i0→i1 (adiante) todo no lado-mestre?
        k = (i0 + 1) % m
        while k != i1:
            if sgn * (out[k][ai] - c) <= 0.0:
                return False
            k = (k + 1) % m
        return True

    a, b = seams
    if side_ok(a, b):
        start, end = a, b
    elif side_ok(b, a):
        start, end = b, a
    else:
        return None, None
    master = [out[start]]
    k = (start + 1) % m
    while True:
        master.append(out[k])
        if k == end:
            break
        k = (k + 1) % m
    segs = len(master) - 1
    if segs < 2:                                 # espelho degeneraria (N < 4)
        return None, None
    mirrored = [mirror_point(p, axis, c) for p in reversed(master[1:-1])]
    new_nodes = master + mirrored                # N' = 2·segs, nós 0 e segs no eixo
    nn = len(new_nodes)
    new_lines = set()
    for t in range(segs):
        if (start + t) % m in lines2:
            new_lines.add(t)                     # reta do mestre…
            new_lines.add(nn - 1 - t)            # …e o espelho dela
    return new_nodes, new_lines


def translate_nodes(nodes, dxy):
    """Modo Pan: translação 2D pura dos nós (mm). Devolve NOVA lista. Deslocar todos
    os nós E o eixo de simetria pelo mesmo passo preserva o pareamento — por isso o
    Pan, ao contrário do Rotate, NÃO desliga a simetria."""
    dx, dy = float(dxy[0]), float(dxy[1])
    if dx == 0.0 and dy == 0.0:
        return list(nodes)
    return [(x + dx, y + dy) for (x, y) in nodes]


def rotate_nodes(nodes, angle_deg, center):
    """F4: rotação 2D pura dos nós (mm) em torno de `center`. Devolve NOVA lista."""
    if angle_deg == 0.0:
        return list(nodes)
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = center
    return [(cx + (x - cx) * ca - (y - cy) * sa,
             cy + (x - cx) * sa + (y - cy) * ca) for (x, y) in nodes]


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

    Plano 011: **Symmetry** (F1) espelha cada edição no par por índice ((N−i)%N) em
    torno do eixo pontilhado — que é ARRASTÁVEL (F1b) e os botões **Mirror ◀/▶**
    reconstroem um lado como espelho do outro (constrói o pareamento p/ qualquer
    contorno). **Ruler** (F2) liga régua mm + cota W×H. **Rotate** (F4) entra no modo
    de giro fino (linha-guia no cursor; cliques/rodinha giram foto+nós juntos em
    passos de 0.1°/0.05°). **Pan** (gêmeo do Rotate) desloca o CONTORNO (nós + eixo
    de simetria juntos, foto parada) p/ esquerda/direita em passos de 0.1/0.05 mm —
    corrige viés lateral da detecção sem desligar a simetria.

    Modelo de coordenadas: mm (nós) → pixel-da-foto (mm_to_px) → pixel-de-TELA por uma
    transformada afim própria `tela = px·zoom + off` (não usa scrollregion do Canvas). O fundo
    é renderizado por RECORTE do VIEWPORT (só a parte visível é redimensionada/codificada),
    então o custo não explode com o zoom — o polimento pedido."""

    def __init__(self, root, rect, nodes0, mmpp_x, mmpp_y, symmetry="none", sym_c=None):
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
        self.history = []                   # pilha p/ Desfazer (snapshots do estado editável)
        self.result = None                  # (cúbicas, foto) ao Finalizar; None = cancelado
        self.zoom = 1.0
        self.off_x = 0.0                    # posição (px de tela) do pixel (0,0) da foto
        self.off_y = 0.0
        self.drag_idx = None
        self._pan = None                    # (x0, y0, off_x0, off_y0) durante o pan
        self._fitted = False               # 1º <Configure> ajusta a foto à janela
        self._photo = None                 # ref. viva do PhotoImage (evita GC)
        self._photo_xy = (0.0, 0.0)        # canto (nw) do fundo em px de tela
        self._notice = ""                  # aviso transitório mostrado no status

        # --- simetria (F1/F1b): eixo FIXO vindo da detecção (não recalculado dos nós,
        # senão edições moveriam a bbox e o eixo "andaria") -----------------------
        self.sym_axis = symmetry if symmetry in ("vertical", "horizontal") else "vertical"
        self.axis_locked = symmetry in ("vertical", "horizontal")   # orientação do CLI manda
        self.sym_c = sym_c                  # posição atual do eixo (mm); None = nunca posto
        self._sym_c0 = sym_c                # eixo ORIGINAL da detecção (p/ o Reset)
        self.paired_c = None                # eixo em torno do qual o pareamento VALE
        self._axis_drag = False
        # --- rotação manual (F4): giro acumulado da foto+nós (modo "Rotate") -----
        self.rot_deg = 0.0
        self.rot_center = None              # pivô (mm) fixado no 1º passo de giro
        self._rot_mode = False
        self._guide_y = None                # linha-guia horizontal (y de tela) no modo Rotate
        # --- pan manual (modo "Pan"): desloca o CONTORNO (nós + eixo de simetria)
        # com a FOTO PARADA — corrige viés lateral da detecção (sombra que empurrou
        # o contorno inteiro p/ um lado). O pareamento sobrevive por construção.
        self.pan_mm = 0.0                   # deslocamento x acumulado (mm), p/ o status
        self._pan_mode = False
        self._guide_x = None                # linha-guia vertical (x de tela) no modo Pan
        self._last_op = None                # coalesce do histórico ('rot'/'pan'/None)

        root.title("PtoO — node editor (Re-trace / Finalize)")
        bar = tk.Frame(root)
        bar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(bar, text="Re-trace", command=self.retrace).pack(side=tk.LEFT)
        tk.Button(bar, text="Undo", command=self.undo).pack(side=tk.LEFT)
        tk.Button(bar, text="Reset", command=self.reset).pack(side=tk.LEFT)
        tk.Button(bar, text="Line", command=self.make_line).pack(side=tk.LEFT)
        # simetria: toggle sempre habilitado (o Mirror CONSTRÓI o pareamento quando o
        # CLI não trouxe --symmetry); orientação V/H travada quando o CLI a definiu.
        self.sym_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Symmetry", variable=self.sym_var,
                       command=self.on_sym_toggle).pack(side=tk.LEFT, padx=(8, 0))
        self.axis_var = tk.StringVar(value="V" if self.sym_axis == "vertical" else "H")
        st = tk.NORMAL if not self.axis_locked else tk.DISABLED
        for lbl in ("V", "H"):
            tk.Radiobutton(bar, text=lbl, value=lbl, variable=self.axis_var,
                           command=self.on_axis_change, state=st).pack(side=tk.LEFT)
        self.mirror_lo = tk.Button(bar, text="Mirror ◀", command=lambda: self.do_mirror("low"))
        self.mirror_hi = tk.Button(bar, text="Mirror ▶", command=lambda: self.do_mirror("high"))
        self.mirror_lo.pack(side=tk.LEFT)
        self.mirror_hi.pack(side=tk.LEFT)
        # F2: régua mm + cota W×H (toggle p/ peças que ocupam o quadro inteiro)
        self.ruler_var = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="Ruler", variable=self.ruler_var,
                       command=lambda: self.redraw()).pack(side=tk.LEFT, padx=(8, 0))
        # F4: modo "Rotate" explícito (decisão b do plano 011 — sem conflito de binding)
        self.rot_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Rotate", variable=self.rot_var,
                       command=self.on_rot_toggle).pack(side=tk.LEFT)
        # Pan: mesmo funcionamento do Rotate (modo explícito, cliques/rodinha em
        # passos finos), mas DESLOCANDO o contorno (e a simetria junto) esq./dir.
        self.pan_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Pan", variable=self.pan_var,
                       command=self.on_pan_toggle).pack(side=tk.LEFT)
        tk.Button(bar, text="Finalize", command=self.finish).pack(side=tk.RIGHT)
        self.status = tk.Label(bar, text="", anchor="w")
        self.status.pack(side=tk.LEFT, padx=8)

        # Estado inicial da simetria: ON se o CLI pediu E o pareamento por índice se
        # verifica (symmetrize_beziers pode ter DESISTIDO — contorno cruzando o eixo
        # mais de 2×); OFF nos demais casos, com aviso do porquê.
        if symmetry == "both":
            self._notice = "symmetry 'both' not supported in the editor (phase 2)"
        elif self.axis_locked and sym_c is not None:
            if sym_check_pairing(self.nodes, self.sym_axis, sym_c):
                self.sym_var.set(True)
                self.paired_c = sym_c
            else:
                self._notice = ("symmetry requested but nodes are UNPAIRED — "
                                "turn Symmetry on and Mirror to rebuild")

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
        self.canvas.bind("<Motion>", self.on_motion)                     # linha-guia (Rotate)

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
        if self.rot_deg and self.rot_center is not None:
            # giro acumulado (F4): warpAffine DIRETO p/ o viewport — o custo é
            # proporcional à tela (cada pixel-destino amostra a foto), não ao zoom
            M = self._bg_affine(self.zoom, self.off_x, self.off_y)
            img = cv2.warpAffine(self.rect, M, (cw, ch), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(32, 32, 32))
            self._photo = self.tk.PhotoImage(data=P.encode_png_b64(img))
            self._photo_xy = (0.0, 0.0)
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
        # eixo de simetria (F1): linha PONTILHADA em coordenada de tela contínua
        # (sub-pixel, como as alças) — arrastável perpendicular a si (F1b)
        if self.sym_var.get() and self.sym_c is not None:
            cw, ch = c.winfo_width(), c.winfo_height()
            pos = self._axis_screen_pos()
            if pos is not None:
                if self.sym_axis == "vertical":
                    c.create_line(pos, 0, pos, ch, dash=(6, 4), fill="#ffd800", width=1)
                else:
                    c.create_line(0, pos, cw, pos, dash=(6, 4), fill="#ffd800", width=1)
        # alças dos nós (selecionadas p/ o Line: vermelhas)
        for i, pt in enumerate(self.nodes):
            sx, sy = self._mm_to_screen(pt)
            fill = "#ff4040" if i in self.sel else "#ffe000"
            c.create_oval(sx - HANDLE_R, sy - HANDLE_R, sx + HANDLE_R, sy + HANDLE_R,
                          fill=fill, outline="#000000", tags=f"node{i}")
        if self.ruler_var.get():                 # F2: régua mm + cota do objeto
            self._draw_ruler()
        if self._rot_mode and self._guide_y is not None:   # F4: linha-guia de nível
            c.create_line(0, self._guide_y, c.winfo_width(), self._guide_y,
                          dash=(8, 4), fill="#40c8ff", width=1)
        if self._pan_mode and self._guide_x is not None:   # Pan: guia vertical
            c.create_line(self._guide_x, 0, self._guide_x, c.winfo_height(),
                          dash=(8, 4), fill="#40c8ff", width=1)
        self._update_status()

    def _update_status(self):
        w, h = self._obj_size_mm()
        sym = "off"
        if self.sym_var.get():
            sym = ("V" if self.sym_axis == "vertical" else "H") + \
                  ("·paired" if self._sym_active() else "·unpaired")
        parts = [f"{len(self.nodes)} nodes · {len(self.lines)} lines · "
                 f"obj {w:.1f}×{h:.1f} mm · sym {sym}"]
        if self.rot_deg:
            parts.append(f"rot {self.rot_deg:+.2f}°")
        if self.pan_mm:
            parts.append(f"pan {self.pan_mm:+.2f} mm")
        parts.append(f"zoom {self.zoom:.2f}×")
        if self._rot_mode:
            parts.append("ROTATE: right-click=+0.1° · left-click=−0.1° · wheel=rotate "
                         "(Shift=0.05°) · toggle Rotate to exit")
        elif self._pan_mode:
            parts.append("PAN: right-click=+0.1mm → · left-click=−0.1mm ← · wheel=pan "
                         "(Shift=0.05mm) · outline+axis move, photo stays · toggle Pan to exit")
        else:
            parts.append("drag=move · click curve=insert · right-click=delete · "
                         "shift+click=select (2) then Line · wheel=zoom · Ctrl+drag=pan")
        if self._notice:
            parts.insert(0, self._notice.upper())
        self.status.config(text=" · ".join(parts))

    def _obj_size_mm(self):
        """Tamanho do objeto (mm) = bbox da curva EXIBIDA (achatada) — F2."""
        flat = P.flatten_beziers(self.cubics) if self.cubics else self.nodes
        if not flat:
            return 0.0, 0.0
        return P.size(flat)

    def _push_history(self):
        self.history.append((list(self.nodes), set(self.lines), self.sym_c,
                             self.paired_c, self.rot_deg, self.rot_center, self.pan_mm))
        if len(self.history) > 100:
            self.history.pop(0)
        self._last_op = None

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

    # --- simetria: estado ativo + eixo ----------------------------------------
    def _sym_active(self):
        """Ops espelhadas SÓ com o toggle ON, eixo posicionado E pareamento válido em
        torno do eixo ATUAL (eixo arrastado sem Mirror = ops livres até re-parear)."""
        return (self.sym_var.get() and self.sym_c is not None
                and self.paired_c == self.sym_c
                and sym_check_pairing(self.nodes, self.sym_axis, self.sym_c))

    def _default_axis_c(self):
        """Eixo inicial p/ 'ligar do zero' = centro da bbox da CURVA ATUAL."""
        pts = self.nodes or [(0.0, 0.0)]
        k = 0 if self.sym_axis == "vertical" else 1
        vs = [p[k] for p in pts]
        return 0.5 * (min(vs) + max(vs))

    def _axis_screen_pos(self):
        """Coordenada de TELA (x p/ eixo vertical, y p/ horizontal) da linha do eixo."""
        if self.sym_c is None:
            return None
        if self.sym_axis == "vertical":
            return self._mm_to_screen((self.sym_c, 0.0))[0]
        return self._mm_to_screen((0.0, self.sym_c))[1]

    def on_sym_toggle(self):
        if self.sym_var.get():
            if self.sym_c is None:
                self.sym_c = self._default_axis_c()
            if sym_check_pairing(self.nodes, self.sym_axis, self.sym_c):
                self.paired_c = self.sym_c
                self._notice = ""
            else:                                # ligar sem pareamento: fluxo "do zero"
                self._notice = ("position the axis (drag the dashed line), then "
                                "Mirror ◀/▶ to build the pairing")
        else:
            self._notice = ""                    # edições viram livres; religar = fluxo acima
        self.redraw()

    def on_axis_change(self):
        self.sym_axis = "vertical" if self.axis_var.get() == "V" else "horizontal"
        v = self.sym_axis == "vertical"
        self.mirror_lo.config(text="Mirror ◀" if v else "Mirror ▼")
        self.mirror_hi.config(text="Mirror ▶" if v else "Mirror ▲")
        if self.sym_var.get():
            self.sym_c = self._default_axis_c()
            self.paired_c = self.sym_c if sym_check_pairing(
                self.nodes, self.sym_axis, self.sym_c) else None
        self.redraw()

    def do_mirror(self, keep):
        """F1b: reconstrói um lado como espelho do OUTRO em torno do eixo atual —
        constrói o pareamento a partir de QUALQUER contorno (inclusive religando a
        simetria após edições livres)."""
        if not self.sym_var.get():
            self._notice = "Mirror: turn Symmetry on first"
            self.redraw()
            return
        if self.sym_c is None:
            self.sym_c = self._default_axis_c()
        self._push_history()
        nodes = self.nodes
        if (self.paired_c is not None and self.paired_c != self.sym_c
                and sym_check_pairing(nodes, self.sym_axis, self.paired_c)):
            # eixo movido com pareamento ainda válido: encosta as emendas no eixo novo
            # ANTES do espelho (senão haveria um degrau de 2(c'−c) na emenda)
            nodes = snap_seam_nodes(nodes, self.sym_axis, self.paired_c, self.sym_c)
        new_nodes, new_lines = mirror_contour(nodes, self.lines, self.sym_axis,
                                              self.sym_c, keep=keep)
        if new_nodes is None:                    # mesma limitação/critério do CLI
            self.history.pop()
            self._notice = "Mirror refused: contour crosses the axis more than twice"
            self.redraw()
            return
        self.nodes, self.lines, self.sel = new_nodes, new_lines, []
        self.paired_c = self.sym_c
        self._notice = ""
        self.retrace()

    def on_press(self, e):
        if self._rot_mode:                       # F4: clique-esquerdo = girar −passo
            self._rot_step(-0.1)
            return
        if self._pan_mode:                       # Pan: clique-esquerdo = esquerda
            self._pan_step(-0.1)
            return
        mm = self._screen_to_mm(e.x, e.y)
        i = nearest_node(self.nodes, mm, max_dist=self._hit_tol_mm())
        if i is not None:
            self._push_history()
            self.drag_idx = i
            return
        # linha do eixo (F1b): arrastável, perpendicular a si — NÃO mexe nos nós
        if self.sym_var.get() and self.sym_c is not None:
            pos = self._axis_screen_pos()
            d = abs(e.x - pos) if self.sym_axis == "vertical" else abs(e.y - pos)
            if d <= HIT_TOL:
                self._push_history()
                self._axis_drag = True
                return
        j = nearest_segment(self.nodes, mm)      # clique fora de alça = inserir no trecho
        if j is not None:
            self._push_history()
            if self._sym_active():
                self.nodes, self.lines = insert_node_sym(self.nodes, self.lines, j, mm,
                                                         self.sym_axis, self.sym_c)
            else:
                self.nodes = insert_node(self.nodes, j, mm)
                self.lines = remap_lines_insert(self.lines, j)
            self.sel = []                        # índices mudaram: seleção caduca
            self.retrace()                       # curva na tela segue os nós (WYSIWYG)

    def on_drag(self, e):
        if self._axis_drag:
            mm = self._screen_to_mm(e.x, e.y)
            self.sym_c = mm[0] if self.sym_axis == "vertical" else mm[1]
            self.redraw()                        # a cota W×H acompanha (sinergia F1b×F2)
            return
        if self.drag_idx is not None:
            mm = self._screen_to_mm(e.x, e.y)
            if self._sym_active():
                self.nodes = move_node_sym(self.nodes, self.drag_idx, mm,
                                           self.sym_axis, self.sym_c)
            else:
                self.nodes = move_node(self.nodes, self.drag_idx, mm)
            self.redraw()                        # alça segue o mouse; curva atualiza ao soltar

    def on_release(self, _e):
        if self._axis_drag:
            self._axis_drag = False
            if self.paired_c is not None and self.paired_c != self.sym_c:
                self._notice = "axis moved — Mirror ◀/▶ to re-pair around it"
            self.redraw()
            return
        if self.drag_idx is not None:
            self.drag_idx = None
            self.retrace()                       # re-traça a curva pelos nós na posição final

    def on_right(self, e):
        if self._rot_mode:                       # F4: clique-direito = girar +passo
            self._rot_step(+0.1)
            return
        if self._pan_mode:                       # Pan: clique-direito = direita
            self._pan_step(+0.1)
            return
        mm = self._screen_to_mm(e.x, e.y)
        i = nearest_node(self.nodes, mm, max_dist=self._hit_tol_mm())
        if i is None or len(self.nodes) <= 3:    # delete guarda o mínimo de 3
            return
        self._push_history()
        if self._sym_active():
            self.nodes, self.lines = delete_node_sym(self.nodes, self.lines, i,
                                                     self.sym_axis, self.sym_c)
        else:
            self.lines = remap_lines_delete(self.lines, i, len(self.nodes))
            self.nodes = delete_node(self.nodes, i)
        self.sel = []                            # índices mudaram: seleção caduca
        self.retrace()                           # curva na tela segue os nós (WYSIWYG)

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
        do caminho mais curto e marca o trecho como RETO (ver straighten_between).
        Com simetria ativa, aplica DOS DOIS LADOS (straighten_between_sym)."""
        if len(self.sel) != 2:
            self.status.config(text="Line: shift+click TWO nodes first")
            return
        self._push_history()
        if self._sym_active():
            nodes, lines, seg = straighten_between_sym(self.nodes, self.lines,
                                                       *self.sel, self.sym_axis, self.sym_c)
        else:
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
        if self._rot_mode or self._pan_mode:     # nos modos finos a rodinha gira/desloca
            fine = 0.05 if (getattr(e, "state", 0) & 0x0001) else 0.1   # Shift = fino
            step = fine if up else -fine
            (self._rot_step if self._rot_mode else self._pan_step)(step)
            return
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

    # --- rotação manual fina (F4, modo explícito — decisão b do plano 011) -----
    def on_rot_toggle(self):
        self._rot_mode = self.rot_var.get()
        self._guide_y = None
        if self._rot_mode and self._pan_mode:    # modos exclusivos: um por vez
            self.pan_var.set(False)
            self._pan_mode = False
            self._guide_x = None
        if self._rot_mode and self.sym_var.get():
            # girar quebra o eixo v/h (v1): desliga a simetria com aviso — p/ peça
            # torta COM simetria prefira `--level` no CLI (nivela ANTES da simetria)
            self.sym_var.set(False)
            self._notice = "symmetry turned OFF (rotation breaks the v/h axis) — prefer --level"
        self.redraw()

    # --- pan manual fino (modo explícito, gêmeo do Rotate) ---------------------
    def on_pan_toggle(self):
        self._pan_mode = self.pan_var.get()
        self._guide_x = None
        if self._pan_mode and self._rot_mode:    # modos exclusivos: um por vez
            self.rot_var.set(False)
            self._rot_mode = False
            self._guide_y = None
        # ao contrário do Rotate, o Pan NÃO desliga a simetria: o eixo desloca JUNTO
        # com os nós e o pareamento sobrevive por construção (translate_nodes).
        self.redraw()

    def on_motion(self, e):
        if self._rot_mode:                       # linha-guia horizontal segue o cursor
            self._guide_y = e.y
            self.redraw()
        elif self._pan_mode:                     # linha-guia vertical (deslocamento é em x)
            self._guide_x = e.x
            self.redraw()

    def _coalesce_history(self, op):
        """Histórico coalescido dos modos de passo fino (Rotate/Pan): um bloco de
        passos SEGUIDOS do mesmo modo empilha UM snapshot só (1 Undo desfaz o bloco)."""
        if self._last_op != op:
            self._push_history()
            self._last_op = op                   # _push_history zera; re-marca

    def _rot_step(self, step_deg):
        """Um passo de giro: nós giram no NÚCLEO (rotate_nodes) e a foto gira na VIEW
        (transformada afim, warpAffine só do viewport) — os dois em torno do MESMO
        pivô, fixado no 1º passo."""
        if self.rot_center is None:
            min_x, min_y, max_x, max_y = P.bbox(self.nodes)
            self.rot_center = (0.5 * (min_x + max_x), 0.5 * (min_y + max_y))
        self._coalesce_history("rot")
        self.nodes = rotate_nodes(self.nodes, step_deg, self.rot_center)
        self.rot_deg += step_deg
        self.cubics = cubics_through_nodes(self.nodes, self.lines)
        self._refresh()                          # fundo muda junto (foto gira)

    def _pan_step(self, dx_mm):
        """Um passo do modo Pan: desloca o CONTORNO inteiro (translate_nodes) e o
        eixo de simetria JUNTO — a foto fica parada (o deslocamento é visível e
        corrige viés lateral da detecção, ex.: sombra que empurrou o contorno p/ um
        lado). O pareamento sobrevive (nós e eixo andam o mesmo dx), simetria segue ON."""
        self._coalesce_history("pan")
        self.nodes = translate_nodes(self.nodes, (dx_mm, 0.0))
        self.pan_mm += dx_mm
        if self.sym_c is not None and self.sym_axis == "vertical":
            self.sym_c += dx_mm                  # o eixo acompanha o objeto
            if self.paired_c is not None:
                self.paired_c += dx_mm
        self.retrace()                           # foto parada: só o vetor redesenha

    def _bg_affine(self, scale, dx, dy):
        """Matriz 2×3 pixel-da-foto → destino, compondo o giro acumulado (F4) em torno
        do pivô com a transformada `dst = px·scale + (dx,dy)`. O giro dos NÓS é +φ em
        mm (Y p/ cima); no referencial do pixel (Y p/ baixo) isso é K = D·R(φ)·D⁻¹ com
        D = diag(1/mmpp_x, −1/mmpp_y) — anisotropia incluída (mmpp_x ≠ mmpp_y)."""
        import numpy as np
        phi = math.radians(self.rot_deg)
        cphi, sphi = math.cos(phi), math.sin(phi)
        k01 = (self.mmpp_y / self.mmpp_x) * sphi
        k10 = -(self.mmpp_x / self.mmpp_y) * sphi
        pcx, pcy = mm_to_px(self.rot_center, self.mmpp_x, self.mmpp_y)
        # dst = scale·(K·(p − pc) + pc) + (dx,dy)
        return np.array([
            [scale * cphi, scale * k01, scale * (pcx - cphi * pcx - k01 * pcy) + dx],
            [scale * k10, scale * cphi, scale * (pcy - k10 * pcx - cphi * pcy) + dy]],
            np.float64)

    def _rotated_rect_full(self):
        """Foto INTEIRA girada pelo giro acumulado (p/ o overlay ao Finalizar)."""
        if not self.rot_deg or self.rot_center is None:
            return self.rect
        import cv2
        h, w = self.rect.shape[:2]
        return cv2.warpAffine(self.rect, self._bg_affine(1.0, 0.0, 0.0), (w, h),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    # --- régua mm + cota do objeto (F2, só view) -------------------------------
    def _draw_ruler(self):
        c = self.canvas
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 2 or ch < 2:
            return
        band = 18                                # faixa (px de tela) nas bordas sup./esq.
        px_per_mm = self.zoom / self.mmpp_x      # escala de tela (giro preserva escala)
        # espaçamento ADAPTATIVO: menor tick com ≥ ~8 px; rótulo no múltiplo "redondo"
        minor = next((s for s in (1, 5, 10, 20, 50) if s * px_per_mm >= 8.0), 100)
        label = next((s for s in (10, 20, 50, 100) if s >= minor and s * px_per_mm >= 40.0), 200)
        c.create_rectangle(0, 0, cw, band, fill="#202020", stipple="gray50", outline="")
        c.create_rectangle(0, band, band, ch, fill="#202020", stipple="gray50", outline="")
        # mm visíveis: as réguas medem o referencial mm da foto retificada
        x0mm = self._screen_to_mm(0, 0)[0]
        x1mm = self._screen_to_mm(cw, 0)[0]
        y1mm = self._screen_to_mm(0, 0)[1]       # topo da tela = y mm MAIOR (Y p/ cima)
        y0mm = self._screen_to_mm(0, ch)[1]
        for v in range(int(math.floor(x0mm / minor)) * minor,
                       int(math.ceil(x1mm)) + minor, minor):
            sx = self._mm_to_screen((float(v), 0.0))[0]
            major = v % label == 0
            c.create_line(sx, band, sx, band - (10 if major else 5), fill="#e0e0e0")
            if major:
                c.create_text(sx + 2, 2, text=str(v), anchor="nw",
                              fill="#e0e0e0", font=("TkDefaultFont", 7))
        for v in range(int(math.floor(y0mm / minor)) * minor,
                       int(math.ceil(y1mm)) + minor, minor):
            sy = self._mm_to_screen((0.0, float(v)))[1]
            major = v % label == 0
            c.create_line(band, sy, band - (10 if major else 5), sy, fill="#e0e0e0")
            if major:
                c.create_text(2, sy + 2, text=str(-v), anchor="nw",   # mm positivos p/ baixo
                              fill="#e0e0e0", font=("TkDefaultFont", 7))
        # cota W×H fora da bbox do objeto (setas ↔ abaixo e à direita)
        if not self.cubics:
            return
        flat = P.flatten_beziers(self.cubics)
        min_x, min_y, max_x, max_y = P.bbox(flat)
        w, h = max_x - min_x, max_y - min_y
        gap = 14
        x0, y0 = self._mm_to_screen((min_x, min_y))   # min_y (mm) = base = y de tela MAIOR
        x1, y1 = self._mm_to_screen((max_x, max_y))
        c.create_line(x0, y0 + gap, x1, y0 + gap, arrow="both", fill="#40ff80")
        c.create_text(0.5 * (x0 + x1), y0 + gap + 4, text=f"{w:.1f} mm", anchor="n",
                      fill="#40ff80", font=("TkDefaultFont", 8))
        c.create_line(x1 + gap, y0, x1 + gap, y1, arrow="both", fill="#40ff80")
        c.create_text(x1 + gap + 4, 0.5 * (y0 + y1), text=f"{h:.1f} mm", anchor="w",
                      fill="#40ff80", font=("TkDefaultFont", 8))

    # --- botões --------------------------------------------------------------
    def retrace(self):                           # traça a curva G1 pelos nós (retas incl.)
        self.cubics = cubics_through_nodes(self.nodes, self.lines)
        self.redraw()

    def undo(self):
        if self.history:
            (self.nodes, self.lines, self.sym_c, self.paired_c,
             rot, self.rot_center, self.pan_mm) = self.history.pop()
            self.sel = []
            self._last_op = None
            if rot != self.rot_deg:              # giro desfeito: o fundo muda junto
                self.rot_deg = rot
                self._render_bg()
            self.retrace()

    def reset(self):
        self._push_history()
        self.nodes = list(self.nodes0)
        self.lines = set()                       # retas manuais também voltam ao zero
        self.sel = []
        self.pan_mm = 0.0                        # Reset zera o pan e devolve o eixo
        self.sym_c = self._sym_c0                # ORIGINAL da detecção (pan/arrasto fora)
        if self.sym_var.get() and self.sym_c is None:
            self.sym_c = self._default_axis_c()  # simetria ligada sem eixo do CLI
        self.paired_c = self.sym_c if (self.sym_c is not None and sym_check_pairing(
            self.nodes, self.sym_axis, self.sym_c)) else None
        if self.rot_deg:                         # Reset zera também o ângulo (F4)
            self.rot_deg = 0.0
            self.rot_center = None
            self._render_bg()
        self.retrace()

    def finish(self):
        # WYSIWYG: grava EXATAMENTE a curva que está na tela (o último Re-traçar), sem
        # recalcular — e a FOTO com o mesmo giro acumulado (F4), p/ o overlay casar.
        self.result = (self.cubics, self._rotated_rect_full())
        self.root.destroy()


def run_editor(rect, nodes0, mmpp_x, mmpp_y, symmetry="none", sym_c=None):
    """Abre o editor e BLOQUEIA até o usuário Finalizar ou fechar a janela. Devolve
    `(cúbicas, foto)` ao Finalizar — as cúbicas EXATAMENTE como exibidas (Catmull-Rom
    G1 pelos nós, o mesmo do Re-traçar) e a foto retificada com o giro acumulado do
    modo Rotate (p/ o overlay continuar casado) — ou `None` se cancelado. `symmetry`/
    `sym_c` (F1): modo e eixo detectados pelo CLI — o editor NÃO recalcula o eixo."""
    import tkinter as tk
    root = tk.Tk()
    app = EditorApp(root, rect, nodes0, mmpp_x, mmpp_y, symmetry=symmetry, sym_c=sym_c)
    root.mainloop()
    return app.result
