# Análise de Timing do Kernel de Eventos: o bug do quadro de 263 linhas

Status: RESOLVIDO - a correção de delta=1 (Rodada 11) implementa a Opção A
recomendada (apply direto da tabela); veja a seção 14 para os números finais.

Data: 2026-08-20

Documento em inglês correspondente: `docs/en/event-kernel-timing-analysis.md`.

## Resumo

Um **evento duplo** (duas escritas de registradores na mesma scanline) faz o
kernel visível estourar seu orçamento de 76 ciclos. O caminho duplo custa
**77 ciclos de CPU** após o `WSYNC` (o "rest" da linha do evento é 73 ciclos).
Qualquer linha de evento cujo rest exceda 71 ciclos empurra o quadro de 262
para 263 scanlines. O bug é reproduzido na ROM montada com um emulador
determinístico, é capturado pela suíte de regressão existente e tem duas
correções candidatas analisadas no final deste documento.

---

## 1. Cenário exato do artefato da Bola reproduzido

Injeção determinística, aplicada à RAM logo antes de `BuildEvents` rodar (a
mesma técnica de `tests/test_frame_timing.py`):

| Variável | Valor |
| --- | --- |
| `P0Y` | 88 |
| `P1Y` | 50 |
| `ball_y` | 88 |
| `m0_y`, `m1_y` | 88 |
| `m_active` | 0 |
| `p0_hp`, `p1_hp` | 3 |

Tabela de eventos resultante (bytes, após `ConvertDeltas`):

```
offset  delta  reg1    val1  reg2  val2    significado
  0      50     0x82    60           -     P1 ON      (simples)
  3      12     0x82     0           -     P1 OFF     (simples)
  6      26     0x01    60     0x05    2   P0 ON + Ball ON   (DUPLO)
 11       4     0x85     0           -     Ball OFF   (simples)
 14       8     0x81     0           -     P0 OFF     (simples)
 17      85     0x7F     0           -     marcador   (simples)
```

`reg1 = 0x01` = `EV_REG_GRP0` (sprite P0 ON, valor `PADDLE_BITS` 60);
`reg2 = 0x05` = `EV_REG_ENABL` (bola ON, valor `BALL_ENABLE` 2). O evento
duplo dispara na **linha 87** do kernel.

Medido no emulador determinístico (`tools/emu6502.py`):

* a linha do evento duplo roda **121** ciclos (passo do WSYNC 48 + rest 73);
* a linha seguinte roda **107** ciclos (passo do WSYNC 79 + rest 28);
* o par consome **228 ciclos = 3 scanlines** em vez de 2;
* todo quadro neste estado roda **19988 ciclos = 263 scanlines** (a linha de
  base é 19912 = 262), repetido em 6 quadros injetados consecutivos.

## 2. Combinação exata de eventos que dispara o caminho problemático

Qualquer **dois eventos fundidos em uma scanline** (uma entrada "dupla" de 5
bytes): o kernel precisa aplicar as duas escritas E decodificar a próxima
entrada na mesma linha. Combinações reproduzidas:

* P0 ON + Ball ON (a injeção manual acima);
* P1 ON + Ball OFF na linha 127, que ocorre **naturalmente** sob o estresse de
  colisão em `test_vblank_never_overruns_with_realistic_branch_timing`
  (quadro 24: 19988 ciclos = 263 scanlines, entrada dupla
  `(linha 127, reg1=GRP1, val1=60, reg2=ENABL, val2=0)`).

A lógica de mesclagem do `InsertEvent` (ordem de geração: o evento existente
mantém a escrita 1, o novo evento assume a escrita 2) é o que cria duplos.
Qualquer mesclagem de dois objetos na mesma linha produz um.

## 3. Prova ciclo a ciclo do caminho do kernel atual

Desmontagem do kernel (`$F100`-`$F15F`), com custos reais do 6502. O "rest"
são todas as instruções entre a conclusão do `STA WSYNC` e o próximo
`STA WSYNC`.

Linha de evento duplo:

```
$F100  STA WSYNC            4     (WSYNC adiciona alinhamento; não faz parte do rest)
$F102  LDX pendReg1         3
$F104  LDA pendVal1         3
$F106  STA $1A,X            4     escrita 1
$F108  LDX pendReg2         3
$F10A  LDA pendVal2         3
$F10C  STA $1A,X            4     escrita 2
$F10E  DEC evCnt            5
$F110  BNE $F100            2     não tomado (evCnt chegou a 0)
$F112  LDA evTbl+1,Y        4     reg1 | EV_SINGLE_FLAG
$F115  BMI $F134            2     não tomado (duplo: sem flag simples)
$F117  STA pendReg1         3
$F119  LDA evTbl+2,Y        4     val1
$F11C  STA pendVal1         3
$F11E  LDA evTbl+3,Y        4     reg2
$F121  STA pendReg2         3
$F123  LDA evTbl+4,Y        4     val2
$F126  STA pendVal2         3
$F128  TYA                  2
$F129  ADC #5               2
$F12B  TAY                  2     avançar para a próxima entrada
$F12C  LDA evTbl,Y          4     próximo delta
$F12F  STA evCnt            3     recarregar contagem
$F131  JMP $F100            3     voltar ao WSYNC
       ---------------------------------
       rest = 73 ciclos      (caminho = 73 + 4 = 77 ciclos)
```

Linha de evento simples (mesmo front; BMI tomado em `$F115`):

```
... front (STA..BNE)        20+5+2
$F112  LDA evTbl+1,Y        4
$F115  BMI $F134            3     tomado
$F134  AND #$7F             2
$F136  CMP #$7F             2
$F138  BEQ $F151            2     não tomado (não é o marcador)
$F13A  STA pendReg1         3
$F13C  LDA evTbl+2,Y        4
$F13F  STA pendVal1         3
$F141  LDA #0               2
$F143  STA pendReg2         3
$F145  TYA / ADC #3 / TAY   6     avançar por 3
$F149  LDA evTbl,Y          4
$F14C  STA evCnt            3
$F14E  JMP $F100            3
       ---------------------------------
       rest = 71 ciclos      (caminho = 75 ciclos)
```

Linha sem evento:

```
$F100  STA WSYNC            4
$F102..$F10C bloco de escrita 20
$F10E  DEC evCnt            5
$F110  BNE $F100            3     tomado
       ---------------------------------
       rest = 28 ciclos      (caminho = 32 ciclos)
```

Totais de linha confirmados no emulador (com o alinhamento do WSYNC):

| Linha | Passo WSYNC | rest | total |
| --- | --- | --- | --- |
| sem evento | 48 | 28 | 76 |
| evento simples | 48 | 71 | 119 |
| evento duplo | 48 | 73 | 121 |
| linha após simples | 5 | 28 | 33 |
| linha após duplo | 79 | 28 | 107 |

## 4. Por que o caminho atual chega a 77 ciclos

Cada peça do caminho duplo está no seu piso do 6502:

* escritas: 2 x (LDX zp 3 + LDA zp 3 + STA zp,X 4) = 20 - mínimo;
* contagem: DEC zp 5 + BNE 2 = 7 - mínimo;
* teste de flag: LDA abs,Y 4 + BMI 2 = 6 - mínimo;
* armazenamento de decodificação: 4 x (LDA abs,Y 4 + STA zp 3) = 28, e reg1
  reutiliza o load do teste de flag - mínimo;
* avanço: TYA/ADC #5/TAY = 6 (ver seção 6 - mínimo);
* recarga: LDA abs,Y 4 + STA zp 3 = 7 - mínimo;
* JMP de fechamento: 3.

A linha de evento precisa aplicar 2 escritas, decodificar a próxima entrada
(reg1/val1/reg2/val2 + avanço + recarga) e reiniciar a scanline, tudo dentro
de uma linha de 76 ciclos. Só a decodificação custa 46 ciclos (flag 6 +
stores 28 + avanço 6 + recarga 7, menos o front que é compartilhado). Nada no
caminho pode ser encurtado sem mudar a arquitetura (seções 6 e 8).

## 5. Por que isso causa o artefato observado na Bola

