#!/usr/bin/env python3
# =============================================================================
# photo_to_outline.py — foto do objeto → SVG de contorno em mm
# -----------------------------------------------------------------------------
# Recebe uma FOTO de um objeto apoiado sobre a BASE DE CALIBRAÇÃO impressa
# (moldura de marcadores ArUco + miolo branco — gerada por make_calibration_target
# → base.svg) e emite um SVG em MILÍMETROS — contorno + preenchimento translúcido
# numa cor destacada (sobrepõe o objeto p/ conferir cobertura) — com o contorno EXTERNO
# da peça, corrigido de perspectiva/inclinação pelos
# marcadores e SUAVIZADO para impressão 3D (sem cantos de 90°, sem bicos afiados).
# Objetivo final: traçar objetos para gerar gridfinity personalizável (a cavidade
# onde a peça encaixa); o fluxo aqui termina no SVG.
#
# Pipeline (5 estágios): rectify (homografia ArUco → miolo branco em mm) →
# segment_tool (objeto sobre branco) → [symmetrize_mask, opcional] → extract_outline
# → process_for_print → polygon_to_svg. O estágio de simetria (--symmetry) espelha a
# máscara e tira a MÉDIA das duas metades (duas amostras do mesmo contorno → menos
# ruído) quando o objeto é simétrico. Funções puras de polígono/escala ficam separadas da I/O para
# serem testáveis sem imagem (tests/). A GEOMETRIA da base vem de
# calibration_target.py (fonte única, compartilhada com o renderizador do alvo).
#
# Roda no venv isolado .venv (numpy + opencv-python). Uso:
#   .venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg
# (imprima base.svg em A4 a 100%, apoie a peça no centro branco e
#  fotografe de cima — o mais próximo do nadir, mirando pelo anel-guia.)
# =============================================================================

import argparse
import base64
import json
import math
import os
import sys
from xml.sax.saxutils import escape as _xml_escape

import numpy as np

try:
    import cv2
except ImportError:  # mensagem amigável fora do venv
    print("ERRO: opencv ausente. Use o Python do venv: .venv/Scripts/python", file=sys.stderr)
    raise

import calibration_target as CT

# Console do Windows costuma ser cp1252 — força UTF-8 para "→", "·" etc.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# -----------------------------------------------------------------------------
# Constantes / defaults (ver docs/design.md)
# -----------------------------------------------------------------------------
PX_PER_MM = 8.0            # resolução do canvas métrico retificado (px/mm)
DICT_NAME = "DICT_4X4_50"  # dicionário ArUco da base; DEVE casar com a impressa
MIN_MARKERS = 8            # mínimo de marcadores detectados p/ homografia confiável
TILT_WARN_DEG = 5.0        # avisa se a câmera passou disto do nadir (paralaxe cresce)
SEG_SAT_MARGIN = 45        # saturação ACIMA do fundo (branco) → pixel colorido = objeto
SEG_VAL_FRAC = 0.30        # DEFAULT do corte escuro (flag --val-frac): brilho ABAIXO de
                           # SEG_VAL_FRAC × fundo → pixel escuro = objeto. 0.30 (não 0.5): exclui
                           # a SOMBRA DE CONTATO (faixa fofa V≈90-130 na base da peça) mantendo o
                           # corpo preto real (V≈30-50) — sem ela o teste de escuro abocanhava a
                           # sombra e serrilhava a base. SUBA (~0.7-0.8) p/ capturar CORPOS
                           # CINZA-NEUTROS de baixo contraste (V≈0.6-0.7·fundo, sem croma p/ os
                           # outros predicados); aí pareie com --mask-smooth-mm e atente que a
                           # sombra de contato pode vazar. Ver docs/historico.md (v0.5).
SEG_VAL_WEAK_FRAC = 0.65   # corte FRACO da histerese de borda (--shadow): V abaixo disto (não é
                           # papel claro) E com croma continua sendo objeto. Cresce a borda
                           # arredondada (bisel preto no topo, toe laranja no fundo) pela rampa até
                           # parar, recuperando a borda real que o corte único deixava comida/serrilhada.
SEG_WEAK_SAT_MIN = 35      # piso de SATURAÇÃO do corte fraco da histerese: o plástico real (tanto o
                           # bisel preto do topo quanto o toe laranja do fundo) tem CROMA (S≈40-85); a
                           # SOMBRA DE CONTATO é cinza DESATURADA (S≈25). Exigir S ≥ isto faz a histerese
                           # crescer pela borda dos DOIS lados (recupera a borda real) SEM inundar a
                           # sombra cinza da base — que só deixaria o pocket frouxo. Separa os dois.
SEG_SHADOW_GROW_MM = 3.0   # alcance MÁX. do crescimento da histerese a partir dos núcleos (preto+colorido).
                           # Limitado (dilatação geodésica) p/ cobrir a RAMPA da borda; com o piso
                           # de saturação (SEG_WEAK_SAT_MIN) o crescimento é AUTO-LIMITADO — para no
                           # papel claro e não entra na sombra cinza, então 3 mm cobre a borda dos dois
                           # lados sem risco de inflar (medido: topo +2.6 mm preto, fundo +0.4 mm toe).
SEG_TEX_WIN = 9            # janela (px) do DESVIO-PADRÃO local de V que mede TEXTURA no modo
                           # `--shadow texture` (a peça é texturizada; sombra/papel são lisos).
SEG_TEX_GAIN = 6.0         # escala do mapa de textura (std→0..255) antes do Otsu; só normaliza
                           # o histograma p/ o limiar adaptativo, não muda a separação.
SEG_TEX_BG_FRAC = 0.93     # o Otsu do limiar de textura roda SÓ sobre o que não é papel claro
                           # (V < frac·fundo), p/ o histograma não ser dominado pelo oceano liso.
SEG_TEX_BODY_FRAC = 0.80   # corte de VALOR do corpo no modo textura: V ≤ frac·fundo = candidato a
                           # corpo (cinza-neutro escuro, INCLUSIVE o liso que a textura perderia).
SEG_TEX_LIGHT_FRAC = 0.70  # a sombra PROJETADA é LISA e mais clara que isto·fundo (~0.8-0.9): o
                           # recorte tira do corpo só o que é (liso E mais claro) → rejeita a sombra
                           # sem comer o corpo escuro. (Sombra de CONTATO é escura → fora deste termo;
                           # pendência da v0.5, ver docs/historico.md.)
SEG_WS_ERODE_MM = 2.0      # erosão da máscara p/ virar marcador FG do watershed de refino de borda:
                           # o miolo é peça certa; a casca de ±band vira zona incerta onde a fronteira
                           # é re-decidida pelo GRADIENTE (a borda física é degrau; a sombra é rampa).
SEG_WS_BAND_MM = 3.0       # dilatação da máscara: fora disto = fundo certo (marcador BG).
SEG_WS_FG_VAL_FRAC = 0.50  # tira do marcador FG o que é LISO e mais claro que isto·fundo — a UMBRA
                           # (sombra escura, V≈0.55-0.70·fundo) que o recorte por brilho deixa passar;
                           # ela fica na zona incerta e o watershed a devolve ao fundo (a inundação
                           # do papel entra pela rampa suave; a da peça esbarra no degrau da borda).
ILLUM_SCALE = 0.125        # escala reduzida p/ estimar o campo de luz (só velocidade)
ILLUM_KERNEL_FRAC = 0.9    # kernel do closing ≈ fração do maior lado; DEVE cobrir o objeto
ILLUM_MAX_GAIN = 3.0       # teto do ganho da divisão (não amplifica ruído/JPEG nas zonas escuras)
SEG_HUE_MARGIN = 25        # |matiz − matiz_do_fundo| (unid. OpenCV, ½°) acima disto = pixel cromático
SEG_HUE_SAT_MIN = 60       # saturação mínima p/ aceitar um pixel SÓ pelo matiz (acima do ruído do fundo).
                           # Recupera a BORDA LARANJA arredondada com brilho (highlight) que baixa a
                           # saturação abaixo do corte de `colored` mas continua com matiz quente,
                           # bem longe do fundo azulado — sem isso o realce virava uma "mossa".
SYM_SEARCH_MM = 4.0         # busca do eixo de simetria em torno do centroide (± mm), maximizando IoU
LEVEL_MIN_DEG = 0.2         # --level (F3): desvio MÍNIMO p/ aplicar a correção — abaixo disto a
                            # peça já está nivelada e girar só degradaria a foto (INTER_LINEAR);
                            # garante saída IDÊNTICA ao baseline no que já está no nível.
LEVEL_MAX_DEG = 7.0         # --level: teto da correção FINA. A foto deve vir "o mais no nível
                            # possível"; acima disto a inclinação não é acidente de apoio — warn
                            # e segue sem girar (reposicione a peça em vez de confiar no giro).
LEVEL_ASPECT_MIN = 1.05     # --level: razão de aspecto do minAreaRect abaixo disto = peça
                            # ~quadrada/redonda → envelope instável (num disco o ângulo é ruído).
                            # Só corrige se uma RETA longa do contorno confirmar que há aresta.
LEVEL_LINE_MIN_MM = 8.0     # --level: comprimento mínimo (mm) da reta "alinhável" que resgata a
                            # peça ~quadrada da guarda acima (quadrado tem aresta; disco não).
FUSE_SEARCH_MM = 10.0       # registro da fusão 2-fotos (--in2): busca de TRANSLAÇÃO (± mm) entre as
                            # duas máscaras retificadas — absorve tanto o resíduo de retificação
                            # (papel flexionado) quanto o reposicionamento manual da peça entre as
                            # fotos. Score = IoU × concordância de TEXTURA (ZNCC): a silhueta sozinha
                            # é ambígua (sombra∩sombra infla a rotação errada em peça retangular).
FUSE_ANGLE_DEG = 4          # refino de ROTAÇÃO (± graus, passo 1°) em torno do melhor quarto de volta:
                            # além dos quartos {0,90,180,270}° (girar a peça/papel p/ mudar a luz é o
                            # protocolo típico), a mão não acerta o ângulo exato — o refino absorve.
FUSE_MIN_LOBE_MM = 2.0      # fusão direcional: lado mínimo (mm) do lóbulo de discordância p/ ele
                            # contar como SOMBRA de uma foto (lóbulo = pixels presentes numa máscara
                            # só). Abaixo disso não há sombra a resolver → cai no AND puro.
FUSE_ALIGN_MAX = 0.7        # fusão direcional: se as direções de sombra das duas fotos apontam p/
                            # o MESMO lado (cosseno acima disto), a luz mudou pouco — a regra por
                            # pixel degrada p/ ~AND sozinha, mas AVISA p/ refotografar melhor.
FUSE_FAINT_SAT_MARGIN = 10  # predicado "metal apagado" (SÓ no modo 2 fotos): S ≥ fundo+margem, bem
                            # abaixo de SEG_SAT_MARGIN. Metal claro liso (topo de conector) tem V ≈
                            # papel e S fraco (~18-31 vs ~8 do papel) — invisível aos predicados
                            # normais. O corte baixo TAMBÉM pega a sombra (S~25), o que o torna
                            # proibitivo em foto única; com --in2 a fusão direcional REMOVE a sombra,
                            # então a captação agressiva é segura e o metal entra na máscara.
FUSE_FAINT_VAL_MAX = 1.05   # teto de V do predicado acima (× fundo): exclui papel estourado/reflexo
FUSE_GROW_MM = 0.0          # pós-AND opcional (--fuse-grow): cresce a interseção GEODESICAMENTE de
                            # volta p/ dentro da UNIÃO das duas máscaras, até este raio. Recupera o que
                            # a PARALAXE comeu (peça ALTA + câmera em posição diferente nas duas fotos →
                            # as projeções não coincidem e o AND rói conectores/bordas elevadas), ao
                            # custo de readmitir até este raio de sombra ONDE ela encosta na peça.
                            # 0 = desligado. Antes de subir isto, prefira consertar o PROTOCOLO: girar
                            # base+peça JUNTAS e fotografar do lado oposto com o MESMO enquadramento
                            # relativo à base (mesma geometria câmera-peça → paralaxe idêntica → AND
                            # exato); aí o grow é desnecessário.
MASK_SMOOTH_MM = 0.0        # regularização da SILHUETA (raio mm): borra o campo de distância com
                            # sinal e re-corta em 0, removendo saliências/ondulações de amplitude
                            # < este valor na borda da MÁSCARA (típicas na carcaça PRETA, de baixo
                            # contraste) sem arredondar os cantos macro. 0 = desligado. Ortogonal
                            # ao SMOOTH_MM (que age na curva); aqui a forma é limpa na FONTE.
MIN_RADIUS_MM = 1.5
SMOOTH_MM = 8.0             # janela do low-pass que remove o serrilhado (≪ features reais)
CLEARANCE_MM = 0.0          # ETAPA 1 SEM GANHO: contorno no tamanho REAL; a folga é aplicada
                            # depois (a jusante no OpenSCAD/gridfinity, ou escalando à mão).
FIT_TOL_MM = 0.2            # tolerância do ajuste de Bézier (Schneider): passa pela média
BEZIER_GUIDE_MM = 0.5      # folga do guia p/ o ajuste (contém a peça; bbox depois é fixada ao objeto)
CORNER_ANGLE_DEG = 40.0    # ângulo p/ marcar um canto (nó cusp entre curvas suaves)
ANCHOR_SIMPLIFY_MM = 2.0   # RDP do fecho convexo: MAIOR = menos âncoras/nós (mais "hull"),
                            # MENOR = mais âncoras = contorno mais justo (porém mais nós)
ANCHOR_EPS_MM = 0.08       # penetração máx. (mm) tolerada no piso ao ajustar cada trecho (modo fiel)
POCKET_EPS_MM = 0.5        # penetração tolerada (mm) no modo POCKET de encaixe: a curva pode
                            # TOCAR/cortar de leve a peça em vez de estufar p/ fora a span inteira
                            # por ruído sub-mm → pocket bem mais justo, ainda contendo ~0.998
ANCHOR_HANDLE_CAP = 0.40   # teto do comprimento de cada handle = fração da corda do trecho. Acima
                           # da "regra de 1/3" (0.333), folgado p/ não engessar a curvatura útil,
                           # mas abaixo do ponto onde um handle longo demais faz a cúbica laçar
                           # sozinha (auto-cruzamento). Ver _cap_handles / _one_cubic_contained.
ANCHOR_MIN_DIST_MM = 10.0  # distância mínima (mm) entre âncoras DO MESMO QUADRANTE — a ÚNICA
                            # alavanca de densidade do pocket: cada quadrante recebe TODAS as
                            # extremidades a ≥ este valor umas das outras (sem teto de nós).
                            # MENOR = mais âncoras = pocket mais justo; MAIOR = menos = folgado
PROTRUSION_DEV_MM = 0.8    # proeminência mín. (mm) de uma SALIÊNCIA local p/ virar âncora forçada:
                            # o seletor radial por quadrante ancora os CANTOS (mais externos ao
                            # centro) e ignora ressaltos no MEIO de uma aresta (pega lateral etc.).
                            # Um pico convexo que se ergue ≥ este valor acima da vizinhança ganha
                            # âncora própria → a cúbica não arredonda por cima dele.
                            # Ver _protrusion_anchors.
CONTAIN_COVERAGE = 0.99    # encaixe mínimo p/ dar a peça por "contida"; abaixo disso, no modo
                            # pocket, o CLI avisa p/ diminuir --min-dist (adensa as âncoras)
MASK_SMOOTH_WARN_AREA_MM2 = 1.0  # área mínima (mm²) de uma saliência REMOVIDA pelo
                            # --mask-smooth-mm p/ disparar o aviso (junto com proeminência
                            # ≥ PROTRUSION_DEV_MM): abaixo disso é ruído de borda, que
                            # remover é justamente o trabalho da regularização.
CONTAIN_TOL_MM = 0.3        # tolerância de PROFUNDIDADE do `contém` (v0.6): medindo contra a
                            # silhueta de REFERÊNCIA crua (pré --mask-smooth-mm), a serrilha de
                            # ruído da segmentação fura o pocket em lascas rasas por todo o
                            # perímetro; penetração ≤ este valor não conta (é ruído de medição,
                            # coberto pelo --clearance a jusante) — um corte profundo (feature
                            # real perdida, ex.: gancho da trena) continua derrubando o gate.
PIN_FALLOFF_MM = 6.0        # meia-janela (mm de ARCO) da deformação de um PIN (v0.15): o
                            # vértice mais próximo do pin recebe o Δ inteiro (a curva passa
                            # EXATA por ele) e o Δ decai em cos² até zerar a esta distância
                            # ao longo do contorno — correção LOCAL (sombra num trecho) sem
                            # arrastar o resto da silhueta. Ver apply_pins.
HUMBLE_MIN_FIRM_FRAC = 0.5  # gatilho do modo AUTO do contorno HUMILDE (v0.12): fração da
                            # borda com apoio visual (gradiente) abaixo disto = "não existe
                            # borda clara em quase todo o objeto" → ativa o fallback de
                            # cordas entre trechos firmes. Ver humble_rewrite.
HUMBLE_GRAD_WIN_MM = 0.5    # janela de tolerância da FIRMEZA: a borda da máscara pode estar
                            # a ~meio mm do degrau real da foto — dilata |Sobel| por este
                            # raio antes de amostrar sob cada ponto do contorno.
HUMBLE_SLIVER_TEX_FRAC = 0.03  # guarda de LISURA do descarte: a lasca entre o vão original e
                            # a corda só é descartável se MENOS disto dos pixels têm gradiente
                            # acima do limiar (papel/sombra são lisos; peça real tem textura).
HUMBLE_SLIVER_MIN_MM2 = 4.0 # lasca menor que isto (mm²) é descartável SEM olhar a textura:
                            # pequena demais p/ conter feature real (e a fração seria ruidosa).
HUMBLE_MIN_GAP_MM = 10.0    # piso da SUBDIVISÃO: vão texturizado menor que isto não divide
                            # mais — mantém a borda original e FLAGRA p/ revisão no --edit.
HUMBLE_FIRM_CLOSE_MM = 1.0  # limpeza da classificação: buraco INCERTO < isto entre firmes
                            # fecha (vira firme) — evita retalhar um degrau real por ruído.
HUMBLE_FIRM_ISLAND_MM = 2.0 # ...e ilha FIRME < isto vira incerta (âncora de chatter não
                            # sustenta corda; melhor cair no vão vizinho).
HUMBLE_CHORD_STEP_MM = 1.0  # densificação das cordas (~1 ponto/mm): o resto do pipeline
                            # (low-pass, reamostragem, primitivas) espera contorno denso.
HUMBLE_GRAD_FLOOR = 8.0     # piso ABSOLUTO de |Sobel| do "apoio visual": abaixo disto (e de
                            # 4× a mediana global do gradiente) é ruído de papel/JPEG, não
                            # degrau. Borda sem NENHUM valor acima do piso = 0% firme (§9).
HUMBLE_GRAD_CAP = 3.0       # teto do limiar de firmeza = este fator × o piso: impede o Otsu
                            # de dividir uma borda TODA forte (thermpro: p5=51 ≫ papel ~6)
                            # e chamar a metade menos contrastada de incerta — acima de
                            # 3× o nível liso da foto já é degrau real, não halo.
SPIKE_MIN_RECEDE_MM = 0.3   # recuo mínimo (mm) da ponta pelo low-pass p/ um pico virar
                            # candidato a restauração (`_preserve_spikes`): abaixo disso o
                            # suavizado praticamente cobre o pico — restaurar só reinjetaria
                            # a serrilha crua (picos de ruído recuam ~0.1-0.2 mm).
SPIKE_MAX_WIDTH_MM = 3.0    # boca máxima (mm) da base de um ESPIGÃO restaurável: separa a
                            # protuberância fina real (gancho da trena, ~1-2 mm) dos CANTOS
                            # e curvaturas macro (boca ≫ 3 mm), cujo recuo é o arredondamento
                            # LEGÍTIMO do smooth-mm p/ impressão.
LINE_TOL_MM = 0.3           # detecção de RETAS no contorno (flag --line-tol): trecho maximal
                            # onde TODOS os pontos desviam < isto da corda vira UMA reta
                            # (cúbica degenerada, deslocada p/ fora pela contenção). 0 = desliga
                            # retas E arcos (caminho legado, só âncoras por quadrante). Ver
                            # _detect_line_runs / v0.10 "primitivas".
ARC_TOL_MM = 0.3            # detecção de ARCOS (flag --arc-tol): nos vãos entre retas, um
                            # círculo por mínimos quadrados com resíduo radial < isto (e
                            # varredura monótona) vira arco tangente (canto = filete). 0 =
                            # desliga só os arcos. Ver _detect_arc_runs.
LINE_MIN_MM = 5.0           # comprimento mínimo (mm) de uma reta detectável — abaixo disso o
                            # trecho fica p/ os arcos/âncoras (evita retalhar curvas em cordas)
ARC_MIN_MM = 2.5            # comprimento mínimo (mm) de arco detectável nos vãos
ARC_R_MIN_MM = 0.8          # faixa de raio plausível de um arco: abaixo é ruído de borda,
ARC_R_MAX_MM = 60.0         # acima é quase-reta (deixa p/ a reta/cúbica livre). Também VETA
                            # retas: trecho que um círculo nesta faixa ajusta melhor que a
                            # corda é arco, não reta (círculo grande não vira polígono).
PRIM_TRIM_MM = 0.8          # recuo (mm) das pontas de cada reta detectada: garante um vão
                            # curvo entre primitivas → a junção reta↔canto vira filete G1
                            # (mantém o invariante "todo nó suave") e tira a ponta da reta
                            # de dentro da curvatura do canto.
CORNER_RADIUS_MM = 0.0      # prior de RAIO de canto (flag --corner-radius, v0.13): > 0 = raio
                            # MEDIDO pelo usuário (via --describe da skill /ptoo). Arco
                            # detectado com raio na janela ±max(1 mm, 20%) é REFIT com raio
                            # FIXO (só o centro) — o canto sai com o raio declarado, não o
                            # estatístico. 0 = desligado. Ver _arc_check/_detect_arc_runs.
SHAPE_INFL_MAX_MM = 2.0     # teto (mm) da INFLAÇÃO por eixo p/ conter a peça no --shape:
                            # modelo que precisa crescer mais que isto não descreve a peça
                            # (descrição suspeita) → aviso e fallback p/ o caminho genérico.
SHAPE_GAP_MM = 5.0          # teto (mm) do VÃO modelo→peça no --shape: ponto do modelo mais
                            # longe que isto de qualquer ponto da silhueta = a peça não é o
                            # shape declarado (ex.: círculo "descrito" como retângulo) →
                            # aviso e fallback. Ver _fit_shape_rect.
RASTER_PPM = 16.0           # px/mm das operações raster (filete/IoU)
PEN_SAMPLE_MM = 0.25        # passo (mm) ao amostrar a cúbica p/ medir penetração no piso
OUTLINE_COLOR = "#ff00ff"      # cor BEM DESTACADA (magenta) do vetor de saída e do overlay
OUTLINE_FILL_OPACITY = 0.25    # preenchimento quase transparente: sobrepõe TODO o objeto p/ conferir
                               # de relance se o contorno o cobre (qualquer parte de fora = contorno curto)
SVG_HAIRLINE_MM = 0.264583     # traço fino do contorno = 1 px CSS (1/96") em mm (não-escalável)


class GridDetectionError(RuntimeError):
    """Confiança insuficiente na retificação (marcadores ArUco insuficientes)."""


def warn(msg):
    print(f"WARNING: {msg}", file=sys.stderr)


# =============================================================================
# FUNÇÕES PURAS DE POLÍGONO  (pts = list[(x,y)] ou ndarray Nx2, em mm)
# =============================================================================
def _xy(pts):
    """Normaliza para lista de tuplas float."""
    return [(float(p[0]), float(p[1])) for p in pts]


def signed_area(pts):
    """Área com sinal (shoelace): >0 = CCW (eixo Y para cima)."""
    p = _xy(pts)
    n = len(p)
    a = 0.0
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def polygon_area(pts):
    return abs(signed_area(pts))


def ensure_ccw(pts):
    p = _xy(pts)
    return p if signed_area(p) >= 0 else list(reversed(p))


def bbox(pts):
    p = _xy(pts)
    xs = [q[0] for q in p]
    ys = [q[1] for q in p]
    return (min(xs), min(ys), max(xs), max(ys))


def size(pts):
    min_x, min_y, max_x, max_y = bbox(pts)
    return (max_x - min_x, max_y - min_y)


def is_closed(pts, tol=1e-6):
    p = _xy(pts)
    if len(p) < 2:
        return False
    return abs(p[0][0] - p[-1][0]) < tol and abs(p[0][1] - p[-1][1]) < tol


def dedup_closing_point(pts, tol=1e-6):
    p = _xy(pts)
    return p[:-1] if (len(p) >= 2 and is_closed(p, tol)) else p


def close_polygon(pts):
    p = _xy(pts)
    return p if is_closed(p) else p + [p[0]]


