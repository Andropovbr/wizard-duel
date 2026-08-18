# Wizard Duel - Arquitetura

A Rodada 3 adiciona projéteis básicos e substitui o kernel de exibição sem
desvios da Rodada 2 por um kernel orientado a eventos. A Rodada 3.1 reduz a
pegada de RAM de 122 para 48 bytes ao usar entradas de tabela de tamanho
variável e remover os buffers separados de registros/ordem.

Funcionalidades:

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
(65 no pior caso, veja [timing.md](timing.md)).

Cada entrada da tabela tem tamanho variável (Rodada 3.1):

| byte | significado                               |
| ---- | ----------------------------------------- |
| 0    | delta: scanlines até esta entrada disparar |
| 1    | índice do registrador da primeira escrita |

Se a entrada tiver uma segunda escrita, o bit 7 do byte 1 fica limpo e mais
dois bytes seguem:

| byte | significado                               |
| ---- | ----------------------------------------- |
| 2    | valor da primeira escrita                 |
| 3    | índice do registrador da segunda escrita  |
| 4    | valor da segunda escrita                  |

Se o bit 7 do byte 1 estiver setado, a entrada é de escrita única e apenas um
byte de valor segue (o valor nunca carrega bit 7 porque é sempre uma escrita
de registrador de enable: `$00`, `PADDLE_BITS`, `BALL_ENABLE` ou
`MISSILE_ENABLE`, nenhum com bit 7). O kernel despacha nesse bit com um único
`BMI`:

* entrada simples (3 bytes): delta + `reg|$80` + valor
* entrada dupla (5 bytes): delta + reg + valor + reg + valor

Ambos os caminhos são lineares, então as linhas de evento mantêm temporização
determinística (54 ciclos simples, 65 dupla, 11 ciclos de folga no pior
caminho). Uma linha de evento único não precisa de segunda escrita; quando
nenhum evento dispara, o kernel gasta apenas 18 ciclos antes do `WSYNC`.

