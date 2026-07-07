# Manual de parâmetros — `photo_to_outline.py`

> Referência **operacional** de cada flag do CLI: o que faz, default, quando mexer, com que
> outras interage e o efeito em **contém** (cobertura da peça) e **folga** (pocket − objeto).
> Não repete a arquitetura/pipeline — para isso veja [design.md](design.md) (estágios, API,
> constantes) e [historico.md](historico.md) (evolução). O guia de uso em inglês é o
> [README.md](../README.md). Este manual é em pt-BR e serve de base para a skill `/ptoo`.
>
> **Unidades: mm.** O modo **padrão é o POCKET de encaixe** (cavidade que CONTÉM a peça, ≥ objeto).

## Visão de 30 segundos

- A **densidade/justeza do pocket** é controlada por **`--min-dist`** (única alavanca; menor =
  mais âncoras = mais justo). **Não existe mais `--max-nodes`** — a quantidade de nós emerge do
  espaçamento.
- O **lever fino do contém** (raspar os últimos 0.0x) é **`--smooth-mm`**.
- A **detecção/segmentação** se ajusta com **`--shadow`** e **`--symmetry`** (e `--dict` para a
  base).
- A **folga real de impressão** NÃO sai daqui: aplique a jusante (OpenSCAD/`--clearance`). O SVG
  sai no tamanho real (`--clearance 0`).
- O **`contém` é honesto (v0.7):** medido contra a silhueta **pré** `--mask-smooth-mm` com
  tolerância de profundidade de 0.3 mm — ruído raso não conta, mas uma feature removida pela
  regularização (o CLI avisa) derruba o gate.
- **Sombra dura ou metal claro que some no branco → 2 fotos (v0.9):** `--in2 <foto2>` com a luz
  do outro lado; registro e fusão são automáticos (ver seção 1).

---

## 1. Detecção e segmentação (o que o tool "enxerga" da peça)

### `--shadow {off,remove,texture}`  · default `off`
Estratégia de separação **corpo ↔ sombra** na segmentação.

**`remove` — histerese de borda por CROMA.** Cresce os núcleos preto E colorido pela borda
arredondada que vira para a base (bisel preto no topo, *toe* laranja dessaturado no fundo), **só
pelos pixels com croma**, recuperando a borda real que o corte único comia — e **parando na sombra
de contato cinza** (que fica de fora, sem afrouxar o pocket).
- **Quando usar:** a borda arredondada some / a segmentação "come" a peça; peça **cromática** com
  bisel escuro. Quase sempre `remove` em peças coloridas reais.
- **Sintoma oposto:** com `remove`, se a sombra cinza vazasse, ela é barrada (não vaza).

**`texture` — subtrator de sombra por TEXTURA (v0.5).** Para **corpo cinza-neutro sem croma**, onde
nem croma nem valor separam o corpo da sombra projetada (mesmo brilho). O **valor** pega o corpo
escuro inteiro (inclusive o liso) e a **textura** (desvio-padrão local de V, limiar **Otsu
adaptativo** da própria foto) **recorta** as regiões ao mesmo tempo **lisas E mais claras** = a
sombra projetada. O recorte vale p/ todo o candidato (valor **ou** croma), então funciona até com
fundo de papel cromático (a sombra sobre o papel lavanda também é cromática, mas é lisa → recortada).
- **Quando usar:** corpo cinza-neutro **com sombra projetada** que `--val-frac` sozinho engloba.
  Substitui o antigo paliativo `--val-frac 0.68 --shadow off`.
- **Refino de borda por watershed (v0.8, embutido):** re-decide a fronteira pelo gradiente e
  expulsa a sombra de **contato/UMBRA** (escura, que passava pelo recorte). Resíduo típico:
  ~0,5–1,5 mm. Mecanismo em [design.md](design.md) §Pipeline 2.
- **Efeito geral:** sobe a fidelidade da silhueta → pocket mais correto.