def _dist_point_seg(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    dd = dx * dx + dy * dy
    if dd == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / dd
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def douglas_peucker(pts, eps):
    """Ramer–Douglas–Peucker numa polilinha ABERTA (mantém extremos)."""
    p = _xy(pts)
    if len(p) < 3:
        return p
    dmax, idx = 0.0, 0
    for i in range(1, len(p) - 1):
        d = _dist_point_seg(p[i], p[0], p[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = douglas_peucker(p[:idx + 1], eps)
        right = douglas_peucker(p[idx:], eps)
        return left[:-1] + right
    return [p[0], p[-1]]


def chaikin(pts, iterations, closed=True):
    """Corner-cutting de Chaikin (suaviza/arredonda cantos)."""
    p = _xy(pts)
    for _ in range(max(0, int(iterations))):
        out = []
        n = len(p)
        rng = range(n) if closed else range(n - 1)
        for i in rng:
            a = p[i]
            b = p[(i + 1) % n]
            q = (0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1])
            r = (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])
            out.extend((q, r))
        if not closed:
            out = [p[0]] + out + [p[-1]]
        p = out
    return p


def corner_angles(pts, closed=True):
    """Ângulo interno (graus) em cada vértice."""
    p = _xy(pts)
    n = len(p)
    out = []
    rng = range(n) if closed else range(1, n - 1)
    for i in rng:
        a = p[(i - 1) % n]
        b = p[i]
        c = p[(i + 1) % n]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        ang = math.degrees(math.atan2(abs(cross), dot))
        out.append(ang)
    return out


def _circumradius(a, b, c):
    """Raio do círculo por 3 pontos; colineares → inf."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    la = math.hypot(bx - cx, by - cy)
    lb = math.hypot(ax - cx, ay - cy)
    lc = math.hypot(ax - bx, ay - by)
    area2 = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))
    if area2 < 1e-12:
        return float("inf")
    return (la * lb * lc) / (2.0 * area2)


def corner_radii(pts, closed=True):
    """Raio osculador (círculo por vizinhos imediatos) em cada vértice."""
    p = _xy(pts)
    n = len(p)
    out = []
    rng = range(n) if closed else range(1, n - 1)
    for i in rng:
        out.append(_circumradius(p[(i - 1) % n], p[i], p[(i + 1) % n]))
    return out


def lowpass_closed(pts, win_mm, step=0.15):
    """Low-pass de um contorno fechado: reamostra uniforme e convolui x(s)/y(s)
    com janela de Hann (circular) de largura ~win_mm. Remove ripple de
    rasterização (sub-mm) preservando a curvatura macro."""
    rp = resample_uniform(pts, step, closed=True)
    n = len(rp)
    if n < 5 or win_mm <= step:
        return rp
    half = max(1, int(round((win_mm / step) / 2.0)))
    w = np.hanning(2 * half + 1)
    w = w / w.sum()
    xs = np.array([p[0] for p in rp])
    ys = np.array([p[1] for p in rp])
    xe = np.concatenate([xs[-half:], xs, xs[:half]])   # padding circular
    ye = np.concatenate([ys[-half:], ys, ys[:half]])
    xf = np.convolve(xe, w, mode="same")[half:half + n]
    yf = np.convolve(ye, w, mode="same")[half:half + n]
    return list(zip(xf.tolist(), yf.tolist()))


def _perimeter(pts, closed=True):
    p = _xy(pts)
    n = len(p)
    rng = range(n) if closed else range(n - 1)
    return sum(math.hypot(p[(i + 1) % n][0] - p[i][0], p[(i + 1) % n][1] - p[i][1]) for i in rng)


def resample_uniform(pts, step, closed=True):
    """Reamostra a poligonal em passos ~iguais de comprimento `step`."""
    p = _xy(pts)
    if len(p) < 2 or step <= 0:
        return p
    pts_loop = p + [p[0]] if closed else p
    out = [pts_loop[0]]
    acc = 0.0
    for i in range(len(pts_loop) - 1):
        a = pts_loop[i]
        b = pts_loop[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg == 0:
            continue
        while acc + seg >= step:
            t = (step - acc) / seg
            nx = a[0] + t * (b[0] - a[0])
            ny = a[1] + t * (b[1] - a[1])
            out.append((nx, ny))
            a = (nx, ny)
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            acc = 0.0
        acc += seg
    if closed and len(out) > 1:
        # remove ponto final coincidente com o inicial
        if math.hypot(out[-1][0] - out[0][0], out[-1][1] - out[0][1]) < step * 0.5:
            out.pop()
    return out


def min_corner_radius(pts, closed=True, sample_step=0.2, window=0.8):
    """Menor raio de curvatura ao longo do contorno, robusto e sem viés.

    Reamostra a passos uniformes (`sample_step` mm) e mede o circunraio com
    vizinhos afastados ~`window` mm (não os imediatos): 3 pontos sobre um arco de
    raio R dão circunraio R exato, mas o afastamento `window` evita o viés de
    subestimação do estimador de 3 pontos vizinhos sobre um contorno discretizado.
    """
    rp = resample_uniform(pts, sample_step, closed=closed)
    n = len(rp)
    if n < 5:
        return float("inf")
    k = max(1, int(round(window / (2.0 * sample_step))))
    best = float("inf")
    rng = range(n) if closed else range(k, n - k)
    for i in rng:
        a = rp[(i - k) % n]
        b = rp[i]
        c = rp[(i + k) % n]
        r = _circumradius(a, b, c)
        if r < best:
            best = r
    return best


# --- filete por morfologia raster: arredonda TODO canto ao raio mínimo --------
def _polys_to_mask(polys_px, w, h):
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [np.round(np.array(pp, np.float32)).astype(np.int32) for pp in polys_px], 255)
    return mask


def enforce_min_radius(pts, r_min, closed=True, clearance=0.0, ppm=RASTER_PPM):
    """Arredonda cantos a um raio mínimo `r_min` (mm) via abertura+fechamento
    morfológico com disco; opcional `clearance` (mm) dilata o contorno (folga do
    bolso). Garante curvatura mínima ~r_min em TODO canto convexo (inclui o bico).
    """
    p = ensure_ccw(dedup_closing_point(pts))
    if len(p) < 3 or r_min <= 0:
        return p
    min_x, min_y, max_x, max_y = bbox(p)
    pad_mm = r_min + clearance + 2.0
    ox, oy = min_x - pad_mm, min_y - pad_mm
    w = int(math.ceil((max_x - min_x + 2 * pad_mm) * ppm))
    h = int(math.ceil((max_y - min_y + 2 * pad_mm) * ppm))
    poly_px = [((x - ox) * ppm, (y - oy) * ppm) for (x, y) in p]
    mask = _polys_to_mask([poly_px], w, h)

    rr = max(1, int(round(r_min * ppm)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rr + 1, 2 * rr + 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)   # arredonda côncavos
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)    # arredonda convexos
    if clearance > 0:
        cr = max(1, int(round(clearance * ppm)))
        kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * cr + 1, 2 * cr + 1))
        mask = cv2.dilate(mask, kc)

    # Suaviza só o serrilhado de 1px (sigma fixo pequeno; NÃO erode o raio macro).
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=1.0)
    _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return p
    c = max(cnts, key=cv2.contourArea)
    out = [(float(pt[0][0]) / ppm + ox, float(pt[0][1]) / ppm + oy) for pt in c]
    # Low-pass (janela ~r_min) remove o ripple de rasterização preservando o raio
    # macro garantido pela abertura morfológica.
    out = lowpass_closed(out, win_mm=r_min, step=0.15)
    return ensure_ccw(out)


# =============================================================================
# ESCALA / HOMOGRAFIA / DETECÇÃO DOS MARCADORES ArUco
# =============================================================================
def px_per_mm(spacing_px, mm):
    """Utilitário de escala: px por mm dado um comprimento de `mm` em `spacing_px`."""
    return spacing_px / mm


def mm_per_px(spacing_px, mm):
    return mm / spacing_px


def homography_from_corners(src4, dst4):
    s = np.array(src4, np.float32)
    d = np.array(dst4, np.float32)
    return cv2.getPerspectiveTransform(s, d)


def apply_homography(H, pts):
    H = np.asarray(H, np.float64)
    out = []
    for x, y in _xy(pts):
        v = H @ np.array([x, y, 1.0])
        out.append((v[0] / v[2], v[1] / v[2]))
    return out


def detect_markers(gray, dict_name=DICT_NAME):
    """Detecta os marcadores ArUco da base. Devolve `(corners, ids)` onde `corners`
    é a lista de arrays (1×4×2) de cantos sub-pixel (ordem ArUco) e `ids` é a lista
    de IDs inteiros (vazia se nenhum)."""
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    det = cv2.aruco.ArucoDetector(dic, cv2.aruco.DetectorParameters())
    corners, ids, _rej = det.detectMarkers(gray)
    return list(corners), ([] if ids is None else [int(i) for i in ids.flatten()])


def aruco_correspondences(corners, ids, layout):
    """Casa os cantos DETECTADOS (px na imagem) com os cantos NOMINAIS (mm) de cada
    marcador, pelo ID — o contrato de `calibration_target.homography_correspondences`.
    Devolve `(img_pts Nx2, mm_pts Nx2)` em float32 (4 pontos por marcador casado)."""
    corr = dict(CT.homography_correspondences(layout))
    img_pts, mm_pts = [], []
    for c, i in zip(corners, ids):
        if i in corr:
            for (px, py), (mx, my) in zip(np.asarray(c).reshape(-1, 2), corr[i]):
                img_pts.append((float(px), float(py)))
                mm_pts.append((float(mx), float(my)))
    return np.array(img_pts, np.float32), np.array(mm_pts, np.float32)


def estimate_tilt_deg(H_mm2img, image_shape):
    """Inclinação (graus) entre o eixo da câmera e a NORMAL do papel, a partir da
    homografia mm→pixel `H_mm2img` — o INVERSO da imagem→mm que a retificação já
    resolveu (nada de um segundo RANSAC aqui) — decomposta com uma intrínseca
    APROXIMADA (foco ~1,2·lado maior — chute razoável p/ celular). Mede o quão longe
    do nadir a foto está; o valor é aproximado (não temos calibração da lente),
    serve de aviso de paralaxe. Devolve `nan` se não der p/ estimar."""
    if H_mm2img is None:
        return float("nan")
    h, w = image_shape[:2]
    f = 1.2 * max(h, w)
    K = np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1]], np.float64)
    B = np.linalg.inv(K) @ np.asarray(H_mm2img, np.float64)
    n0 = np.linalg.norm(B[:, 0])
    if n0 < 1e-12:                             # homografia degenerada
        return float("nan")
    lam = 1.0 / n0
    r0 = B[:, 0] * lam
    r1 = B[:, 1] * lam
    r2 = np.cross(r0, r1)
    U, _s, Vt = np.linalg.svd(np.column_stack([r0, r1, r2]))
    R = U @ Vt
    return float(math.degrees(math.acos(min(1.0, abs(R[2, 2])))))


# =============================================================================
# PIPELINE (I/O)
# =============================================================================
def load_image(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"não consegui ler a imagem: {path}")
    return img


def rectify(img, dict_name=DICT_NAME, ppmm=PX_PER_MM, layout=None, debug_dir=None):
    """Estágio 1: detecta a moldura ArUco da base, resolve a homografia imagem→mm
    e RETIFICA recortando o MIOLO BRANCO (onde está o objeto) para um canvas
    métrico de escala UNIFORME `ppmm` px/mm. Os marcadores e o anel-guia ficam de
    FORA do recorte → o segmentador vê só objeto sobre branco.

    A dimensão real do objeto sai daqui (px do canvas × 1/ppmm). `layout` é o layout
    do alvo (default = o padrão de calibration_target, que casa com a base.svg
    impressa nos defaults). Também estima a INCLINAÇÃO da foto vs o nadir e AVISA se
    passar de TILT_WARN_DEG (a paralaxe pela altura do objeto cresce com o ângulo).

    Devolve `(rectified, mm_per_px, mm_per_px, confidence)` (escala uniforme, X = Y);
    levanta `GridDetectionError` se faltarem marcadores p/ uma homografia confiável.
    """
    if layout is None:
        layout = CT.target_layout(dict_name=dict_name)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids = detect_markers(gray, layout["dict"])
    img_pts, mm_pts = aruco_correspondences(corners, ids, layout)
    n = len(img_pts) // 4
    if n < MIN_MARKERS:
        raise GridDetectionError(
            f"só {n} marcadores ArUco detectados (mínimo {MIN_MARKERS}) — confira a "
            f"base impressa (base.svg), o foco e a iluminação")
    H, _m = cv2.findHomography(img_pts, mm_pts, cv2.RANSAC, 3.0)   # imagem → mm
    if H is None:
        raise GridDetectionError("homografia ArUco falhou (marcadores degenerados)")

    # Aviso de inclinação (aproximado): longe do nadir = mais paralaxe pela altura.
    # Reusa o H imagem→mm já resolvido (invertido) em vez de um segundo RANSAC.
    try:
        tilt = estimate_tilt_deg(np.linalg.inv(H), gray.shape)
    except np.linalg.LinAlgError:
        tilt = float("nan")
    if not math.isnan(tilt) and tilt > TILT_WARN_DEG:
        warn(f"foto a ~{tilt:.0f}° do nadir (> {TILT_WARN_DEG:.0f}°): a altura do "
             f"objeto pode inflar o contorno — fotografe mais de cima.")

    # Canvas = miolo branco do alvo a `ppmm` px/mm. Compõe mm→px(canvas) ∘ imagem→mm.
    x0, y0, x1, y1 = layout["inner_rect"]
    S = np.array([[ppmm, 0, -x0 * ppmm], [0, ppmm, -y0 * ppmm], [0, 0, 1]], np.float64)
    Hc = S @ H
    out_w = int(round((x1 - x0) * ppmm))
    out_h = int(round((y1 - y0) * ppmm))
    rect = cv2.warpPerspective(img, Hc, (out_w, out_h), flags=cv2.INTER_LINEAR,
                               borderValue=(255, 255, 255))
    mmpp = 1.0 / ppmm
    conf = n / len(layout["markers"])
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "01_rectified.png"), rect)
    return rect, mmpp, mmpp, conf


def normalize_illumination(img, scale=ILLUM_SCALE, kernel_frac=ILLUM_KERNEL_FRAC,
                           max_gain=ILLUM_MAX_GAIN, debug_dir=None):
    """Estágio 1b (tratamento de luz / remoção de sombra) — entre rectify e segment.
    A sombra é um ESCURECIMENTO SUAVE e multiplicativo do papel branco. Estima-se o
    campo de luz L(x,y) por um CLOSING em escala-cinza com kernel MAIOR que o objeto
    (ele "pinta" a peça escura com o branco ao redor, sobrando só a iluminação),
    seguido de um borrão gaussiano; depois divide-se a imagem por L. O ganho é
    HUE-PRESERVING (mesmo fator nos 3 canais BGR) → o fundo branco fica uniforme e o
    halo de sombra é atenuado SEM mudar a cor da peça. Feito em escala reduzida
    (`scale`) por velocidade e reampliado. NÃO remove a sombra de CONTATO (faixa
    escura justo na base da peça, que é local e fica dentro da estimativa de L) —
    essa é tratada na segmentação (limiar de escuro)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ks = max(3, int(max(small.shape) * kernel_frac)) | 1
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks))
    L = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kern)     # remove o objeto escuro
    L = cv2.GaussianBlur(L, (0, 0), sigmaX=ks / 4.0)       # suaviza → campo de luz
    L = cv2.resize(L, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    L = np.maximum(L, 1.0)
    target = float(np.median(L))
    gain = np.clip(target / L, 0.0, max_gain)
    out = np.clip(img.astype(np.float32) * gain[:, :, None], 0.0, 255.0).astype(np.uint8)
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "01b_illumination.png"), L.astype(np.uint8))
        cv2.imwrite(os.path.join(debug_dir, "01b_flat.png"), out)
    return out


def _refine_edge_watershed(img, mask, Vd, smooth, bg_v):
    """Refino de borda do modo texture: re-decide a fronteira da máscara pelo GRADIENTE
    via watershed com marcadores. Motivo: o recorte de sombra por brilho (liso E mais
    claro que LIGHT·fundo) deixa passar a UMBRA — lisa mas ESCURA — que infla a silhueta
    (~4-5 mm medidos na trena cinza). O cue que separa de verdade é a nitidez: a borda
    física peça↔fundo é um DEGRAU de V; sombra→papel é RAMPA suave. Soltando a casca da
    máscara como zona incerta, a inundação do fundo atravessa a rampa e a da peça esbarra
    no degrau — a fronteira assenta na borda real. Marcadores: FG = miolo erodido MENOS o
    liso-e-meio-claro (umbra provável, SEG_WS_FG_VAL_FRAC); BG = fora da máscara dilatada."""
    def kell(mm):
        d = max(3, int(round(mm * PX_PER_MM)) | 1)
        return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    sure_fg = cv2.erode(mask, kell(SEG_WS_ERODE_MM))
    sure_fg[smooth & (Vd > SEG_WS_FG_VAL_FRAC * bg_v)] = 0
    if not sure_fg.any():
        return mask                                  # sem marcador FG → não refina
    markers = np.zeros(mask.shape, np.int32)
    markers[cv2.dilate(mask, kell(SEG_WS_BAND_MM)) == 0] = 1     # fundo certo
    markers[sure_fg > 0] = 2                                     # peça certa
    cv2.watershed(img, markers)
    return np.where(markers == 2, 255, 0).astype(np.uint8)


