# Wizard Duel - Timing

Este documento registra a análise de timing em nível de ciclo do kernel
orientado a eventos e do quadro da Rodada 11. Cada número abaixo foi
derivado manualmente e depois verificado contra o listing montado pela suíte
de testes automatizada; o comprimento do quadro foi também verificado com um
emulador 6502 determinístico que modela as paradas de WSYNC e o timer do
RIOT.

## Estrutura do quadro (NTSC)

| Região    | Scanlines | Como é produzida               |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | três `STA WSYNC` explícitos    |
| VBLANK    | 64        | contagem `TIM64T = 77`         |
| KERNEL    | 185       | loop explícito de `STA WSYNC`  |
| OVERSCAN  | 10        | loop fixo de `WSYNC`            |
| **Total** | **262**   |                                |

O VBLANK cresceu de 37 (Rodada 2) para 57 linhas e o OVERSCAN encolheu de 30
para 10 linhas para dar espaço ao `BuildEvents` reconstruir a tabela de
eventos a cada quadro. Na Rodada 6 o VBLANK cresceu de 57 para 64 linhas e o
KERNEL encolheu de 192 para 185 para fechar um bug de tremor de quadro sob
timing de branch realista (ver abaixo).

### Por que o timer do VBLANK é 77 e o overscan é um loop de WSYNC

O timer do RIOT conta a cada 64 ciclos. A Rodada 2 usou `43`/`37` para uma
divisão de 37/30 linhas; os valores da Rodada 3/4 foram derivados do mesmo
modo (o timer expira alguns ciclos antes do valor ingênuo `valor * 64`, e o
`STA WSYNC` após a espera sincroniza na linha correta) e depois ajustados
empiricamente para que o emulador reporte exatamente 262 scanlines por
quadro:

* `VBLANK_TIMER_VALUE = 77` expira na penúltima linha do VBLANK; o
  `STA WSYNC` seguinte sincroniza na última linha do VBLANK, onde `HMOVE` é
  escrito imediatamente após o `WSYNC` (exigido para que os registradores de
  movimento atuem durante o blanking horizontal da última linha do VBLANK);
* o OVERSCAN NÃO usa timer. Uma espera `TIM64T` só é determinística quando o
  trabalho executado antes de armar o timer é fixo; na Rodada 4 a passagem de
  colisão de custo variável fez a saída de `INTIM < 64` cair em fronteiras de
  76 ciclos diferentes e o quadro ocasionalmente escorregou para 263
  scanlines. Em vez disso, o overscan escreve exatamente `OVERSCAN_LOOP_COUNT
  = 7` `WSYNC`s. A partir da última linha do kernel, um epílogo fixo + o JSR e
  o corpo sem branches do `ProcessCollisions` + o JSR do `ProcessHitEffects`
  (Rodada 5) colocam o primeiro `WSYNC` entre os ciclos 187 e 207 da região
  (modelo do emulador; todo caminho cai na mesma fronteira no ciclo 228 =
  scanline 3). O loop conta então exatamente 10 linhas e o `JMP` + preâmbulo
  de VSYNC seguintes alinham o primeiro `WSYNC` de VSYNC do próximo quadro em
  760 ciclos após a última linha do kernel. Como a única passagem de custo
  variável (`ProcessHitEffects`) fica confinada a uma janela que nunca escapa
  da primeira fronteira, a região tem exatamente 10 scanlines
  independentemente de quantos acertos forem detectados ou de os jogadores
  estarem mortos.

## O kernel visível

Um scanline = **76 ciclos de CPU**. Cada iteração do kernel começa com
`STA WSYNC`, então cada iteração é exatamente um scanline; o quadro não pode
derivar quando eventos disparam.

### Estrutura orientada a eventos

O kernel não calcula enables de objetos. `BuildEvents` (executado durante o
VBLANK) escreve uma tabela fixa (`evTbl`, 60 bytes) de entradas uniformes de 5
bytes `[delta, reg1, val1, reg2, val2]` (reg2 = 0 marca uma escrita única).
Os índices 1..5 endereçam GRP0..ENABL; o índice 0 é o dummy AUDV0 usado pelos
primeiros 5 bytes da tabela. A tabela é `[dummy][entrada 0][entrada 1]...
[entrada N][marcador]`, onde o byte de delta do marcador é `$FF` e encerra o
kernel. Os deltas são as distâncias até a PRÓXIMA entrada; `nullDelta` inicia
a primeira contagem.

