# Wizard Duel - Arquitetura

A Rodada 3 adiciona projéteis básicos e substitui o kernel de exibição sem
desvios da Rodada 2 por um kernel orientado a eventos:

* um quadro NTSC estável de exatamente 262 scanlines
* dois jogadores TIA visíveis simultaneamente (P0 à esquerda, P1 à direita),
  renderizados como raquetes verticais simples
* movimento apenas vertical controlado pelo joystick 1 (P0) e joystick 2 (P1)
* um objeto Bola TIA que se move continuamente e quica nas quatro bordas da
  arena
* cada jogador pode disparar um míssil com o botão de fogo do joystick
  (INPT4 para P0, INPT5 para P1); mísseis voam horizontalmente a 2 px/quadro
  e desaparecem nas bordas da arena

Intencionalmente ainda não há sistema de magia, HP, IA, colisões, placar ou
HUD; as regras de jogo devem evoluir nas próximas rodadas sem exigir mudanças
arquiteturais. Nesta rodada a bola e os mísseis não interagem com os
jogadores.

## Kernel orientado a eventos

Com um segundo par de objetos (os mísseis), o kernel sem desvios da Rodada 2
não cabe mais no orçamento de 76 ciclos por scanline (precisava de ~98 ciclos
para dois jogadores, a bola e dois mísseis). Em vez de calcular o enable de
cada objeto em cada scanline, `BuildEvents` roda durante o VBLANK e escreve
uma pequena tabela (`evTbl`) descrevendo as escritas de registradores que cada
scanline deve executar. O kernel então apenas conta os ciclos até a próxima
entrada e aplica as escritas, mantendo cada scanline bem abaixo de 76 ciclos
(69 no pior caso, veja [timing.md](timing.md)).

Cada entrada da tabela tem 5 bytes:

| byte | significado                               |
| ---- | ----------------------------------------- |
| 0    | delta: scanlines até esta entrada disparar |
| 1    | índice do registrador da primeira escrita |
| 2    | valor da primeira escrita                 |
| 3    | índice do registrador da segunda escrita  |
| 4    | valor da segunda escrita                  |

Os índices de registrador são deslocamentos a partir de
`EV_WRITE_BASE = AUDV1 ($1A)`: índice 0 escreve AUDV1 (um dummy inofensivo),
1..5 endereçam GRP0..ENABL. Toda entrada sempre executa duas escritas, então o
caminho de evento é código linear.

Deltas: a primeira entrada dispara na linha `delta - 1`; cada entrada seguinte
dispara `delta` linhas depois da anterior, então `BuildEvents` calcula
`delta(primeira) = linha + 1` e `delta(próxima) = linha - linhaAnterior`. O
kernel conta suas 192 linhas com uma contagem regressiva em RAM (`scanCnt`)
em vez do registrador X, porque o código de evento usa `TAX` como índice de
registrador e corromperia um contador de linhas em X a cada linha de evento.

## Layout do código

`src/main.asm` contém o programa completo em um único banco de ROM
`$F000-$FFFF` (4 KiB, sem bankswitching). `src/constants.inc` contém todos os
endereços de registradores de hardware e constantes de build.

| Endereço | Conteúdo                                        |
| -------- | ---------------------------------------------- |
| `$F000`  | `Reset` (inicialização)                        |
| `$F04F`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F100`  | `KernelLoop` (kernel de exibição por eventos)  |
| `$F142`  | `OverscanWait`                                 |
| `$F14A`  | `UpdatePlayers` (entrada do joystick + movimento) |
| `$F184`  | `UpdateBall` (movimento + quique da bola)      |
| `$F1BB`  | `UpdateMissiles` (botões de fogo, movimento)   |
| `$F238`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F25B`  | `PositionBall` (RESBL + HMBL)                  |
| `$F26D`  | `PositionMissiles` (RESM0/RESM1 + HMM)         |
| `$F298`  | `BuildEvents` (reconstrói a tabela de eventos) |
| `$F313`  | `AddEvent` (anexa um registro)                 |
| `$F332`  | `SortEvents` (ordenação por inserção)          |
| `$F372`  | `EmitEvents` (escreve a tabela)                |
| `$F421`  | `BubbleOrder` (resolução de colisão)           |
| `$F454`  | `PosObject` (RESPx/HMPx genérico)              |
| `$F500`  | `fineAdjustBegin` (tabela HMP alinhada a página) |
| `$FFFA`  | Vetores NMI / RESET / IRQ                      |