### `--val-frac <f>`  · default `0.30`
Corte de **valor** do predicado "escuro" da segmentação: um pixel é objeto se `V ≤ f × fundo`.
- **O que faz:** `0.30` (default) exclui a **sombra de contato** em peças **cromáticas** (a cor já
  entra pela saturação/matiz, então o corte escuro só precisa pegar o miolo preto real).
- **Quando subir (~0.7–0.8):** **corpo cinza-neutro** de baixo contraste (carcaça plástica que vive
  em `V≈0.6–0.7×fundo` e **sem croma** → não passa por `colored`/`chromatic` nem pelo corte
  default). Foi o caso da `trena`: em `0.30` só o botão metálico central era segmentado; em `0.75`
  a carcaça inteira aparece.
- **Cuidado:** acima do nível que pega o corpo, a **sombra de contato** (também cinza) pode **vazar**
  → pocket inflado em fotos de fundo sujo. Pareie com `--mask-smooth-mm` p/ limpar a borda
  corpo↔sombra; em fundo muito claro funciona bem.
- **Interação:** ortogonal a `--shadow remove` (a histerese cresce por **croma**, não ajuda em
  cinza). Para corpo cinza **com sombra projetada**, o caminho robusto hoje é **`--shadow texture`**
  (recorta a sombra pela textura) em vez de só subir `--val-frac` — ver acima.

### `--in2 <foto2>`  · default off  ·  **fusão 2-fotos (v0.9)**
Segunda foto da **mesma peça sobre a mesma base**, com a **luz vindo do outro lado** (protocolo:
girar **base+peça juntas** ~180° em relação ao sol/lâmpada e refotografar). As duas retificações
ancoram no mesmo alvo impresso → a peça cai no mesmo canvas métrico; só a sombra muda de lado.
A CLI então faz tudo sozinha: **registro rígido automático** (pode girar a peça à mão livre entre
as fotos, o registro absorve), **fusão direcional** (cada foto é soberana no seu lado iluminado →
as duas sombras caem, e a paralaxe não rói peça alta) e o **predicado faint-metal** (recupera
metal claro liso ≈ brilho do papel — seguro só aqui, porque a fusão remove a sombra readmitida).
O overlay usa de fundo a foto de melhor luz. Mecanismo em [design.md](design.md) §Pipeline 2b.
- **Quando usar:** sombra dura (sol) que nenhum `--shadow` resolve; peça com conectores/metal claro
  que some no papel branco. É o caminho robusto p/ os dois problemas de uma vez.
- **Diagnóstico no stderr:** `registro rot=…° shift=…mm score=…` + direções de sombra; **AVISO**
  "sombras caem do MESMO lado" = a luz mudou pouco entre as fotos → refotografe com a luz oposta
  (nesse caso o resultado degrada p/ ~AND e sombra∩sombra pode vazar).

### `--fuse-grow <mm>`  · default `0.0`  ·  *(só com `--in2`)*
Pós-fusão opcional: cresce o resultado **geodesicamente** (dilatação contida na UNIÃO das duas
máscaras) até este raio. Com a fusão direcional raramente é necessário — fica p/ resíduo de
paralaxe perto da **bissetriz** das duas direções de sombra (onde nenhuma foto é soberana).
- **Quando usar:** só se o zoom mostrar a peça roída num trecho onde as duas sombras se encontram.
- **Custo:** readmite até este raio de sombra onde ela encosta na peça.

### `--humble {auto,on,off}`  · default `auto`  ·  **contorno humilde (v0.12)**
Fallback p/ quando **não existe borda visível clara em quase todo o objeto** (peça clara em
papel branco, bisel lavado pela luz): troca os trechos da borda **sem apoio visual** por
**cordas retas** entre os trechos firmes vizinhos — desde que a região descartada seja lisa
(papel/sombra, sem textura de peça) — e **FLAGRA** o que ficou incerto: aviso no stdout com
posição/extensão e trecho pintado de **laranja** no overlay (PNG e camada própria no
`--inkscape`), o alvo natural da revisão no `--edit`. É o "melhor palpite honesto + onde
conferir"; mecanismo completo em [design.md](design.md) §Pipeline 2e.
- **`auto` (default):** a fração firme é computada em toda execução (métrica `firme NN%`); o
  fallback só ativa abaixo de 50%, com aviso `só NN% da borda tem apoio visual`. Foto boa
  (thermpro ~92% firme) **não muda em nada** (regressão garantida por teste).