O kernel é um **apply direto da tabela**: todo scanline começa aplicando as
duas escritas da última entrada decodificada diretamente da tabela, lendo por
`Y-5` (Y sempre aponta uma entrada além da última decodificada), e então conta
`evCnt` até o próximo evento. Como o apply roda incondicionalmente no INÍCIO
de toda linha - seja linha de evento ou não - dois eventos em linhas
consecutivas (delta 1) nunca podem colidir como acontecia com o pipeline
pendente em duas fases da Rodada 10: cada entrada aplica suas escritas no
início da sua própria linha de exibição. O apply é idempotente, o que torna
inofensivo reaplicar a mesma entrada nas linhas entre eventos.

Os primeiros 5 bytes da tabela são uma entrada dummy (reg1 = reg2 = 0, então
ambas as escritas vão para AUDV0 - inofensivo com a tela ligada). Nas linhas
antes de o primeiro evento disparar, Y = 5 faz o apply ler o dummy. As
entradas reais começam no offset 5 da tabela e o marcador fica no offset
`5 + 5*N`.

### Contabilidade de ciclos (verificada no listing)

Existem três caminhos por scanline: sem evento, evento e marcador de fim. O
corpo do kernel é alinhado a página (`ALIGN 256` antes de `KernelLoop`) para
que todo desvio tenha tempo determinístico, e todos os acessos à tabela são
indexados em zero page (`LDX evTbl-4,Y` emite `0xB6` LDX zp,Y) para que
nenhum acesso indexado cruze uma página.

Linha sem evento (o caso comum):

| Instrução           | Ciclos |
| ------------------- | ------ |
| `STA WSYNC`         | 3      |
| `LDX evTbl-4,Y`     | 4      |
| `LDA evTbl-3,Y`     | 4      |
| `STA EV_WRITE_BASE,X` | 4    |
| `LDX evTbl-2,Y`     | 4      |
| `LDA evTbl-1,Y`     | 4      |
| `STA EV_WRITE_BASE,X` | 4    |
| `DEC evCnt`         | 5      |
| `BNE .applyOnly`    | 3      |
| `JMP KernelLoop`    | 3      |
| **Total**           | **38** |

Linha de evento (leitura do delta + avanço):

| Instrução           | Ciclos |
| ------------------- | ------ |
| (bloco apply, 24) + `DEC evCnt` (5) + `BNE` não tomado | 31 |
| `LDA evTbl,Y`       | 4      |
| `STA evCnt`         | 3      |
| `CMP #EV_MARKER_VAL` | 2     |
| `BEQ .kernelEnd` não tomado | 2 |
| `TYA` / `ADC #5` / `TAY` | 6  |
| `JMP KernelLoop`    | 3      |
| **Total**           | **54** |

Linha do marcador de fim (marcador disparou -> kernel termina):

| Instrução           | Ciclos |
| ------------------- | ------ |
| (bloco apply, 24) + `DEC evCnt` (5) + `BNE` não tomado | 31 |
| `LDA evTbl,Y`       | 4      |
| `STA evCnt`         | 3      |
| `CMP #EV_MARKER_VAL` | 2     |
| `BEQ .kernelEnd` tomado | 3   |
| **Total**           | **46** |

| Caminho                    | Ciclos |
| -------------------------- | ------ |
| Linha sem evento           | **38** |
| Linha de evento            | **54** |
| Linha do marcador de fim   | **46** |
| Orçamento do scanline      | 76     |
| Folga (linha de evento)    | **22 ciclos** |

A flag de carry é limpa exatamente uma vez, na inicialização (`CLC`); em todo
caminho do kernel o carry está limpo no `ADC #5`: o `CMP #$FF` do decode de
evento o limpa para todo delta real (< $FF), e o `CMP` do marcador só seta o
carry no caminho `BEQ .kernelEnd` (que pula o `ADC`). Não existe `CLC` dentro
do corpo do kernel.

### Tempos de escrita dos registradores gráficos

Medidos no emulador determinístico, as escritas de registrador caem nestes
ciclos de CPU dentro de um scanline:

