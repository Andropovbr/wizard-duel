# Wizard Duel - Mapa de memória

O Atari 2600 (6507) expõe 4 KiB de ROM (`$F000-$FFFF`), 128 bytes de RAM
RIOT (`$80-$FF`, espelhada a cada 256 bytes a partir de `$0280`), os
registradores do TIA (`$00-$3F`) e os registradores de I/O/timer do RIOT
(`$0280-$02FF`).

## Layout da ROM (`$F000-$FFFF`)

| Endereço | Conteúdo                                   |
| -------- | ------------------------------------------ |
| `$F000`  | Reset/inicialização + loop de um quadro    |
| `$F0F4`  | `P0Sprite`  (12 bytes de linha)            |
| `$F100`  | `P1Sprite`  (12 bytes de linha)            |
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
reporta ambos os números.

## Layout da RAM (RAM RIOT `$80-$FF`, 128 bytes)

| Endereço | Nome       | Tam. | Finalidade                            |
| -------- | ---------- | ---- | ------------------------------------- |
| `$80`    | `P0Y`      | 1    | posição vertical do jogador 0 (0..179)|
| `$81`    | `P1Y`      | 1    | posição vertical do jogador 1 (0..179)|
| `$82`    | `joystate` | 1    | valor amostrado de `SWCHA`            |
| `$83-$FF`| -          | 125  | não alocado                          |

Apenas 3 dos 128 bytes são usados na Rodada 1. As variáveis ficam na zero
page para que todos os acessos usem os modos de endereçamento curtos e
rápidos de zero page.

## Uso de registradores de hardware

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUBK`,
  `REFP0/1` (zerados), `RESP0/1`, `GRP0/1`, `HMOVE`, `HMP0/1`, `CTRLPF`,
  `VDELP0/1`.
* RIOT: `SWCHA` (leitura de joysticks), `SWACNT` (todos como entrada),
  `INTIM` (leitura do timer), `TIM64T` (escrita do timer, clock de 64 ciclos).

Nenhum outro recurso do TIA ou do RIOT é usado nesta rodada.