def segment_tool(img, deshadow=False, val_frac=SEG_VAL_FRAC, debug_dir=None, faint_metal=False):
    """Estágio 2: máscara da ferramenta sobre o miolo BRANCO da base. O fundo é
    branco conhecido e o objeto está centrado, então a MOLDURA da borda do canvas é
    fundo puro — amostrada p/ modelar o branco (auto-adapta ao balanço de branco e à
    iluminação). Um pixel é OBJETO se for COLORIDO (saturação bem acima do fundo —
    a borda laranja) OU ESCURO (brilho bem abaixo do fundo — a moldura preta); a
    SOMBRA suave é dessaturada e só um pouco mais escura, então fica no fundo. Depois:
    morfologia (abre respingos, fecha vãos), maior componente conectado e preenche
    buracos internos (display, texto) p/ um contorno cheio.

    `deshadow` ∈ {False/"off", True/"remove", "texture"} (True = "remove", compat. retro):

    - **"remove"** liga a HISTERESE de borda por CROMA: a borda arredondada que vira p/ a base
      cai no VÃO entre `colored` e `dark` (o corte único a come e serrilha) dos DOIS lados — o
      BISEL PRETO no topo (escurece, mas com croma) e o TOE LARANJA no fundo (dessatura, mas
      com croma). A histerese cresce os DOIS núcleos (preto `dark` + colorido `colored`) pelos
      pixels "fracos" — não-claros (≤ SEG_VAL_WEAK_FRAC·fundo) E COM CROMA (S ≥ SEG_WEAK_SAT_MIN)
      — recuperando a borda real e PARANDO na sombra de contato CINZA desaturada da base.
    - **"texture"** (v0.5, p/ corpo CINZA-NEUTRO sem croma): VALOR pega o corpo escuro inteiro e a
      TEXTURA (std local de V, limiar Otsu adaptativo) RECORTA do corpo as regiões LISAS-E-mais-
      CLARAS = sombra PROJETADA. Ver docs/historico.md (v0.5).

    `faint_metal` (ligado pelo modo 2 fotos, --in2): acrescenta o predicado de saturação FRACA
    (S ≥ fundo + FUSE_FAINT_SAT_MARGIN, V ≤ FUSE_FAINT_VAL_MAX·fundo) que recupera metal claro
    liso (topos de conectores ≈ brilho do papel). Admite a sombra junto — por isso é EXCLUSIVO
    do modo 2 fotos, onde a fusão direcional a remove."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H = hsv[:, :, 0].astype(np.int16)
    S = hsv[:, :, 1].astype(np.int16)
    V = hsv[:, :, 2].astype(np.int16)
    hh, ww = S.shape
    # Moldura da borda (3% do menor lado) = fundo branco garantido (objeto é central).
    b = max(2, int(round(0.03 * min(hh, ww))))
    frame = np.ones((hh, ww), bool)
    frame[b:-b, b:-b] = False
    bg_h = float(np.median(H[frame]))
    bg_s = float(np.median(S[frame]))
    bg_v = float(np.median(V[frame]))
    dh = np.abs(H - bg_h)
    dh = np.minimum(dh, 180 - dh)                 # distância CIRCULAR de matiz (0..90)
    colored = S >= bg_s + SEG_SAT_MARGIN          # laranja/colorido saturado
    chromatic = (dh >= SEG_HUE_MARGIN) & (S >= SEG_HUE_SAT_MIN)  # matiz quente ≠ fundo (borda c/ realce)
    dark = V <= val_frac * bg_v                   # núcleo escuro (default 0.30; --val-frac sobe p/ cinza)
    # deshadow ∈ {False/"off", True/"remove", "texture"}. True = "remove" (compat. retro dos testes).
    mode = "remove" if deshadow is True else (deshadow or "off")
    if mode == "texture":
        # VALOR-primário + TEXTURA-subtratora-de-sombra (v0.5; corpos CINZA-NEUTROS, sem croma).
        # O valor pega o corpo escuro INTEIRO (inclusive o liso, que a textura sozinha perde); a
        # TEXTURA (std local de V) então RECORTA do corpo as regiões que são ao mesmo tempo LISAS
        # (textura < limiar Otsu ADAPTATIVO da própria foto) E mais CLARAS (V > LIGHT·fundo) — i.e.
        # a SOMBRA PROJETADA, que tem o mesmo brilho do corpo mas é lisa. Inverte o papel da textura:
        # de crescedor/localizador p/ SUBTRATOR de sombra. Ver docs/historico.md (v0.5).
        Vd = cv2.bilateralFilter(V.astype(np.uint8), 7, 40, 7).astype(np.float32)  # denoise preserva borda
        win = (SEG_TEX_WIN, SEG_TEX_WIN)
        mu = cv2.boxFilter(Vd, -1, win)
        mu2 = cv2.boxFilter(Vd * Vd, -1, win)
        tex = np.sqrt(np.maximum(mu2 - mu * mu, 0.0))            # desvio-padrão local de V
        tex_u = np.clip(tex * SEG_TEX_GAIN, 0, 255).astype(np.uint8)
        not_bg = Vd < SEG_TEX_BG_FRAC * bg_v
        if int(np.count_nonzero(not_bg)) >= 50:
            th, _ = cv2.threshold(tex_u[not_bg], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            th = 0.0                                             # nada p/ separar → não recorta
        body_val = Vd < SEG_TEX_BODY_FRAC * bg_v
        shadow_like = (tex_u < th) & (Vd > SEG_TEX_LIGHT_FRAC * bg_v)   # liso E mais claro = sombra
        # O recorte vale p/ TODO o candidato (valor OU croma), não só o valor: em fundo de papel
        # CROMÁTICO (lavanda saturada) a sombra projetada também fica cromática → sem subtrair do
        # `colored|chromatic` ela voltaria por essa porta. A textura é o único cue que a separa.
        cand = body_val | colored | chromatic
        tool = (cand & ~shadow_like).astype(np.uint8) * 255
        # guarda os cues p/ o refino por watershed no fim (borda física por gradiente)
        ws_cues = (Vd, tex_u < th)
    else:
        if mode == "remove":
            # Histerese (estilo Canny) p/ recuperar a BORDA arredondada do objeto, dos DOIS
            # lados, com o MESMO separador físico (croma). A borda vira p/ a base e cai no VÃO
            # entre `colored` e `dark`, então o corte único a perde e serrilha:
            #   • TOPO  — BISEL PRETO: escurece (V cai) mas mantém croma → semeado por `dark`.
            #   • FUNDO — TOE LARANJA: dessatura (S cai p/ ~40) e escurece um pouco → o corte
            #             `colored` (S alto) o larga; semeado por `colored`.
            # Os dois NÚCLEOS (preto + colorido) crescem pelos pixels "fracos" — não-claros
            # (V ≤ WEAK·fundo, exclui o papel) E COM CROMA (S ≥ SAT_MIN) — por ALCANCE LIMITADO
            # (dilatação geodésica). O piso de saturação é o que separa o PLÁSTICO (croma → entra,
            # recupera a borda real) da SOMBRA DE CONTATO cinza desaturada (S≈25 → barrada): o
            # crescimento para exatamente na sombra. Sem ele inundaria o anel de sombra e deixaria
            # o pocket frouxo (medido: base inflava +2 mm; topo recupera ~2.6 mm de preto real).
            weak = ((V <= SEG_VAL_WEAK_FRAC * bg_v) & (S >= SEG_WEAK_SAT_MIN)).astype(np.uint8) * 255
            core = ((dark | colored).astype(np.uint8) * 255)    # núcleo: preto (topo) E colorido (fundo)
            seed = cv2.bitwise_and(core, weak)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            for _ in range(max(1, int(round(SEG_SHADOW_GROW_MM * PX_PER_MM)))):
                seed = cv2.bitwise_and(cv2.dilate(seed, k), weak)   # cresce 1px, contido em weak
            dark = dark | (seed > 0)                            # une a borda recuperada ao núcleo
        tool = (colored | chromatic | dark).astype(np.uint8) * 255

    if faint_metal:
        # Metal claro liso (S fraco, V ≈ papel) — só seguro com --in2 (a fusão tira a sombra).
        faint = (S >= bg_s + FUSE_FAINT_SAT_MARGIN) & (V <= FUSE_FAINT_VAL_MAX * bg_v)
        tool = cv2.bitwise_or(tool, faint.astype(np.uint8) * 255)

    # Abertura remove respingos finos; fechamento tapa vãos internos do corpo.
    tool = cv2.morphologyEx(tool, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    tool = cv2.morphologyEx(tool, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(tool, connectivity=8)
    if n <= 1:
        raise GridDetectionError("nenhum objeto segmentado sobre o miolo branco")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = np.where(labels == biggest, 255, 0).astype(np.uint8)
    # Preenche buracos internos (display, texto gravado, reflexos) → contorno cheio.
    ff = mask.copy()
    cv2.floodFill(ff, np.zeros((hh + 2, ww + 2), np.uint8), (0, 0), 255)
    mask = cv2.bitwise_or(mask, cv2.bitwise_not(ff))

    if mode == "texture":
        # Refino de borda por gradiente (watershed): expulsa a UMBRA que o recorte por
        # brilho não pega e assenta a fronteira no degrau físico da peça.
        mask = _refine_edge_watershed(img, mask, ws_cues[0], ws_cues[1], bg_v)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n > 1:                       # re-limpa: watershed pode soltar farelos
            biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            mask = np.where(labels == biggest, 255, 0).astype(np.uint8)
            ff = mask.copy()
            cv2.floodFill(ff, np.zeros((hh + 2, ww + 2), np.uint8), (0, 0), 255)
            mask = cv2.bitwise_or(mask, cv2.bitwise_not(ff))

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "02_mask.png"), mask)
    return mask


def _rot_about(src, angle, center, interp=cv2.INTER_NEAREST):
    """Rotação rígida de `angle`° em torno de `center`, mantendo o canvas."""
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(src, M, (src.shape[1], src.shape[0]), flags=interp)


def _register_masks(mask1, mask2, ppmm=PX_PER_MM, search_mm=FUSE_SEARCH_MM,
                    gray1=None, gray2=None):
    """REGISTRO rígido da máscara 2 sobre a 1 (mesmo canvas métrico): rotação em
    quartos {0,90,180,270}° + refino fino ±FUSE_ANGLE_DEG (passo 1°), em torno do
    centroide da máscara 2, e translação ±search_mm. Score = IoU × (0.5+0.5·ZNCC⁺)
    dos `gray*` na sobreposição — a TEXTURA desempata rotações que a silhueta
    sozinha não distingue (numa peça quase retangular, sombra∩sombra infla o IoU
    da rotação ERRADA); sem os grays cai no IoU puro. O refino fino roda em TODOS
    os quartos ANTES de eleger o vencedor (o ZNCC só "encaixa" no ângulo exato;
    3° de erro descorrelacionam a textura na borda). Busca em escala 1/4, com
    refino final de translação ±2 px na escala cheia.
    Devolve `(angle, center, dx, dy, score)`: girar `mask2` de `angle`° em torno
    de `center` e transladar `(dx, dy)` px a leva sobre `mask1`."""
    ds = 4                                    # escala da busca (1/4)
    m1s = cv2.resize(mask1, None, fx=1.0 / ds, fy=1.0 / ds, interpolation=cv2.INTER_NEAREST)
    m2s = cv2.resize(mask2, None, fx=1.0 / ds, fy=1.0 / ds, interpolation=cv2.INTER_NEAREST)
    g1s = g2s = g1f = g2f = None
    if gray1 is not None and gray2 is not None:
        g1f, g2f = gray1.astype(np.float32), gray2.astype(np.float32)
        g1s = cv2.resize(g1f, (m1s.shape[1], m1s.shape[0]), interpolation=cv2.INTER_AREA)
        g2s = cv2.resize(g2f, (m2s.shape[1], m2s.shape[0]), interpolation=cv2.INTER_AREA)
    mm = cv2.moments(m2s, binaryImage=True)
    if mm["m00"] <= 0:
        raise GridDetectionError("fusão 2-fotos: a segunda máscara está vazia")
    c2s = (mm["m10"] / mm["m00"], mm["m01"] / mm["m00"])   # centroide (escala 1/4)

    def best_shift(a, b, rad, step, seed=(0, 0), ga=None, gb=None):
        """Melhor translação de `b` sobre `a` numa grade ±rad, passo `step`. Score =
        IoU das máscaras × (0.5 + 0.5·ZNCC⁺ dos grays na sobreposição) — a textura
        desempata rotações que a silhueta sozinha não distingue."""
        A = a > 0
        bx, by, bs = seed[0], seed[1], -1.0
        for dy in range(seed[1] - rad, seed[1] + rad + 1, step):
            for dx in range(seed[0] - rad, seed[0] + rad + 1, step):
                M = np.float32([[1, 0, dx], [0, 1, dy]])
                B = cv2.warpAffine(b, M, (b.shape[1], b.shape[0]), flags=cv2.INTER_NEAREST) > 0
                ov = A & B
                union = np.count_nonzero(A | B)
                s = (np.count_nonzero(ov) / union) if union else 0.0
                if s > 0.0 and ga is not None:
                    Bg = cv2.warpAffine(gb, M, (gb.shape[1], gb.shape[0]),
                                        flags=cv2.INTER_NEAREST)
                    va, vb = ga[ov], Bg[ov]
                    va, vb = va - va.mean(), vb - vb.mean()
                    den = math.sqrt(float(np.dot(va, va)) * float(np.dot(vb, vb)))
                    zncc = (float(np.dot(va, vb)) / den) if den > 0 else 0.0
                    s *= 0.5 + 0.5 * max(0.0, zncc)
                if s > bs:
                    bx, by, bs = dx, dy, s
        return bx, by, bs

    rad_s = max(2, int(round(search_mm * ppmm / ds)))
    # Semente da translação = diferença dos centroides das DUAS máscaras: a rotação
    # gira em torno do centroide da máscara 2 (deslocado do centro da PEÇA pela
    # sombra), então a 180° a peça cai ~2× esse desvio p/ longe — sem a semente, o
    # deslocamento estoura a janela ±search_mm e a rotação certa nunca competiria.
    m1m = cv2.moments(m1s, binaryImage=True)
    seed0 = ((int(round(m1m["m10"] / m1m["m00"] - c2s[0])),
              int(round(m1m["m01"] / m1m["m00"] - c2s[1]))) if m1m["m00"] > 0 else (0, 0))
    best = (-1.0, 0.0, 0, 0)                  # (score, ângulo, dx_s, dy_s)
    for quarter in (0, 90, 180, 270):         # girar peça/papel p/ mudar a luz é o protocolo típico
        r = _rot_about(m2s, quarter, c2s)
        rg = _rot_about(g2s, quarter, c2s, cv2.INTER_LINEAR) if g2s is not None else None
        dx, dy, s = best_shift(m1s, r, rad_s, 2, seed=seed0, ga=g1s, gb=rg)
        qbest = (s, float(quarter), dx, dy)
        for dang in range(-FUSE_ANGLE_DEG, FUSE_ANGLE_DEG + 1):   # ângulo fino (passo 1°)
            if dang == 0:
                continue
            ang = quarter + dang
            r = _rot_about(m2s, ang, c2s)
            rg = _rot_about(g2s, ang, c2s, cv2.INTER_LINEAR) if g2s is not None else None
            dx, dy, s = best_shift(m1s, r, 3, 1, seed=(qbest[2], qbest[3]), ga=g1s, gb=rg)
            if s > qbest[0]:
                qbest = (s, ang, dx, dy)
        if qbest[0] > best[0]:
            best = qbest
    # escala cheia: aplica a rotação vencedora e refina a translação ±2 px
    c2 = (c2s[0] * ds, c2s[1] * ds)
    r2r = _rot_about(mask2, best[1], c2)
    g2r = _rot_about(g2f, best[1], c2, cv2.INTER_LINEAR) if g2f is not None else None
    dx, dy, s = best_shift(mask1, r2r, 2, 1, seed=(best[2] * ds, best[3] * ds), ga=g1f, gb=g2r)
    return best[1], c2, float(dx), float(dy), s


# --- fusão 2-fotos (--in2): melhor lado de CADA foto, com registro fino -------
# Protocolo: DUAS fotos do MESMO objeto sobre a base, mudando só a LUZ (girar
# base+peça juntas em relação ao sol/lâmpada). As duas retificações ancoram no
# MESMO alvo impresso → a peça cai no MESMO lugar do canvas métrico; a sombra
# muda de lado. Em cada foto o lado ILUMINADO (oposto à sombra) tem a borda
# limpa — esse lado é SOBERANO. A fusão descobre a direção da sombra de cada
# foto pela própria discordância das máscaras (o "lóbulo" presente numa máscara
# só é a sombra dela) e monta a máscara final tomando de cada foto o seu lado
# iluminado — sem heurística de brilho/textura/croma. É o caminho robusto p/
# sombra dura (sol) e peças cujo corpo se confunde com a própria sombra.
def fuse_masks(mask1, mask2, ppmm=PX_PER_MM, search_mm=FUSE_SEARCH_MM, grow_mm=FUSE_GROW_MM,
               debug_dir=None, gray1=None, gray2=None, reg1=None, reg2=None):
    """Fusão direcional das máscaras das duas fotos retificadas, em três passos:
    1. REGISTRO rígido (`_register_masks`): rotação + translação que levam a máscara 2
       sobre a 1, pontuadas por IoU × textura (ZNCC de `gray1`/`gray2`) — ver a função.
    2. DIREÇÃO da sombra de cada foto: centroide do lóbulo exclusivo (máscara_i e não
       na outra) relativo ao centroide do núcleo comum (AND).
    3. FUSÃO por lado iluminado: o plano é dividido pela bissetriz das duas direções
       de sombra; em cada metade vale a máscara da foto cuja sombra aponta p/ o OUTRO
       lado. Cada foto contribui só com a borda que a luz dela deixou limpa — e a
       PARALAXE deixa de roer a peça alta (não há AND na borda soberana).
    Fallback: lóbulo minúsculo (sem sombra) ou sombras do mesmo lado (luz não mudou)
    → AND puro. Devolve `(fused, reg)`: `reg` traz a transformação do registro
    (angle/center/dx/dy) e as áreas dos lóbulos (px) p/ o caller escolher a foto de
    melhor luz como fundo do overlay.

    `reg1`/`reg2` (opcionais): máscaras LIMPAS (sombra removida) usadas SÓ no registro.
    Com o predicado faint-metal as máscaras de conteúdo readmitem a sombra, e o IoU
    volta a premiar alinhar sombra∩sombra (medido: shift saltou 13mm); registrar nas
    limpas ancora a transformação na PEÇA, e ela é então aplicada às de conteúdo."""
    if mask1.shape != mask2.shape:            # canvases devem coincidir (mesma base/layout)
        hh = min(mask1.shape[0], mask2.shape[0]); ww = min(mask1.shape[1], mask2.shape[1])
        mask1, mask2 = mask1[:hh, :ww], mask2[:hh, :ww]
        if gray1 is not None:
            gray1, gray2 = gray1[:hh, :ww], gray2[:hh, :ww]
        if reg1 is not None:
            reg1, reg2 = reg1[:hh, :ww], reg2[:hh, :ww]
    r1 = reg1 if reg1 is not None else mask1  # máscaras do REGISTRO (limpas se houver)
    r2 = reg2 if reg2 is not None else mask2
    # O registro pontua nas máscaras de REGISTRO; a transformação vale p/ as de conteúdo.
    angle, c2, dx, dy, score = _register_masks(r1, r2, ppmm=ppmm, search_mm=search_mm,
                                               gray1=gray1, gray2=gray2)
    print(f"fusão 2-fotos: registro rot={angle:.0f}° shift=({dx / ppmm:+.1f},{dy / ppmm:+.1f})mm "
          f"score={score:.3f}", file=sys.stderr)
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    m2r = _rot_about(mask2, angle, c2)
    m2f = cv2.warpAffine(m2r, M, (m2r.shape[1], m2r.shape[0]), flags=cv2.INTER_NEAREST)

    # Direção da sombra de cada foto = centroide do lóbulo exclusivo relativo ao núcleo.
    b1, b2 = mask1 > 0, m2f > 0
    core = (b1 & b2).astype(np.uint8) * 255
    lobe1 = (b1 & ~b2).astype(np.uint8) * 255   # só na foto 1 → sombra (e paralaxe) dela
    lobe2 = (b2 & ~b1).astype(np.uint8) * 255   # só na foto 2 → sombra (e paralaxe) dela
    mc = cv2.moments(core, binaryImage=True)
    if mc["m00"] <= 0:
        raise GridDetectionError("fusão 2-fotos: as máscaras das duas fotos não se "
                                 "sobrepõem — a peça moveu em relação à base entre as fotos?")
    cx, cy = mc["m10"] / mc["m00"], mc["m01"] / mc["m00"]

    def shadow_dir(lobe):
        """Versor centroide(lóbulo)−centroide(núcleo); None se o lóbulo é desprezível."""
        m = cv2.moments(lobe, binaryImage=True)
        if m["m00"] < (FUSE_MIN_LOBE_MM * ppmm) ** 2:
            return None
        vx, vy = m["m10"] / m["m00"] - cx, m["m01"] / m["m00"] - cy
        nrm = math.hypot(vx, vy)
        return (vx / nrm, vy / nrm) if nrm > 1e-6 else None

    s1, s2 = shadow_dir(lobe1), shadow_dir(lobe2)
    # Fusão direcional POR PIXEL DISPUTADO: o núcleo (AND) sempre entra; um pixel que
    # só existe na máscara da foto i entra SÓ se estiver no lado ILUMINADO dela
    # ((p−c)·ŝᵢ ≤ 0) — lá a borda da foto i é limpa, então o excesso é peça real
    # (paralaxe); na direção da sombra dela, o excesso É a sombra e cai. Não exige
    # sombras opostas: se a luz mudou pouco, degrada graciosamente p/ ~AND.
    yy, xx = np.mgrid[0:mask1.shape[0], 0:mask1.shape[1]]
    px, py = xx - cx, yy - cy

    def lit_part(lobe, s):
        """Parte do lóbulo no lado iluminado da própria foto (None = lóbulo desprezível
        → sem sombra a rejeitar, mantém tudo)."""
        if s is None:
            return lobe
        return np.where(px * s[0] + py * s[1] <= 0.0, lobe, 0).astype(np.uint8)

    fused = cv2.bitwise_or(core, cv2.bitwise_or(lit_part(lobe1, s1), lit_part(lobe2, s2)))
    if s1 and s2:
        print(f"fusão 2-fotos: direcional — sombra foto1→({s1[0]:+.2f},{s1[1]:+.2f}) "
              f"foto2→({s2[0]:+.2f},{s2[1]:+.2f}); lado iluminado de cada foto soberano",
              file=sys.stderr)
        if s1[0] * s2[0] + s1[1] * s2[1] > FUSE_ALIGN_MAX:
            print("fusão 2-fotos: AVISO — as sombras das duas fotos caem do MESMO lado "
                  "(a luz mudou pouco); resultado ≈ AND. Refotografe com a luz oposta.",
                  file=sys.stderr)
    if grow_mm and grow_mm > 0:
        # Recuperação de paralaxe adicional: dilatação geodésica DENTRO da união,
        # limitada a grow_mm. Com a fusão direcional raramente é necessária (a borda
        # soberana não sofre AND); mantida p/ o caso de resíduo perto da bissetriz.
        union = cv2.bitwise_or(mask1, m2f)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        for _ in range(max(1, int(round(grow_mm * ppmm)))):
            fused = cv2.bitwise_and(cv2.dilate(fused, k), union)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fused, connectivity=8)
    if n <= 1:
        raise GridDetectionError("fusão 2-fotos: as máscaras das duas fotos não se "
                                 "sobrepõem — a peça moveu em relação à base entre as fotos?")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    fused = np.where(labels == biggest, 255, 0).astype(np.uint8)
    ff = fused.copy()
    hh, ww = fused.shape
    cv2.floodFill(ff, np.zeros((hh + 2, ww + 2), np.uint8), (0, 0), 255)
    fused = cv2.bitwise_or(fused, cv2.bitwise_not(ff))
    # Registro + áreas dos lóbulos p/ o caller: menor lóbulo = foto com MENOS sombra
    # (melhor luz) → candidata a fundo do overlay (warpada pela mesma transformação).
    reg = {"angle": angle, "center": c2, "dx": dx, "dy": dy,
           "lobe1_px": int(np.count_nonzero(lobe1)), "lobe2_px": int(np.count_nonzero(lobe2))}
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "02e_mask_in2.png"), m2f)
        split = cv2.merge([m2f // 2 + core // 2, core, mask1 // 2 + core // 2])  # BGR:
        cv2.imwrite(os.path.join(debug_dir, "02g_fuse_split.png"), split)        # núcleo
        cv2.imwrite(os.path.join(debug_dir, "02f_fused.png"), fused)  # branco, lóbulo1 verm., lóbulo2 azul
    return fused, reg


# --- simetria: espelha a máscara e tira a MÉDIA das duas metades --------------
# Muitos objetos são simétricos: se o eixo é conhecido, a metade esquerda e a
# metade direita (ou topo/baixo) são DUAS medições do MESMO contorno. Espelhar e
# fazer a média cancela o ruído aleatório da foto (sombra, serrilhado de um lado
# só, realce assimétrico) e FORÇA a simetria perfeita. A média de duas formas é
# feita pelo campo de distância COM SINAL (positivo dentro, negativo fora): médio
# os dois campos e corto em 0 → a "forma média" (média morfológica), não a
# interseção (AND) nem a união (OR), que enviesariam p/ dentro/fora.
def _signed_distance(mask):
    """Distância com sinal (mm-agnóstica, em px): >0 dentro, <0 fora da máscara."""
    inside = cv2.distanceTransform(mask, cv2.DIST_L2, 5).astype(np.float32)
    outside = cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5).astype(np.float32)
    return inside - outside


def _mask_from_sdf(sdf):
    """Re-binariza um campo de distância com sinal em máscara 0/255 (corte em 0)."""
    return (sdf >= 0.0).astype(np.uint8) * 255


def _reflect_mask(mask, axis, c):
    """Reflete a máscara na linha de simetria: 'vertical' = linha VERTICAL em x=c
    (espelha esquerda↔direita), 'horizontal' = linha HORIZONTAL em y=c (topo↔baixo)."""
    h, w = mask.shape
    if axis == "vertical":
        M = np.array([[-1.0, 0.0, 2.0 * c], [0.0, 1.0, 0.0]], np.float32)
    else:
        M = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 2.0 * c]], np.float32)
    return cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)


def snap90(angle_deg):
    """Desvio (graus) de `angle_deg` ao múltiplo de 90° mais próximo, em [−45°, +45°).
    É o "quanto falta p/ ficar no nível" de um envelope retangular (F3/--level)."""
    return (angle_deg + 45.0) % 90.0 - 45.0


def estimate_level_angle(mask, ppmm=PX_PER_MM):
    """F3 (--level auto): estima a inclinação FINA da peça pelo ENVELOPE —
    `cv2.minAreaRect` da maior componente, desvio ao múltiplo de 90° mais próximo
    (mod 90 em [−45°,+45°)). Recuperou EXATO os ângulos injetados no experimento do
    plano 011. Devolve `(desvio°, centro_px, None)`, ou `(None, None, motivo)` quando
    não dá p/ confiar: peça ~quadrada/redonda (aspecto < LEVEL_ASPECT_MIN) SEM nenhuma
    reta ≥ LEVEL_LINE_MIN_MM alinhável no contorno — um disco deixa o envelope
    instável; um quadrado tem arestas que o confirmam."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None, "nenhum contorno na máscara"
    c = max(cnts, key=cv2.contourArea)
    (cx, cy), (w, h), ang = cv2.minAreaRect(c)
    if min(w, h) < 1e-6:
        return None, None, "máscara degenerada"
    dev = snap90(ang)
    if max(w, h) / min(w, h) < LEVEL_ASPECT_MIN:
        step = 0.4
        rp = resample_uniform(extract_outline(mask, 1.0 / ppmm), step, closed=True)
        n = len(rp)
        aligned = False
        for (i0, i1) in _detect_line_runs(rp, step, min_len_mm=LEVEL_LINE_MIN_MM):
            a, b = rp[i0 % n], rp[i1 % n]
            la = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            if abs(snap90(la)) <= LEVEL_MAX_DEG:
                aligned = True
                break
        if not aligned:
            return None, None, "peça ~quadrada/redonda sem reta alinhável (envelope instável)"
    return dev, (cx, cy), None


def level_rect_and_mask(rect, mask, ppmm=PX_PER_MM, debug_dir=None):
    """F3 (--level auto): "coloca no nível" a peça apoiada levemente torta na base —
    estima o desvio (estimate_level_angle) e gira `rect` E `mask` com a MESMA matriz
    (centro da peça; máscara em NEAREST), SEM re-segmentar: overlay e todos os
    estágios seguintes consomem o par já nivelado de graça. Aplica só na faixa
    LEVEL_MIN_DEG ≤ |desvio| ≤ LEVEL_MAX_DEG (abaixo: já nivelado, não mexe — saída
    idêntica; acima: warn e segue sem girar). Devolve (rect, mask, desvio | None)."""
    dev, center, reason = estimate_level_angle(mask, ppmm=ppmm)
    if dev is None:
        warn(f"--level: sem correção — {reason}.")
        return rect, mask, None
    if abs(dev) < LEVEL_MIN_DEG:
        return rect, mask, None
    if abs(dev) > LEVEL_MAX_DEG:
        warn(f"--level: inclinação estimada {dev:+.2f}° fora da faixa fina "
             f"(±{LEVEL_MAX_DEG:.0f}°) — apoie a peça mais no nível; sem correção.")
        return rect, mask, None
    # Sinal validado em sintético: girar por +desvio (getRotationMatrix2D) ZERA o
    # resíduo (o referencial mm tem Y p/ cima e a imagem p/ baixo — a convenção do
    # OpenCV já absorve a inversão; ver TestAutoLevel).
    M = cv2.getRotationMatrix2D(center, dev, 1.0)
    h, w = mask.shape[:2]
    rect2 = cv2.warpAffine(rect, M, (w, h), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)
    mask2 = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "02a_leveled.png"), mask2)
    return rect2, mask2, dev


def symmetrize_mask(mask, axis, ppmm=PX_PER_MM, search_mm=SYM_SEARCH_MM, debug_dir=None):
    """Impõe a simetria do objeto: acha o eixo (parte do centroide, refina por máx.
    IoU entre a máscara e seu espelho ±`search_mm`) e devolve a MÉDIA morfológica
    das duas metades (média dos campos de distância com sinal). `axis` ∈
    {'vertical','horizontal','both'}; 'both' aplica os dois eixos em sequência."""
    if axis == "both":
        return symmetrize_mask(symmetrize_mask(mask, "vertical", ppmm, search_mm),
                               "horizontal", ppmm, search_mm, debug_dir=debug_dir)
    m = cv2.moments(mask, binaryImage=True)
    if m["m00"] == 0:
        return mask
    c0 = (m["m10"] / m["m00"]) if axis == "vertical" else (m["m01"] / m["m00"])

    # Refina o eixo: o centroide é o eixo exato p/ uma forma perfeita, mas a foto
    # tem ruído/leve perspectiva — varre ±search_mm a 0,5 px e fica com o de maior IoU.
    rng = max(1, int(round(search_mm * ppmm)))
    best_c, best_iou = c0, -1.0
    for c in (c0 + 0.5 * d for d in range(-rng, rng + 1)):
        refl = _reflect_mask(mask, axis, c)
        inter = np.count_nonzero(cv2.bitwise_and(mask, refl))
        union = np.count_nonzero(cv2.bitwise_or(mask, refl))
        iou = (inter / union) if union else 0.0
        if iou > best_iou:
            best_iou, best_c = iou, c

    refl = _reflect_mask(mask, axis, best_c)
    sdf = 0.5 * (_signed_distance(mask) + _signed_distance(refl))
    out = _mask_from_sdf(sdf)
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        dbg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        dbg[:, :, 2] = refl                                # vermelho = espelho
        cv2.imwrite(os.path.join(debug_dir, "02b_symmetry_pair.png"), dbg)
        cv2.imwrite(os.path.join(debug_dir, "02b_symmetric.png"), out)
    return out


def regularize_silhouette(mask, radius_mm, ppmm=PX_PER_MM, debug_dir=None,
                          preserve_convex=False):
    """Suaviza a SILHUETA da máscara borrando o campo de distância com sinal (reusa
    `_signed_distance`) e re-cortando em 0. Remove saliências e reentrâncias de amplitude
    < `radius_mm` de forma ISOTRÓPICA — some com as ondulações da borda serrilhada (típicas
    na carcaça PRETA, onde o contraste contra a sombra é baixo) SEM arredondar os cantos
    macro (raio ≫ radius_mm). É ortogonal ao `--smooth-mm` (que age na curva já extraída):
    aqui a forma é limpa na FONTE, antes de extrair o contorno. `radius_mm` ≤ 0 = no-op.

    `preserve_convex=True` (v0.5, Etapa B): em vez do borrado puro, toma `max(sdf, blur)` —
    um *closing* no campo de distância. Só preenche REENTRÂNCIAS (côncavas, ruído da serrilha)
    e PRESERVA os RESSALTOS convexos (ex.: a aba lateral da peça), que o borrado isotrópico
    arredondaria junto. Cuidado: também mantém picos de ruído convexo (raros sub-mm)."""
    if not radius_mm or radius_mm <= 0:
        return mask
    sdf = _signed_distance(mask)
    blur = cv2.GaussianBlur(sdf, (0, 0), sigmaX=radius_mm * ppmm)
    # max(sdf,blur) = closing no SDF: escolhe o mais "dentro" → enche côncavos, mantém convexos.
    sdf = np.maximum(sdf, blur) if preserve_convex else blur
    out = _mask_from_sdf(sdf)
    # v0.6: a remoção de uma saliência convexa REAL (ex.: o gancho da fita de uma trena) é
    # silenciosa p/ o gate `contém` (medido sobre a silhueta já regularizada) — então AVISA
    # quando some algo com proeminência ≥ PROTRUSION_DEV_MM e área ≥ o piso (ruído de borda,
    # que é o alvo legítimo da regularização, fica abaixo dos dois cortes).
    removed = cv2.bitwise_and(mask, cv2.bitwise_not(out))
    if np.any(removed):
        dist = cv2.distanceTransform(cv2.bitwise_not(out), cv2.DIST_L2, 5)
        num, labels, stats, _ = cv2.connectedComponentsWithStats(removed, 8)
        for i in range(1, num):
            area_mm2 = stats[i, cv2.CC_STAT_AREA] / (ppmm * ppmm)
            if area_mm2 < MASK_SMOOTH_WARN_AREA_MM2:
                continue
            prom_mm = float(dist[labels == i].max()) / ppmm
            if prom_mm >= PROTRUSION_DEV_MM:
                warn(f"--mask-smooth-mm removeu uma saliência convexa de ~{area_mm2:.1f} mm² "
                     f"(proeminência ~{prom_mm:.1f} mm) — se ela é uma feature real da peça, "
                     f"use --mask-smooth-keep-bumps ou um --mask-smooth-mm menor")
                break
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "02c_regularized.png"), out)
    return out


def _cyclic_true_runs(flags):
    """Runs cíclicos de True no array booleano `flags`: [(start, stop)] com stop
    EXCLUSIVO em índice DESENROLADO (stop > n quando o run cruza a emenda do anel)."""
    n = len(flags)
    if flags.all():
        return [(0, n)]
    if not flags.any():
        return []
    # Gira p/ começar num False: no array girado nenhum run de True cruza a emenda.
    off = int(np.flatnonzero(~flags)[0])
    f = np.roll(flags, -off)
    d = np.diff(f.astype(np.int8))
    starts = np.flatnonzero(d == 1) + 1
    stops = list(np.flatnonzero(d == -1) + 1) + [n]
    runs = []
    for s in starts:
        e = next(x for x in stops if x > s)
        runs.append((int((s + off) % n), int((s + off) % n + (e - s))))
    return runs


def _flip_short_runs(flags, seglen, value, max_mm):
    """Limpeza da classificação firme/incerto: inverte os runs cíclicos de `value`
    com comprimento de arco < `max_mm` (fecha buracos incertos curtos / derruba
    ilhas firmes de chatter). Modifica e devolve `flags`."""
    n = len(flags)
    for s, e in _cyclic_true_runs(flags if value else ~flags):
        idx = np.arange(s, e) % n
        if float(seglen[idx].sum()) < max_mm:
            flags[idx] = not value
    return flags