Condição de estabilidade do quadro. As linhas do kernel rodam em uma fase
fixa: o rest `r` de uma linha módulo 76 determina a fase da linha seguinte.
Uma linha é *segura* se `r <= 71` (após uma linha com rest 72 ou 73 o quadro
escorrega):

* `r <= 71`: a linha de evento (48 + r) mais a linha seguinte compensadora
  somam sempre **152 = exatamente 2 scanlines** (48+r + 104-r = 152). A fase
  volta ao estado estacionário e o quadro permanece em 262.
* `r = 72`: o próximo `WSYNC` cai exatamente numa fronteira de 76 (rem 0) e o
  modelo adiciona uma linha extra completa; o par vira 228 ciclos = 3
  scanlines.
* `r = 73`: o par é 121 + 107 = 228 ciclos = 3 scanlines (medido).

O evento duplo tem `r = 73`, então o par consome 3 scanlines e todo quadro
vira 263 scanlines. O artefato da Bola é o deslocamento vertical do *quadro
inteiro* (uma scanline extra empurra todos os objetos uma linha para baixo
naquele quadro). Como um duplo pode envolver a bola (P0+Ball ON, P1+Ball
OFF), o artefato é comumente visto na bola, mas não é específico dela:
**qualquer** mesclagem na mesma linha de quaisquer dois objetos o dispara.

Nota: a posição horizontal da bola **não** entra no caminho do kernel - o
kernel é construído apenas a partir das linhas. X só importa para o timing de
escrita vs feixe (Rounds 8/9, seção 9), que o kernel atual satisfaz.

## 6. Por que a otimização `nextPtr` anteriormente proposta é impossível

O plano era estender cada entrada da tabela com um byte "ponteiro para a
próxima entrada" para que o kernel avançasse com um `LDY evTbl+5,Y` de 4
ciclos (ou `+3`) em vez dos 6 ciclos de `TYA / ADC #5 / TAY`.

O 6502 **não tem o modo de endereçamento `LDY abs,Y`**. Os modos `abs,Y`
existem apenas para `ADC, AND, CMP, EOR, LDA, LDX, ORA, SBC, STA` (verificado
contra a matriz de opcodes). Os substitutos válidos custam todos os mesmos 6
ciclos do avanço atual:

* `LDA evTbl+5,Y` (4) + `TAY` (2) = 6;
* ou manter `LDA evTbl+5,Y` em A e usá-lo como delta diretamente = 4 + 3
  (STA evCnt) = 7, que é *mais* que o 6 + 7 atual.

Então o formato `nextPtr` economiza **zero** ciclos e foi abandonado.

## 7. Todas as alternativas realistas investigadas

Para a arquitetura atual a redução necessária é de **2 ciclos** (rest 73 deve
virar <= 71):

1. **Reestruturar a cauda do duplo.** Teste de flag (6), stores (28), avanço
   (6), recarga (7) estão todos no piso do 6502; `DEC evCnt`/`BNE` (7) é
   mínimo. Nenhuma instrução individual pode ser removida ou encurtada.
2. **Formato `nextPtr`.** Inválido: não existe `LDY abs,Y` (seção 6).
3. **Evitar estado em RAM / heurísticas para economizar um ciclo.** O esquema
   de escritas pendentes é o próprio mecanismo de velocidade (as escritas
   custam 10 ciclos cada porque os valores ficam em zero page); carregar da
   tabela custa 14 cada (seção 10). Não há arranjo mais barato.
4. **Eliminar o `JMP` de fechamento por layout de código** (descoberto nesta
   análise). O bloco de decodificação pode ser colocado imediatamente antes
   de `KernelLoop`, de modo que o `BNE` da contagem (tomado para linhas sem
   evento) pule para o WSYNC e o caminho "não tomado" caia *dentro* da
   decodificação, cuja recarga então cai *através* do WSYNC. Isso remove o
   `JMP` de 3 ciclos: rest do duplo 73 -> **70**, rest do simples 71 -> **68**.
   Ambos são <= 71, então o quadro volta a 262 **sem nenhuma mudança de RAM**
   e com o timing de escrita intocado. Margem: o caminho duplo tem apenas
   **1 ciclo** de folga abaixo do limite de 71 (e 2 abaixo do orçamento de
   76).