* escrita 1 (reg1/val1): termina no ciclo **15**, antes de o feixe chegar ao
  pixel 0 (cerca do ciclo 23), então é segura para todo objeto, incluindo a
  bola em x = 0;
* escrita 2 (reg2/val2): termina no ciclo **27**.

Uma escrita no TIA se aplica ao scanline atual apenas se terminar antes de o
feixe passar pela posição horizontal do objeto; caso contrário, aplica-se um
scanline depois. Usando o modelo de feixe documentado (o pixel `p` é atingido
no ciclo de CPU `~(p + 69) / 3`), a escrita 2 no ciclo 27 exige `x >= 13`
(conservador; a porta real é menor). O builder por isso aplica a regra de
slot: a segunda escrita de uma dupla é sempre GRP0 (x=16), GRP1 (x=136) ou
ENAM0 (x >= 18) - nunca ENABL ou ENAM1, cujo X pode cair abaixo de 13. A bola
e o M1 sempre ganham o slot 1 em um empate de linha.

O ciclo de escrita impõe uma restrição de *escalonamento*, não apenas de
margem: um objeto cujo X pode cair abaixo do limite da segunda escrita nunca
deve ocupar o segundo slot (veja `docs/en/architecture.md`). O `delta` da
próxima entrada é lido até o ciclo 50 no pior caminho, confortavelmente antes
do `WSYNC` que inicia a próxima linha.

## Orçamentos de VBLANK e OVERSCAN

O gameplay (decodificação do joystick + movimento + atualização dos mísseis +
posicionamento) e o build da tabela de eventos rodam no VBLANK entre a
liberação do VSYNC e a espera do timer. A passagem de colisão deliberadamente
NÃO fica aqui: o caminho mais pesado de VBLANK (dois mísseis ativos, duas
bordas de disparo) já está a poucos ciclos da fronteira de alinhamento da
janela do timer, e adicionar uma passagem de custo variável ali fez um quadro
por rodada de estresse escorregar para 263 scanlines. Com a colisão tratada
no overscan, o trabalho do VBLANK termina com folga suficiente para que a
espera do timer sempre segure a região em seu número fixo de linhas.

### Rodada 6: o bug de tremor do VBLANK e como foi fechado

A Rodada 5 deixou o VBLANK com 57 linhas e `VBLANK_TIMER_VALUE = 69`,
ajustado contra um emulador cuja tabela de ciclos dobrava todo branch
condicional em 2 ciclos. No silício real, um branch *tomado* custa 3 ciclos
(4 com page crossing). Sob o trabalho de VBLANK da Rodada 5 (movimento +
atualização de mísseis + `BuildEvents` com o gate de jogador morto), o pior
caso realista chegou a ~4919 ciclos, mas o timer T=69 expira em ~4553 ciclos
(`(69 - 1) * 64` antes de `INTIM` ler 0). Isso é invertido: o trabalho
ultrapassou o timer, então `WaitVBlank` parou de esperar no `INTIM == 0`
(fronteira fixa) e caiu para fora no *fim variável do trabalho*. Dependendo
de onde o trabalho caía em relação à grade de 76 ciclos, quadros individuais
esticavam para 263/264/265 scanlines — um tremor visível que os atalhos do
emulador escondiam por completo.

A Rodada 6 corrige o orçamento, não o poll:

* `VBLANK_SCANLINES` 57 -> 64, KERNEL 192 -> 185, `VBLANK_TIMER_VALUE` 69 ->
  77. O timer agora expira em ~4864 ciclos (`(77 - 1) * 64`), bem depois do
  trabalho de pior caso medido de ~4455 ciclos (folga ~409). O poll sempre
  sai na fronteira fixa do timer, então o quadro tem exatamente 262 scanlines
  independentemente do comprimento do trabalho de VBLANK;
* o emulador (`tools/emu6502.py`) agora modela o custo de branch tomado (+1)
  e de page crossing (+2 num branch tomado, +1 em `LDA abs,Y`), para que a
  regressão seja detectável sem hardware real. O benchmark registra
  `vblank_work` (escrita do TIM64T até o primeiro `LDA INTIM`) e
  `vblank_margin` (`(timer - 1) * 64 - vblank_work`).