def _humble_classify(mask, gray, ppmm):
    """Classifica cada ponto do contorno externo da máscara como FIRME (apoiado num
    degrau de gradiente da foto retificada) ou INCERTO. Limiar por Otsu sobre os
    valores da própria borda (adaptativo por foto, mesmo espírito do --shadow texture),
    com guarda p/ distribuição unimodal (borda toda parecida → decide contra o piso
    absoluto). Devolve (contorno Nx2 px, firm bool[N], seglen mm[N], gm, thr,
    firm_frac) ou None se não há contorno utilizável."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea).reshape(-1, 2)
    if len(c) < 8:
        return None
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    gm = cv2.magnitude(cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3),
                       cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3))
    r = max(1, int(round(HUMBLE_GRAD_WIN_MM * ppmm)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    gmd = cv2.dilate(gm, k)                      # máximo local = janela de tolerância
    vals = gmd[c[:, 1], c[:, 0]]
    floor = max(HUMBLE_GRAD_FLOOR, 4.0 * float(np.median(gm)))
    vmax = float(vals.max())
    if vmax <= floor:                            # foto sem degrau NENHUM sob a borda
        firm = np.zeros(len(c), bool)
        thr = floor
    else:
        v8 = np.clip(vals * (255.0 / vmax), 0, 255).astype(np.uint8)
        t8, _ = cv2.threshold(v8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Teto: numa borda TODA forte o Otsu divide a própria moda e chamaria a metade
        # menos contrastada de incerta; acima de CAP× o nível liso já é degrau real.
        thr = min(float(t8) * vmax / 255.0, HUMBLE_GRAD_CAP * floor)
        firm = vals > thr
    seglen = np.hypot(*(np.roll(c, -1, axis=0) - c).T) / ppmm     # mm, ponto i → i+1
    firm = _flip_short_runs(firm.copy(), seglen, False, HUMBLE_FIRM_CLOSE_MM)
    firm = _flip_short_runs(firm, seglen, True, HUMBLE_FIRM_ISLAND_MM)
    total = float(seglen.sum())
    firm_frac = float(seglen[firm].sum() / total) if total > 0 else 1.0
    return c, firm, seglen, gm, float(thr), firm_frac


def _sliver_stats(ring_px, gm, thr, ppmm):
    """(área mm², fração texturizada) da LASCA delimitada pelo anel de pontos px
    `ring_px` — a região que uma corda descartaria. Rasteriza só no ROI da lasca."""
    p = np.asarray(np.rint(ring_px), np.int32)
    x0, y0 = p.min(axis=0); x1, y1 = p.max(axis=0)
    x0 = max(0, int(x0) - 1); y0 = max(0, int(y0) - 1)
    x1 = min(gm.shape[1] - 1, int(x1) + 1); y1 = min(gm.shape[0] - 1, int(y1) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0
    roi = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
    cv2.fillPoly(roi, [p - (x0, y0)], 255)
    area_px = int(np.count_nonzero(roi))
    if area_px == 0:
        return 0.0, 0.0
    tex = int(np.count_nonzero((gm[y0:y1 + 1, x0:x1 + 1] > thr) & (roi > 0)))
    return area_px / (ppmm * ppmm), tex / area_px


def _sliver_is_smooth(ring_px, gm, thr, ppmm):
    """Guarda de lisura do descarte (§2 do plano v0.12): a lasca é descartável se for
    LISA (sem textura de peça) ou pequena demais p/ conter feature real."""
    area_mm2, tex = _sliver_stats(ring_px, gm, thr, ppmm)
    return area_mm2 < HUMBLE_SLIVER_MIN_MM2 or tex < HUMBLE_SLIVER_TEX_FRAC


def _humble_gap(c, seglen, gm, thr, ppmm, i0, i1, out, depth=0):
    """Processa o vão INCERTO entre os pontos firmes c[i0] e c[i1] (índices
    desenrolados, i1 > i0): corda se o descarte é liso; senão subdivide ao meio (por
    arco) e recursa; vão pequeno e ainda texturizado mantém a borda original (flag).
    Anexa segmentos ['chord'|'keep', i0, i1] a `out`."""
    n = len(c)
    ring = [c[j % n] for j in range(i0, i1 + 1)]     # vão + corda de volta (implícita)
    if _sliver_is_smooth(ring, gm, thr, ppmm):
        out.append(["chord", i0, i1])
        return
    arclen = float(sum(seglen[j % n] for j in range(i0, i1)))
    if arclen < HUMBLE_MIN_GAP_MM or i1 - i0 < 4 or depth > 12:
        out.append(["keep", i0, i1])                 # regra 3: honestidade > palpite
        return
    acc, m = 0.0, i0 + (i1 - i0) // 2                # divide no MEIO do arco
    for j in range(i0, i1):
        acc += seglen[j % n]
        if acc >= arclen / 2:
            m = j + 1
            break
    m = min(max(m, i0 + 2), i1 - 2)
    _humble_gap(c, seglen, gm, thr, ppmm, i0, m, out, depth + 1)
    _humble_gap(c, seglen, gm, thr, ppmm, m, i1, out, depth + 1)


def _humble_merge(c, gm, thr, ppmm, segs):
    """Passada 2b: tenta derrubar cada VÉRTICE DE EMENDA entre cordas adjacentes da
    subdivisão — se o triângulo (a, emenda, b) entre as duas cordas e a corda fundida
    for liso, funde (remove a 'tenda' que a subdivisão deixa no ápice do halo)."""
    n = len(c)
    changed = True
    while changed:
        changed = False
        k = 0
        while k + 1 < len(segs):
            a, b = segs[k], segs[k + 1]
            if (a[0] == "chord" and b[0] == "chord" and a[2] == b[1]
                    and _sliver_is_smooth([c[a[1] % n], c[a[2] % n], c[b[2] % n]],
                                          gm, thr, ppmm)):
                segs[k] = ["chord", a[1], b[2]]
                del segs[k + 1]
                changed = True
            else:
                k += 1
    return segs


def humble_rewrite(mask, gray, ppmm, mode="auto", merge=True):
    """Contorno HUMILDE (v0.12): quando a borda da máscara não tem apoio visual na
    foto (fração firme < HUMBLE_MIN_FIRM_FRAC no modo `auto`, ou sempre com `on`),
    troca o CHUTE da segmentação nos vãos incertos por CORDAS RETAS entre os trechos
    firmes vizinhos — halo de penumbra some, concavidade real fecha (ambos seguros
    p/ um pocket que deve CONTER a peça) — e FLAGRA o que ficou sem resposta.

    Devolve `(mask2, report)`: `mask2` é a máscara reescrita (ou a PRÓPRIA `mask`
    quando nada muda) e `report` = {firm_frac, active, chords [((x0,y0),(x1,y1)) px],
    flags [((cx,cy) mm frame da foto, extensão mm)], flag_runs_px [ndarray Nx2 p/ o
    overlay], note}. Pura (não faz I/O) — testável com fixtures sintéticas."""
    report = {"firm_frac": 1.0, "active": False, "chords": [], "flags": [],
              "flag_runs_px": [], "note": None}
    res = _humble_classify(mask, gray, ppmm)
    if res is None:
        return mask, report
    c, firm, seglen, gm, thr, firm_frac = res
    report["firm_frac"] = firm_frac
    if mode != "on" and firm_frac >= HUMBLE_MIN_FIRM_FRAC:
        return mask, report                          # gatilho auto não dispara
    report["active"] = True
    if not firm.any():
        report["note"] = ("nenhum trecho da borda tem apoio visual — sem âncoras p/ "
                          "cordas; contorno original mantido")
        return mask, report
    if firm.all():
        return mask, report                          # nada a reescrever
    n = len(c)
    runs = sorted(_cyclic_true_runs(firm))
    gaps = []                                        # [((s,e) firme, [segmentos do vão])]
    for k, (s, e) in enumerate(runs):
        s2 = runs[(k + 1) % len(runs)][0]
        i0 = e - 1                                   # último ponto firme deste run
        i1 = s2 if s2 > i0 % n else s2 + n           # primeiro firme do próximo
        while i1 <= i0:
            i1 += n
        segs = []
        _humble_gap(c, seglen, gm, thr, ppmm, i0, i1, segs)
        if merge:
            _humble_merge(c, gm, thr, ppmm, segs)
        gaps.append(((s, e), segs))
    poly, chords, flags, flag_runs = [], [], [], []
    step_px = max(1.0, HUMBLE_CHORD_STEP_MM * ppmm)
    for (s, e), segs in gaps:
        poly.extend(c[j % n] for j in range(s, e))   # trecho firme: mantém como está
        for si, (kind, i0, i1) in enumerate(segs):
            p0, p1 = c[i0 % n].astype(float), c[i1 % n].astype(float)
            if kind == "chord":
                m = max(1, int(round(math.hypot(*(p1 - p0)) / step_px)))
                poly.extend(p0 + (p1 - p0) * (t / m) for t in range(1, m))
                chords.append((tuple(int(v) for v in c[i0 % n]),
                               tuple(int(v) for v in c[i1 % n])))
            else:                                    # keep: borda original + flag
                run = [c[j % n] for j in range(i0 + 1, i1)]
                poly.extend(run)
                arclen = float(sum(seglen[j % n] for j in range(i0, i1)))
                mid = c[(i0 + (i1 - i0) // 2) % n]
                flags.append(((float(mid[0]) / ppmm, float(mid[1]) / ppmm), arclen))
                flag_runs.append(np.asarray([c[j % n] for j in range(i0, i1 + 1)],
                                            np.int32))
            if si < len(segs) - 1:                   # emenda interna do vão
                poly.append(c[i1 % n])
    report.update(chords=chords, flags=flags, flag_runs_px=flag_runs)
    if not chords:
        return mask, report                          # só keeps = máscara original intacta
    mask2 = np.zeros_like(mask)
    cv2.fillPoly(mask2, [np.asarray(np.rint(np.asarray(poly, float)), np.int32)], 255)
    return mask2, report


def extract_outline(mask, mm_per_px_x, mm_per_px_y=None, debug_dir=None):
    """Estágio 3: maior contorno externo → pontos em mm (escala X/Y separada, Y
    invertido p/ impressão). `mm_per_px_y` default = `mm_per_px_x` (grade quadrada)."""
    if mm_per_px_y is None:
        mm_per_px_y = mm_per_px_x
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        raise GridDetectionError("nenhum contorno externo encontrado")
    c = max(cnts, key=cv2.contourArea)
    pts = [(float(p[0][0]) * mm_per_px_x, -float(p[0][1]) * mm_per_px_y) for p in c]
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        dbg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(dbg, [c], -1, (0, 0, 255), 2)
        cv2.imwrite(os.path.join(debug_dir, "03_contour.png"), dbg)
    return ensure_ccw(pts)


def process_for_print(pts_mm, min_radius=MIN_RADIUS_MM, smooth_mm=SMOOTH_MM, clearance=CLEARANCE_MM):
    """Estágio 4: filete dos cantos (≥ r_min) + FOLGA (encaixe) → low-pass forte
    (remove o serrilhado da foto) → decima. A folga `clearance` (dilatação externa)
    mais que compensa o leve recuo do low-pass, garantindo pocket ⊇ ferramenta."""
    # 1) Morfologia: arredonda todo canto a ≥ r_min e dilata `clearance` (margem de
    #    encaixe). É a etapa que GARANTE o raio mínimo e empurra a borda p/ fora.
    p = enforce_min_radius(pts_mm, min_radius, closed=True, clearance=clearance)
    # 2) Low-pass forte (janela ≫ pixel): elimina o serrilhado de alta frequência da
    #    foto, preservando as features reais da peça (todas ≫ smooth_mm).
    if smooth_mm and smooth_mm > 0:
        p = lowpass_closed(p, win_mm=smooth_mm, step=0.15)
    # 3) Decima pontos redundantes (desvio ≤ ~0,02 mm) p/ um polígono leve.
    if len(p) >= 3:
        c = cv2.approxPolyDP(np.array(p, np.float32).reshape(-1, 1, 2), 0.02, True)
        p = [(float(q[0][0]), float(q[0][1])) for q in c]
    return ensure_ccw(p)


# =============================================================================
# AJUSTE DE BÉZIERS CÚBICAS (Schneider) — polyline → poucas curvas suaves
# -----------------------------------------------------------------------------
# Substitui o polyline denso/facetado por curvas de Bézier cúbicas com poucos
# nós, que PASSAM PELA MÉDIA do traço (mínimos quadrados): remove o serrilhado
# residual (menos inflexões de curvatura) e economiza pontos. É a matemática do
# "Simplify" do Inkscape — o que o usuário aplicou à mão nas curvas da lâmina.
# Cada Bézier = (p0, c1, c2, p3) em mm.
# =============================================================================
def _bernstein3(t):
    u = 1.0 - t
    return (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)


def bezier_point(bez, t):
    b0, b1, b2, b3 = bez
    c0, c1, c2, c3 = _bernstein3(t)
    return (c0 * b0[0] + c1 * b1[0] + c2 * b2[0] + c3 * b3[0],
            c0 * b0[1] + c1 * b1[1] + c2 * b2[1] + c3 * b3[1])


def _segments_cross(p1, p2, p3, p4):
    """True se os segmentos abertos p1p2 e p3p4 se cruzam ESTRITAMENTE (sem contar
    toque nas pontas) — usado p/ detectar auto-sobreposição de polilinhas/cúbicas."""
    d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
    if abs(d) < 1e-12:
        return False
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    return 1e-6 < t < 1 - 1e-6 and 1e-6 < u < 1 - 1e-6


def _cubic_is_simple(bez, nsamp=16):
    """True se a cúbica NÃO se auto-cruza (sem laço/cusp) em t∈(0,1). Amostra a curva e
    testa cruzamento de cordas não adjacentes — handles longos demais (estufamento p/
    conter) ou tangentes que discordam da corda criam um laço; aqui ele é rejeitado.
    O par de pontas compartilhadas (1ª×última corda) é ignorado: tocam-se só nos nós."""
    pts = [bezier_point(bez, k / nsamp) for k in range(nsamp + 1)]
    for i in range(len(pts) - 1):
        for j in range(i + 2, len(pts) - 1):
            if i == 0 and j == len(pts) - 2:
                continue
            if _segments_cross(pts[i], pts[i + 1], pts[j], pts[j + 1]):
                return False
    return True


def _shrink_handles(bez, factor):
    """Puxa os DOIS handles em direção à corda (alpha·factor), mantendo a DIREÇÃO das
    tangentes (preserva G1) — só encurta, então a curva anda p/ DENTRO, nunca expõe a
    peça. `factor=1` é a cúbica original; `factor→0` tende à reta da corda."""
    p0, c1, c2, p3 = bez
    return (p0,
            (p0[0] + (c1[0] - p0[0]) * factor, p0[1] + (c1[1] - p0[1]) * factor),
            (p3[0] + (c2[0] - p3[0]) * factor, p3[1] + (c2[1] - p3[1]) * factor),
            p3)


def _cap_handles(bez, cap=None):
    """Limita o comprimento de cada handle a `cap`·corda (regra de 1/3 folgada): um handle
    longo demais p/ a corda já produz laço antes mesmo do estufamento. Só ENCURTA handles
    que excedem o teto, mantendo a direção das tangentes (G1)."""
    cap = ANCHOR_HANDLE_CAP if cap is None else cap
    p0, c1, c2, p3 = bez
    L = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    if L < 1e-9:
        return bez

    def clamp(anchor, ctrl):
        vx, vy = ctrl[0] - anchor[0], ctrl[1] - anchor[1]
        d = math.hypot(vx, vy)
        if d > cap * L and d > 1e-9:
            s = cap * L / d
            return (anchor[0] + vx * s, anchor[1] + vy * s)
        return ctrl

    return (p0, clamp(p0, c1), clamp(p3, c2), p3)


def _unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-12 else (0.0, 0.0)


def _chord_params(pts):
    """Parametrização por comprimento de corda, normalizada em [0,1]."""
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = d[-1] or 1.0
    return [x / total for x in d]


def _fit_one_cubic(pts, t, that1, that2):
    """Mínimos quadrados de UMA cúbica com tangentes fixas nas pontas (Schneider)."""
    p0, p3 = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for i in range(len(pts)):
        b0, b1, b2, b3 = _bernstein3(t[i])
        a1 = (that1[0] * b1, that1[1] * b1)
        a2 = (that2[0] * b2, that2[1] * b2)
        c00 += a1[0] * a1[0] + a1[1] * a1[1]
        c01 += a1[0] * a2[0] + a1[1] * a2[1]
        c11 += a2[0] * a2[0] + a2[1] * a2[1]
        tmp = (pts[i][0] - (p0[0] * (b0 + b1) + p3[0] * (b2 + b3)),
               pts[i][1] - (p0[1] * (b0 + b1) + p3[1] * (b2 + b3)))
        x0 += a1[0] * tmp[0] + a1[1] * tmp[1]
        x1 += a2[0] * tmp[0] + a2[1] * tmp[1]
    det = c00 * c11 - c01 * c01
    seg = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    if abs(det) < 1e-12:
        alpha1 = alpha2 = seg / 3.0
    else:
        alpha1 = (x0 * c11 - c01 * x1) / det
        alpha2 = (c00 * x1 - x0 * c01) / det
    if alpha1 < 1e-6 or alpha2 < 1e-6:
        alpha1 = alpha2 = seg / 3.0
    return (p0,
            (p0[0] + that1[0] * alpha1, p0[1] + that1[1] * alpha1),
            (p3[0] + that2[0] * alpha2, p3[1] + that2[1] * alpha2),
            p3)


def _max_error(pts, t, bez):
    dmax, idx = 0.0, len(pts) // 2
    for i in range(len(pts)):
        bp = bezier_point(bez, t[i])
        d = math.hypot(bp[0] - pts[i][0], bp[1] - pts[i][1])
        if d > dmax:
            dmax, idx = d, i
    return dmax, idx


def _fit_cubic_recursive(pts, that1, that2, tol, out, depth=0):
    if len(pts) < 2:
        return
    if len(pts) == 2:
        seg = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]) / 3.0
        out.append((pts[0],
                    (pts[0][0] + that1[0] * seg, pts[0][1] + that1[1] * seg),
                    (pts[1][0] + that2[0] * seg, pts[1][1] + that2[1] * seg),
                    pts[1]))
        return
    t = _chord_params(pts)
    bez = _fit_one_cubic(pts, t, that1, that2)
    err, idx = _max_error(pts, t, bez)
    if err < tol or depth > 16 or idx <= 0 or idx >= len(pts) - 1:
        out.append(bez)
        return
    tc = _unit((pts[idx + 1][0] - pts[idx - 1][0], pts[idx + 1][1] - pts[idx - 1][1]))
    _fit_cubic_recursive(pts[:idx + 1], that1, (-tc[0], -tc[1]), tol, out, depth + 1)
    _fit_cubic_recursive(pts[idx:], tc, that2, tol, out, depth + 1)


def _corner_indices(rp, angle_thresh, win):
    """Índices de cantos (cusp) por ângulo de virada acumulado numa janela ±win."""
    n = len(rp)
    flags = [False] * n
    for i in range(n):
        a, b, c = rp[(i - win) % n], rp[i], rp[(i + win) % n]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        cr = v1[0] * v2[1] - v1[1] * v2[0]
        if math.degrees(math.atan2(abs(cr), dot)) >= angle_thresh:
            flags[i] = True
    if all(flags):                            # degenerado (todo o contorno "vira")
        return [0]
    # NMS circular: ancora num ponto FORA de canto p/ não partir um grupo na emenda.
    start = flags.index(False)
    order = list(range(start, n)) + list(range(0, start))
    corners, i = [], 0
    while i < n:
        if flags[order[i]]:
            grp = [order[i]]
            i += 1
            while i < n and flags[order[i]]:
                grp.append(order[i])
                i += 1
            corners.append(grp[len(grp) // 2])
        else:
            i += 1
    return sorted(corners)


def fit_closed_beziers(poly, tol=FIT_TOL_MM, corner_angle=CORNER_ANGLE_DEG, step=0.4):
    """Ajusta o contorno fechado por Béziers cúbicas: corta em cantos (cusp) e fita
    cada trecho por mínimos quadrados recursivos. Devolve lista de (p0,c1,c2,p3)."""
    rp = resample_uniform(poly, step, closed=True)
    n = len(rp)
    if n < 4:
        return []
    corners = _corner_indices(rp, corner_angle, max(1, int(round(1.2 / step))))
    if len(corners) < 2:                      # contorno liso: fecha em 2 pontos opostos
        corners = [0, n // 2]
    cubics = []
    m = len(corners)
    for k in range(m):
        i0, i1 = corners[k], corners[(k + 1) % m]
        seg = rp[i0:i1 + 1] if i1 > i0 else rp[i0:] + rp[:i1 + 1]
        if len(seg) < 2:
            continue
        t1 = _unit((seg[1][0] - seg[0][0], seg[1][1] - seg[0][1]))
        t2 = _unit((seg[-2][0] - seg[-1][0], seg[-2][1] - seg[-1][1]))
        _fit_cubic_recursive(seg, t1, t2, tol, cubics)
    return cubics


def flatten_beziers(cubics, seg=16):
    """Achata uma lista de cúbicas numa polilinha fechada (p/ métricas/checagem)."""
    out = []
    for bez in cubics:
        for i in range(seg):
            out.append(bezier_point(bez, i / seg))
    return out


# -----------------------------------------------------------------------------
# Ajuste de Béziers com RESTRIÇÃO DE CONTENÇÃO (one-sided): o MÍNIMO de curvas tal
# que o contorno nunca invade a ferramenta (a peça cabe). A recursão divide um
# trecho SÓ quando a cúbica penetraria o "piso" (silhueta + folga de encaixe) —
# não por tolerância. Cada trecho entre cantos vira 1 Bézier, ganhando mais só
# onde a curvatura real exige para não cortar a peça.
# -----------------------------------------------------------------------------
def _floor_field(silhouette, c_fit, ppm):
    """Mapa de profundidade-para-dentro do piso (silhueta dilatada por `c_fit`):
    para um ponto, quão FUNDO ele está dentro da peça+folga, em mm. Devolve
    (dt, ppm, ox, oy)."""
    min_x, min_y, max_x, max_y = bbox(silhouette)
    pad = c_fit + 3.0
    ox, oy = min_x - pad, min_y - pad
    w = int(math.ceil((max_x - min_x + 2 * pad) * ppm))
    h = int(math.ceil((max_y - min_y + 2 * pad) * ppm))
    poly = [((x - ox) * ppm, (y - oy) * ppm) for (x, y) in silhouette]
    mask = _polys_to_mask([poly], w, h)
    if c_fit > 0:
        cr = max(1, int(round(c_fit * ppm)))
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * cr + 1, 2 * cr + 1)))
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 3)   # profundidade p/ dentro (px)
    return dt, ppm, ox, oy


def _max_penetration(bez, field, nsamp):
    """Maior penetração (mm) da cúbica no piso + parâmetro t do pior ponto."""
    dt, ppm, ox, oy = field
    H, W = dt.shape
    worst, ti = 0.0, 0.5
    for i in range(nsamp + 1):
        t = i / nsamp
        x, y = bezier_point(bez, t)
        px = int(round((x - ox) * ppm))
        py = int(round((y - oy) * ppm))
        if 0 <= px < W and 0 <= py < H:
            d = float(dt[py, px]) / ppm
            if d > worst:
                worst, ti = d, t
    return worst, ti


def _beziers_max_penetration(cubics, field):
    """Maior penetração (mm) de QUALQUER cúbica no piso de contenção."""
    worst = 0.0
    for bez in cubics:
        rough = (math.hypot(bez[1][0] - bez[0][0], bez[1][1] - bez[0][1]) +
                 math.hypot(bez[2][0] - bez[1][0], bez[2][1] - bez[1][1]) +
                 math.hypot(bez[3][0] - bez[2][0], bez[3][1] - bez[2][1]))
        pen, _ = _max_penetration(bez, field, max(12, int(rough / PEN_SAMPLE_MM)))
        if pen > worst:
            worst = pen
    return worst


# Tolerâncias testadas (grande→pequena): a MAIOR que ainda contém a peça vence.
_FIT_TOL_GRID = (3.0, 2.4, 2.0, 1.6, 1.3, 1.0, 0.8, 0.6, 0.45, 0.3, 0.2)


def fit_closed_beziers_contained(guide, silhouette, c_fit=0.3, eps=0.06, ppm=10.0):
    """MÍNIMO de Béziers tal que a peça cabe: escolhe a MAIOR tolerância de ajuste
    cuja curva não penetra a peça+`c_fit` além de `eps` (mais tolerância = menos
    nós). Usa o ajuste por tolerância (`fit_closed_beziers`), que é bem-comportado
    (não estufa para fora) — só varia a quantidade de curvas."""
    g = dedup_closing_point(guide)
    field = _floor_field(silhouette, c_fit, ppm)
    for tol in sorted(_FIT_TOL_GRID, reverse=True):
        cub = fit_closed_beziers(g, tol=tol)
        if cub and _beziers_max_penetration(cub, field) <= eps:
            return cub
    return fit_closed_beziers(g, tol=min(_FIT_TOL_GRID))


# -----------------------------------------------------------------------------
# Ajuste ANCORADO NAS EXTREMIDADES (ideia do usuário) — o MELHOR p/ impressão 3D:
#   1) Fixa âncoras nos pontos MAIS DISTANTES do objeto (vértices do fecho convexo,
#      simplificados). Ancorar nas extremidades GARANTE que a peça cabe: a cavidade
#      alcança o bico, o calcanhar e os cantos.
#   2) Entre âncoras, traça cúbicas CONTIDAS (nunca cortam a peça), suaves — evita
#      mudanças de direção bruscas, fácil de imprimir.
# Resultado: poucos nós, contorno justo e limpo, contendo a ferramenta.
# -----------------------------------------------------------------------------
def douglas_peucker_idx(pts, eps):
    """RDP sobre a CADEIA ABERTA pts[0..n-1] → lista ordenada dos ÍNDICES mantidos
    (cantos dominantes; descarta pontos quase-colineares). Os dois extremos ficam
    sempre e a aresta de fechamento n-1→0 NÃO é simplificada — suficiente p/ o uso
    (destilar o fecho convexo nas extremidades dominantes), não um RDP circular."""
    n = len(pts)
    if n <= 3:
        return list(range(n))
    keep = {0, n - 1}

    def rec(a, b):
        dmax, idx = 0.0, -1
        for i in range(a + 1, b):
            d = _dist_point_seg(pts[i], pts[a], pts[b])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps and idx != -1:
            keep.add(idx)
            rec(a, idx)
            rec(idx, b)

    rec(0, n - 1)
    return sorted(keep)


def hull_anchor_indices(rp, simplify_mm=ANCHOR_SIMPLIFY_MM):
    """Índices em `rp` das EXTREMIDADES dominantes: vértices do fecho convexo,
    destilados por RDP (`simplify_mm`) p/ remover os quase-colineares das bordas
    retas. São os pontos mais distantes do objeto — ancorar neles garante caber."""
    pts = np.asarray(rp, np.float32).reshape(-1, 1, 2)
    hidx = sorted(int(i) for i in cv2.convexHull(pts, returnPoints=False).flatten())
    if len(hidx) <= 3:
        return hidx
    hull_pts = [rp[i] for i in hidx]
    keep = douglas_peucker_idx(hull_pts, simplify_mm)
    return sorted(hidx[j] for j in keep)


def _fit_segment_contained(seg, that1, that2, field, eps, out):
    """Ajusta o trecho [âncora→âncora] pela MAIOR tolerância cuja cúbica não penetra
    o piso além de `eps`: 1 curva onde a peça é lisa, mais só onde a forma exige."""
    chosen, tmp = None, []
    for tol in sorted(_FIT_TOL_GRID, reverse=True):
        tmp = []
        _fit_cubic_recursive(seg, that1, that2, tol, tmp)
        if _beziers_max_penetration(tmp, field) <= eps:
            chosen = tmp
            break
    out.extend(chosen if chosen is not None else tmp)


def _anchor_tangents(rp, anchors):
    """Tangente SUAVE em cada âncora = direção de marcha do contorno ali (corda pelos
    vizinhos imediatos no `rp`). Usar a MESMA tangente nos dois trechos que se encontram
    numa âncora torna o nó SUAVE (G1, sem bico) — assim TODO nó do contorno fica liso."""
    n = len(rp)
    return {i: _unit((rp[(i + 1) % n][0] - rp[(i - 1) % n][0],
                      rp[(i + 1) % n][1] - rp[(i - 1) % n][1])) for i in anchors}


def _anchor_segments(rp, anchors, tang):
    """Quebra o contorno reamostrado `rp` nos trechos âncora→âncora. Cada trecho vira
    um (pontos, tangente_inicial, tangente_final) que ajusta para UMA cúbica suave: a
    tangente em cada âncora é COMPARTILHADA com o trecho vizinho → nó G1 (sem bico)."""
    m = len(anchors)
    segs = []
    for k in range(m):
        i0, i1 = anchors[k], anchors[(k + 1) % m]
        seg = rp[i0:i1 + 1] if i1 > i0 else rp[i0:] + rp[:i1 + 1]
        if len(seg) < 2:
            continue
        segs.append((seg, tang[i0], (-tang[i1][0], -tang[i1][1])))
    return segs


def _quadrant_anchors(rp, min_dist_mm=ANCHOR_MIN_DIST_MM):
    """Âncoras BALANCEADAS POR QUADRANTE p/ um pocket que CONTÉM a peça (encaixe num case
    3D). Divide a peça em 4 quadrantes (sinal de x-cx, y-cy em torno do MEIO da bbox) e, em
    cada um, ancora os pontos MAIS EXTERNOS (maior distância ao centro = as extremidades que
    TÊM de caber), das pontas p/ dentro, com a ÚNICA restrição de que âncoras DO MESMO
    QUADRANTE fiquem a ≥ `min_dist_mm` umas das outras — assim a 1ª é a ponta, a 2ª/3ª caem
    ~`min_dist_mm` adiante (espalhadas pelas bordas, sem aglomerar na ponta). NÃO há teto:
    a quantidade de âncoras emerge só do espaçamento — `min_dist_mm` MENOR = mais âncoras
    (pocket mais justo), MAIOR = menos (mais folgado). Devolve índices em `rp` ordenados ao
    longo do contorno."""
    xs = [p[0] for p in rp]
    ys = [p[1] for p in rp]
    cx = 0.5 * (min(xs) + max(xs))               # centro = meio da bbox ("divide ao meio")
    cy = 0.5 * (min(ys) + max(ys))
    quads = [(True, True), (False, True), (False, False), (True, False)]
    md2 = min_dist_mm * min_dist_mm
    kept = []
    for q in quads:
        cand = sorted(((  (rp[i][0] - cx) ** 2 + (rp[i][1] - cy) ** 2, i)
                       for i in range(len(rp)) if (rp[i][0] >= cx, rp[i][1] >= cy) == q),
                      reverse=True)                # mais externos primeiro
        sel = []
        for _d2, i in cand:                        # TODOS os que respeitam o espaçamento
            if all((rp[i][0] - rp[k][0]) ** 2 + (rp[i][1] - rp[k][1]) ** 2 >= md2
                   for k in sel):                  # ≥ min_dist das já escolhidas do quadrante
                sel.append(i)
        kept.extend(sel)
    return sorted(kept)


def cubic_roots(A, B, C, D):
    roots = []
    if abs(A) < 1e-9:
        if abs(B) < 1e-9:
            if abs(C) > 1e-9:
                t = -D / C
                if 0 <= t <= 1: roots.append(t)
            return roots
        det = C*C - 4*B*D
        if det >= 0:
            t1 = (-C + math.sqrt(det)) / (2*B)
            t2 = (-C - math.sqrt(det)) / (2*B)
            for t in (t1, t2):
                if 0 <= t <= 1: roots.append(t)
        return roots
        
    p = (3*A*C - B*B) / (3*A*A)
    q = (2*B*B*B - 9*A*B*C + 27*A*A*D) / (27*A*A*A)
    det = (q*q)/4 + (p*p*p)/27
    # Tolerância RELATIVA p/ o caso de raiz dupla: det = 0 matemático arredonda p/
    # ±~1e-19 em float e a comparação exata caía no ramo de raiz única, PERDENDO a
    # raiz dupla (um cruzamento tangente do eixo sumia em symmetrize_beziers).
    eps = 1e-12 * ((q*q)/4 + abs(p*p*p)/27) + 1e-30

    if det > eps:
        u1 = -q/2 + math.sqrt(det)
        u1 = math.copysign(abs(u1)**(1/3), u1)
        u2 = -q/2 - math.sqrt(det)
        u2 = math.copysign(abs(u2)**(1/3), u2)
        t = u1 + u2 - B/(3*A)
        roots.append(t)
    elif det >= -eps:                          # raiz dupla (det ≈ 0)
        u = math.copysign(abs(-q/2)**(1/3), -q/2)
        roots.append(2*u - B/(3*A))
        roots.append(-u - B/(3*A))
    else:
        r = math.sqrt(-(p*p*p)/27)
        phi = math.acos(max(-1.0, min(1.0, -q / (2*r))))
        rho = 2 * math.sqrt(-p/3)
        roots.append(rho * math.cos(phi/3) - B/(3*A))
        roots.append(rho * math.cos((phi + 2*math.pi)/3) - B/(3*A))
        roots.append(rho * math.cos((phi + 4*math.pi)/3) - B/(3*A))
        
    return [t for t in roots if 0 <= t <= 1]

def _get_bezier_poly(bez, axis_idx):
    p0, p1, p2, p3 = [p[axis_idx] for p in bez]
    A = -p0 + 3*p1 - 3*p2 + p3
    B = 3*p0 - 6*p1 + 3*p2
    C = -3*p0 + 3*p1
    D = p0
    return A, B, C, D

def _split_cubic(bez, t):
    p0, p1, p2, p3 = bez
    p01 = (p0[0] + t*(p1[0]-p0[0]), p0[1] + t*(p1[1]-p0[1]))
    p12 = (p1[0] + t*(p2[0]-p1[0]), p1[1] + t*(p2[1]-p1[1]))
    p23 = (p2[0] + t*(p3[0]-p2[0]), p2[1] + t*(p3[1]-p2[1]))
    p012 = (p01[0] + t*(p12[0]-p01[0]), p01[1] + t*(p12[1]-p01[1]))
    p123 = (p12[0] + t*(p23[0]-p12[0]), p12[1] + t*(p23[1]-p12[1]))
    p0123 = (p012[0] + t*(p123[0]-p012[0]), p012[1] + t*(p123[1]-p012[1]))
    return (p0, p01, p012, p0123), (p0123, p123, p23, p3)

def symmetrize_beziers(cubics, axis, c):
    if not cubics: return []
    axis_idx = 0 if axis == 'vertical' else 1
    split_cubics = []
    for bez in cubics:
        A, B, C, D = _get_bezier_poly(bez, axis_idx)
        D -= c
        roots = cubic_roots(A, B, C, D)
        valid_roots = sorted(list(set([t for t in roots if 1e-5 < t < 1 - 1e-5])))
        
        if not valid_roots:
            split_cubics.append(bez)
            continue
            
        rem = bez
        t_offset = 0.0
        for t in valid_roots:
            t_rel = (t - t_offset) / (1.0 - t_offset)
            left, right = _split_cubic(rem, t_rel)
            cross_pt = list(left[3])
            cross_pt[axis_idx] = c
            p2 = list(left[2])
            p2[1 - axis_idx] = cross_pt[1 - axis_idx]
            left = (left[0], left[1], tuple(p2), tuple(cross_pt))
            p1 = list(right[1])
            p1[1 - axis_idx] = cross_pt[1 - axis_idx]
            right = (tuple(cross_pt), tuple(p1), right[2], right[3])
            split_cubics.append(left)
            rem = right
            t_offset = t
        split_cubics.append(rem)
        
    is_right = []
    for bez in split_cubics:
        bx, by = bezier_point(bez, 0.5)
        v = bx if axis == 'vertical' else by
        is_right.append(v >= c - 1e-7)
        
    n = len(split_cubics)
    if all(is_right) or not any(is_right): return cubics

    # nº de ARCOS do lado mantido = nº de transições esquerda→direita na ordem circular.
    runs = sum(1 for i in range(n) if is_right[i] and not is_right[(i - 1) % n])
    if runs > 1:
        # O contorno cruza o eixo MAIS de 2 vezes (forma côncava através do eixo): o lado
        # mantido tem 2+ arcos e cada arco+espelho fecharia um LAÇO separado (furo/multi-
        # contorno) — não existe simetrizado de caminho ÚNICO. Devolve o contorno ORIGINAL
        # intacto (antes: só o 1º arco sobrevivia e o resto era descartado em silêncio).
        warn("simetria de Béziers ignorada: o contorno cruza o eixo de simetria mais de "
             "2 vezes — mantido o contorno sem espelhar (use só a simetria de máscara).")
        return cubics

    start_idx = 0
    for i in range(n):
        if is_right[i] and not is_right[(i - 1) % n]:
            start_idx = i
            break

    rotated = split_cubics[start_idx:] + split_cubics[:start_idx]
    rotated_is_right = is_right[start_idx:] + is_right[:start_idx]

    right_cubics = []
    for i in range(n):
        if rotated_is_right[i]: right_cubics.append(rotated[i])
        else: break
            
    left_cubics = []
    for bez in reversed(right_cubics):
        mirrored = []
        for p in reversed(bez):
            mx = 2*c - p[0] if axis == 'vertical' else p[0]
            my = 2*c - p[1] if axis == 'horizontal' else p[1]
            mirrored.append((mx, my))
        left_cubics.append(tuple(mirrored))
        
    return right_cubics + left_cubics


def _protrusion_anchors(rp, min_dev_mm, span_mm=ANCHOR_MIN_DIST_MM):
    """Âncoras de CONVEXIDADE LOCAL (saliências) que o seletor radial por quadrante
    (`_quadrant_anchors`) não pega: um ressalto no MEIO de uma aresta não é 'externo ao
    centro' como um canto, então nunca entra no orçamento — e a cúbica suave arredonda
    por cima dele. Aqui se mede, em cada ponto, o desvio CONVEXO (p/ fora) em relação à
    corda dos vizinhos a ~`span_mm` de arco; um PICO local cuja PROEMINÊNCIA (altura
    acima do desvio nas bordas da janela) seja ≥ `min_dev_mm` vira âncora. A proeminência
    (não o desvio absoluto) é o que separa um ressalto de uma curvatura suave/uniforme:
    num círculo o desvio é constante → proeminência ~0 → nada é marcado. Devolve índices
    em `rp` (ordem ao longo do contorno), sem dois picos a < `span_mm` (fica o + proeminente)."""
    n = len(rp)
    if n < 8 or min_dev_mm <= 0:
        return []
    cx = sum(p[0] for p in rp) / n
    cy = sum(p[1] for p in rp) / n
    per = sum(math.hypot(rp[(i + 1) % n][0] - rp[i][0], rp[(i + 1) % n][1] - rp[i][1])
              for i in range(n))
    k = max(2, int(round(span_mm / (per / n))))      # meia-janela da corda, em amostras
    dev = [0.0] * n
    for i in range(n):
        ax, ay = rp[(i - k) % n]
        bx, by = rp[i]
        dx, dy = rp[(i + k) % n][0] - ax, rp[(i + k) % n][1] - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        d = abs((bx - ax) * dy - (by - ay) * dx) / L     # dist. perpendicular à corda
        # convexo = a ponta está MAIS LONGE do centro que o meio da corda (bojo p/ fora)
        if math.hypot(bx - cx, by - cy) > math.hypot(ax + 0.5 * dx - cx,
                                                      ay + 0.5 * dy - cy):
            dev[i] = d
    cand = []
    for i in range(n):
        if dev[i] < min_dev_mm:
            continue
        if not all(dev[i] >= dev[(i + j) % n] for j in range(-k, k + 1)):
            continue                                     # tem de ser máximo local
        prom = dev[i] - min(dev[(i - k) % n], dev[(i + k) % n])   # altura sobre a janela
        if prom >= min_dev_mm:
            cand.append((prom, i))
    cand.sort(reverse=True)                              # mais proeminentes primeiro
    chosen = []
    for _prom, i in cand:                                # supressão de não-máximos por arco
        if all(min((i - j) % n, (j - i) % n) >= k for j in chosen):
            chosen.append(i)
    return sorted(chosen)


def _preserve_spikes(raw, smoothed, min_dev_mm=PROTRUSION_DEV_MM, span_mm=ANCHOR_MIN_DIST_MM):
    """Reinjeta na curva SUAVIZADA os espigões convexos REAIS da curva crua (v0.6, caso
    "gancho da trena"): o low-pass do `smooth_mm` RECUA a ponta de uma protuberância fina
    antes da seleção de âncoras — o piso de contenção nasce sem ela e o pocket corta o
    topo do espigão sem que o `contém` mal se mova. Os picos vêm de `_protrusion_anchors`
    sobre a curva CRUA (proeminência ≥ `min_dev_mm`) e um pico só é restaurado se for
    mesmo ESPIGÃO, com dois filtros medidos no trecho contíguo p/ FORA do suavizado
    (≥ 0.1 mm além, pela distância ao centróide):
    • recuo da ponta ≥ SPIKE_MIN_RECEDE_MM — pico de serrilha recua ~0.1-0.2 mm; restaurá-lo
      só reinjetaria o ruído que o smooth-mm removeu;
    • boca da base ≤ SPIKE_MAX_WIDTH_MM — canto/curvatura macro tem boca larga; seu recuo é
      o arredondamento LEGÍTIMO p/ impressão, não perda de feature.
    `raw` e `smoothed` pareiam índice-a-índice (mesmo passo de reamostragem — o mesmo
    pareamento de `boundary_roughness`)."""
    n = min(len(raw), len(smoothed))
    if n < 8 or min_dev_mm <= 0:
        return smoothed
    peaks = _protrusion_anchors(raw[:n], min_dev_mm, span_mm=span_mm)
    if not peaks:
        return smoothed
    raw = raw[:n]
    out = list(smoothed[:n])
    cx = sum(p[0] for p in raw) / n
    cy = sum(p[1] for p in raw) / n

    def outward(i):
        return (math.hypot(raw[i][0] - cx, raw[i][1] - cy)
                - math.hypot(out[i][0] - cx, out[i][1] - cy))

    for pk in peaks:
        if outward(pk) < SPIKE_MIN_RECEDE_MM:
            continue                            # o suavizado praticamente cobre este pico
        lo = pk                                 # varre as duas flancas até voltar p/ dentro
        while True:
            j = (lo - 1) % n
            if j == pk or outward(j) < 0.1:
                break
            lo = j
        hi = pk
        while True:
            j = (hi + 1) % n
            if j == pk or outward(j) < 0.1:
                break
            hi = j
        mouth = math.hypot(raw[lo][0] - raw[hi][0], raw[lo][1] - raw[hi][1])
        if mouth > SPIKE_MAX_WIDTH_MM:
            continue                            # base larga = canto/curvatura, não espigão
        i = lo
        while True:                             # restaura o trecho cru lo..hi
            out[i] = raw[i]
            if i == hi:
                break
            i = (i + 1) % n
    return out


def _one_cubic_contained(seg, field, eps):
    """UMA cúbica suave para o trecho que NÃO corta a peça. Parte do ajuste por mínimos
    quadrados (honra as tangentes das pontas → nó G1) e, se penetrar o piso além de
    `eps`, ESTUFA p/ fora alongando os handles em torno das âncoras — mantém a DIREÇÃO
    das tangentes (segue G1) e empurra a curva p/ fora até conter a peça. Garante o
    requisito do pocket: a peça cabe (a forma só fica do tamanho real ou maior, nunca
    cortando p/ dentro). Devolve a de menor penetração se nem a estufada máxima contiver.

    GUARDA DE SIMPLICIDADE (v0.4): o ajuste base tem o handle LIMITADO a `ANCHOR_HANDLE_CAP`·
    corda (handle longo demais já nasce laçado) e, no estufamento, candidatos que se
    AUTO-CRUZAM (`_cubic_is_simple` falso) são rejeitados — prefere-se o simples que contém;
    se nenhum simples contém, o simples de menor penetração (um laço nunca é resposta: a curva
    só pode estar do tamanho real ou maior, então o trecho simples ainda contém ~a peça)."""
    pts, t1, t2 = seg
    p0, c1, c2, p3 = _cap_handles(_fit_one_cubic(pts, _chord_params(pts), t1, t2))
    best_bez, best_pen = None, float("inf")            # melhor SIMPLES (não-laçado)
    fallback_bez, fallback_pen = None, float("inf")    # melhor de todos (se nenhum simples)
    for scale in (1.0, 1.25, 1.6, 2.0, 2.6, 3.4, 4.5, 6.0):
        bez = (p0,
               (p0[0] + (c1[0] - p0[0]) * scale, p0[1] + (c1[1] - p0[1]) * scale),
               (p3[0] + (c2[0] - p3[0]) * scale, p3[1] + (c2[1] - p3[1]) * scale),
               p3)
        pen = _beziers_max_penetration([bez], field)
        if pen < fallback_pen:
            fallback_pen, fallback_bez = pen, bez
        if not _cubic_is_simple(bez):                  # rejeita laço/cusp
            continue
        if pen <= eps:
            return bez
        if pen < best_pen:
            best_pen, best_bez = pen, bez
    return best_bez if best_bez is not None else fallback_bez


# =============================================================================
# PRIMITIVAS (v0.10): retas e arcos detectados no contorno reamostrado — compressão
# "CAD-like" do pocket: aresta reta vira UMA reta, canto vira arco tangente, e as
# âncoras por quadrante ficam só p/ os trechos LIVRES (forma orgânica).
# =============================================================================
def _seg_pts(rp, i0, i1):
    """Pontos `i0..i1` (inclusivo) do polígono FECHADO `rp`; `i1` pode passar de n."""
    n = len(rp)
    return [rp[k % n] for k in range(i0, i1 + 1)]


def _chord_dev(a, b, seg):
    """Desvio perpendicular MÁXIMO dos pontos `seg` à reta a→b (mm)."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ux, uy)
    if L < 1e-9:
        return 0.0
    s = np.asarray(seg, np.float64)
    return float(np.max(np.abs((s[:, 0] - a[0]) * uy - (s[:, 1] - a[1]) * ux)) / L)