5. **Dividir a decodificação em duas linhas (prefetch).** Carregar metade da
   próxima entrada na linha onde `evCnt == 2` e metade onde `evCnt == 1`, de
   modo que a linha do evento apenas aplique as escritas. As linhas de
   prefetch rodariam em rest ~43 e ~58 (ambas <= 71). Rejeitada como complexa
   demais: o kernel precisa testar `evCnt` contra 1 e 2 toda linha (pares
   extras de CMP/BNE), ainda precisa saber se a próxima entrada é simples ou
   dupla (formato de tamanho variável mantém os testes de flag), e o builder
   só fica intocado se o formato permanecer variável - o ganho sobre a opção
   4 é marginal.

A opção 4 é viável e é a candidata "mudança menor"; a opção 1 com o formato
table-direct é a candidata grande porém durável. Ambas são dimensionadas na
seção 14.

## 8. Arquitetura proposta A: kernel table-direct de 5 bytes uniformes

### Representação antiga de eventos

Dois formatos de tamanho variável, distinguidos pelo bit 7 do byte reg1:

```
simples (3 bytes): [delta, reg1|EV_SINGLE_FLAG, val1]
duplo   (5 bytes): [delta, reg1, val1, reg2, val2]
marcador (3 bytes):[delta, EV_MARKER_REG, val]
```

O kernel copia uma entrada para quatro registradores pendentes em zero page
na linha de evento anterior e as aplica no início de cada scanline. O custo
da decodificação é o que estoura o orçamento.

### Nova representação de eventos

Um formato uniforme para todas as entradas (inclusive o marcador):

```
entrada (5 bytes): [delta, reg1, val1, reg2, val2]
marcador (5 bytes):[delta, 0, $FF, 0, 0]   val1 = $FF é o sentinela final
null    (5 bytes):[delta, 0, 0, 0, 0]     entrada de preenchimento em Y = 0
```

* simples definem `reg2 = 0, val2 = 0` (uma escrita benigna em `$1A`, o byte
  TIA reservado `EV_WRITE_BASE + 0`);
* o marcador é detectado por `val1 == $FF` (a decodificação lê `evTbl+2,Y`);
  seus bytes reg/val são 0, então suas próprias escritas são benignas;
* `EV_SINGLE_FLAG`, `EV_MARKER_REG`, `EV_MARKER_INDEX` são removidos.

Layout da tabela: `[null] + até EV_MAX_EVENTS entradas + [marcador]`.

### Fluxo antigo do kernel

```
WSYNC -> aplicar pendReg1/val1 -> aplicar pendReg2/val2
      -> DEC evCnt -> BNE WSYNC
      -> (evCnt == 0) LDA evTbl+1,Y -> BMI simples
           duplo: STA pendReg1/val1/reg2/val2 (4 loads), TYA/ADC#5/TAY,
                  LDA evTbl,Y, STA evCnt, JMP
           simples: AND#7F, CMP#7F, BEQ fim-marcador, STA pendReg1/val1,
                    pendReg2=0, TYA/ADC#3/TAY, recarga, JMP
```

### Novo fluxo do kernel

Toda linha lê suas escritas direto da entrada atual da tabela (Y só muda em
linhas de evento):

```
WSYNC
LDA evTbl+1,Y / TAX / LDA evTbl+2,Y / STA $1A,X    escrita 1 (14 ciclos)
LDA evTbl+3,Y / TAX / LDA evTbl+4,Y / STA $1A,X    escrita 2 (14 ciclos)
DEC evCnt -> BNE WSYNC                                (contagem)
(evCnt == 0) LDA evTbl+2,Y / CMP #$FF / BEQ marcador  teste do marcador
             TYA / CLC / ADC #5 / TAY                 avanço (sempre +5)
             LDA evTbl,Y / STA evCnt                  recarga do delta
             cair através no WSYNC (sem JMP)
```

Sem registradores pendentes, sem distinção simples/duplo, sem ramificação
dependente de dados no caminho do kernel.

### Contagens de ciclo do kernel

| Linha | ciclos | rest | vs limite 71 |
| --- | --- | --- | --- |
| sem evento | 40 | 36 | 35 abaixo |
| evento simples | 62 | 58 | 13 abaixo |
| evento duplo | 62 | 58 | 13 abaixo |
| linha do marcador | 48 | 44 | - |