- **`on`:** força a reescrita mesmo com borda majoritariamente firme (útil p/ atacar um halo
  localizado). **`off`:** nunca reescreve.
- **Fora de escopo:** ignorado com `--faithful`/`--tol-fit` (fidelidade e humilde se
  contradizem; com `on` explícito, avisa). Quando ativa, o `contém` passa a ser medido contra a
  silhueta **pós-humilde** (a pré é sabidamente errada nos vãos incertos); a honestidade migra
  p/ os flags.
- **Limite conhecido:** peça **lisa** com borda curva genuína sem contraste — a guarda de
  textura não distingue bojo real liso de halo, e a corda rasparia o bojo. O gatilho
  conservador (só em cena degradada) e o aviso sempre presente mitigam; confira o overlay.

### `--level {off,auto}`  · default `off`  ·  **auto-nível (011/F3)**
Corrige a **rotação fina** (poucos graus) da peça apoiada levemente torta na base — "coloca no
nível". Estima o desvio pelo envelope e gira **foto retificada + máscara juntas**, sem
re-segmentar (mecanismo em [design.md](design.md) §Pipeline 2c). Roda **antes** de `--symmetry` —
o eixo de simetria é sempre vertical/horizontal, então nivelar primeiro é o que faz a simetria
encaixar. O overlay sai corrigido.
- **Quando usar:** a peça ficou visivelmente torta na foto (arestas quase-horizontais inclinadas
  ~0.5–5°) e você quer o SVG alinhado aos eixos sem refotografar.
- **Salvaguardas:** só aplica se `LEVEL_MIN_DEG (0.2°) ≤ |desvio| ≤ LEVEL_MAX_DEG (7°)` — abaixo
  já está nivelado (saída **idêntica**, regressão garantida por teste); acima, avisa e segue sem
  girar (a foto deve vir "o mais no nível possível"; reposicione a peça). Peça **~quadrada ou
  redonda** (razão de aspecto do envelope < 1.05) sem **reta ≥ 8 mm** alinhável no contorno não é
  corrigida (aviso): num disco o ângulo do envelope é ruído.
- **Limite:** "nível" pelo **envelope** ≠ "nível" pela **face de baixo** — no thermpro os dois
  divergem ~1.2° (a face inferior é genuinamente inclinada). Uma variante `bottom` (maior reta de
  baixo) fica documentada como possível fase 2, só se o `auto` errar em peças reais.
- **Alternativa manual:** o modo **Rotate** do editor (`--edit`) gira foto+nós em passos de 0.1°.

### `--symmetry {none,vertical,horizontal,both}`  · default `none`
Impõe a simetria do objeto: **espelha e faz a MÉDIA das duas metades** (duas amostras do mesmo
contorno → menos ruído). `vertical` = eixo vertical (metades esq./dir.), `horizontal` = topo/baixo,
`both` = os dois.
- **Quando usar:** peça com eixo de espelho **claro** e contorno ruidoso/torto. Avaliar logo no 1º
  passe (pelo overview).
- **Cuidado:** **nunca** em peça assimétrica — distorce o contorno.
- **Efeito:** limpa ruído lateral e **sobe o contém**.
- **Limite (espelhamento de Béziers):** se o contorno cruza o eixo **mais de 2 vezes** (forma
  côncava atravessando o eixo, ex.: fenda central), o espelhamento das curvas é **ignorado com
  aviso** — cada arco+espelho fecharia um laço separado (multi-contorno), sem caminho único
  fiel. A simetria de **máscara** (a média das metades, feita antes) continua valendo.