Não há tabelas de sprites: os dois jogadores são retângulos sólidos
`PADDLE_BITS` desenhados pela tabela de eventos. Os endereços exatos podem
mudar entre builds; os testes automatizados os resolvem pelos arquivos de
símbolos/listing em vez de valores fixos.

## Fluxo de execução por quadro

```
StartOfFrame
 ├─ VSYNC   3 scanlines  (três escritas explícitas em WSYNC)
 ├─ VBLANK 57 scanlines  (TIM64T = 69; gameplay e build de eventos aqui)
 │   ├─ UpdatePlayers    lê SWCHA, move P0/P1, limita à arena
 │   ├─ UpdateBall       move a bola, quica nas bordas
 │   ├─ UpdateMissiles   lê INPT4/INPT5, dispara/move/remove mísseis
 │   ├─ PositionPlayers  posicionamento grosso/fino RESP0/RESP1 + HMP0/HMP1
 │   ├─ PositionBall     posicionamento RESBL + HMBL
 │   ├─ PositionMissiles posicionamento RESM0/RESM1 + HMM0/HMM1
 │   └─ BuildEvents      reconstrói a tabela de eventos do kernel visível
 ├─ KERNEL 192 scanlines (loop explícito de WSYNC; apenas renderiza)
 └─ OVERSCAN 10 scanlines (TIM64T = 11; volta ao StartOfFrame)
```

Entrada, movimento e build de eventos acontecem durante o VBLANK; o kernel
visível apenas aplica as escritas pré-calculadas. O VBLANK é maior que na
Rodada 2 (57 vs 37 linhas) para dar espaço ao `BuildEvents`; o OVERSCAN
encolhe para 10 linhas para manter o quadro em 262.

## Entrada

Os joysticks são lidos da porta de E/S do RIOT `SWCHA` (`$0280`), ativa em
nível baixo: um bit é 0 quando a direção correspondente está pressionada.
Apenas as direções verticais são usadas nesta rodada:

| Porta | Direção | bit SWCHA |
| ---- | --------- | --------- |
| P0 (esquerda, joystick 1) | cima  | D4 |
| P0 (esquerda, joystick 1) | baixo | D5 |
| P1 (direita, joystick 2)  | cima  | D0 |
| P1 (direita, joystick 2)  | baixo | D1 |

`UpdatePlayers` amostra `SWCHA` uma vez por quadro na variável RAM
`joystate`, aplica no máximo um passo de cima/baixo por jogador e protege as
bordas da arena para que a posição nunca ultrapasse os limites.

## Mísseis

Cada jogador pode disparar um míssil com o botão de fogo. Os botões são lidos
pelos latches INPT do TIA: o bit 7 de `INPT4` (P0) e `INPT5` (P1) é 0 enquanto
pressionado. `UpdateMissiles` amostra os dois botões de forma independente a
cada quadro e dispara na **borda de subida** do botão (solto -> pressionado),
apenas enquanto o míssil daquele jogador estiver inativo:

* segurar o botão não produz uma rajada de mísseis (`fire_prev` guarda o
  estado do quadro anterior);
* uma borda de subida com o míssil ainda voando não cria um segundo míssil
  nem reinicia o existente;
* soltar o botão apenas rearmer a entrada, então a próxima transição solto ->
  pressionado dispara novamente.