Pior caminho do kernel: **62 / 76 ciclos** (folga 14). O rest 58 da linha de
evento pareia com a linha seguinte em exatamente 152 ciclos = 2 scanlines,
então o quadro é 262 para qualquer entrada. O custo é constante porque o
bloco de escrita e a decodificação leem offsets fixos - nenhum branch depende
de quais objetos dispararam, de quantas escritas a entrada tem, dos deltas ou
das linhas.

### Mudanças no BuildEvents

* `InsertEvent`: insere uma entrada uniforme de 5 bytes; a mesclagem na mesma
  linha só preenche `reg2/val2` em `+3/+4` (sem shift, a entrada já tem 5
  bytes); lógica de bump de três-na-mesma-linha inalterada; o branching de
  simples/duplo é removido. Uma mesclagem na mesma linha preserva a ordem de
  geração por padrão.
* `ConvertDeltas`: avança por 5 incondicionalmente (sem teste de flag); delta
  do marcador = `KERNEL_SCANLINES - prevRow`.
* Priming: `Y = 0` aponta para a entrada null; `evCnt = evTbl+5` (primeiro
  delta real). Um prime com delta 0 define `Y = 5`, `evCnt = evTbl+10`.

### Prova de estabilidade / quadro para todas as entradas

A estabilidade exige que o rest de toda linha de evento seja <= 71. Neste
kernel o rest do evento é uma **constante 58** independente de:

* quais dois objetos fundiram (reg1/reg2 = qualquer um de
  GRP0/GRP1/ENAM0/ENAM1/ENABL);
* os valores de escrita;
* os deltas (linhas);
* a posição X da bola (X nunca aparece no kernel; só afeta a posição
  horizontal RESBL definida no VBLANK).

Não há entrada que possa fazer a linha de evento exceder 62 ciclos, então a
condição que produziu rest 73 (e o quadro de 263 scanlines) é estruturalmente
inalcançável. Em particular, **toda posição válida da Bola (0..156) é
segura**: o timing do kernel não depende de X, e a garantia de timing de
escrita para X é coberta separadamente abaixo.

### Timing de escrita e a garantia horizontal

A garantia dos Rounds 8/9 é "uma escrita termina antes de o feixe passar pelo
X do objeto na linha alvo" (modelo do feixe: pixel `p` no ciclo ~`(p+69)/3`;
pixel 0 em ~ciclo 23). Neste kernel:

* a escrita 1 termina no **ciclo 14** (gate cobre todo x >= -27, ou seja,
  todo x);
* a escrita 2 termina no **ciclo 28** (gate cobre x >= 15).

P0 (x=16), P1 (x=136) e M0 (x >= 18) sempre satisfazem o segundo gate, mas a
bola (x 0..156) e M1 (x até 2) podem cair abaixo de 15. O builder deve
portanto garantir que a bola e o M1 nunca ocupem o slot 2. Duas regras
pequenas no `InsertEvent`:

* inserir os eventos da bola e do M1 **antes** dos jogadores e do M0 (eles
  naturalmente assumem o slot 1 em uma mesclagem);
* nunca mesclar a bola com M1 (ambos têm x < 15 alcançável) - mover o evento
  M1 para linha+1, reutilizando o mecanismo existente de três-na-mesma-linha.

Com essas regras, toda segunda escrita mira P0/P1/M0 (x >= 15), então a
garantia horizontal vale para todos os objetos em todas as posições. Custo:
algumas instruções extras de VBLANK; o kernel fica intocado.

### Detalhamento de RAM (antes / depois)

Antes (56 bytes usados, $80-$B7):

```
$80-$81 P0Y/P1Y            $82-$83 p0_hp/p1_hp
$84-$87 ball_x/y/dx/dy     $88-$8B m0_x/m0_y/m1_x/m1_y
$8C m_active  $8D hit_flags  $8E fire_prev  $8F evCnt
$90 pendReg1 $91 pendVal1 $92 pendReg2 $93 pendVal2
$94-$B4 evTbl (33 bytes)   $B5 evRow  $B6 tempCount  $B7 tblLen
```