Uma espera `TIM64T` só é determinística quando o trabalho executado antes de
armar o timer é fixo ou fica confortavelmente abaixo da expiração. O OVERSCAN
também NÃO usa timer pelo mesmo motivo: uma passagem de custo variável
(`ProcessHitEffects`) roda entre o kernel e a espera do overscan, então o
overscan escreve exatamente `OVERSCAN_LOOP_COUNT = 6` `WSYNC`s. A partir da
última linha do kernel, um epílogo fixo + o JSR e o corpo sem branches do
`ProcessCollisions` + o JSR do `ProcessHitEffects` (Rodada 5) + 8 ciclos de
padding colocam o primeiro `WSYNC` entre os ciclos 236 e 254 da região
(modelo do emulador; todo caminho cai na mesma fronteira no ciclo 304 =
scanline 4). O loop conta então exatamente 10 linhas e o `JMP` + preâmbulo de
VSYNC seguintes alinham o primeiro `WSYNC` de VSYNC do próximo quadro em 760
ciclos após a última linha do kernel. Como a única passagem de custo variável
(`ProcessHitEffects`) fica confinada a uma janela que nunca escapa da primeira
fronteira, a região tem exatamente 10 scanlines independentemente de quantos
acertos forem detectados ou de os jogadores estarem mortos.

### Rodada 7: o deslocamento de mesma linha e o estiramento por delta 0

`InsertEvent` nunca deixa uma scanline precisar de mais de duas escritas: um
terceiro evento em uma linha que já contém uma dupla é deslocado para a
linha+1. A Rodada 7 corrigiu um bug latente nesse caminho. `.insertSingle`
gravava a *linha original empilhada* do evento mesmo quando o deslocamento já
tinha avançado `evRow`, então um terceiro evento colidindo com uma dupla
produzia **duas entradas de tabela na mesma linha absoluta**.
`ConvertDeltas` emitia então delta 0, o `DEC evCnt` do kernel virava
`0 -> $FF`, e esse evento OFF nunca disparava: o objeto ficava habilitado da
sua linha ON até a borda inferior — um estiramento vertical que só aparecia
quando objetos suficientes coincidiam numa mesma linha (os dois jogadores
vivos na mesma linha, os dois mísseis voando e a bola cruzando as linhas dos
mísseis).

A correção faz o `.insertSingle` gravar o `evRow` efetivo (possivelmente
deslocado) e descartar a linha original empilhada, de modo que as linhas das
entradas ficam estritamente crescentes e nenhuma entrada de delta 0 pode
existir. O custo é +1 ciclo por `insertSingle` (um `LDA evRow` extra,
zero-page), executado no VBLANK: o trabalho de pior caso do VBLANK cresceu de
4455 para 4485 ciclos, margem ~409 -> ~379, ainda muito dentro da expiração
T=77 (~4864). O kernel em si não foi alterado, então o pior caminho de 65/76
e o quadro de 262 scanlines continuam inalterados.

### Rodada 8: correção do slot de escrita da bola (deslocamento vertical de 1 scanline)

Uma entrada dupla dispara duas escritas em um scanline, mas a primeira cai no
ciclo 30 e a segunda no ciclo 44 (medidos no emulador determinístico). Com o
modelo de feixe acima isso é uma lacuna de ~42-49 pixels, então um objeto
escrito em segundo pode perder seu próprio limite quando está à esquerda do
limite da segunda escrita (`x < 63` no modelo). Antes da Rodada 8, um merge de
mesma linha mantinha a ordem de geração, então a BOLA — gerada entre os
jogadores e os mísseis — normalmente virava a *segunda* escrita de uma linha
compartilhada. Para todo `ball_x < 63` o ON/OFF da bola disparava um scanline
atrasado e toda a bola se deslocava uma linha para baixo (altura inalterada)
sempre que compartilhava uma linha com outro objeto ativo. O sintoma relatado
era um pequeno deslocamento vertical em certos scanlines.