**Sincronização de boot**: em hardware real (e no Stella) os latches INPT do
TIA leem as linhas de fogo como pressionadas nos primeiros quadros após o
RESET. A primeira chamada de `UpdateMissiles` após ligar, portanto, apenas
adota o estado real dos botões em `fire_prev` (flag `fire_sync`), nunca
dispara. Isso garante que iniciar com FIRE solto não produza tiro, e iniciar
com FIRE segurado não produza tiro automático - o jogador precisa soltar e
pressionar novamente.

Um míssil tem `MISSILE_HEIGHT = 4` scanlines de altura e `MISSILE_WIDTH = 2`
pixels de largura (bits de tamanho de míssil do NUSIZ0/NUSIZ1). Ele nasce
`MISSILE_SPAWN_OFFSET = 4` linhas abaixo do seu jogador, mantém essa linha
enquanto voa, move-se horizontalmente a `MISSILE_SPEED = 2` px/quadro e
desaparece na borda da arena:

* M0 (jogador da esquerda): nasce em x = 18, move-se para a direita,
  desaparece em x > 158
* M1 (jogador da direita): nasce em x = 134, move-se para a esquerda,
  desaparece em x < 2

Os mísseis são renderizados na cor da bola (`COLUPF`) e, como a bola, usam a
compensação horizontal `input = x + 8` (são objetos Missile do TIA, não
objetos Player).

## Renderização

O kernel visível é orientado a eventos (veja acima). Os dois jogadores são
sprites TIA de cópia única com cores diferentes: P0 é vermelho
(`COLUP0 = $46`) e P1 é azul (`COLUP1 = $84`). Cada sprite é um retângulo
sólido de `%00111100` (raquete de 4 pixels de largura) com `PLAYER_HEIGHT = 12`
linhas. A bola é o objeto Ball do TIA, 4 pixels de largura (CTRLPF D5:D4 =
`%10`) e 4 linhas de altura. Os mísseis são os objetos Missile do TIA, 2
pixels de largura e 4 linhas de altura.

A tabela de eventos registra um evento ON (liga o registrador) e um evento
OFF (desliga) nas linhas de exibição de cada objeto:

| objeto | evento ON                              | evento OFF                       |
| ------ | ------------------------------------- | ------------------------------- |
| P0     | `(P0Y, GRP0, PADDLE_BITS)`            | `(P0Y+12, GRP0, 0)`             |
| P1     | `(P1Y, GRP1, PADDLE_BITS)`            | `(P1Y+12, GRP1, 0)`             |
| Bola   | `(ball_y, ENABL, BALL_ENABLE)`        | `(ball_y+4, ENABL, 0)`          |
| M0     | `(m0_y, ENAM0, MISSILE_ENABLE)`       | `(m0_y+4, ENAM0, 0)`            |
| M1     | `(m1_y, ENAM1, MISSILE_ENABLE)`       | `(m1_y+4, ENAM1, 0)`            |

`BALL_ENABLE` e `MISSILE_ENABLE` são `%00000010`: o TIA amostra apenas o bit 1
dos registradores de enable (verificado no código-fonte do Stella), então o
valor `$FF` antigo era desnecessário.

O posicionamento horizontal é fixado a cada quadro com a técnica clássica
RESP0/RESP1/RESM0/RESM1/RESBL + HMP + HMOVE: um strobe grosso posiciona o
objeto em até 15 pixels e um deslocamento fino `HMPx`/`HMMx`/`HMBL` da tabela
`fineAdjustTable` alinhada a página finaliza o trabalho. O `HMOVE` que aplica
os deslocamentos é escrito imediatamente após um `STA WSYNC` na última linha
do VBLANK, como exige o Guia do Programador Stella.