Depois (79 bytes usados, $80-$CF):

```
$80-$8F inalterado (estado do jogo + evCnt)           16 bytes
$90-$93 liberados (registradores pendentes removidos)  -4 bytes
$94-$CF evTbl = 5 + 10*5 + 5 = 60 bytes               +27 bytes
$B5-$B7 scratch do builder inalterado                  3 bytes
```

**Líquido: 56 - 4 + 27 = 79 bytes usados, 49 disponíveis.**

### Por que o aumento é exatamente 23 bytes

* a tabela cresce 33 -> 60 (+27): entrada null (5) + 10 entradas uniformes
  (50) + marcador (5), contra 30 + 3 do pior caso antigo. No pior caso, uma
  tabela só de simples agora é 5 + 30 + 5 = 40 (era 33); uma tabela cheia é
  60;
* os quatro registradores pendentes são removidos (-4);
* líquido +23.

### Algum dos 23 bytes pode ser reutilizado?

* Os 4 bytes pendentes liberados estão genuinamente mortos (o kernel não os
  precisa mais) e são recuperados pelo crescimento.
* A tabela é escrita durante o VBLANK (BuildEvents) e lida durante a exibição,
  então deve persistir o quadro inteiro; não pode se sobrepor ao estado do
  jogo (lido durante o VBLANK) nem ao scratch do builder
  (`evRow`/`tempCount`/`tblLen`, vivos durante a construção).
* `tblLen`/`evRow`/`tempCount` poderiam teoricamente dividir bytes com a
  tabela após a construção, mas estão no meio do walk do quadro e o kernel
  precisa da tabela intacta - não existe sobreposição segura.

Então **79 bytes é o requisito real de estado estacionário**, não uma
alocação conservadora. A única forma de encolher é reduzir `EV_MAX_EVENTS`
(cada entrada custa 5 bytes): com 9 eventos a tabela tem 55 bytes e a RAM 74.
Dez é o teto natural (5 objetos x ON/OFF = 10 eventos de linhas distintas;
ON/OFF nunca podem dividir a mesma linha porque todo objeto tem >= 2 pixels
de altura).

### A tabela pode ser colocada/reutilizada de outra forma?

O kernel lê entradas com `LDA abs,Y` (base de 16 bits) e escreve com
`STA $1A,X` (zero page), então a tabela poderia viver em qualquer lugar do
espaço de endereçamento - mas a única RAM gravável no 2600 é a RIOT $80-$FF
(128 bytes) mais a página de pilha. A pilha está viva durante o VBLANK
(JSRs), então a tabela não pode usá-la. Não há colocação alternativa que evite
o +23.

### Estimativa de ROM (antes / depois)

* ROM atual: 1552 / 4096 bytes (37,9%).
* O novo kernel perde o branching de decodificação simples/duplo e os stores
  pendentes (economiza ~10 bytes), mas o bloco de escrita cresce (18 vs 12
  bytes);
* o BuildEvents perde o branching de tamanho no InsertEvent/ConvertDeltas
  (~15 bytes economizados) e ganha as regras de ordenação de slot (~10
  bytes);
* resultado estimado é **aproximadamente neutro: 1530-1590 bytes** (bem
  dentro do limite de 4096; não é uma restrição em nenhum dos casos).

### Custo de VBLANK (antes / depois)

O código de VBLANK (movimento, mísseis, posicionamento, a construção) não é
alterado pela reescrita do kernel. `BuildEvents` fica ligeiramente *mais
barato* (sem branching de tamanho simples/duplo, avanço sempre +5) além das
verificações de ordenação de slot. O pior caso atual medido de trabalho de
VBLANK é ~4867 ciclos contra expiração do timer de (77*64) = 4928 (margem
~61 ciclos sob o limite real; a fórmula conservadora "(77-1)*64 = 4864" é
apenas convenção de segurança). Delta esperado: alguns ciclos em qualquer
direção - **não é o motor desta mudança**.

### Impacto esperado na RAM de gameplay futuro