def _circle_fit(seg):
    """Círculo por mínimos quadrados (Kasa). Devolve `(cx, cy, r, resíduo_máx)` ou
    None se degenerado (colinear demais / raio imaginário)."""
    s = np.asarray(seg, np.float64)
    x, y = s[:, 0], s[:, 1]
    A = np.column_stack([x, y, np.ones(len(s))])
    b = -(x * x + y * y)
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = -sol[0] / 2.0, -sol[1] / 2.0
    r2 = cx * cx + cy * cy - sol[2]
    if not np.isfinite(r2) or r2 <= 0:
        return None
    r = math.sqrt(r2)
    res = np.abs(np.hypot(x - cx, y - cy) - r)
    return cx, cy, r, float(res.max())


def _refit_center_fixed_r(seg, r, cx, cy, iters=3):
    """Reajusta SÓ o centro do círculo com raio FIXO `r` (prior do usuário): ponto
    fixo de Gauss–Newton — o centro vira a média de `p - r·û(p−c)`. Devolve
    `(cx, cy, resíduo_máx)`."""
    s = np.asarray(seg, np.float64)
    for _ in range(iters):
        dx, dy = s[:, 0] - cx, s[:, 1] - cy
        d = np.hypot(dx, dy)
        d[d < 1e-9] = 1e-9
        cx = float(np.mean(s[:, 0] - r * dx / d))
        cy = float(np.mean(s[:, 1] - r * dy / d))
    res = np.abs(np.hypot(s[:, 0] - cx, s[:, 1] - cy) - r)
    return cx, cy, float(res.max())


def _arc_check(seg, tol_mm, r_prior_mm=0.0):
    """`seg` é um ARCO de verdade? Exige: resíduo radial < tol, raio plausível
    (`ARC_R_MIN_MM..ARC_R_MAX_MM`) e varredura angular MONÓTONA de 10°–350° (não é
    serpentina que por acaso tangencia o círculo). Devolve `(cx, cy, r, sigma)` com
    `sigma` = sentido (+1 anti-horário em torno do centro), ou None.

    `r_prior_mm` > 0 (v0.13, flag --corner-radius): raio MEDIDO pelo usuário. Arco
    aceito cujo raio livre cai na janela ±max(1 mm, 20%) do prior é REFIT com o raio
    FIXO (só o centro) e aceito com tolerância frouxa (2×) — a medida do usuário vence
    o viés da segmentação. Fora da janela, o arco não é o canto descrito: fica livre."""
    if len(seg) < 5:
        return None
    fit = _circle_fit(seg)
    if fit is None:
        return None
    cx, cy, r, res = fit
    if res >= tol_mm or not (ARC_R_MIN_MM <= r <= ARC_R_MAX_MM):
        return None
    s = np.asarray(seg, np.float64)
    ang = np.unwrap(np.arctan2(s[:, 1] - cy, s[:, 0] - cx))
    sweep = ang[-1] - ang[0]
    if not (math.radians(10) <= abs(sweep) <= math.radians(350)):
        return None
    dif = np.diff(ang)
    if np.count_nonzero(np.sign(dif) == np.sign(sweep)) < 0.9 * len(dif):
        return None
    # GIRO por ponto ~constante (≈ passo/r): um CANTO engolido (bico arredondado pelo
    # low-pass) gira 20–30° num único ponto e passaria no resíduo — o círculo grande
    # tangencia as duas flancas. Sem isto, arcos atravessam bicos/vales e as tangentes
    # nas fronteiras saem erradas (caso estrela).
    d = np.diff(s, axis=0)
    turn = np.abs(np.arctan2(d[:-1, 0] * d[1:, 1] - d[:-1, 1] * d[1:, 0],
                             (d[:-1] * d[1:]).sum(axis=1)))
    step_local = float(np.median(np.hypot(d[:, 0], d[:, 1])))
    if float(turn.max()) > max(3.0 * step_local / r, 0.12):
        return None
    sg = 1.0 if sweep > 0 else -1.0
    if r_prior_mm and abs(r - r_prior_mm) <= max(1.0, 0.2 * r_prior_mm):
        cx2, cy2, res2 = _refit_center_fixed_r(seg, r_prior_mm, cx, cy)
        if res2 < 2.0 * tol_mm:
            return cx2, cy2, r_prior_mm, sg
    return cx, cy, r, sg