Uma varredura de modelo de todas as 16.956 combinações (ball_x, cenário)
confirmou a causa raiz: a bola ocupava a segunda escrita em suas linhas
compartilhadas, e o limite da segunda escrita (63) está muito além das
posições alcançáveis pela bola. Uma ordenação pura por deadline de X foi
avaliada, mas só reduziu as falhas da bola de 4957 para 4429: P0 (x=16) está
sempre à esquerda da bola para `ball_x > 16`, então a bola ainda seria escrita
em segundo nas linhas compartilhadas com P0. A correção adotada é
**bola primeiro**: `InsertEvent` troca ENABL para a primeira escrita sempre
que um evento de bola se funde a uma única entrada, dando à bola a escrita
mais cedo (ciclo 30) em toda dupla e uma escrita única (ciclo 33) quando
sozinha. As falhas da bola caem para 2890; as falhas residuais são a faixa
`x < 30` da bola sozinha (inerente à escrita única no ciclo 33) e o
co-objeto ocupando o segundo slot. O custo da troca é +1 no pior caso do
caminho de merge (VBLANK): trabalho de pior caso do VBLANK medido 4485 -> 4486
ciclos, margem ~379 -> ~378, ainda confortavelmente dentro da expiração T=77
(~4864). O kernel não foi alterado (65/76, folga 11) e o quadro permanece em
exatamente 262 scanlines.

## Comprimento medido do quadro

Verificado com um emulador 6502 determinístico que modela paradas de WSYNC e
o timer do RIOT:

* comprimento de quadro em estado estável: **19912 ciclos = exatamente 262
  scanlines**, estável em 30+ quadros para os estados sem mísseis, com dois
  mísseis e patológico; com a passagem de colisão da Rodada 4 o quadro é
  uniforme em 600+ quadros de estresse máximo (ambos os latches de colisão
  assertados todo quadro, pressionamentos de disparo alternados);
  anteriormente a mesma entrada fazia ~1% dos quadros escorregar para 263
linhas. A Rodada 5 adiciona os caminhos de HP/morte: o quadro permanece em
   19912 ciclos sob a mesma entrada de estresse máximo (jogadores mantidos
   vivos) e com ambos os jogadores mortos. A Rodada 6 revalida o mesmo
   estresse com um emulador que modela timing de branch realista: o quadro
   permanece em exatamente 19912 ciclos (262 scanlines) para todos os quadros
   da rodada de estresse máximo, provando que o timer do VBLANK (T=77) nunca
   ultrapassa;
* o kernel visível roda exatamente 185 iterações: `evCnt` é inicializado com
  `nullDelta` (ou com o delta da própria entrada 0 quando ela dispara na linha
  0) e conta até o marcador, cujo delta é lido no topo da linha 184 e encerra
  o kernel na linha 185.

O primeiro quadro após ligar é alguns ciclos mais curto que o estado estável
porque os relógios da CPU e do TIA ainda não estão alinhados; todos os
quadros seguintes têm exatamente 19912 ciclos. Isso é comportamento normal de
reset.

### Status da validação em tempo de execução

A suíte automatizada valida a estrutura do quadro **estaticamente**
(constantes, listing, soma das regiões == 262, orçamento de ciclos do kernel)
e o builder da tabela de eventos com um modelo em Python (deltas, mesclagens,
resolução de colisões). Um teste de tempo de execução do quadro
(`tests/test_frame_timing.py`) dirige o emulador determinístico por muitos
quadros e afirma a estabilidade do quadro (262 scanlines), que o comprimento
da tabela nunca excede `EV_TBL_SIZE` sob entrada de fogo agressiva e que os
mísseis de fato aparecem e desaparecem pelo pipeline de eventos. A Rodada 5
adiciona `tests/test_hp.py`, que dirige o assembly real de
`ProcessHitEffects` e afirma as semânticas de dano/morte, e mantém a regressão
de estresse máximo viva repondo o HP todo quadro. O contador de ciclos do
emulador é aproximado (os totais de quadro único variam alguns ciclos), então
o teste de tempo de execução afirma a contagem de scanlines e o
comportamento, não totais de ciclos exatos.

## Por que isso importa

"Correção visual não é prova de correção de hardware": um quadro que parece
certo, mas deriva para 260 ou 263 scanlines, viola o contrato de timing NTSC.
Os valores do timer acima foram ajustados precisamente para que o quadro seja
exatamente 262 scanlines, e a contagem `evCnt` do kernel mantém a região
visível em exatamente 185 linhas, independentemente de quantos eventos
disparam. O tremor de VBLANK da Rodada 6 era exatamente essa classe de bug:
visualmente correto em um emulador com timing de branch abreviado, ele
quebrava no silício real porque o orçamento do timer não cobria o pior caso
de trabalho verdadeiro. O emulador agora modela os custos reais de ciclo para
que a regressão seja detectada deterministicamente.