49 bytes permanecem (de 128) com o design table-direct. Para o escopo atual
(jogadores, bola, dois mísseis, HP, flags de hit) isso é confortável:
aproximadamente 10-20 bytes adicionais absorveriam mais objetos ou estado. A
folga de ROM é de 2544 bytes. O recurso vinculante após esta mudança é a RAM,
e ela permanece adequada.

## 9. O design table-direct elimina o artefato da Bola para todas as posições X válidas?

Sim, por três razões independentes:

1. **O custo do kernel é independente da entrada.** O caminho de evento é uma
   constante de 62 ciclos (rest 58) para toda tabela de eventos possível. A
   condição do bug (rest 73) é inalcançável porque nenhum branch do kernel
   depende dos dados dos objetos.
2. **A matemática do quadro é independente da posição.** Qualquer linha de
   evento (rest 58) mais sua linha seguinte soma exatamente 152 ciclos = 2
   scanlines, então o quadro é 262 independente das linhas envolvidas.
   Posições X nunca entram no kernel.
3. **A garantia horizontal (escrita vs feixe) é preservada** pelas regras de
   ordenação de slot do builder (seção 8), então nenhum objeto - inclusive a
   bola em qualquer x de 0..156 - é escrito depois do seu gate.

A única ressalva é o gate da segunda escrita no ciclo 28, que as regras de
ordenação foram projetadas exatamente para lidar; sem elas, uma bola/M1 no
slot 2 com x < 15 reintroduziria um artefato horizontal. Este é o detalhe de
implementação mais importante a acertar.

## 10. 79/128 é o requisito verdadeiro de estado estacionário?

Sim. Não há memória temporária/do builder cujo tempo de vida não se sobreponha
à tabela:

* a tabela está viva desde o BuildEvents (VBLANK) até a última linha do
  kernel;
* `evRow`, `tempCount`, `tblLen` estão vivos *durante* a construção, quando a
  tabela está sendo escrita - sem sobreposição;
* os registradores pendentes são removidos inteiramente;
* os quatro bytes liberados são recuperados pelo crescimento da tabela.

A única alavanca é `EV_MAX_EVENTS` (5 bytes por entrada) - 79 é o requisito
verdadeiro no teto atual de 10 eventos.

## 11. Comparação das duas correções viáveis

| Métrica | Atual (quebrado) | Opção 4: remoção do JMP | Opção A: table-direct |
| --- | --- | --- | --- |
| Rest do evento duplo | 73 | **70** | **58** |
| Rest do evento simples | 71 | 68 | 58 |
| Pior caminho do kernel | 77 | 74 | 62 |
| Folga do kernel (76 - pior) | -1 (estoura) | 2 | 14 |
| Folga abaixo do limite 71 | -2 (estoura) | 1 | 13 |
| Scanlines do quadro | 263 (bug) | 262 | 262 |
| RAM usada / disponível | 56 / 72 | 56 / 72 | 79 / 49 |
| ROM (estimativa) | 1552 | ~1550 | ~1530-1590 |
| Ciclo da segunda escrita | 23 | 23 | 28 |
| Mudanças no builder | - | nenhuma | formato uniforme + regras de slot |
| Testes que precisam mudar | - | apenas orçamento do test_timing | modelo de eventos, timing, testes de quadro |
| Garantia horizontal | todo x | todo x | todo x *com* regras de slot |

## 12. Recomendação

Ponderando **folga de timing do kernel para recursos futuros** contra **folga
de RAM para gameplay futuro** (e não otimizando somente para o bug atual):

* Opção A (table-direct): o pior caso do kernel cai de 77 para uma **constante
  62**, deixando 13 ciclos de folga abaixo do limite de perigo e 14 abaixo do
  orçamento de 76. O custo constante e sem branch significa que *essa classe
  de bug não pode voltar* quando o gameplay crescer (mais objetos, efeitos,
  mudanças por linha). Custo: +23 bytes de RAM (49 livres - ainda confortável
  para o escopo do jogo), uma regra de ordenação de slot no builder para
  preservar a garantia horizontal, e uma revisão maior dos testes.