### `--dict <nome>`  · default `DICT_4X4_50`
Dicionário ArUco da base impressa; **deve casar** com o `base.svg` gerado.
- **Quando mexer:** só se você regerou a base com outro dicionário. Se não casar, a retificação
  falha (`ERRO: retificação pela base ArUco falhou`) — aí é problema de foto/base, não de pocket.
- **Validação:** só os dicionários da tabela `DICT_CAPACITY`/`DICT_MODULES`
  (`calibration_target.py`) são aceitos (`choices` do argparse, nos dois CLIs); um nome fora da
  tabela é rejeitado no parse. Para usar outro dicionário, acrescente-o à tabela.

### `--min-radius <mm>`  · default `1.5`
Raio **mínimo** de canto na suavização (evita bico/cusp de 90°).
- **Quando subir (+0.5):** apareceu bico/canto vivo onde devia ser arredondado.
- **Interação:** muito alto arredonda cantos legítimos.

---

## 2. Densidade e contorno do POCKET

### `--min-dist <mm>`  · default `10.0`  ·  **alavanca principal**
Distância **mínima** entre âncoras do **mesmo quadrante**. Cada quadrante recebe **todas** as
extremidades mais externas que fiquem a ≥ este valor umas das outras — **sem teto de nós**: a
quantidade de Béziers emerge só do espaçamento.
- **MENOR** (ex.: 1 → 0.5) = **mais âncoras = pocket mais justo = contém mais alto**.
- **MAIOR** (ex.: 10 → 20) = menos âncoras = pocket mais folgado.
- **Contra-intuitivo:** `--min-dist` **grande** (poucas âncoras) deixa o pocket **mais folgado E
  com contém MENOR** — âncoras esparsas geram Béziers longas que **arqueiam para dentro** nos
  cantos arredondados, cortando a peça. Para **conter** mais, **diminua** `--min-dist`.
- **Rampa adaptativa (1º lever):** direção padrão ↓; enquanto melhorar, continue; parou de
  melhorar → inverta p/ ↑; piorou na invertida → volte ao melhor e passe p/ a 2ª rampa.
  Piso = 1 mm; teto ~10.
- **v0.10:** com as primitivas ligadas (default), `--min-dist` rege só os trechos **livres**
  (nem reta nem arco) — em peças retilíneas o default 10 já sai justo (as retas não arqueiam).
  Comece a rampa no default; se o objeto for orgânico (pouca primitiva), a rampa volta a mandar.

### `--line-tol <mm>`  · default `0.3`  ·  **primitivas: RETAS (v0.10)**
Detecção de **retas** no contorno: um trecho maximal onde **todos** os pontos desviam menos que
isto da corda vira **uma reta** (cúbica degenerada na corda, deslocada para FORA pelo desvio
residual — contenção garantida). Trechos colineares adjacentes fundem (uma aresta física = uma
reta); as pontas recuam ~0.8 mm para o canto virar filete tangente (**G1** mantido em todo nó).
Âncoras de quadrante internas à reta são suprimidas — menos nós, e a aresta reta **não arqueia
para dentro** (o caso "placa retangular" que fechava a rampa min-dist alto).
- **`0` = DESLIGA retas E arcos** (caminho legado puro, idêntico ao pré-v0.10).
- **MAIOR** (0.5+): mais agressivo — pega arestas abauladas, mas começa a facetar curvas gentis.
- **MENOR** (0.1–0.2): só reta de verdade; fotos ruidosas podem perder arestas legítimas.
- Um **círculo grande não vira polígono**: trecho que um círculo de raio plausível ajusta melhor
  que a corda é vetado e fica para os arcos.