Medido no alvo (TIA/Stella), a rotina renderiza um jogador em
`15*q + (s - 7)` para `q >= 1` e em `3 + (s - 7)` para `q = 0`, onde
`q = input / 15` e `s = input mod 15`. A bola e os mísseis renderizam 1 pixel
à esquerda de um jogador para a mesma entrada, então `PositionBall`/
`PositionMissiles` passam `x + 8` (ou `x + 5` quando abaixo de 15) e os
jogadores passam `X + 7` (ou `X + 4`).

## Movimento e quique da bola

`UpdateBall` move a bola um pixel por quadro nos dois eixos em velocidade
constante. `ball_dx`/`ball_dy` guardam o passo de direção (+1 ou $FF). O
quique é implementado invertendo a direção quando a bola atinge uma borda
exata da arena antes de se mover, então a posição fica sempre dentro do
intervalo válido e nunca pode estourar por underflow sem sinal. `ball_y` é a
primeira linha de exibição; a bola ocupa as linhas `ball_y .. ball_y + 3`. A
bola não colide com os jogadores nem com os mísseis; quica apenas nas quatro
bordas da área de jogo.

## Builder da tabela de eventos

`BuildEvents` tem três fases:

1. **Gerar** - `AddEvent` anexa um registro de 3 bytes `(linha, reg, val)` por
   fronteira de objeto e registra seu deslocamento no array `evOrder`.
2. **Ordenar** - `SortEvents` ordena o array `evOrder` por linha com ordenação
   por inserção. Ordenar offsets de 1 byte (em vez dos registros de 3 bytes)
   mantém o custo dentro do orçamento do VBLANK.
3. **Emitir** - `EmitEvents` percorre a ordem ordenada e escreve a tabela,
   mesclando no máximo dois registros da mesma linha em uma entrada de duas
   escritas. Se um terceiro registro patológico compartilhar a linha, sua
   linha é incrementada em 1 e `BubbleOrder` restaura a ordem. Isso garante
   que nenhuma scanline precise de mais de duas escritas.

A tabela termina com uma entrada terminadora cujo delta (`$FF`) nunca pode
disparar dentro do kernel de 192 linhas.

## Alocação de variáveis

122 de 128 bytes de RAM do RIOT são usados:

| Endereço | Nome      | Propósito                            |
| ------- | --------- | ------------------------------------ |
| `$80`   | `P0Y`     | posição vertical do jogador 0        |
| `$81`   | `P1Y`     | posição vertical do jogador 1        |
| `$82`   | `joystate`| valor amostrado de SWCHA             |
| `$83`   | `ball_x`  | pixel visível mais à esquerda da bola|
| `$84`   | `ball_y`  | primeira linha de exibição da bola   |
| `$85`   | `ball_dx` | passo de direção horizontal          |
| `$86`   | `ball_dy` | passo de direção vertical            |
| `$87-$8C` | `m0_x/m0_y/m0_active`, `m1_x/m1_y/m1_active` | mísseis |
| `$8D`   | `fire_prev` | estado de borda dos botões        |
| `$8E-$90` | `evCnt/evIdx/scanCnt` | estado do kernel       |
| `$91-$C7` | `evTbl`  | tabela de eventos (11 entradas x 5 bytes) |
| `$C8-$E5` | `events` | registros de eventos (até 10 x 3 bytes) |
| `$E6`   | `evCount` | número de registros deste quadro    |
| `$E7-$F0` | `evOrder` | offsets ordenados dos registros   |
| `$F1-$F8` | temporários do builder/kernel       |

## Por que VBLANK para gameplay

O kernel visível tem um orçamento de 76 ciclos por scanline. Executar a
decodificação do joystick, o movimento, os quiques e o build da tabela de
eventos lá adicionaria temporização dependente de dados a um caminho de
renderização que precisa ser determinístico. Movê-los para o VBLANK (veja
[timing.md](timing.md)) mantém o kernel estável em exatamente um scanline por
iteração, independentemente da entrada ou do estado do jogo.