def _detect_line_runs(rp, step, tol_mm=LINE_TOL_MM, min_len_mm=LINE_MIN_MM):
    """Trechos RETOS maximais do polígono fechado `rp` (reamostrado a `step` mm):
    cresce cada trecho enquanto TODOS os pontos desviam < `tol_mm` da corda; aceita se
    ≥ `min_len_mm`. VETO POR CÍRCULO: se um círculo de raio plausível ajusta o trecho
    bem melhor que a corda, é arco — rejeita (círculo grande não vira polígono). Runs
    colineares adjacentes são FUNDIDOS (uma aresta física = UMA reta) e cada reta tem
    as pontas RECUADAS `PRIM_TRIM_MM` (junta G1 com o vizinho). Devolve [(i0, i1)]
    ordenado; só o último run pode atravessar a emenda (i1 ≥ n)."""
    n = len(rp)
    if n < 8:
        return []
    # gira o início da varredura p/ a extremidade mais distante do centróide (um canto,
    # nunca o MEIO de uma aresta) — evita partir em dois a aresta que cruza o índice 0.
    cx = sum(p[0] for p in rp) / n
    cy = sum(p[1] for p in rp) / n
    ofs = max(range(n), key=lambda i: (rp[i][0] - cx) ** 2 + (rp[i][1] - cy) ** 2)
    rot = rp[ofs:] + rp[:ofs]
    min_pts = max(3, int(round(min_len_mm / step)))
    runs = []
    i = 0
    while i < n:
        j, best = i + 2, None
        while j <= i + n - 2:
            if _chord_dev(rot[i], rot[j % n], _seg_pts(rot, i, j)) < tol_mm:
                best = j
                j += 1
            else:
                break
        if best is None or best - i < min_pts:
            i += 1
            continue
        seg = _seg_pts(rot, i, best)
        circ = _circle_fit(seg)
        if circ is not None and ARC_R_MIN_MM <= circ[2] <= ARC_R_MAX_MM \
                and circ[3] < 0.5 * tol_mm:
            i += 1                               # arco disfarçado de reta: NÃO consome o
            continue                             # trecho — a reta real pode começar adiante
        runs.append((i, best))
        i = best
    # fusão COLINEAR de adjacentes (inclusive pela emenda): a corda da UNIÃO ainda
    # respeita a tolerância (frouxa 1.3× p/ absorver o leve abaulamento da aresta real).
    merged = True
    while merged and len(runs) > 1:
        merged = False
        out, k = [], 0
        while k < len(runs):
            a = runs[k]
            if k + 1 < len(runs):
                b = runs[k + 1]
                if b[0] - a[1] <= 2 and _chord_dev(rot[a[0] % n], rot[b[1] % n],
                                                   _seg_pts(rot, a[0], b[1])) < 1.3 * tol_mm:
                    out.append((a[0], b[1]))
                    k += 2
                    merged = True
                    continue
            out.append(a)
            k += 1
        runs = out
    if len(runs) > 1:                            # emenda circular: último ↔ primeiro
        a, b = runs[-1], runs[0]
        if (b[0] + n) - a[1] <= 2 and (b[1] + n) - a[0] <= n - 2 and \
                _chord_dev(rot[a[0] % n], rot[b[1] % n],
                           _seg_pts(rot, a[0], b[1] + n)) < 1.3 * tol_mm:
            runs = runs[1:-1] + [(a[0], b[1] + n)]
    # recuo das pontas (PRIM_TRIM_MM) — mantém o mínimo de pontos da reta
    trim = max(0, int(round(PRIM_TRIM_MM / step)))
    trimmed = []
    for (i0, i1) in runs:
        t = min(trim, (i1 - i0 - min_pts) // 2)
        if t > 0:
            i0, i1 = i0 + t, i1 - t
        trimmed.append((i0, i1))
    # de volta ao referencial original, ordenado por i0 (mod n)
    return sorted(((i0 + ofs) % n, (i0 + ofs) % n + (i1 - i0)) for (i0, i1) in trimmed)


def _detect_arc_runs(rp, step, line_runs, tol_mm=ARC_TOL_MM, r_prior_mm=CORNER_RADIUS_MM):
    """ARCOS nos vãos entre retas consecutivas (contorno inteiro se não há retas):
    tenta o vão INTEIRO como um arco (`_arc_check`); senão cresce sub-arcos gulosos.
    Fronteiras coladas (≤ 3 pontos) são SOLDADAS às vizinhas — sem nós gêmeos.
    Devolve [(i0, i1, cx, cy, r, sigma)] no mesmo referencial de `line_runs`.
    `r_prior_mm` > 0 = prior de raio do usuário (--corner-radius; ver _arc_check)."""
    n = len(rp)
    min_pts = max(4, int(round(ARC_MIN_MM / step)))
    weld = 3
    gaps = []
    if not line_runs:
        gaps = [(0, n)] if n >= min_pts else []
    else:
        m = len(line_runs)
        for k in range(m):
            g0 = line_runs[k][1]
            g1 = line_runs[(k + 1) % m][0] + (n if k + 1 == m else 0)
            if g1 - g0 >= 2:
                gaps.append((g0, g1))
    arcs = []
    for (g0, g1) in gaps:
        whole = _arc_check(_seg_pts(rp, g0, g1), tol_mm, r_prior_mm=r_prior_mm)
        if whole is not None:
            arcs.append((g0, g1) + whole)
            continue
        found = []
        i = g0
        while i <= g1 - min_pts:
            j, best = i + min_pts, None
            while j <= g1:
                got = _arc_check(_seg_pts(rp, i, j), tol_mm, r_prior_mm=r_prior_mm)
                if got is not None:
                    best = (j,) + got
                    j += 1
                elif best is not None:
                    break
                else:
                    j += 1
            if best is not None:
                found.append([i, best[0], best[1], best[2], best[3], best[4]])
                i = best[0]
            else:
                i += 1
        # solda: cola as fronteiras dos sub-arcos nos limites do vão e entre si
        for a in found:
            if a[0] - g0 <= weld:
                a[0] = g0
            if g1 - a[1] <= weld:
                a[1] = g1
        for a, b in zip(found, found[1:]):
            if 0 < b[0] - a[1] <= weld:
                a[1] = b[0]
        arcs.extend(tuple(a) for a in found)
    return arcs


def _arc_split_indices(arc, step):
    """Índices INTERNOS que dividem o arco em pedaços de ≤ ~90° de varredura (uma
    cúbica aproxima até 90° com erro desprezível; acima, laçaria/achataria)."""
    i0, i1, _cx, _cy, r, _sg = arc
    sweep_deg = math.degrees((i1 - i0) * step / max(r, 1e-9))
    parts = max(1, int(math.ceil(sweep_deg / 90.0)))
    return [i0 + (i1 - i0) * k // parts for k in range(1, parts)]


def _arc_tangent(rp, k, cx, cy, sg):
    """Tangente do círculo (cx,cy) no ponto `rp[k % n]`, no sentido de marcha `sg`."""
    v = _unit((rp[k % len(rp)][0] - cx, rp[k % len(rp)][1] - cy))
    return (-v[1] * sg, v[0] * sg)


_PRIM_COS_G1 = 0.906                             # consenso de tangentes ≈ até ~25°


def _open_corner_gaps(rp, lines, arcs, step):
    """Abre um VÃO nos CANTOS entre primitivas coladas: quando o fim de uma encosta
    (≤ 1 ponto) no início da outra com tangentes DISCORDANTES (> ~25° — bico/vale da
    peça, não junção tangente), RECUA a fronteira do lado que é ARCO — cada arco
    mantém as tangentes do próprio círculo e o canto vira um trecho livre curto,
    emitido G1 como no legado (as retas já nascem recuadas por PRIM_TRIM_MM).
    Devolve (lines, arcs) ajustados; primitiva que encolher demais é descartada
    (ex.: flancos curtos de um espigão em V — a região volta ao legado, que o
    contém melhor que retas com tangente envenenada pelo bico)."""
    pull = max(2, int(round(PRIM_TRIM_MM / step)))
    min_arc = max(4, int(round(ARC_MIN_MM / step)))
    min_line = max(3, int(round(LINE_MIN_MM / step)))
    n = len(rp)
    prims = sorted([["line", i0, i1, None] for (i0, i1) in lines] +
                   [["arc", a[0], a[1], a[2:]] for a in arcs], key=lambda p: p[1] % n)
    m = len(prims)
    for k in range(m):
        a, b = prims[k], prims[(k + 1) % m]
        b0 = b[1] + (n if k + 1 == m else 0)
        if b0 - a[2] > 1:
            continue                             # já há vão (canto/trecho livre)
        ta = (_unit((rp[a[2] % n][0] - rp[a[1] % n][0], rp[a[2] % n][1] - rp[a[1] % n][1]))
              if a[0] == "line" else _arc_tangent(rp, a[2], a[3][0], a[3][1], a[3][3]))
        tb = (_unit((rp[b[2] % n][0] - rp[b[1] % n][0], rp[b[2] % n][1] - rp[b[1] % n][1]))
              if b[0] == "line" else _arc_tangent(rp, b[1], b[3][0], b[3][1], b[3][3]))
        if ta[0] * tb[0] + ta[1] * tb[1] >= _PRIM_COS_G1:
            continue                             # tangentes concordam: junção G1 direta
        a[2] -= pull
        b[1] += pull
    lines2 = [(p[1], p[2]) for p in prims
              if p[0] == "line" and p[2] - p[1] >= min_line]
    arcs2 = [(p[1], p[2]) + p[3] for p in prims
             if p[0] == "arc" and p[2] - p[1] >= min_arc]
    return lines2, arcs2


def _fit_primitives(rp, field, eps, lines, arcs, min_dist_mm, step,
                    r_prior_mm=CORNER_RADIUS_MM):
    """Emissão do pocket COM primitivas: âncoras = pontas de reta/arco (+ divisões de
    arco > 90°) + âncoras de quadrante/saliência dos trechos LIVRES. Tangente nas
    pontas = direção da primitiva (reta: corda; arco: tangente do círculo) → junção
    G1. Pontas de RETA são DESLOCADAS p/ fora pelo desvio residual máximo (a corda
    vira reta-suporte externa: contenção garantida — estufar uma cúbica colinear não
    a move de lado). Cada trecho vira UMA `_one_cubic_contained`, como sempre.
    Arco COLADO no prior (--corner-radius; raio == `r_prior_mm`): as pontas são
    PROJETADAS radialmente no círculo declarado — só quando o movimento é p/ FORA
    (p/ dentro penetraria a peça) e sem sobrepor o deslocamento de ponta de reta."""
    n = len(rp)
    lines, arcs = _open_corner_gaps(rp, lines, arcs, step)
    covered = [False] * n
    for (i0, i1) in lines:
        for k in range(i0 + 1, i1):
            covered[k % n] = True
    for a in arcs:
        for k in range(a[0] + 1, a[1]):
            covered[k % n] = True
    bounds = set()
    want, pos_over = {}, {}                      # want: nó → tangentes DESEJADAS pelas primitivas
    line_dir = {}                                # nó que é ponta de RETA → direção da reta
    for (i0, i1) in lines:
        a, b = rp[i0 % n], rp[i1 % n]
        u = _unit((b[0] - a[0], b[1] - a[1]))
        nh = (u[1], -u[0])                       # CCW: p/ FORA = direita da marcha
        s = np.asarray(_seg_pts(rp, i0, i1), np.float64)
        sign = (s[:, 0] - a[0]) * u[1] - (s[:, 1] - a[1]) * u[0]   # >0 = lado de FORA
        d_out = max(0.0, float(sign.max()))      # quanto a peça abaúla além da corda
        for k, p in ((i0 % n, a), (i1 % n, b)):
            bounds.add(k)
            want.setdefault(k, []).append(u)
            line_dir[k] = u
            pos_over[k] = (p[0] + nh[0] * d_out, p[1] + nh[1] * d_out)
    for arc in arcs:
        i0, i1, cx, cy, _r, sg = arc
        snapped = bool(r_prior_mm) and _r == r_prior_mm
        for k in [i0, i1] + _arc_split_indices(arc, step):
            km = k % n
            bounds.add(km)
            want.setdefault(km, []).append(_arc_tangent(rp, km, cx, cy, sg))
            if snapped and km not in pos_over:
                p = rp[km]
                d = math.hypot(p[0] - cx, p[1] - cy)
                if 1e-9 < d < _r:                # projeta SÓ p/ fora (contenção)
                    pos_over[km] = (cx + (p[0] - cx) * _r / d,
                                    cy + (p[1] - cy) * _r / d)
    # Tangente por nó: a da primitiva quando há CONSENSO (junção tangente: reta↔arco
    # do filete, arcos encadeados — após `_open_corner_gaps`, a regra geral). Se ainda
    # houver DISCÓRDIA (> ~25°) num nó, fica a tangente de MARCHA do legado — o
    # compromisso arredondado que o estufamento contém, G1 preservado.
    tang_over = {}
    for km, dirs in want.items():
        if all(dirs[a][0] * dirs[b][0] + dirs[a][1] * dirs[b][1] >= _PRIM_COS_G1
               for a in range(len(dirs)) for b in range(a + 1, len(dirs))):
            # RETA manda no consenso (é rígida — girar a tangente a entortaria em S);
            # o arco vizinho absorve a diferença. Só arcos: média das tangentes.
            tang_over[km] = line_dir.get(km) or \
                _unit((sum(d[0] for d in dirs), sum(d[1] for d in dirs)))
    prot = _protrusion_anchors(rp, PROTRUSION_DEV_MM, span_mm=min_dist_mm)
    radial = _quadrant_anchors(rp, min_dist_mm=min_dist_mm)
    free = {a for a in set(radial) if not covered[a]
            and all(min((a - b) % n, (b - a) % n) > 2 for b in bounds)}
    # Saliência é SAGRADA (espigão fino/pega lateral): entra mesmo colada/coberta —
    # sem a âncora da ponta o filete atalharia por cima dela (mesma razão do legado).
    free |= {a for a in set(prot) if a not in bounds}
    anchors = sorted(bounds | free)
    if len(anchors) < 2:
        anchors = [0, n // 2]
    tang = _anchor_tangents(rp, anchors)
    tang.update(tang_over)
    segs = []
    m = len(anchors)
    for k in range(m):
        i0, i1 = anchors[k], anchors[(k + 1) % m]
        seg = rp[i0:i1 + 1] if i1 > i0 else rp[i0:] + rp[:i1 + 1]
        if len(seg) < 2:
            continue
        seg = list(seg)
        if i0 in pos_over:
            seg[0] = pos_over[i0]
        if i1 in pos_over:
            seg[-1] = pos_over[i1]
        segs.append((seg, tang[i0], (-tang[i1][0], -tang[i1][1])))
    return [_one_cubic_contained(s, field, eps) for s in segs]


def _poly_step(rp):
    """Passo médio (mm) do polígono fechado reamostrado uniformemente."""
    n = len(rp)
    per = sum(math.hypot(rp[(i + 1) % n][0] - rp[i][0], rp[(i + 1) % n][1] - rp[i][1])
              for i in range(n))
    return per / n if n else 0.0


def _fit_anchored(rp, field, eps, min_dist_mm=ANCHOR_MIN_DIST_MM,
                  line_tol_mm=LINE_TOL_MM, arc_tol_mm=ARC_TOL_MM,
                  corner_radius_mm=CORNER_RADIUS_MM):
    """Âncoras BALANCEADAS POR QUADRANTE (ver `_quadrant_anchors`): as extremidades de cada
    setor angular, espaçadas a ≥ `min_dist_mm`, mais as âncoras de SALIÊNCIA local
    (`_protrusion_anchors`); entre âncoras consecutivas UMA cúbica suave CONTIDA
    (`_one_cubic_contained`, estufa p/ fora se preciso → a peça cabe). Todas G1. É o
    contorno de ENCAIXE: não busca fidelidade máxima, e sim um pocket que contém a peça e
    fica mais justo conforme `min_dist_mm` diminui (mais âncoras). SEM teto de nós.

    v0.10: com `line_tol_mm` > 0, RETAS e ARCOS detectados no contorno viram primitivas
    (ver `_fit_primitives`) e as âncoras acima regem só os trechos livres; 0 = legado."""
    n = len(rp)
    if line_tol_mm and line_tol_mm > 0:
        step = _poly_step(rp)
        lines = _detect_line_runs(rp, step, tol_mm=line_tol_mm)
        arcs = (_detect_arc_runs(rp, step, lines, tol_mm=arc_tol_mm,
                                 r_prior_mm=corner_radius_mm)
                if arc_tol_mm and arc_tol_mm > 0 else [])
        if lines or arcs:
            return _fit_primitives(rp, field, eps, lines, arcs, min_dist_mm, step,
                                   r_prior_mm=corner_radius_mm)
    prot = _protrusion_anchors(rp, PROTRUSION_DEV_MM, span_mm=min_dist_mm)
    radial = _quadrant_anchors(rp, min_dist_mm=min_dist_mm)
    anchors = sorted(set(radial) | set(prot))        # densidade ditada só por min_dist
    if len(anchors) < 2:
        anchors = [0, n // 2]
    tang = _anchor_tangents(rp, anchors)
    return [_one_cubic_contained(s, field, eps)
            for s in _anchor_segments(rp, anchors, tang)]


_BEZIER_ARC_K = 0.5522847498307936   # kappa: handle da cúbica que aproxima um arco de 90°

_SHAPE_LAST = None                   # relato do último _fit_shape_rect que RODOU (r, inflação);
                                     # None = não rodou ou caiu no fallback. O main anexa às métricas.


def _fit_shape_rect(sil, r_mm, pocket_eps=0.0):
    """Modelo paramétrico do `--shape rect` (v0.13): a peça foi DECLARADA um retângulo
    de cantos arredondados (campo --describe da skill /ptoo) → o pocket é CONSTRUÍDO
    exato em vez de ajustado estatisticamente. Pose (centro, W×H, θ) pelo
    `cv2.minAreaRect` da silhueta; contorno = 4 retas + 4 arcos de 90° de raio `r_mm`
    (piso MIN_RADIUS_MM — canto vivo declarado vira filete imprimível), tangentes em
    todo nó (G1), emitidos como cúbicas (kappa). W/H inflam UNIFORMEMENTE o mínimo p/
    conter a silhueta com penetração ≤ `pocket_eps` (SDF analítico do retângulo
    arredondado). Devolve as 8 cúbicas em CCW — ou None (com WARNING → o chamador cai
    no caminho genérico) quando a descrição não bate com a peça: inflação >
    SHAPE_INFL_MAX_MM ou vão modelo→peça > SHAPE_GAP_MM."""
    global _SHAPE_LAST
    _SHAPE_LAST = None
    pts = np.asarray([(float(x), float(y)) for (x, y) in _xy(sil)], np.float64)
    if len(pts) < 8:
        return None
    (rcx, rcy), (w, h), ang = cv2.minAreaRect(pts.astype(np.float32).reshape(-1, 1, 2))
    th = math.radians(ang)
    c, s = math.cos(th), math.sin(th)
    X = (pts[:, 0] - rcx) * c + (pts[:, 1] - rcy) * s
    Y = -(pts[:, 0] - rcx) * s + (pts[:, 1] - rcy) * c
    r = min(max(float(r_mm), MIN_RADIUS_MM), w / 2.0, h / 2.0)
    aX, aY = np.abs(X), np.abs(Y)

    def max_sdf(hw, hh):                         # SDF do retângulo arredondado (mm; >0 = fora)
        qx, qy = aX - (hw - r), aY - (hh - r)
        outer = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
        inner = np.minimum(np.maximum(qx, qy), 0.0)
        return float(np.max(outer + inner - r))

    hw, hh = w / 2.0, h / 2.0
    d = max(0.0, max_sdf(hw, hh) - pocket_eps)   # inflar ambos os semieixos por d reduz
    if d > SHAPE_INFL_MAX_MM:                    # TODO sdf positivo em ≥ d → 1 passo basta
        warn(f"--shape rect: precisaria inflar {d:.1f} mm p/ conter a peça (teto "
             f"{SHAPE_INFL_MAX_MM}) — a descrição não bate; usando o caminho genérico")
        return None
    hw, hh = hw + d, hh + d

    k = _BEZIER_ARC_K * r
    ex, ey = hw - r, hh - r                      # centros dos cantos: (±ex, ±ey)

    def line(p0, p3):                            # reta = cúbica degenerada (handles a 1/3)
        v = ((p3[0] - p0[0]) / 3.0, (p3[1] - p0[1]) / 3.0)
        return (p0, (p0[0] + v[0], p0[1] + v[1]), (p3[0] - v[0], p3[1] - v[1]), p3)

    def arc(ctr, a0_deg):                        # arco de 90° CCW a partir de a0
        a0, a1 = math.radians(a0_deg), math.radians(a0_deg + 90.0)
        p0 = (ctr[0] + r * math.cos(a0), ctr[1] + r * math.sin(a0))
        p3 = (ctr[0] + r * math.cos(a1), ctr[1] + r * math.sin(a1))
        return (p0, (p0[0] - k * math.sin(a0), p0[1] + k * math.cos(a0)),
                (p3[0] + k * math.sin(a1), p3[1] - k * math.cos(a1)), p3)

    segs = [line((-ex, -hh), (ex, -hh)), arc((ex, -ey), -90.0),   # base → canto BR
            line((hw, -ey), (hw, ey)), arc((ex, ey), 0.0),        # direita → TR
            line((ex, hh), (-ex, hh)), arc((-ex, ey), 90.0),      # topo → TL
            line((-hw, ey), (-hw, -ey)), arc((-ex, -ey), 180.0)]  # esquerda → BL

    def to_world(p):
        return (rcx + p[0] * c - p[1] * s, rcy + p[0] * s + p[1] * c)

    cubs = [tuple(to_world(q) for q in b) for b in segs]
    # Vão modelo→peça: ponto do modelo longe de QUALQUER ponto da silhueta = a peça
    # não é o shape declarado (círculo "descrito" como retângulo sobra nos cantos).
    flat = np.asarray(flatten_beziers(cubs, seg=16), np.float64)
    dif = flat[:, None, :] - pts[None, :, :]
    gap = float(np.max(np.min(np.hypot(dif[..., 0], dif[..., 1]), axis=1)))
    if gap > SHAPE_GAP_MM:
        warn(f"--shape rect: vão de {gap:.1f} mm entre o modelo e a peça (teto "
             f"{SHAPE_GAP_MM}) — a peça não parece o retângulo descrito; usando o "
             f"caminho genérico")
        return None
    _SHAPE_LAST = {"shape": "rect", "r": r, "infl": d}
    return cubs


def _self_intersecting_indices(cubics, window=8, nsamp=20):
    """Índices das cúbicas envolvidas em alguma AUTO-SOBREPOSIÇÃO do contorno fechado:
    laço próprio (`_cubic_is_simple` falso) OU cruzamento com uma vizinha a ≤ `window` de
    índice (onde os cruzamentos reais ocorrem — handles de trechos próximos se ultrapassam
    numa aresta de baixa curvatura). Ignora o TOQUE legítimo no nó compartilhado entre
    cúbicas consecutivas. Janela limitada → O(n·window), não O(n²)."""
    n = len(cubics)
    polys = [[bezier_point(b, k / nsamp) for k in range(nsamp + 1)] for b in cubics]
    bad = set()
    for i in range(n):
        if not _cubic_is_simple(cubics[i]):
            bad.add(i)
        Pi = polys[i]
        for dj in range(1, min(window, n)):
            j = (i + dj) % n
            Pj = polys[j]
            crossed = False
            for a in range(len(Pi) - 1):
                for b in range(len(Pj) - 1):
                    if dj == 1 and a == len(Pi) - 2 and b == 0:
                        continue                       # nó compartilhado i→i+1
                    if dj == n - 1 and a == 0 and b == len(Pj) - 2:
                        continue                       # nó compartilhado da emenda
                    if _segments_cross(Pi[a], Pi[a + 1], Pj[b], Pj[b + 1]):
                        crossed = True
                        break
                if crossed:
                    break
            if crossed:
                bad.add(i)
                bad.add(j)
    return bad


def _repair_self_intersections(cubics, window=8, max_iter=12):
    """Passe global anti-auto-sobreposição (v0.4): enquanto houver cúbicas que se cruzam,
    ENCURTA os handles das envolvidas em direção à corda. Handle só encurta → a curva anda
    p/ DENTRO (nunca expõe a peça além do que já estava), então a contenção se mantém. Pega
    os cruzamentos de VIZINHAS que a guarda por-segmento de `_one_cubic_contained` não
    enxerga. Converge em poucas iterações (0.7 por passo); para no teto de iterações."""
    cubs = list(cubics)
    if len(cubs) < 3:
        return cubs
    for _ in range(max_iter):
        bad = _self_intersecting_indices(cubs, window)
        if not bad:
            break
        for i in bad:
            cubs[i] = _shrink_handles(cubs[i], 0.7)
    return cubs


def fit_closed_beziers_anchored(silhouette, smooth_mm=SMOOTH_MM,
                                simplify_mm=ANCHOR_SIMPLIFY_MM, eps=ANCHOR_EPS_MM,
                                step=0.4, ppm=12.0, faithful=False,
                                min_dist_mm=ANCHOR_MIN_DIST_MM,
                                pocket_eps=POCKET_EPS_MM, symmetry='none',
                                line_tol_mm=LINE_TOL_MM, arc_tol_mm=ARC_TOL_MM,
                                shape="off", corner_radius_mm=CORNER_RADIUS_MM):
    """Ajuste com TODOS os nós SUAVES (G1), contendo a peça. Devolve lista de
    (p0,c1,c2,p3) no referencial da silhueta; o snap de bbox (depois) fixa a dimensão real.

    v0.13 (priors do --describe): `corner_radius_mm` > 0 cola os arcos detectados no
    raio MEDIDO pelo usuário (ver _arc_check); `shape='rect'` constrói o pocket como
    retângulo arredondado EXATO (ver _fit_shape_rect) — só no modo pocket (ignorado
    com `faithful`); se o modelo não bate com a peça, cai no caminho genérico.

    Dois regimes:
    • POCKET de encaixe (default, `faithful=False`): âncoras por QUADRANTE (ver
      `_fit_anchored`/`_quadrant_anchors`) — as extremidades de cada setor angular,
      espaçadas a ≥ `min_dist_mm`, cúbicas contidas que ESTUFAM p/ fora se preciso.
      Contorno de ENCAIXE (a peça cabe), mais justo conforme `min_dist_mm` diminui. SEM
      teto de nós: a densidade emerge só do espaçamento.
    • FIEL (`faithful=True`): ancora nas extremidades do fecho convexo (RDP `simplify_mm`)
      e subdivide cada trecho por contenção até caber (mais nós, contorno fiel à peça)."""
    # O low-pass denoisa a silhueta, mas RECUA a ponta de espigões finos reais —
    # `_preserve_spikes` restaura os trechos crus proeminentes ANTES do piso/âncoras.
    rp0 = resample_uniform(silhouette, 0.15, closed=True)
    clean = ensure_ccw(_preserve_spikes(rp0, lowpass_closed(rp0, win_mm=smooth_mm, step=0.15),
                                        span_mm=min_dist_mm))
    rp = resample_uniform(clean, step, closed=True)
    n = len(rp)
    if n < 4:
        return []
    modeled = None
    if shape == "rect" and not faithful:         # forma DECLARADA: modelo exato (v0.13)
        modeled = _fit_shape_rect(clean, corner_radius_mm, pocket_eps)
    if modeled is not None:
        cubics = modeled
    elif not faithful:                           # POCKET de encaixe (âncoras por quadrante)
        field = _floor_field(clean, 0.0, ppm)    # piso de contenção = peça denoisada
        cubics = _fit_anchored(rp, field, pocket_eps, min_dist_mm=min_dist_mm,
                               line_tol_mm=line_tol_mm, arc_tol_mm=arc_tol_mm,
                               corner_radius_mm=corner_radius_mm)
    else:
        # FIEL/ilimitado: âncoras do fecho convexo + subdivisão por contenção (legado).
        field = _floor_field(clean, 0.0, ppm)
        anchors = hull_anchor_indices(rp, simplify_mm=simplify_mm)
        if len(anchors) < 2:
            anchors = [0, n // 2]
        tang = _anchor_tangents(rp, anchors)         # tangente suave (marcha) por âncora
        cubics = []
        for seg, t1, t2 in _anchor_segments(rp, anchors, tang):
            _fit_segment_contained(seg, t1, t2, field, eps, cubics)

    # Modelo paramétrico já é exato e simétrico na PRÓPRIA pose; espelhar em torno do
    # eixo da bbox (que ignora a rotação da peça) o entortaria — simetria só no genérico.
    if symmetry and symmetry != 'none' and modeled is None:
        min_x, min_y, max_x, max_y = bbox(silhouette)
        if symmetry == 'both':
            cubics = symmetrize_beziers(cubics, 'vertical', 0.5 * (min_x + max_x))
            cubics = symmetrize_beziers(cubics, 'horizontal', 0.5 * (min_y + max_y))
        else:
            c = 0.5 * (min_x + max_x) if symmetry == 'vertical' else 0.5 * (min_y + max_y)
            cubics = symmetrize_beziers(cubics, symmetry, c)

    # De-loop: garante um contorno fechado SIMPLES (sem auto-cruzar) — exigência geométrica
    # do pocket (dentro/fora bem definido p/ o boolean a jusante). Roda após a simetria p/
    # também limpar cruzamentos na emenda das metades espelhadas.
    cubics = _repair_self_intersections(cubics)
    return cubics


def _scale_cubics_to_bbox(cubics, target_w, target_h):
    """Normaliza as cúbicas (por eixo, em torno do canto da bbox) p/ a bbox achatada
    ficar EXATAMENTE `target_w × target_h` — garante a dimensão real medida pela grade."""
    flat = flatten_beziers(cubics)
    min_x, min_y, max_x, max_y = bbox(flat)
    cw, ch = max_x - min_x, max_y - min_y
    sx = target_w / cw if cw > 1e-9 else 1.0
    sy = target_h / ch if ch > 1e-9 else 1.0
    return [tuple((min_x + (qx - min_x) * sx, min_y + (qy - min_y) * sy) for (qx, qy) in bez)
            for bez in cubics]


def _cubics_to_path_d(cubics, tx):
    """String 'd' do SVG (M…C…Z) de uma lista de cúbicas, aplicando o transform de
    coordenada `tx` a cada ponto. Fonte única usada pelo .svg e pelo overlay editável."""
    f = CT.fmt_mm
    start = tx(cubics[0][0])
    d = f"M {f(start[0])},{f(start[1])}"
    for (_p0, c1, c2, p3) in cubics:
        a, b, e = tx(c1), tx(c2), tx(p3)
        d += f" C {f(a[0])},{f(a[1])} {f(b[0])},{f(b[1])} {f(e[0])},{f(e[1])}"
    return d + " Z"


# A mesma silhueta + parâmetros são ajustados até 3× por execução (overlay SVG, .svg final
# e estatística do CLI). Memoiza o ÚLTIMO resultado (mantém só 1 entrada): o ajuste ancorado
# é o passo mais caro do pipeline. _scale_cubics_to_bbox não muta a lista, então é seguro
# compartilhar o resultado entre os consumidores.
_ANCHORED_CACHE = {}


def fit_anchored_cached(sil, smooth_mm=SMOOTH_MM, simplify_mm=ANCHOR_SIMPLIFY_MM,
                        faithful=False, min_dist_mm=ANCHOR_MIN_DIST_MM, pocket_eps=POCKET_EPS_MM,
                        symmetry='none', line_tol_mm=LINE_TOL_MM, arc_tol_mm=ARC_TOL_MM,
                        shape="off", corner_radius_mm=CORNER_RADIUS_MM):
    """Wrapper memoizado de `fit_closed_beziers_anchored` (mesma assinatura/retorno)."""
    key = (tuple(map(tuple, sil)), round(smooth_mm, 6), round(simplify_mm, 6),
           bool(faithful), round(min_dist_mm, 6), round(pocket_eps, 6), symmetry,
           round(line_tol_mm, 6), round(arc_tol_mm, 6),
           shape, round(corner_radius_mm, 6))
    cached = _ANCHORED_CACHE.get(key)
    if cached is None:
        cached = fit_closed_beziers_anchored(sil, smooth_mm=smooth_mm, simplify_mm=simplify_mm,
                                             faithful=faithful, min_dist_mm=min_dist_mm,
                                             pocket_eps=pocket_eps, symmetry=symmetry,
                                             line_tol_mm=line_tol_mm, arc_tol_mm=arc_tol_mm,
                                             shape=shape, corner_radius_mm=corner_radius_mm)
        _ANCHORED_CACHE.clear()
        _ANCHORED_CACHE[key] = cached
    return cached


def _fit_for_output(sil, smooth_mm=SMOOTH_MM, simplify_mm=ANCHOR_SIMPLIFY_MM,
                    faithful=False, min_dist_mm=ANCHOR_MIN_DIST_MM,
                    pocket_eps=POCKET_EPS_MM, symmetry="none",
                    line_tol_mm=LINE_TOL_MM, arc_tol_mm=ARC_TOL_MM,
                    shape="off", corner_radius_mm=CORNER_RADIUS_MM):
    """Cúbicas PRONTAS p/ emissão — fonte ÚNICA dos três consumidores (.svg final, overlay
    Inkscape e métricas do CLI), garantindo que todos usem os MESMOS parâmetros (inclusive
    `symmetry`) e a mesma chave do cache: ajuste ancorado memoizado + snap de bbox no modo
    FIEL. No POCKET não há snap (o pocket fica ≥ objeto p/ conter a peça)."""
    cub = fit_anchored_cached(sil, smooth_mm=smooth_mm, simplify_mm=simplify_mm,
                              faithful=faithful, min_dist_mm=min_dist_mm,
                              pocket_eps=pocket_eps, symmetry=symmetry,
                              line_tol_mm=line_tol_mm, arc_tol_mm=arc_tol_mm,
                              shape=shape, corner_radius_mm=corner_radius_mm)
    if cub and faithful:
        cub = _scale_cubics_to_bbox(cub, *size(sil))
    return cub


def polygon_to_svg(pts_mm, name="outline", curves=True, tol=FIT_TOL_MM,
                   silhouette=None, c_fit=0.3, anchored=True,
                   smooth_mm=SMOOTH_MM, simplify_mm=ANCHOR_SIMPLIFY_MM, faithful=False,
                   min_dist_mm=ANCHOR_MIN_DIST_MM, pocket_eps=POCKET_EPS_MM, symmetry='none',
                   line_tol_mm=LINE_TOL_MM, arc_tol_mm=ARC_TOL_MM,
                   shape="off", corner_radius_mm=CORNER_RADIUS_MM):
    """Estágio 5: SVG em mm — contorno + PREENCHIMENTO translúcido (`OUTLINE_COLOR` a
    `OUTLINE_FILL_OPACITY`, cor destacada quase transparente p/ sobrepor o objeto e
    conferir cobertura), feito SÓ de curvas de Bézier cúbicas (`C`). Com `silhouette`:
      • `anchored` (padrão): ancora nas EXTREMIDADES e traça curvas contidas (ver
        fit_closed_beziers_anchored);
      • senão: mínimo de Béziers por contenção a partir do guia `pts_mm`.
    No modo ENCAIXE (anchored e não `faithful`) NÃO se faz o snap de bbox: o pocket fica no
    tamanho métrico real e ≥ objeto (contém a peça; folga mínima do encaixe). Nos demais
    modos a bbox é fixada na dimensão real medida pela grade. Sem silhueta, ajusta por
    tolerância `tol`. `curves=False` emite o polyline cru (`L`)."""
    p = dedup_closing_point(pts_mm)
    f = CT.fmt_mm

    if not curves:
        cubics = []
    elif silhouette is not None:
        if anchored:
            # _fit_for_output faz o snap de bbox SÓ no modo fiel (no ENCAIXE o pocket
            # fica ≥ objeto, sem snap) — mesma geometria do overlay e das métricas.
            cubics = _fit_for_output(silhouette, smooth_mm=smooth_mm,
                                     simplify_mm=simplify_mm, faithful=faithful,
                                     min_dist_mm=min_dist_mm, pocket_eps=pocket_eps,
                                     symmetry=symmetry, line_tol_mm=line_tol_mm,
                                     arc_tol_mm=arc_tol_mm, shape=shape,
                                     corner_radius_mm=corner_radius_mm)
        else:
            cubics = fit_closed_beziers_contained(p, silhouette, c_fit=c_fit)
            if cubics:                            # snap p/ a dimensão real medida pela grade
                cubics = _scale_cubics_to_bbox(cubics, *size(silhouette))
    else:
        cubics = fit_closed_beziers(p, tol=tol)

    if cubics:                                # caminho normal: emite as cúbicas ajustadas
        return _svg_from_cubics(cubics, name)
    # polyline cru (--polyline): bbox da própria poligonal, sem curvas.
    min_x, min_y, max_x, max_y = bbox(p)
    w, h = max_x - min_x, max_y - min_y
    pp = [(q[0] - min_x, max_y - q[1]) for q in p]   # mm (Y p/ cima) → SVG (Y p/ baixo)
    d = "M " + " L ".join(f"{f(x)},{f(y)}" for (x, y) in pp) + " Z"
    return _svg_envelope(d, w, h, name, len(pp))


def _svg_safe_name(name):
    """Escapa `name` (vem do arquivo de entrada ou de --name) p/ inserção segura no SVG:
    escapa &<>\" e colapsa '--' (proibido dentro de comentário XML). Sem isto um nome
    hostil quebraria o documento ou injetaria markup executável (navegador roda <script>
    de SVG)."""
    s = _xml_escape(str(name), {'"': "&quot;"})
    while "--" in s:
        s = s.replace("--", "-")
    return s


def _svg_envelope(d, w, h, name, npts):
    """Monta o documento SVG (mm) em torno de um caminho `d` já no referencial SVG
    (origem topo-esq, Y p/ baixo): contorno + preenchimento translúcido na cor de
    saída. Fonte única do envelope usada pelo polyline E por `_svg_from_cubics`."""
    f = CT.fmt_mm
    name = _svg_safe_name(name)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        f'<!-- GERADO por photo_to_outline.py — contorno de {name} (mm), {npts} nós -->\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1"\n'
        f'     width="{f(w)}mm" height="{f(h)}mm" viewBox="0 0 {f(w)} {f(h)}">\n'
        f'  <path d="{d}"\n'
        f'        style="fill:{OUTLINE_COLOR};fill-opacity:{OUTLINE_FILL_OPACITY};'
        f'stroke:{OUTLINE_COLOR};stroke-width:{f(SVG_HAIRLINE_MM)};vector-effect:non-scaling-stroke"/>\n'
        f'</svg>\n'
    )


def _svg_from_cubics(cubics, name="outline"):
    """SVG (mm) a partir de uma lista de cúbicas PRONTAS `(p0,c1,c2,p3)` — sem
    reajustar nada. A bbox vem da GEOMETRIA EMITIDA (achatada) → width/height corretos.
    Usado pelo fluxo padrão (`polygon_to_svg`) e pelo modo `--edit` (curva editada à mão,
    emitida LITERALMENTE, sem snap de bbox)."""
    geo = flatten_beziers(cubics)
    min_x, min_y, max_x, max_y = bbox(geo)
    w, h = max_x - min_x, max_y - min_y

    def tx(pt):                               # mm (Y p/ cima) → SVG (origem topo-esq, Y p/ baixo)
        return (pt[0] - min_x, max_y - pt[1])

    return _svg_envelope(_cubics_to_path_d(cubics, tx), w, h, name, len(cubics))


def encode_png_b64(img):
    """Codifica uma imagem BGR (OpenCV) em base64 de PNG (string ascii, sem o prefixo
    `data:`). Fonte única — foto embutida no overlay SVG (`write_overlay_svg`) e
    tk.PhotoImage da view do editor (outline_editor)."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("falha ao codificar a imagem em PNG")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def write_overlay(rect, mask, path, flag_runs=None):
    """Grava o OVERLAY de conferência: o contorno SEGMENTADO (já com a simetria, se
    houver) desenhado em vermelho sobre a foto retificada — o "o que o tool enxergou
    da peça". Mesma resolução px do `rect`, então é exato (sem remapeamento). Serve p/
    validar de relance a segmentação/iluminação ANTES de aceitar o .svg. `flag_runs`
    (v0.12): trechos INCERTOS flagrados pelo contorno humilde (ndarray Nx2 px),
    pintados em LARANJA por cima — onde conferir/revisar no --edit."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ov = rect.copy()
    cv2.drawContours(ov, cnts, -1, (0, 0, 255), 2)
    for run in (flag_runs or []):
        cv2.polylines(ov, [np.asarray(run, np.int32).reshape(-1, 1, 2)], False,
                      (0, 165, 255), 3)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cv2.imwrite(path, ov)


def write_overlay_svg(rect, cubics, mmpp_x, mmpp_y, path, name="contorno",
                      flag_polylines_mm=None):
    """Overlay EDITÁVEL p/ Inkscape: a foto retificada embutida (raster, em camada
    TRAVADA) + o MESMO contorno de Béziers do `.svg` por cima (camada editável), tudo no
    referencial MÉTRICO do canvas (viewBox em mm). Abra no Inkscape, ajuste os nós do
    contorno sobre a foto, apague/oculte a camada da foto e exporte → contorno corrigido
    na escala real. O frame da foto é (x_mm, −y_mm): px(0,0) no topo-esq, como em `rect`.
    `flag_polylines_mm` (v0.12): trechos INCERTOS do contorno humilde, já no frame da
    foto (mm, Y p/ baixo) — camada própria em laranja, o alvo natural da edição."""
    name = _svg_safe_name(name)
    h, w = rect.shape[:2]
    canvas_w, canvas_h = w * mmpp_x, h * mmpp_y
    b64 = encode_png_b64(rect)

    f = CT.fmt_mm

    def tx(pt):                      # mm (x≥0, y≤0) → frame da foto (Y p/ baixo)
        return (pt[0], -pt[1])

    d = _cubics_to_path_d(cubics, tx) if cubics else ""
    flags_g = ""
    if flag_polylines_mm:
        paths = "".join(
            f'    <path d="M {" L ".join(f"{f(x)},{f(y)}" for (x, y) in run)}"\n'
            f'          style="fill:none;stroke:#ff8800;stroke-width:'
            f'{f(SVG_HAIRLINE_MM * 2)};vector-effect:non-scaling-stroke"/>\n'
            for run in flag_polylines_mm if len(run) >= 2)
        flags_g = ('  <g inkscape:groupmode="layer" inkscape:label="incerto (revisar)">\n'
                   + paths + '  </g>\n')
    svg = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<!-- OVERLAY EDITÁVEL (foto retificada + contorno) — photo_to_outline.py.\n'
        '     Ajuste os nós do contorno sobre a foto no Inkscape, apague a camada "foto" e exporte. -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"\n'
        '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"\n'
        '     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.0.dtd"\n'
        f'     version="1.1" width="{f(canvas_w)}mm" height="{f(canvas_h)}mm"\n'
        f'     viewBox="0 0 {f(canvas_w)} {f(canvas_h)}">\n'
        '  <g inkscape:groupmode="layer" inkscape:label="foto" sodipodi:insensitive="true">\n'
        f'    <image x="0" y="0" width="{f(canvas_w)}" height="{f(canvas_h)}" preserveAspectRatio="none"\n'
        f'           xlink:href="data:image/png;base64,{b64}"/>\n'
        '  </g>\n'
        f'  <g inkscape:groupmode="layer" inkscape:label="{name}">\n'
        f'    <path d="{d}"\n'
        f'          style="fill:{OUTLINE_COLOR};fill-opacity:{OUTLINE_FILL_OPACITY};'
        f'stroke:{OUTLINE_COLOR};stroke-width:{f(SVG_HAIRLINE_MM)};vector-effect:non-scaling-stroke"/>\n'
        '  </g>\n'
        + flags_g +
        '</svg>\n'
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)


# =============================================================================
# Ajuste manual PERSISTENTE (sidecar `<foto>.adjust.json`)
# -----------------------------------------------------------------------------
# O Rotate/Pan do editor (--edit) é CALIBRAÇÃO da foto (peça torta na base, viés
# lateral da segmentação) — não edição de nós — e por isso vale p/ TODAS as
# execuções seguintes sobre a mesma foto. Ao Finalize o total acumulado é salvo
# num sidecar JSON ao lado da entrada; toda execução (com ou sem --edit) o lê e
# REAPLICA no pipeline: o giro roda foto+máscaras JUNTAS (mesma matriz da view
# do editor — fonte única adjust_rot_affine) e o pan translada o contorno
# extraído em x, exato em mm (a foto fica parada, como no editor). Replay
# canônico: PRIMEIRO o giro, DEPOIS o pan (passos intercalados no editor
# diferem disso por O(φ·pan) — desprezível nos passos finos de 0.05–0.1).
# v0.15: o sidecar também guarda PINS — nós que o usuário REPOSICIONOU no editor
# (pontos fixos da borda verdadeira, ex.: onde a sombra inflou a segmentação);
# o replay deforma a silhueta extraída p/ passar por eles (apply_pins), DEPOIS
# do rot+pan (os pins vivem no referencial final, o mesmo do editor).
# =============================================================================
def adjust_path(in_path):
    """Caminho do sidecar de ajuste manual da foto `in_path` (`<stem>.adjust.json`,
    ao lado da entrada — versionado junto com o `<name>.svg`)."""
    return os.path.splitext(in_path)[0] + ".adjust.json"


def load_adjust(in_path):
    """Lê o ajuste salvo: dict `{'rot_deg','pan_mm','center','pins'}` (center = pivô do
    giro em mm, ou None; pins = pontos FIXOS do contorno em mm, v0.15) — ou None se não
    há sidecar/ajuste efetivo. Sidecar ilegível é IGNORADO com aviso (calibração
    corrompida não derruba a CLI)."""
    path = adjust_path(in_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        rot = float(d.get("rot_deg", 0.0))
        pan = float(d.get("pan_mm", 0.0))
        c = d.get("center")
        center = (float(c[0]), float(c[1])) if c is not None else None
        pins = [(float(p[0]), float(p[1])) for p in (d.get("pins") or [])]
        if rot == 0.0 and pan == 0.0 and not pins:
            return None
        if rot != 0.0 and center is None:
            raise ValueError("rot_deg sem center (pivô do giro)")
        return {"rot_deg": rot, "pan_mm": pan, "center": center, "pins": pins}
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as e:
        warn(f"ajuste manual ignorado ({path}: {e})")
        return None


def save_adjust(in_path, rot_deg, pan_mm, center, pins=()):
    """Grava o sidecar do ajuste manual (chamado pelo Finalize do --edit) e devolve o
    caminho. Ajuste todo ZERADO (rot, pan E pins — usuário desfez a calibração)
    REMOVE o sidecar e devolve None — a execução seguinte não reaplica nada."""
    path = adjust_path(in_path)
    if abs(rot_deg) < 1e-9 and abs(pan_mm) < 1e-9 and not pins:
        if os.path.exists(path):
            os.remove(path)
        return None
    data = {"rot_deg": round(float(rot_deg), 6), "pan_mm": round(float(pan_mm), 6),
            "center": ([round(float(center[0]), 6), round(float(center[1]), 6)]
                       if center is not None else None),
            "pins": [[round(float(x), 6), round(float(y), 6)] for (x, y) in pins]}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh)
        fh.write("\n")
    return path


def apply_pins(sil, pins, falloff_mm=PIN_FALLOFF_MM):
    """Replay dos PINS (pontos fixos marcados no --edit, v0.15): deforma a silhueta
    `sil` (polilinha fechada em mm) p/ passar EXATAMENTE por cada pin. Para cada pin,
    o vértice mais próximo recebe o Δ inteiro e o Δ decai em cos² ao longo do ARCO
    (dos dois lados) até zerar em `falloff_mm` — correção local (o usuário fixou a
    borda verdadeira onde a segmentação errou, ex.: sombra), o resto do contorno fica
    INTACTO. Pins aplicados em sequência; devolve NOVA lista (cópia se não há pins)."""
    out = list(sil)
    n = len(out)
    if n < 2:
        return out
    for pin in pins:
        px, py = float(pin[0]), float(pin[1])
        base = list(out)                         # arco medido ANTES da deformação DESTE pin
        j = min(range(n), key=lambda i: (base[i][0] - px) ** 2 + (base[i][1] - py) ** 2)
        dx, dy = px - base[j][0], py - base[j][1]
        if dx == 0.0 and dy == 0.0:
            continue
        half = math.pi / (2.0 * falloff_mm)
        out[j] = (px, py)                        # centro da janela: Δ inteiro (exato)
        for sgn in (1, -1):                      # decai p/ os dois lados do arco
            s = 0.0
            k = j
            for _ in range(n - 1):
                k2 = (k + sgn) % n
                s += math.hypot(base[k2][0] - base[k][0], base[k2][1] - base[k][1])
                k = k2
                if s >= falloff_mm or k == j:
                    break
                w = math.cos(half * s) ** 2
                out[k] = (out[k][0] + dx * w, out[k][1] + dy * w)
    return out


def adjust_rot_affine(rot_deg, center_mm, mmpp_x, mmpp_y):
    """Matriz 2×3 (pixel→pixel) do giro manual: +φ em mm (Y p/ cima) em torno de
    `center_mm` vira K = D·R(φ)·D⁻¹ no referencial do pixel (Y p/ baixo), com
    D = diag(1/mmpp_x, −1/mmpp_y) — anisotropia mmpp_x ≠ mmpp_y incluída. FONTE
    ÚNICA da matriz: a view do editor (fundo girado no modo Rotate) e o replay do
    sidecar compõem/aplicam esta mesma K."""
    phi = math.radians(rot_deg)
    c, s = math.cos(phi), math.sin(phi)
    k01 = (mmpp_y / mmpp_x) * s
    k10 = -(mmpp_x / mmpp_y) * s
    pcx = center_mm[0] / mmpp_x
    pcy = -center_mm[1] / mmpp_y
    return np.array([[c, k01, pcx - c * pcx - k01 * pcy],
                     [k10, c, pcy - k10 * pcx - c * pcy]], np.float64)


def generate_outline(in_path, dict_name=DICT_NAME, min_radius=MIN_RADIUS_MM,
                     smooth_mm=SMOOTH_MM, clearance=CLEARANCE_MM, symmetry="none",
                     deshadow=False, simplify_mm=ANCHOR_SIMPLIFY_MM, faithful=False,
                     min_dist_mm=ANCHOR_MIN_DIST_MM, pocket_eps=POCKET_EPS_MM,
                     mask_smooth_mm=MASK_SMOOTH_MM, mask_smooth_keep_bumps=False,
                     val_frac=SEG_VAL_FRAC, in2_path=None, fuse_grow_mm=FUSE_GROW_MM,
                     line_tol_mm=LINE_TOL_MM, arc_tol_mm=ARC_TOL_MM,
                     shape="off", corner_radius_mm=CORNER_RADIUS_MM, level="off",
                     humble="auto", adjust=None, overlay_path=None, overlay_svg_path=None,
                     debug_dir=None, return_silhouette=False, return_silhouettes=False,
                     return_edit_data=False, return_humble_report=False):
    """Pipeline completo → lista de pontos (x,y) em mm. Usado pelos testes E pelo CLI.
    `symmetry` ∈ {'none','vertical','horizontal','both'} impõe a simetria do objeto
    (espelha + média das metades) p/ limpar o contorno. `deshadow=True` liga a histerese
    de borda na segmentação (recupera o bisel preto do topo E o toe laranja do fundo,
    barrando a sombra de contato cinza). `overlay_path` grava o
    overlay PNG de conferência (contorno segmentado sobre a foto); `overlay_svg_path`
    grava o overlay SVG EDITÁVEL (foto embutida + Béziers do .svg) p/ ajuste no Inkscape.
    `return_silhouette=True` devolve também a silhueta crua (p/ checar encaixe).
    `return_silhouettes=True` (v0.6) devolve `(out, sil, sil_ref)`: `sil_ref` é a silhueta
    de REFERÊNCIA pré `--mask-smooth-mm` (o que a segmentação viu) — é contra ela que o CLI
    mede o `contém`, senão o gate validaria uma silhueta já mutilada pela regularização.
    `return_edit_data=True` devolve `(out, sil, sil_ref, rect, mmpp_x, mmpp_y)` — inclui a
    silhueta de REFERÊNCIA (como `return_silhouettes`) p/ o `--edit` medir o `contém` pelo mesmo
    gate honesto, mais a foto retificada e a escala p/ o editor manual de nós; tem precedência
    sobre os dois anteriores. `humble` ∈ {'auto','on','off'} (v0.12): contorno HUMILDE —
    troca os vãos da borda SEM apoio visual por cordas entre trechos firmes (ver
    humble_rewrite); 'auto' só ativa quando a fração firme fica abaixo de
    HUMBLE_MIN_FIRM_FRAC; ignorado com `faithful` (contradição — avisa se 'on').
    `return_humble_report=True` anexa o report do humilde (ou None) ao fim da tupla.
    `adjust` = ajuste manual salvo pelo editor (`load_adjust`): o giro roda
    foto+máscaras juntas, o pan translada o contorno extraído e os pins deformam
    a silhueta (e a referência do gate) p/ passar pelos pontos fixados (ver a
    seção do sidecar, acima)."""
    img = load_image(in_path)
    rect, mmpp_x, mmpp_y, _conf = rectify(img, dict_name=dict_name, debug_dir=debug_dir)
    flat = normalize_illumination(rect, debug_dir=debug_dir)
    mask = segment_tool(flat, deshadow=deshadow, val_frac=val_frac, debug_dir=debug_dir,
                        faint_metal=bool(in2_path))
    if in2_path:
        # Fusão 2-fotos: mesma peça/base, luz de outro lado — cada foto entra com o
        # seu lado ILUMINADO (fusão direcional; ver fuse_masks).
        img2 = load_image(in2_path)
        rect2, _, _, _ = rectify(img2, dict_name=dict_name)
        flat2 = normalize_illumination(rect2)
        mask2 = segment_tool(flat2, deshadow=deshadow, val_frac=val_frac, faint_metal=True)
        # Máscaras LIMPAS (sem faint, sombra removida) só p/ ANCORAR o registro na
        # peça — as de conteúdo readmitem a sombra e enviesariam o IoU (ver fuse_masks).
        reg_m1 = segment_tool(flat, deshadow=deshadow, val_frac=val_frac)
        reg_m2 = segment_tool(flat2, deshadow=deshadow, val_frac=val_frac)
        if debug_dir:
            cv2.imwrite(os.path.join(debug_dir, "01d_rectified_in2.png"), rect2)
        mask, reg = fuse_masks(mask, mask2, ppmm=1.0 / mmpp_x, grow_mm=fuse_grow_mm,
                               debug_dir=debug_dir,
                               gray1=cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY),
                               gray2=cv2.cvtColor(flat2, cv2.COLOR_BGR2GRAY),
                               reg1=reg_m1, reg2=reg_m2)
        if reg["lobe2_px"] < reg["lobe1_px"]:
            # Foto 2 tem MENOS sombra (lóbulo menor) → melhor luz → vira o fundo do
            # overlay, warpada pelo MESMO registro da máscara (senão o contorno, que
            # vive no canvas da foto 1, cairia deslocado sobre ela).
            Mr = cv2.getRotationMatrix2D(reg["center"], reg["angle"], 1.0)
            Mr[0, 2] += reg["dx"]; Mr[1, 2] += reg["dy"]
            rect = cv2.warpAffine(rect2, Mr, (rect.shape[1], rect.shape[0]),
                                  flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            print("fusão 2-fotos: overlay usa a FOTO 2 de fundo (menos sombra)", file=sys.stderr)
    if level and level != "off":
        # F3 (--level): auto-nível ANTES da simetria — o eixo de simetria é sempre
        # vertical/horizontal, então nivelar primeiro é o que faz a simetria encaixar.
        rect, mask, applied = level_rect_and_mask(rect, mask, ppmm=1.0 / mmpp_x,
                                                  debug_dir=debug_dir)
        if applied is not None:
            print(f"auto-nível: peça girada {applied:+.2f}° (--level {level})",
                  file=sys.stderr)
    if symmetry and symmetry != "none":
        mask = symmetrize_mask(mask, symmetry, ppmm=1.0 / mmpp_x, debug_dir=debug_dir)
    raw_mask = mask                    # referência do gate: o que a segmentação viu
    if mask_smooth_mm and mask_smooth_mm > 0:
        mask = regularize_silhouette(mask, mask_smooth_mm, ppmm=1.0 / mmpp_x,
                                     debug_dir=debug_dir, preserve_convex=mask_smooth_keep_bumps)
    humble_report = None
    if humble and humble != "off":
        if faithful:
            # Fidelidade e humilde se contradizem (o humilde troca a borda por palpite
            # honesto; o fiel promete a borda exata): fora de escopo do fallback.
            if humble == "on":
                warn("--humble on ignorado com --faithful (fidelidade e contorno "
                     "humilde se contradizem)")
        else:
            mask_h, humble_report = humble_rewrite(
                mask, cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY), ppmm=1.0 / mmpp_x,
                mode=humble)
            if humble_report["active"]:
                if humble_report["note"]:
                    warn(f"contorno humilde: {humble_report['note']}")
                else:
                    print(f"AVISO: só {humble_report['firm_frac']:.0%} da borda tem "
                          f"apoio visual — contorno humilde ativado (cordas entre "
                          f"trechos firmes)", file=sys.stderr)
                if mask_h is not mask:
                    mask = mask_h
                    # sil_ref passa a ser a silhueta PÓS-humilde: a pré é sabidamente
                    # errada nos vãos incertos — medir contra ela puniria o conserto.
                    # A honestidade migra p/ o relatório de flags (listado e pintado).
                    raw_mask = mask
            if debug_dir and humble_report["active"]:
                cv2.imwrite(os.path.join(debug_dir, "02h_humble.png"), mask)
    if adjust and adjust.get("rot_deg"):
        # Replay do GIRO manual salvo (--edit → sidecar): foto e máscaras giram
        # JUNTAS pela mesma matriz da view do editor — a relação foto↔contorno não
        # muda, só a orientação (a peça torta que o usuário nivelou fica nivelada
        # em toda execução). Depois de --level/--symmetry/--humble, que rodaram no
        # frame original, como na sessão em que o usuário calibrou.
        M = adjust_rot_affine(adjust["rot_deg"], adjust["center"], mmpp_x, mmpp_y)
        ah, aw = rect.shape[:2]
        same_ref = raw_mask is mask
        rect = cv2.warpAffine(rect, M, (aw, ah), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
        mask = cv2.warpAffine(mask, M, (aw, ah), flags=cv2.INTER_NEAREST,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        raw_mask = mask if same_ref else cv2.warpAffine(
            raw_mask, M, (aw, ah), flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if overlay_path:
        mask_ov = mask
        if adjust and adjust.get("pan_mm"):
            # O overlay mostra o contorno JÁ deslocado pelo pan salvo: a máscara é
            # deslocada em pixels SÓ p/ o desenho (≤ meio pixel de arredondamento);
            # o pan EXATO (sub-pixel, em mm) vai nos pontos da silhueta, abaixo.
            Mt = np.array([[1.0, 0.0, adjust["pan_mm"] / mmpp_x],
                           [0.0, 1.0, 0.0]], np.float64)
            mask_ov = cv2.warpAffine(mask, Mt, (mask.shape[1], mask.shape[0]),
                                     flags=cv2.INTER_NEAREST,
                                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        write_overlay(rect, mask_ov, overlay_path,
                      flag_runs=(humble_report or {}).get("flag_runs_px"))
    sil = extract_outline(mask, mmpp_x, mmpp_y, debug_dir=debug_dir)
    if adjust and adjust.get("pan_mm"):
        # Replay do PAN manual salvo: translação exata (mm) do contorno em x — a
        # foto fica parada (correção de viés lateral da segmentação, como no editor).
        sil = [(x + adjust["pan_mm"], y) for (x, y) in sil]
    if adjust and adjust.get("pins"):
        # Replay dos PINS (pontos fixos do --edit, v0.15): a silhueta é deformada
        # localmente p/ passar por cada ponto que o usuário fixou — corrige a
        # segmentação (ex.: sombra) na FONTE, antes do smooth/fit. Depois do pan:
        # os pins vivem no referencial FINAL (pós rot+pan), o mesmo do editor.
        sil = apply_pins(sil, adjust["pins"])
    if overlay_svg_path:
        # Mesmos Béziers que o .svg emite (fonte única _fit_for_output, incl. symmetry).
        cub = _fit_for_output(sil, smooth_mm=smooth_mm, simplify_mm=simplify_mm,
                              faithful=faithful, min_dist_mm=min_dist_mm,
                              pocket_eps=pocket_eps, symmetry=symmetry,
                              line_tol_mm=line_tol_mm, arc_tol_mm=arc_tol_mm,
                              shape=shape, corner_radius_mm=corner_radius_mm)
        flag_pl = [[(float(x) * mmpp_x, float(y) * mmpp_y) for (x, y) in run]
                   for run in (humble_report or {}).get("flag_runs_px", [])]
        write_overlay_svg(rect, cub, mmpp_x, mmpp_y, overlay_svg_path,
                          flag_polylines_mm=flag_pl)
    out = process_for_print(sil, min_radius=min_radius, smooth_mm=smooth_mm, clearance=clearance)
    if return_edit_data or return_silhouettes:
        # Silhueta de REFERÊNCIA (pré --mask-smooth-mm) do gate honesto (v0.7): é contra ela
        # que o `contém`/`encaixe` é medido — nos DOIS fluxos (padrão e --edit). Sem
        # regularização a referência É a própria `sil` (mesmo objeto, sem custo extra).
        if raw_mask is mask:
            sil_ref = sil
        else:
            sil_ref = extract_outline(raw_mask, mmpp_x, mmpp_y)
            if adjust and adjust.get("pan_mm"):        # gate mede no MESMO referencial
                sil_ref = [(x + adjust["pan_mm"], y) for (x, y) in sil_ref]
            if adjust and adjust.get("pins"):          # pins valem p/ a referência tb:
                # o usuário DECLAROU a borda verdadeira ali — medir o contém contra a
                # referência crua (com a sombra) puniria a correção que ele pediu.
                sil_ref = apply_pins(sil_ref, adjust["pins"])
    if return_edit_data:
        res = (out, sil, sil_ref, rect, mmpp_x, mmpp_y)
    elif return_silhouettes:
        res = (out, sil, sil_ref)
    elif return_silhouette:
        res = (out, sil)
    else:
        res = out
    if return_humble_report:                        # anexa o report (ou None) ao fim
        return (res if isinstance(res, tuple) else (res,)) + (humble_report,)
    return res


def boundary_roughness(pts, win_mm=2.0, step=0.2):
    """Aspereza do contorno: desvio máximo (mm) entre o contorno e seu low-pass de
    janela `win_mm`. Alto = serrilhado; ~0 = linha limpa."""
    rp = resample_uniform(pts, step, closed=True)
    sm = lowpass_closed(rp, win_mm, step)
    n = min(len(rp), len(sm))
    if n == 0:
        return 0.0
    return max(math.hypot(rp[i][0] - sm[i][0], rp[i][1] - sm[i][1]) for i in range(n))


def coverage(outer, inner, ppm=8.0, tol_mm=0.0):
    """Fração da área de `inner` contida em `outer` (mesmo referencial mm). 1.0 =
    `inner` totalmente dentro de `outer` (a peça cabe no pocket). `tol_mm` > 0 (v0.6)
    ERODE `inner` por essa profundidade antes de medir: penetrações rasas (≤ tol — a
    serrilha de ruído da referência crua) não contam, sem perdoar cortes profundos
    (uma feature perdida continua descoberta mesmo erodida)."""
    bo, bi = bbox(outer), bbox(inner)
    min_x, min_y = min(bo[0], bi[0]), min(bo[1], bi[1])
    max_x, max_y = max(bo[2], bi[2]), max(bo[3], bi[3])
    w = int(math.ceil((max_x - min_x) * ppm)) + 2
    h = int(math.ceil((max_y - min_y) * ppm)) + 2
    mo = _polys_to_mask([[((x - min_x) * ppm, (y - min_y) * ppm) for (x, y) in _xy(outer)]], w, h)
    mi = _polys_to_mask([[((x - min_x) * ppm, (y - min_y) * ppm) for (x, y) in _xy(inner)]], w, h)
    r = int(round(tol_mm * ppm))
    if r > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        mi = cv2.erode(mi, k)
    inside = np.count_nonzero(cv2.bitwise_and(mo, mi))
    total = np.count_nonzero(mi)
    return (inside / total) if total else 0.0


# =============================================================================
# CLI
# =============================================================================
def _pipeline_kwargs(args, overlay_path, overlay_svg_path):
    """Kwargs de `generate_outline` derivados dos flags do CLI — fonte única dos dois
    fluxos (padrão e --edit), p/ os dois nunca divergirem num parâmetro."""
    return dict(dict_name=args.dict_name, min_radius=args.min_radius,
                smooth_mm=args.smooth_mm, clearance=args.clearance, symmetry=args.symmetry,
                deshadow=(False if args.shadow == "off" else args.shadow),
                simplify_mm=args.simplify, faithful=args.faithful, min_dist_mm=args.min_dist,
                pocket_eps=args.pocket_eps, mask_smooth_mm=args.mask_smooth_mm,
                mask_smooth_keep_bumps=args.mask_smooth_keep_bumps, val_frac=args.val_frac,
                # getattr: Namespaces sintéticos dos testes antecedem o --in2 (param novo = default)
                in2_path=getattr(args, "in2_path", None),
                fuse_grow_mm=getattr(args, "fuse_grow", FUSE_GROW_MM),
                line_tol_mm=getattr(args, "line_tol", LINE_TOL_MM),
                arc_tol_mm=getattr(args, "arc_tol", ARC_TOL_MM),
                shape=getattr(args, "shape", "off"),
                corner_radius_mm=getattr(args, "corner_radius", CORNER_RADIUS_MM),
                level=getattr(args, "level", "off"),
                humble=getattr(args, "humble", "auto"),
                # ajuste manual salvo pelo editor (sidecar): reaplicado em TODA execução
                adjust=load_adjust(args.in_path),
                overlay_path=overlay_path, overlay_svg_path=overlay_svg_path,
                debug_dir=args.debug_dir)


def _print_grid_error(e):
    """Mensagem única de falha da retificação ArUco (fluxo padrão e --edit)."""
    print(f"ERRO: retificação pela base ArUco falhou — {e}", file=sys.stderr)
    print("      imprima base.svg em A4 a 100%, apoie a peça no centro branco e "
          "fotografe de cima; use --debug-dir p/ inspecionar.", file=sys.stderr)


def _edit_flow(args, out_path, name, overlay_path, overlay_svg_path):
    """Modo `--edit`: detecta como sempre, abre o editor de nós (outline_editor) e grava as
    MESMAS saídas a partir da curva ajustada à mão. A detecção é automática; o usuário só move/
    inclui/exclui nós (qualquer edição re-traça a spline Catmull-Rom G1 pelos nós). WYSIWYG: ao
    Finalize, grava EXATAMENTE a curva exibida na tela — as cúbicas LITERAIS (sem snap de bbox,
    sem recalcular)."""
    import outline_editor as OE
    try:
        _out, sil, sil_ref, rect, mmpp_x, mmpp_y = generate_outline(
            args.in_path, return_edit_data=True,
            **_pipeline_kwargs(args, overlay_path, None))   # o overlay editável sai DEPOIS
    except GridDetectionError as e:
        _print_grid_error(e)
        return 3

    # Nós iniciais = curva ancorada (mesma geometria que o .svg padrão emitiria).
    # getattr: Namespaces sintéticos dos testes antecedem as flags novas (default)
    cub0 = _fit_for_output(sil, smooth_mm=args.smooth_mm, simplify_mm=args.simplify,
                           faithful=args.faithful, min_dist_mm=args.min_dist,
                           pocket_eps=args.pocket_eps, symmetry=args.symmetry,
                           line_tol_mm=getattr(args, "line_tol", LINE_TOL_MM),
                           arc_tol_mm=getattr(args, "arc_tol", ARC_TOL_MM),
                           shape=getattr(args, "shape", "off"),
                           corner_radius_mm=getattr(args, "corner_radius", CORNER_RADIUS_MM))
    if not cub0:
        # Editor sem nós é beco sem saída (nem inserir dá: precisa de ≥ 2 nós) e o
        # Finalize crasharia em bbox de lista vazia — aborta com diagnóstico.
        print("ERRO: detecção degenerada (nenhuma curva p/ editar) — nada gravado. "
              "Confira o overlay e os parâmetros de segmentação.", file=sys.stderr)
        return 4
    nodes0 = OE.nodes_from_cubics(cub0)

    # F1 (plano 011): o eixo de simetria vai PRONTO p/ o editor — o mesmo da detecção
    # (bbox da silhueta JÁ simetrizada, como em fit_closed_beziers_anchored); o editor
    # não o recalcula (edições mudariam a bbox e o eixo "andaria").
    sym_c = None
    if args.symmetry in ("vertical", "horizontal"):
        min_x, min_y, max_x, max_y = bbox(sil)
        sym_c = 0.5 * (min_x + max_x) if args.symmetry == "vertical" \
            else 0.5 * (min_y + max_y)
    # Ajuste salvo (sidecar): o pipeline acima JÁ o aplicou (foto girada, contorno
    # deslocado) — o editor recebe os totais só p/ o status/Finalize acumularem.
    adj = load_adjust(args.in_path) or {"rot_deg": 0.0, "pan_mm": 0.0, "center": None,
                                        "pins": []}
    try:
        res = OE.run_editor(rect, nodes0, mmpp_x, mmpp_y,
                            symmetry=args.symmetry, sym_c=sym_c,
                            init_rot_deg=adj["rot_deg"], init_pan_mm=adj["pan_mm"],
                            init_center=adj["center"],
                            init_pins=adj.get("pins", []))
    except Exception as e:                          # tkinter ausente/sem display etc.
        print(f"ERRO: não consegui abrir o editor ({e}). Rode sem --edit p/ a saída automática.",
              file=sys.stderr)
        return 4
    if res is None:
        print("editor cancelado — nada gravado (rode de novo ou sem --edit).")
        return 0
    # F4: a foto volta com o giro acumulado do modo Rotate (p/ o overlay casar) e o
    # ajuste TOTAL (rot/pan) volta p/ persistir no sidecar — vale p/ as próximas execuções.
    cub, rect_edit, adj_out = res
    if not cub:                                 # lista vazia ≠ cancelar: nada p/ gravar
        print("ERRO: contorno vazio ao finalizar — nada gravado.", file=sys.stderr)
        return 4

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_svg_from_cubics(cub, name))       # EXATAMENTE a curva exibida no editor (WYSIWYG)
    if overlay_svg_path:
        write_overlay_svg(rect_edit, cub, mmpp_x, mmpp_y, overlay_svg_path)
    ow, oh = size(sil)
    pw, ph = size(flatten_beziers(cub)) if cub else (0.0, 0.0)
    print(f"OK  {args.in_path}  ->  {out_path}  (editado)")
    print(f"    overlay {overlay_path}" + (f" | inkscape {overlay_svg_path}" if overlay_svg_path else ""))
    print(f"    EDITADO {len(cub)} Béziers | obj {ow:.2f}x{oh:.2f} | contorno {pw:.2f}x{ph:.2f} "
          f"| contém {coverage(flatten_beziers(cub), sil_ref, tol_mm=CONTAIN_TOL_MM):.4f}")
    pins_out = adj_out.get("pins", [])
    saved = save_adjust(args.in_path, adj_out["rot_deg"], adj_out["pan_mm"],
                        adj_out["center"], pins=pins_out)
    if saved:
        print(f"    ajuste salvo: rot {adj_out['rot_deg']:+.2f}° · pan "
              f"{adj_out['pan_mm']:+.2f} mm · {len(pins_out)} pins → {saved} "
              f"(reaplicado em toda execução)")
    elif adj["rot_deg"] or adj["pan_mm"] or adj.get("pins"):
        print(f"    ajuste zerado: sidecar removido ({adjust_path(args.in_path)})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Foto da ferramenta → SVG de contorno (mm)")
    ap.add_argument("--in", "-i", dest="in_path", required=True)
    ap.add_argument("--in2", dest="in2_path", default=None,
                    help="SEGUNDA foto do MESMO objeto sobre a MESMA base, com a LUZ vindo de "
                         "outro lado (girar base+peça juntas; NÃO mover a peça no papel). As duas "
                         "máscaras são retificadas p/ o mesmo canvas e INTERSECTADAS: a sombra — "
                         "que muda de lado — é eliminada por construção. Indicado p/ sombra dura "
                         "(sol) e peças que se confundem com a própria sombra.")
    ap.add_argument("--fuse-grow", dest="fuse_grow", type=float, default=FUSE_GROW_MM,
                    help="(só com --in2) raio (mm) da recuperação de PARALAXE pós-fusão: cresce o "
                         "AND de volta p/ dentro da união das máscaras, readmitindo a peça alta que "
                         "o AND roeu (projeções não coincidem quando a câmera muda de posição entre "
                         "as fotos) — ao custo de até este raio de sombra onde ela encosta na peça. "
                         "0 (default) = desligado; prefira refotografar com o mesmo enquadramento.")
    ap.add_argument("--out", "-o", dest="out_path")
    ap.add_argument("--dict", dest="dict_name", default=DICT_NAME,
                    choices=sorted(CT.DICT_CAPACITY),
                    help="dicionário ArUco da base impressa (deve casar com base.svg)")
    ap.add_argument("--min-radius", type=float, default=MIN_RADIUS_MM)
    ap.add_argument("--smooth-mm", dest="smooth_mm", type=float, default=SMOOTH_MM,
                    help="janela do low-pass (mm) que remove o serrilhado")
    ap.add_argument("--clearance", type=float, default=CLEARANCE_MM,
                    help="folga externa (mm). PADRÃO 0 = tamanho REAL (sem ganho); "
                         "a folga de encaixe é aplicada DEPOIS (a jusante no OpenSCAD, ou à mão)")
    ap.add_argument("--shadow", dest="shadow", default="off",
                    choices=["off", "remove", "texture"],
                    help="'remove' = HISTERESE de borda por CROMA: cresce os núcleos preto E "
                         "colorido pela borda arredondada que vira p/ a base (bisel PRETO no topo, "
                         "toe LARANJA dessaturado no fundo), recuperando a borda que o corte único "
                         "comia e PARANDO na sombra de contato cinza. 'texture' = SUBTRATOR de "
                         "sombra p/ CORPO CINZA-NEUTRO sem croma: o valor pega o corpo e a TEXTURA "
                         "(std local de V, limiar Otsu adaptativo) RECORTA a sombra PROJETADA (lisa "
                         "e mais clara) que o --val-frac sozinho engloba. PADRÃO off.")
    ap.add_argument("--val-frac", dest="val_frac", type=float, default=SEG_VAL_FRAC,
                    help="corte de VALOR p/ pixel escuro = objeto (V ≤ val_frac × fundo). PADRÃO "
                         "0.30 (exclui a sombra de contato em peças CROMÁTICAS). SUBA (~0.7-0.8) "
                         "p/ capturar CORPO CINZA-NEUTRO de baixo contraste, que não tem croma p/ "
                         "os outros predicados; pareie com --mask-smooth-mm p/ limpar a borda "
                         "corpo↔sombra. Acima disso a sombra de contato pode vazar.")
    ap.add_argument("--level", dest="level", default="off", choices=["off", "auto"],
                    help="AUTO-NÍVEL (F3): corrige a rotação FINA da peça apoiada torta na "
                         "base — estima pelo envelope (minAreaRect, desvio ao múltiplo de 90° "
                         f"mais próximo) e gira foto+máscara juntas se {LEVEL_MIN_DEG}° ≤ "
                         f"|desvio| ≤ {LEVEL_MAX_DEG}°. Roda ANTES de --symmetry (nivelar "
                         "primeiro faz a simetria encaixar). Peça ~quadrada/redonda sem reta "
                         "longa não é corrigida (envelope instável). PADRÃO off.")
    ap.add_argument("--humble", dest="humble", default="auto",
                    choices=["auto", "on", "off"],
                    help="contorno HUMILDE (v0.12): quando a borda não tem apoio visual "
                         "(sem contraste em quase todo o objeto — peça clara em papel "
                         "branco), troca os vãos incertos por CORDAS retas entre os "
                         "trechos firmes e FLAGRA o que sobrou (overlay em laranja, "
                         f"aviso no stdout). 'auto' (PADRÃO) só ativa se a fração firme "
                         f"da borda cair abaixo de {int(HUMBLE_MIN_FIRM_FRAC * 100)}%%; "
                         "'on' força; 'off' nunca. Ignorado com --faithful/--tol-fit.")
    ap.add_argument("--symmetry", dest="symmetry", default="none",
                    choices=["none", "vertical", "horizontal", "both"],
                    help="impõe a simetria do objeto: espelha e faz a MÉDIA das duas metades "
                         "(duas amostras do mesmo contorno → menos ruído). 'vertical' = eixo "
                         "vertical (metades esq./dir. iguais), 'horizontal' = eixo horizontal "
                         "(topo/baixo), 'both' = os dois. PADRÃO none.")
    ap.add_argument("--simplify", dest="simplify", type=float, default=ANCHOR_SIMPLIFY_MM,
                    help="densidade das âncoras (mm): MAIOR = menos nós (mais 'hull'), "
                         "MENOR = contorno mais justo (mais nós)")
    ap.add_argument("--faithful", dest="faithful", action="store_true",
                    help="modo FIEL: contorno EXATO da peça (bbox = objeto, com snap de dimensão), "
                         "em vez do POCKET de encaixe. Ancora em todas as extremidades do fecho "
                         "convexo e subdivide por contenção. Substitui o antigo '--max-nodes 0'. "
                         "Ignorado se --tol-fit (este já escolhe o ajuste por tolerância).")
    ap.add_argument("--fit-tol", dest="fit_tol", type=float, default=FIT_TOL_MM,
                    help="tolerância (mm) do ajuste por tolerância (só com --tol-fit)")
    ap.add_argument("--c-fit", dest="c_fit", type=float, default=0.0,
                    help="folga embutida no SVG (mm); 0 = traço mínimo encostando na peça "
                         "(a folga de impressão é adicionada a jusante, no OpenSCAD)")
    ap.add_argument("--guide", dest="guide", type=float, default=BEZIER_GUIDE_MM,
                    help="orçamento de suavização (mm): maior = MENOS Béziers, cavidade mais folgada")
    ap.add_argument("--tol-fit", dest="tol_fit", action="store_true",
                    help="ajusta por tolerância (mais nós) em vez do mínimo por contenção")
    ap.add_argument("--polyline", dest="polyline", action="store_true",
                    help="emite polyline cru (L) em vez de curvas de Bézier (C)")
    ap.add_argument("--inkscape", dest="inkscape", action="store_true",
                    help="gera também o overlay SVG EDITÁVEL `_overlay_<nome>.svg` (foto retificada "
                         "embutida + Béziers em camadas, no referencial mm) p/ ajuste fino no Inkscape "
                         "e export na escala real. PADRÃO off (só o overlay PNG de conferência sai sempre).")
    ap.add_argument("--pocket-eps", dest="pocket_eps", type=float, default=POCKET_EPS_MM,
                    help="penetração tolerada (mm) no modo POCKET: a curva pode tocar/cortar a "
                         "peça até este valor. Menor = pocket mais justo p/ fora = 'contém' mais "
                         "alto (→1.0); 0 = não corta a peça (contém ~1.0, encaixe mais folgado).")
    ap.add_argument("--line-tol", dest="line_tol", type=float, default=LINE_TOL_MM,
                    help="detecção de RETAS (mm, v0.10): trecho do contorno onde todos os pontos "
                         "desviam < isto da corda vira UMA reta (menos nós; aresta reta não "
                         "arqueia p/ dentro). MAIOR = mais agressivo (pega arestas abauladas), "
                         "MENOR = só reta de verdade. 0 = DESLIGA retas e arcos (caminho antigo). "
                         f"PADRÃO {LINE_TOL_MM}.")
    ap.add_argument("--arc-tol", dest="arc_tol", type=float, default=ARC_TOL_MM,
                    help="detecção de ARCOS (mm, v0.10): nos vãos entre retas, círculo com resíduo "
                         "radial < isto vira arco tangente (canto = filete limpo, 1 cúbica por "
                         f"90°). 0 = desliga só os arcos. PADRÃO {ARC_TOL_MM}.")
    ap.add_argument("--corner-radius", dest="corner_radius", type=float,
                    default=CORNER_RADIUS_MM,
                    help="prior de RAIO de canto (mm, v0.13): o raio MEDIDO pelo usuário nos "
                         "filetes da peça (via --describe da skill /ptoo). Arco detectado com "
                         "raio a ±max(1 mm, 20%%) disto é REFIT com o raio FIXO — o canto sai "
                         "com o raio declarado, não o estatístico da segmentação. Com --shape "
                         "rect é o raio dos 4 cantos do modelo. 0 = desligado (PADRÃO).")
    ap.add_argument("--shape", dest="shape", default="off", choices=["off", "rect"],
                    help="forma DECLARADA da peça (v0.13): 'rect' = retângulo de cantos "
                         "arredondados — o pocket é CONSTRUÍDO exato (4 retas + 4 arcos de raio "
                         "--corner-radius tangentes, pose por minAreaRect, 8 Béziers), inflado o "
                         "mínimo p/ conter a peça. Se a silhueta não bate com a forma declarada "
                         "(vão/inflação acima do teto), avisa e cai no caminho genérico. Só no "
                         "modo POCKET (ignorado com --faithful/--tol-fit). PADRÃO off.")
    ap.add_argument("--min-dist", dest="min_dist", type=float, default=ANCHOR_MIN_DIST_MM,
                    help="distância MÍNIMA (mm) entre âncoras do MESMO QUADRANTE no pocket de "
                         "encaixe: ao adensar (8, 12…), o 2º/3º ponto de um quadrante só entra "
                         "se ficar a ≥ este valor dos já escolhidos ali (evita aglomerar). PADRÃO 10.")
    ap.add_argument("--mask-smooth-mm", dest="mask_smooth_mm", type=float, default=MASK_SMOOTH_MM,
                    help="regulariza a SILHUETA (raio mm) antes de extrair o contorno: remove "
                         "saliências/ondulações de amplitude < este valor na borda da máscara "
                         "(carcaça PRETA de baixo contraste) sem arredondar os cantos. Ortogonal "
                         "ao --smooth-mm. PADRÃO 0 (off); ~1.5-2 limpa a borda preta do thermpro.")
    ap.add_argument("--mask-smooth-keep-bumps", dest="mask_smooth_keep_bumps", action="store_true",
                    help="enviesa o --mask-smooth-mm p/ FECHAMENTO (closing no campo de distância): "
                         "remove só as REENTRÂNCIAS côncavas (serrilha) e PRESERVA os ressaltos "
                         "convexos (ex.: a aba lateral), que o modo isotrópico arredondaria. PADRÃO off.")
    ap.add_argument("--edit", dest="edit", action="store_true",
                    help="abre o EDITOR de nós (GUI tkinter): a foto retificada de fundo + os nós "
                         "da curva detectada como alças. Mova/inclua/exclua nós, clique 'Re-traçar' "
                         "p/ recompor a curva suave (G1) e 'Finalizar' p/ gravar. A detecção continua "
                         "automática; você só ajusta os nós. Parte sempre da curva ANCORADA (ignora "
                         "--polyline/--tol-fit como ponto de partida). PADRÃO off.")
    ap.add_argument("--name", dest="name")
    ap.add_argument("--debug-dir", dest="debug_dir")
    args = ap.parse_args(argv)

    if args.shape != "off" and (args.faithful or args.tol_fit or args.polyline):
        # Modelo declarado é coisa do POCKET (constrói a cavidade, não reproduz a peça).
        warn(f"--shape {args.shape} ignorado fora do modo pocket "
             f"(--faithful/--tol-fit/--polyline)")
        args.shape = "off"
    if args.tol_fit and args.humble != "off":
        # Fora de escopo do fallback (mesma contradição do --faithful, tratado dentro
        # de generate_outline): avisa só quando o usuário FORÇOU o humilde.
        if args.humble == "on":
            warn("--humble on ignorado com --tol-fit (fidelidade e contorno humilde "
                 "se contradizem)")
        args.humble = "off"
    if args.in2_path and not os.path.exists(args.in2_path):
        print(f"imagem não encontrada: {args.in2_path}", file=sys.stderr)
        return 2
    if not os.path.exists(args.in_path):
        print(f"imagem não encontrada: {args.in_path}", file=sys.stderr)
        return 2
    out_path = args.out_path or os.path.splitext(args.in_path)[0] + ".svg"
    name = args.name or os.path.splitext(os.path.basename(args.in_path))[0]
    # Overlay PNG de conferência SEMPRE gerado ao lado do .svg (prefixo "_overlay_", com
    # underscore inicial = rascunho/ignorado pelo git): contorno segmentado sobre a foto.
    # O overlay SVG EDITÁVEL (foto embutida + Béziers, p/ ajuste fino no Inkscape) só sai
    # com --inkscape. Ambos gravados ANTES do .svg final.
    _ov_base = os.path.join(os.path.dirname(out_path) or ".",
                            f"_overlay_{os.path.splitext(os.path.basename(out_path))[0]}")
    overlay_path = _ov_base + ".png"
    overlay_svg_path = (_ov_base + ".svg") if args.inkscape else None

    if args.edit:                                   # editor manual de nós (GUI tkinter)
        return _edit_flow(args, out_path, name, overlay_path, overlay_svg_path)

    try:
        # `sil` (regularizada) gera o SVG; `sil_ref` (pré --mask-smooth-mm) é a referência
        # do `contém`/`encaixe` — o gate mede contra o que a SEGMENTAÇÃO viu (v0.6).
        pts, sil, sil_ref, hrep = generate_outline(
            args.in_path, return_silhouettes=True, return_humble_report=True,
            **_pipeline_kwargs(args, overlay_path, overlay_svg_path))
    except GridDetectionError as e:
        _print_grid_error(e)
        return 3

    anchored = not args.tol_fit                     # ancorado nas extremidades (padrão)
    floor = None if args.tol_fit else sil
    # Guia de FORMA só p/ o caminho por contenção (--tol-fit): silhueta suavizada com
    # orçamento `--guide`. O caminho ancorado não usa guia — parte da silhueta direto.
    guide = pts
    if floor is not None and not anchored and not args.polyline:
        guide = process_for_print(sil, min_radius=args.min_radius, smooth_mm=args.smooth_mm,
                                  clearance=args.guide)
    svg = polygon_to_svg(guide, name=name, curves=not args.polyline, tol=args.fit_tol,
                         silhouette=floor, c_fit=args.c_fit, anchored=anchored,
                         smooth_mm=args.smooth_mm, simplify_mm=args.simplify,
                         faithful=args.faithful, min_dist_mm=args.min_dist,
                         pocket_eps=args.pocket_eps, symmetry=args.symmetry,
                         line_tol_mm=args.line_tol, arc_tol_mm=args.arc_tol,
                         shape=args.shape, corner_radius_mm=args.corner_radius)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    # Saída COMPACTA e parseável (a skill /ptoo lê isto a cada passo): uma linha de status,
    # uma de overlays e uma de métricas com as chaves estáveis `obj`/`pocket`/`contém`/`encaixe`.
    ow, oh = size(sil)                              # dimensão REAL medida pelos marcadores
    undercontained = False
    pocket = anchored and not args.faithful         # modo ENCAIXE (pocket por quadrante)
    obj = f"obj {ow:.2f}x{oh:.2f}"
    if args.polyline:
        metrics = f"polyline | {obj}"
    elif anchored:
        cub = _fit_for_output(sil, smooth_mm=args.smooth_mm, simplify_mm=args.simplify,
                              faithful=args.faithful, min_dist_mm=args.min_dist,
                              pocket_eps=args.pocket_eps, symmetry=args.symmetry,
                              line_tol_mm=args.line_tol, arc_tol_mm=args.arc_tol,
                              shape=args.shape,           # mesma geometria do SVG emitido
                              corner_radius_mm=args.corner_radius)
        cov = coverage(flatten_beziers(cub), sil_ref, tol_mm=CONTAIN_TOL_MM)
        if pocket:
            pw, ph = size(flatten_beziers(cub))     # pocket = ≥ objeto (contém a peça)
            metrics = (f"POCKET {len(cub)} Béziers | {obj} | pocket {pw:.2f}x{ph:.2f} "
                       f"(folga {pw - ow:+.2f}/{ph - oh:+.2f}) | contém {cov:.4f}")
            if args.shape != "off":                 # relato do modelo declarado (v0.13):
                metrics += (                        # a skill valida r/inflação por aqui
                    f" | shape {_SHAPE_LAST['shape']} r={_SHAPE_LAST['r']:.2f} "
                    f"infl +{_SHAPE_LAST['infl']:.2f}" if _SHAPE_LAST
                    else " | shape FALLBACK")
            undercontained = cov < CONTAIN_COVERAGE
        else:
            metrics = f"FIEL {len(cub)} Béziers | {obj} | encaixe {cov:.4f}"
    elif floor is not None:
        cub = fit_closed_beziers_contained(dedup_closing_point(guide), sil, c_fit=args.c_fit)
        metrics = (f"{len(cub)} Béziers (mín. contenção) | {obj} | "
                   f"encaixe {coverage(flatten_beziers(cub), sil_ref, tol_mm=CONTAIN_TOL_MM):.4f}")
    else:
        n = len(fit_closed_beziers(dedup_closing_point(pts), tol=args.fit_tol))
        metrics = f"{n} Béziers (por tolerância) | {obj}"
    if hrep:                                        # v0.12: fração firme sempre visível;
        metrics += f" | firme {hrep['firm_frac']:.0%}"   # flags só quando existem
        if hrep["flags"]:
            metrics += f" | flags {len(hrep['flags'])}"
    overlays = f"overlay {overlay_path}" + (f" | inkscape {overlay_svg_path}" if overlay_svg_path else "")
    print(f"OK  {args.in_path}  ->  {out_path}")
    print(f"    {overlays}")
    print(f"    {metrics}")
    adj = load_adjust(args.in_path)
    if adj:                                         # calibração do --edit reaplicada
        print(f"    ajuste manual aplicado: rot {adj['rot_deg']:+.2f}° · pan "
              f"{adj['pan_mm']:+.2f} mm · {len(adj.get('pins', []))} pins "
              f"({adjust_path(args.in_path)})")
    for (fx, fy), ext in (hrep["flags"] if hrep else []):
        print(f"    AVISO: trecho incerto de ~{ext:.0f} mm perto de ({fx:.0f},{fy:.0f}) "
              f"mm — revisar no --edit", file=sys.stderr)
    if undercontained:
        print(f"    AVISO: pocket não contém 100% (contém < {CONTAIN_COVERAGE:.2f}); "
              f"diminua --min-dist.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