### `--arc-tol <mm>`  · default `0.3`  ·  **primitivas: ARCOS (v0.10)**
Nos **vãos entre retas** (contorno inteiro se não há retas), um círculo por mínimos quadrados com
resíduo radial abaixo disto — e varredura angular monótona, giro por ponto compatível com o raio
(canto não é engolido) — vira **arco tangente**: canto = filete limpo, 1 cúbica por até 90°.
Raio plausível: 0.8–60 mm. `0` desliga só os arcos (retas continuam).
- No Pi (2 fotos, min-dist 10): folga caiu de +0.83/+0.19 (legado) p/ **+0.07/−0.05** com
  contém 0.9999 — as primitivas colam o pocket na peça.

### `--pocket-eps <mm>`  · default `0.5`
Penetração **tolerada** no modo POCKET: a curva pode tocar/cortar a peça até este valor (em vez de
estufar para fora a span inteira por ruído sub-mm → pocket bem mais justo, ainda contendo ~0.998).
- **Menor (0.5 → 0):** corta MENOS a peça → contém um pouco mais alto, pocket levemente mais
  folgado. Efeito **pequeno** por degrau (~+0.0001–0.0003).
- **Rampa adaptativa (3º lever do contém):** mesma lógica de inversão. Direção padrão ↓. Piso = 0,
  teto = 0.5. Engaja quando min-dist (1ª) e smooth-mm (2ª) esgotaram.

### `--simplify <mm>`  · default `2.0`  ·  *(modo FIEL)*
Densidade das âncoras do **fecho convexo** no modo `--faithful` (RDP): **MAIOR** = menos nós (mais
"hull"); **MENOR** = contorno mais justo (mais nós). **Não afeta o pocket** (lá quem manda é
`--min-dist`).

### `--guide <mm>`  · default `0.5`  ·  *(modo `--tol-fit`)*
Orçamento de suavização do **guia de forma** usado só no caminho `--tol-fit`: maior = menos
Béziers, cavidade mais folgada. Sem efeito no pocket padrão nem no `--faithful`.

---

## 3. Suavização e dimensão

### `--smooth-mm <mm>`  · default `8.0`  ·  **lever fino do contém (2ª rampa)**
Janela do low-pass que remove o serrilhado da silhueta. O piso de contenção é construído sobre a
silhueta **suavizada**:
- **Baixar (8 → 2):** aproxima o piso da peça crua → **empurra o contém para cima**.
- **Subir (+1..2):** tira escadinha/serrilhado — **conflita** com o contém (suaviza para dentro).
- **Rampa adaptativa (2º lever):** mesma lógica de inversão. Direção padrão ↓. Piso ~2 (abaixo
  de ~1 reintroduz serrilha); teto ~10. Engaja quando min-dist (1ª) esgotou.
- **Espigões finos (v0.7):** uma protuberância fina real (recuo ≥ 0.3 mm, boca ≤ 3 mm — ex.: o
  gancho da fita) é **preservada automaticamente** do low-pass (`_preserve_spikes`): não baixe
  o `--smooth-mm` só por causa de um espigão.

### `--mask-smooth-mm <mm>`  · default `0.0` (off)  ·  **regulariza a SILHUETA (não a curva)**
Suaviza a forma da **máscara** ANTES de extrair o contorno: borra o campo de distância com sinal
e re-corta em 0, removendo **saliências e ondulações** de amplitude menor que este raio. Atua na
**fonte** — diferente do `--smooth-mm`, que age na curva já extraída.
- **Quando usar:** borda **PRETA** de baixo contraste (carcaça/borracha) que sai **ondulada** mesmo
  com o contém em 0.9999 — a segmentação serrilha onde o objeto quase se funde com a sombra.
- **Valor:** `~1.5–2` limpa o thermpro sem arredondar os cantos macro (raio ≫ valor). `0` = desligado.
- **Não é um lever das rampas:** some com a ondulação sem apertar/afrouxar o pocket — não mexa
  nas rampas por causa disto.
- **Guarda (v0.7):** se a regularização remover uma **saliência convexa real** (proeminência
  ≥ 0.8 mm e área ≥ 1 mm² — ex.: o gancho da fita de uma trena), o CLI **avisa** no stderr e o
  `contém` — agora medido contra a silhueta **pré**-regularização — **cai abaixo do gate**,
  em vez de validar a silhueta mutilada em silêncio. Resposta típica: `--mask-smooth-keep-bumps`.

