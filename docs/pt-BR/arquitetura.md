# Wizard Duel - Arquitetura

A Rodada 2 estabelece a base técnica mínima de um jogo para Atari 2600:

* um quadro NTSC estável com exatamente 262 scanlines
* dois jogadores TIA visíveis simultaneamente (P0 à esquerda, P1 à direita),
  renderizados como raquetes verticais simples
* movimento apenas vertical, dirigido pelo joystick 1 (P0) e joystick 2 (P1)
* um objeto Ball do TIA que se move continuamente e quica nas quatro
  bordas da arena

Propositalmente ainda não há sistema de magia, projéteis, HP, IA,
colisões, placar ou HUD; as regras de jogo devem evoluir em rodadas
futuras sem exigir mudanças de arquitetura. Nesta rodada a bola não
interage com os jogadores.

## Organização do código

`src/main.asm` contém o programa completo em um único banco de ROM
`$F000-$FFFF` (4 KiB, sem bankswitching). `src/constants.inc` concentra os
endereços dos registradores de hardware e as constantes de compilação.

| Endereço | Conteúdo                                        |
| -------- | ----------------------------------------------- |
| `$F000`  | `Reset` (inicialização)                         |
| `$F049`  | `StartOfFrame` (VSYNC + VBLANK + kernel + overscan) |
| `$F0C9`  | `UpdatePlayers` (entrada de joystick + movimento) |
| `$F103`  | `UpdateBall` (movimento + quique da bola)       |
| `$F13A`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)   |
| `$F149`  | `PositionBall` (RESBL + HMBL)                   |
| `$F164`  | `P0Sprite` / `P1Sprite` (12 bytes cada)         |
| `$F200`  | `fineAdjustBegin` (tabela HMP alinhada a página) |
| `$FFFA`  | vetores NMI / RESET / IRQ                       |

Os endereços exatos podem mudar entre builds; os testes automatizados os
resolvem a partir dos arquivos de símbolos/listing em vez de fixá-los.

## Fluxo de execução por quadro

```
StartOfFrame
 ├─ VSYNC    3 scanlines  (três WSYNC explícitos)
 ├─ VBLANK  37 scanlines  (TIM64T = 44; lógica de jogo roda aqui)
 │   ├─ UpdatePlayers     lê SWCHA, move P0/P1 e limita à arena
 │   ├─ UpdateBall        move a bola e quica nas bordas da arena
 │   ├─ PositionPlayers   posicionamento horizontal RESP0/RESP1 + HMP0/HMP1
 │   └─ PositionBall      posicionamento horizontal RESBL + HMBL
 ├─ KERNEL 192 scanlines  (loop explícito de WSYNC; só renderiza)
 └─ OVERSCAN 30 scanlines (TIM64T = 37; volta ao StartOfFrame)
```

Entrada e atualização de estado ocorrem durante o VBLANK; o kernel visível
apenas desenha os dois sprites e a bola. Isso segue a regra do projeto de
manter o código de exibição previsível em termos de tempo e fora da lógica
de jogo.

## Entrada

Os joysticks são lidos da porta de I/O `SWCHA` do RIOT (`$0280`), que é
ativa em nível baixo: um bit é 0 quando a direção correspondente está
pressionada. Nesta rodada só são usadas as direções verticais:

| Porta | Direção | Bit SWCHA |
| ----- | ------- | --------- |
| P0 (esquerda, joystick 1) | cima  | D4 |
| P0 (esquerda, joystick 1) | baixo | D5 |
| P1 (direita, joystick 2)  | cima  | D0 |
| P1 (direita, joystick 2)  | baixo | D1 |

`UpdatePlayers` amostra `SWCHA` uma vez por quadro na variável `joystate`
(RAM) e aplica no máximo um passo de subida/descida por jogador, protegendo
os limites da arena para que a posição nunca dê a volta (wrap).

## Renderização

Os dois jogadores são sprites TIA de cópia única (`NUSIZ0/1 = 0`) com cores
diferentes: P0 é vermelho (`COLUP0 = $46`) e P1 é azul (`COLUP1 = $84`).
Cada sprite é um retângulo sólido de 12 linhas de `%00111100` (uma raquete
de 4 pixels de largura). O kernel calcula, por scanline, se o índice da
linha atual pertence ao sprite de 12 linhas de um jogador e escreve o byte
correspondente em `GRP0`/`GRP1`.

A bola usa o objeto Ball do TIA (1 scanline de altura, 4 pixels de largura
via `CTRLPF` D5:D4 = `%10`, colorida por `COLUPF`). O kernel a habilita em
exatamente uma scanline por quadro comparando o índice da linha com
`ball_y` e escrevendo `ENABL`; como `ENABL` é registrado (latch) para a
scanline *seguinte*, o kernel precisa escrevê-lo em toda linha (o valor de
habilitação na linha da bola, 0 em todas as outras), senão a bola ficaria
presa na tela.

O posicionamento horizontal é fixado a cada quadro com a técnica clássica
RESP0/RESP1/RESBL + HMP0/HMP1/HMBL + HMOVE: um `RESPx`/`RESBL` grosseiro
coloca o objeto dentro de 15 pixels e um ajuste fino `HMPx`/`HMBL` vindo
da tabela `fineAdjustTable` (alinhada a página) completa o trabalho. O
`HMOVE` que aplica os offsets é escrito na última linha do VBLANK.
`PositionBall` passa `ball_x + 1` para a rotina de posicionamento
compartilhada porque o TIA atrasa os gráficos dos jogadores em um color
clock extra; o mesmo valor de `RESP` colocaria a bola um pixel à esquerda
de onde os jogadores são renderizados.

## Movimento e quique da bola

`UpdateBall` move a bola um pixel por quadro nos dois eixos em velocidade
constante. `ball_dx`/`ball_dy` guardam o passo de direção (+1 ou $FF). O
quique é implementado invertendo uma direção quando a bola atinge uma borda
exata da arena (`BALL_X_MIN/MAX`, `BALL_Y_MIN/MAX`) *antes* de se mover,
de modo que a posição fica sempre limitada ao intervalo válido e nunca
pode dar a volta por um underflow de unsigned. A bola não colide com os
jogadores nem com o playfield; ela quica apenas nas quatro bordas da área
de jogo.

## Alocação de variáveis

Sete variáveis de zero page são usadas (7 de 128 bytes de RAM RIOT):

| Endereço | Nome       | Finalidade                  |
| -------- | ---------- | --------------------------- |
| `$80`    | `P0Y`      | posição vertical do jogador 0 |
| `$81`    | `P1Y`      | posição vertical do jogador 1 |
| `$82`    | `joystate` | valor amostrado de SWCHA      |
| `$83`    | `ball_x`   | pixel visível mais à esquerda |
| `$84`    | `ball_y`   | scanline de escrita do ENABL  |
| `$85`    | `ball_dx`  | passo horizontal (+1 / $FF)   |
| `$86`    | `ball_dy`  | passo vertical (+1 / $FF)     |

## Por que a lógica fica no VBLANK

O kernel visível tem orçamento de 76 ciclos por scanline. Executar a
decodificação do joystick, o movimento e as checagens de quique lá
introduziria ramificações com tempo dependente de dados em um caminho de
renderização que precisa ser determinístico. Movendo-a para o VBLANK (ver
[timing.md](timing.md)) o kernel permanece estável em exatamente uma
scanline por iteração, independentemente da entrada ou da posição da bola.