Os índices de registrador são deslocamentos a partir de
`EV_WRITE_BASE = AUDV1 ($1A)`: índice 0 escreve AUDV1 (um dummy inofensivo),
1..5 endereçam GRP0..ENABL.

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
| `$F155`  | `OverscanWait`                                 |
| `$F15D`  | `UpdatePlayers` (entrada do joystick + movimento) |
| `$F196`  | `UpdateBall` (movimento + quique da bola)      |
| `$F1CD`  | `UpdateMissiles` (botões de fogo, movimento)   |
| `$F262`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F285`  | `PositionBall` (RESBL + HMBL)                  |
| `$F297`  | `PositionMissiles` (RESM0/RESM1 + HMM)         |
| `$F2C6`  | `BuildEvents` (insere eventos em ordem de linha) |
| `$F346`  | `InsertEvent` (insere/mescla uma entrada)      |
| `$F3BC`  | `ShiftBy2` (estende uma simples em dupla)      |
| `$F3CA`  | `ShiftBy3` (insere uma nova entrada simples)   |
| `$F3D8`  | `ConvertDeltas` (linhas -> deltas do kernel)   |
| `$F409`  | `PosObject` (RESPx/HMPx genérico)              |
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

`UpdatePlayers` amostra `SWCHA` e aplica no máximo um passo de cima/baixo por
jogador, protegendo as bordas da arena para que a posição nunca ultrapasse os
limites. O valor é consumido imediatamente; nenhuma variável RAM `joystate` é
necessária (uma economia de memória da Rodada 3.1).

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

O estado dos mísseis é compactado em dois bytes: `m_active` guarda as duas
flags ativas (bit 0 = M0, bit 1 = M1) e `fire_prev` compacta os dois bits dos
botões do quadro anterior mais o bit 7 como flag de sincronização de boot.

**Sincronização de boot**: em hardware real (e no Stella) os latches INPT do
TIA leem as linhas de fogo como pressionadas nos primeiros quadros após o
RESET. A primeira chamada de `UpdateMissiles` após ligar, portanto, apenas
adota o estado real dos botões em `fire_prev` (setando o bit 7 `FIRE_SYNC`),
nunca dispara. Isso garante que iniciar com FIRE solto não produza tiro, e
iniciar com FIRE segurado não produza tiro automático - o jogador precisa
soltar e pressionar novamente.

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

A Rodada 3.1 substitui o pipeline de registros/ordem/emissão por um builder de
inserção direta: `BuildEvents` reinicia a tabela com um único terminador `$FF`
e então insere os eventos ON/OFF de cada objeto direto no `evTbl` em ordem de
linha, então não existem buffers separados de registros ou ordem (os 40 bytes
que usavam na Rodada 3 sumiram). Como as entradas têm tamanho variável, a
inserção precisa de um loop de deslocamento explícito em vez de uma ordenação
estável:

1. `InsertEvent` varre a tabela comparando as linhas das entradas. Em uma
   linha igual, mescla:
   * entrada simples -> `ShiftBy2` desloca a cauda em 2 e escreve o segundo
     valor (a entrada mesclada vira uma dupla de 5 bytes);
   * entrada já dupla -> a linha é incrementada em 1 e a varredura continua
     (isso só pode acontecer transitoriamente durante um único build, então a
     tabela nunca excede seu limite).
   Caso contrário `ShiftBy3` desloca a cauda em 3 e escreve uma nova simples de
   3 bytes.
2. Depois que todos os eventos são inseridos, `ConvertDeltas` reescreve as
   linhas in-place como deltas do kernel (primeiro delta = linha+1, próximos
   deltas = linha - linhaAnterior), deixando o terminador `$FF` no fim da
   tabela.

Como uma simples de 3 bytes pode virar uma dupla de 5 bytes na mescla, o
tamanho máximo da tabela não é mais 10 x 5 bytes: com 10 fronteiras de objeto
e no máximo uma dupla por linha, a tabela precisa de no máximo 31 bytes.
`EV_TBL_SIZE = 31` é um limite rígido; `tblLen` rastreia o comprimento atual
e um teste afirma que ele nunca excede o limite sob entrada de fogo agressiva.

A tabela termina com uma entrada terminadora cujo delta (`$FF`) nunca pode
disparar dentro do kernel de 192 linhas.

## Alocação de variáveis

48 de 128 bytes de RAM do RIOT são usados (abaixo dos 122 da Rodada 3):

| Endereço  | Nome        | Propósito                              |
| --------- | ----------- | -------------------------------------- |
| `$80`     | `P0Y`       | posição vertical do jogador 0          |
| `$81`     | `P1Y`       | posição vertical do jogador 1          |
| `$82`     | `ball_x`    | pixel visível mais à esquerda da bola  |
| `$83`     | `ball_y`    | primeira linha de exibição da bola     |
| `$84`     | `ball_dx`   | passo de direção horizontal            |
| `$85`     | `ball_dy`   | passo de direção vertical              |
| `$86-$87` | `m0_x/m0_y` | posição do míssil 0                    |
| `$88-$89` | `m1_x/m1_y` | posição do míssil 1                    |
| `$8A`     | `m_active`  | máscara ativa compactada (M0/M1)       |
| `$8B`     | `fire_prev` | borda de fogo compactada + sync de boot|
| `$8C-$8D` | `evCnt/scanCnt` | estado do kernel                   |
| `$8E-$AC` | `evTbl`     | tabela de eventos (tamanho variável, máx. 31B) |
| `$AD-$AF` | `evRow/tempCount/tblLen` | temporários do builder |

As economias vêm de: entradas de tabela de tamanho variável (31 vs 55 bytes),
nenhum buffer de registros/ordem (0 vs 40 bytes), nenhum `joystate` (relê o
`SWCHA`), flags de míssil compactadas (um byte para dois), nenhum `fire_sync`
separado (bit 7 de `fire_prev`) e nenhum `evIdx` (o kernel varre a tabela
linearmente).

## Por que VBLANK para gameplay

O kernel visível tem um orçamento de 76 ciclos por scanline. Executar a
decodificação do joystick, o movimento, os quiques e o build da tabela de
eventos lá adicionaria temporização dependente de dados a um caminho de
renderização que precisa ser determinístico. Movê-los para o VBLANK (veja
[timing.md](timing.md)) mantém o kernel estável em exatamente um scanline por
iteração, independentemente da entrada ou do estado do jogo.