### `--mask-smooth-keep-bumps`  · flag · default off  ·  **(v0.5, Etapa B)**
Enviesa o `--mask-smooth-mm` para **fechamento** (um *closing* no campo de distância: `max(sdf,blur)`).
Remove **só as reentrâncias côncavas** (a serrilha de ruído) e **preserva os ressaltos convexos** —
ex.: a **aba lateral** da peça, que o modo isotrópico arredondaria junto com o ruído.
- **Quando usar:** com `--mask-smooth-mm` ligado, quando a regularização está comendo uma **saliência
  real** (convexa) além da serrilha — em particular sempre que o CLI **avisar** que uma saliência
  foi removida (v0.7). Sem efeito se `--mask-smooth-mm` for 0.
- **Cuidado:** também mantém eventuais **picos de ruído convexo** (raros sub-mm; a serrilha de baixo
  contraste é majoritariamente côncava).

### `--clearance <mm>`  · default `0.0`
Folga **externa** aplicada ao contorno. **Padrão 0 = tamanho REAL** (sem ganho). A folga de
encaixe da impressão é aplicada **depois** (a jusante no OpenSCAD, ou à mão). Mexa só se quiser
embutir folga no próprio SVG.

### `--c-fit <mm>`  · default `0.0`
Folga embutida **no SVG** do caminho por contenção; 0 = traço mínimo encostando na peça. Como
`--clearance`, a folga de impressão é normalmente adicionada a jusante. Raramente mexido.

---

## 4. Modos de ajuste (mutuamente relacionados)

| Flag | Default | Modo | bbox | Quando |
|---|---|---|---|---|
| *(nenhuma)* | — | **POCKET de encaixe** | ≥ objeto (sem snap) | padrão; cavidade que contém a peça |
| `--faithful` | off | **FIEL** | = objeto (snap) | contorno **exato** da peça (fecho convexo + subdivisão por contenção). Substitui o antigo `--max-nodes 0` |
| `--tol-fit` | off | por **tolerância** (Schneider) | = objeto (snap) | ajuste por tolerância `--fit-tol` (mais nós). **Tem precedência sobre `--faithful`** |
| `--polyline` | off | polyline cru (`L`) | = objeto | emite o polígono cru em vez de Béziers (`C`) |

### `--fit-tol <mm>`  · default `0.2`
Tolerância do ajuste por tolerância (só com `--tol-fit`).

> **Precedência:** `--tol-fit` desliga o modo ancorado, então `--faithful` é **ignorado** quando
> `--tol-fit` está presente.

---

## 5. Saída e inspeção (não mudam a geometria)

- **`--in` / `-i` `<foto>`** — entrada (obrigatório).
- **`--out` / `-o` `<arquivo.svg>`** — saída; default `<in sem extensão>.svg`.
- **`--inkscape`** (default off) — gera também o overlay **SVG editável** `_overlay_<nome>.svg`
  (foto retificada embutida + Béziers em camadas, no referencial mm) para ajuste fino no Inkscape.
  O overlay **PNG** de conferência (contorno sobre a foto) sai **sempre**.