* Opção 4 (remoção do JMP): a menor correção possível. Zero RAM, timing de
  escrita intocado, garantia de todo-x preservada. Mas o evento duplo fica a
  **1 ciclo** do limite de perigo de 71 - qualquer mudança futura que adicione
  um único ciclo ao caminho de evento (mesmo uma instrução em toda linha)
  quebra o quadro silenciosamente e força outra reforma do kernel.

**Recomendação: Opção A (table-direct).** A folga de timing do kernel é a
restrição vinculante: o kernel é o subsistema mais difícil de mudar e já
produziu este bug uma vez. A margem de 1 ciclo da correção menor está abaixo
do próprio padrão do projeto de "correção de timing em primeiro lugar"
(AGENTS.md) para uma base de código cujo gameplay é explicitamente esperado
para evoluir. 49 bytes de RAM livre permanecem adequados para o escopo
previsível, e a ROM (2544 livres) não é uma restrição.

Alternativa: se a conservação de RAM for julgada mais importante que a folga
de kernel, a Opção 4 é uma correção imediata sólida (rest 70) que deve ser
acompanhada de um teste de regressão afirmando que o caminho duplo permanece
<= 71 ciclos.

## 13. Limitações / notas conhecidas

* O sentinela do marcador `val1 = $FF` reserva $FF como valor de escrita
  impossível; se o gameplay futuro precisar escrever $FF em um registrador
  TIA, o local do sentinela deve mudar (ex.: para `reg1 = $FF`, que é seguro
  porque o bloco de escrita nunca escreve `$1A + $FF`).
* O kernel table-direct escreve um $FF benigno no TIA $1A na linha do marcador
  (registrador reservado, inofensivo).
* Todos os números deste documento vêm do emulador determinístico
  (`tools/emu6502.py`) e da listagem montada; não foram revalidados em
  Stella/hardware.

## 14. Resolução (Rodada 11, correção de delta=1): o que foi realmente construído

A Opção A foi implementada com um pequeno refinamento sobre o esboço da seção
8. A análise acima assumia que a linha de evento *cairia* no próximo `WSYNC`
(economizando o JMP). A implementação mantém um `JMP KernelLoop` uniforme no
final de todo caminho (`.applyOnly`), o que fixa a estrutura do loop e deixa o
teste do marcador reutilizar o mesmo formato de entrada. As consequências:

* o bloco de apply lê a última entrada decodificada através de `Y-5` (Y sempre
  aponta uma entrada além da última decodificada), então **o apply roda
  incondicionalmente em toda linha** - esta é a correção de delta=1: dois
  eventos em linhas consecutivas (delta 1) não podem mais colidir, porque o
  apply acontece antes da contagem, não depois de um pipeline pendente
  adiado;
* o sentinela do marcador mudou para o byte de **delta** da entrada (`$FF`),
  lido com `CMP #EV_MARKER_VAL` depois de carregar `evCnt`; o caminho do
  marcador encerra o kernel no ciclo 46 da linha;
* a entrada nula no offset 0 é um **dummy** (delta `$FF`, regs zerados), então
  o apply anterior ao primeiro evento escreve apenas em AUDV0; as entradas
  reais começam no offset 5;
* orçamentos medidos do kernel (listagem + emulador): **sem evento 38, evento
  54, marcador 46**, pior caso 54/76 (folga 22, maior que o 62 previsto pela
  análise porque o JMP soma 3 ciclos a todo caminho);
* a escrita 1 termina no ciclo **15** (segura para todo x), a escrita 2 no
  ciclo **27** (segura para x >= 13 pelo modelo conservador de feixe; a regra
  de slot do builder exige x >= 15);
* RAM: o dummy adiciona 5 bytes sobre a entrada nula da análise, e os
  registradores pendentes foram removidos: **80 bytes usados, 48 livres**
  (a análise previu 79/49);
* ROM: **1808 / 4096 bytes** (a análise previu ~1530-1590; o build real é
  maior porque o builder ciente de offsets e as regras de ordem de slot custam
  mais do que o estimado, ainda muito dentro do limite).

Os testes de regressão em `tests/test_event_collision.py`, `test_events.py` e
`test_frame_timing.py` validam o kernel implementado contra o modelo Python
byte por byte e executam o kernel real no emulador para as cenas exatas de
delta=1 que estavam quebradas antes.