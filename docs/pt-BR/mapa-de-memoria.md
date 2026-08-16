# Wizard Duel - Mapa de memória

O Atari 2600 (6507) expõe 4 KiB de ROM (`$F000-$FFFF`), 128 bytes de RAM
RIOT (`$80-$FF`, espelhada a cada 256 bytes a partir de `$0280`), os
registradores do TIA (`$00-$3F`) e os registradores de I/O/timer do RIOT
(`$0280-$02FF`).

## Layout da ROM (`$F000-$FFFF`)

| Endereço | Conteúdo                                   |
| -------- | ------------------------------------------ |
| `$F000`  | Reset/inicialização (main.asm)             |
| `$F049`  | `StartOfFrame` (loop de um quadro)         |
| `$F06A`  | `WaitVBlank` (TIM64T + lógica do jogo)     |
| `$F07B`  | `KernelLoop` (kernel de 192 linhas)        |
| `$F0C1`  | `OverscanWait`                             |
| `$F0C9`  | `UpdatePlayers` (input vertical do joystick) |
| `$F103`  | `UpdateBall` (movimento + quique)          |
| `$F13A`  | `PositionPlayers` (RESP0/1 + HMP0/1)       |
| `$F149`  | `PositionBall` (RESBL + HMBL)              |
| `$F154`  | `PosObject` (RESPx/HMPx genérico)          |
| `$F164`  | `P0Sprite`  (12 bytes de linha, raquete)   |
| `$F170`  | `P1Sprite`  (12 bytes de linha, raquete)   |
| `$F200`  | `fineAdjustBegin` (tabela HMP, alinhada a página) |
| `$FFFA`  | vetor NMI (`Reset`)                        |
| `$FFFC`  | vetor RESET (`Reset`)                      |
| `$FFFE`  | vetor IRQ (`Reset`)                        |

`fineAdjustBegin` é alinhado a página de propósito: `PosObject` indexa a
tabela com um resto em complemento de dois, e a passagem de página garantida
do `LDA` indexado mantém a escrita `RESPx` no ciclo exato exigido pelo
contrato de tempo da rotina de posicionamento.

O uso de ROM é medido pelo maior endereço emitido abaixo do bloco de
vetores; o preenchimento com `$FF` conta como espaço disponível. O build
reporta ambos os números. Na Rodada 2 o código adicional da bola coube no
preenchimento de página reservado para o `fineAdjustBegin` alinhado, então o
uso de ROM permaneceu em 528 bytes.

## Layout da RAM (RAM RIOT `$80-$FF`, 128 bytes)

| Endereço | Nome       | Tam. | Finalidade                            |
| -------- | ---------- | ---- | ------------------------------------- |
| `$80`    | `P0Y`      | 1    | posição vertical do jogador 0 (0..179)|
| `$81`    | `P1Y`      | 1    | posição vertical do jogador 1 (0..179)|
| `$82`    | `joystate` | 1    | valor amostrado de `SWCHA`            |
| `$83`    | `ball_x`   | 1    | pixel visível mais à esquerda (0..156)|
| `$84`    | `ball_y`   | 1    | linha de escrita do ENABL (0..190)    |
| `$85`    | `ball_dx`  | 1    | passo horizontal (+1 / $FF)           |
| `$86`    | `ball_dy`  | 1    | passo vertical (+1 / $FF)             |
| `$87-$FF`| -          | 121  | não alocado                          |

7 dos 128 bytes são usados na Rodada 2. As variáveis ficam na zero page para
que todos os acessos usem os modos de endereçamento curtos e rápidos de zero
page.

## Uso de registradores de hardware

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESBL`, `GRP0/1`, `ENABL`, `HMOVE`,
  `HMP0/1`, `HMBL`, `VDELP0/1`, `REFP0/1` (zerados).
* RIOT: `SWCHA` (leitura de joysticks), `SWACNT` (todos como entrada),
  `INTIM` (leitura do timer), `TIM64T` (escrita do timer, clock de 64 ciclos).

Nenhum outro recurso do TIA ou do RIOT é usado nesta rodada.