- **`--edit`** (default off) — abre o **editor de nós** (GUI tkinter, stdlib, rótulos em inglês): a
  foto retificada de fundo + os nós da curva detectada como alças. Arraste = mover; clique na curva =
  inserir; botão-direito = excluir; roda = **zoom no cursor** (o ponto sob o mouse fica parado);
  **Ctrl + arrasto do botão esquerdo = pan**. **Re-trace** traça a curva G1 pelos nós (spline
  Catmull-Rom); mover/inserir/excluir um nó já re-traça. **WYSIWYG:** **Finalize** grava as mesmas
  saídas a partir de **EXATAMENTE a curva que está na tela** — nada é recalculado (fechar sem finalizar
  não grava). A detecção continua automática — você só posiciona os pontos. Parte sempre da curva
  **ancorada** (ignora `--polyline`/`--tol-fit` como ponto de partida) e emite-a **literal** (sem snap
  de bbox). Alternativa fora da CLI: `--inkscape` + Inkscape.
  Controles do plano 011:
  - **Symmetry** (F1) — com `--symmetry` vindo do CLI abre **ligada** (se o pareamento por índice
    se verificar): mover/inserir/excluir/Line num lado **replica no outro** em torno da linha
    pontilhada do eixo (nó sobre o eixo move só ao longo dele; Undo desfaz o casal de uma vez).
    A linha do eixo é **arrastável** (perpendicular a si); eixo movido desativa o espelhamento
    até um **Mirror**. Seletor **V/H** escolhe a orientação quando o CLI não a definiu
    (`--symmetry both` não é suportado no editor — fase 2).
  - **Mirror ◀/▶** (F1b) — reconstrói um lado como **espelho do outro** em torno da posição
    atual do eixo (▶ = a direita é a verdade; com eixo horizontal, ▲/▼). Conserta detecção que a
    sombra inflou de um lado e **constrói o pareamento a partir de qualquer contorno** — é o
    caminho p/ ligar a simetria num contorno que veio sem `--symmetry` ou religá-la após edições
    livres. Recusa (com aviso) contorno que cruza o eixo mais de 2× (mesma limitação do CLI).
  - **Size** (ligada por default) — **cota W×H verde** do objeto fora da bbox; o W×H também
    fica no status bar (útil p/ ajustar o eixo até a largura bater com o paquímetro). A régua
    de bordas da F2 original foi **removida** no redesign da toolbar — a cota + o **Measure**
    cobrem o caso de uso.
  - **Measure** — modo de **medição ponto-a-ponto em mm**: 1º clique marca o ponto A, o
    preview segue o cursor **travado no eixo dominante** do gesto (mais horizontal → trava em
    X; mais vertical → trava em Y) e o 2º clique fecha a medição; **Ctrl no 2º clique = ângulo
    livre** (reta em qualquer direção). Cada medição fica **persistente em destaque** (laranja:
    linha estilo cota com ticks nas pontas, **marca central** em losango e rótulo `NN.NN mm`
    com fundo escuro) até ser excluída com o **botão-direito** sobre ela (dentro do modo; fora
    dele o botão-direito também exclui, se não acertar uma alça de nó). Botão-direito com
    medição em andamento **cancela** o ponto A. Medições são **anotações**: não entram no
    Undo/Reset nem no Finalize (nada vai p/ o SVG). Exclusivo com Rotate/Pan; a rodinha segue
    dando zoom (dentro do modo o Ctrl+arrasto de pan cede a vez ao ângulo livre).
  - **Rotate** (F4) — modo explícito de **giro fino**: linha-guia horizontal no cursor,
    clique-direito = +0.1°, clique-esquerdo = −0.1°, roda = girar (0.05° com Shift); gira
    **foto + nós juntos** (o SVG e o overlay saem girados — WYSIWYG). Girar desliga a simetria
    (v1); p/ peça torta COM simetria prefira `--level` no CLI. Reset zera o ângulo.
  - **Pan** (gêmeo do Rotate) — modo explícito de **deslocamento fino**: linha-guia vertical no
    cursor, clique-direito = +0.1 mm (→), clique-esquerdo = −0.1 mm (←), roda = deslocar
    (0.05 mm com Shift). Move o **contorno inteiro (e o eixo de simetria junto)** com a **foto
    parada** — corrige viés LATERAL da detecção (ex.: sombra que empurrou o contorno p/ um
    lado). Ao contrário do Rotate, **não** desliga a simetria (nós e eixo andam o mesmo passo,
    o pareamento sobrevive por construção). Reset zera o deslocamento e devolve o eixo
    original. Exclusivo com o Rotate (ligar um desliga o outro).
- **`--debug-dir <dir>`** — grava os estágios intermediários (retificação, iluminação,
  segmentação) para inspeção.
- **`--name <nome>`** — rótulo do contorno no SVG; default = nome da foto.

---

## 6. Tabela "sintoma → flag"

| Sintoma observado | Ação |
|---|---|
| **contém < alvo** (pocket não cobre 100%) | Rampas **adaptativas com inversão**: 1ª `--min-dist` → 2ª `--smooth-mm` → 3ª `--pocket-eps`. Direção padrão ↓; parou de melhorar → inverte; piorou na invertida → volta ao melhor e próxima rampa |
| resultado parou de melhorar | Inverta a direção da rampa atual; se a invertida também piora, rampa esgotou → próxima |
| pocket **folgado demais** / clearance grande | sintoma de `--min-dist` alto → **baixe** `--min-dist` (Béziers longas arqueiam p/ dentro) |
| escadinha/serrilhado no contorno | ↑`--smooth-mm` (+1..2) — conflita com o contém; ache o equilíbrio (~2) |
| borda arredondada some / segmentação come a peça (peça **cromática**) | `--shadow remove` |
| corpo **cinza-neutro** + **sombra projetada** vaza no pocket (balão p/ um lado) | `--shadow texture` |
| corpo cinza-neutro **sem** sombra projetada / obj sai pequeno (só o clipe) | ↑`--val-frac` (~0.68) |
| `--mask-smooth-mm` arredondou uma **saliência convexa real** (aba) | + `--mask-smooth-keep-bumps` |
| AVISO `--mask-smooth-mm removeu uma saliência convexa` (e contém caiu) | + `--mask-smooth-keep-bumps` (ou ↓`--mask-smooth-mm`) |
| peça simétrica com contorno ruidoso/torto | `--symmetry vertical\|horizontal` (eixo do objeto) |
| peça apoiada **levemente torta** na base (arestas inclinadas ~0.5–5°) | `--level auto` (antes da simetria); ajuste manual fino = modo **Rotate** do `--edit` |
| sombra inflou **um lado** de peça simétrica (eixo detectado puxado) | `--edit` → Symmetry on → arrastar o eixo → **Mirror** com o lado bom |
| contorno inteiro **deslocado lateralmente** da peça (viés uniforme) | `--edit` → modo **Pan** (0.1 mm/passo; simetria acompanha) |
| bico/canto vivo onde devia arredondar | ↑`--min-radius` (+0.5) |
| quero o contorno **exato** (não pocket) | `--faithful` |
| **sombra dura** (sol) que nenhum `--shadow` resolve | `--in2 <foto2>` com a luz do outro lado (girar base+peça juntas ~180°) — fusão direcional elimina as duas sombras |
| **conector/metal claro** some no papel branco (baía na máscara; pocket bloqueia o conector) | `--in2 <foto2>` — o modo 2 fotos liga o predicado faint-metal e recupera o metal; **conferir no zoom** (o `contém` não acusa, mede contra a própria máscara) |
| peça roída onde as duas sombras se encontram (só com `--in2`) | `--fuse-grow` (~1–2) |
| borda **sem contraste em quase todo o objeto** (peça clara em papel branco; CLI avisou `só NN% da borda tem apoio visual`) | `--humble` (auto, já ativou sozinho) — cordas entre trechos firmes + flags laranja p/ conferir no `--edit`; halo localizado com borda boa no resto → `--humble on` |
| vermelho/contorno vaza p/ o fundo, ou peça clara some no branco (foto única) | limite de segmentação — tentar `--in2` (até com a **mesma** foto: liga o faint-metal, e o halo readmitido é removido pelo `--humble`); persiste → sinalizar p/ melhoria da CLI |
| `ERRO: retificação ... ArUco falhou` | problema de foto/base (imprimir base.svg A4 100%, fotografar perto do nadir, marcadores visíveis, `--dict` casando) |
