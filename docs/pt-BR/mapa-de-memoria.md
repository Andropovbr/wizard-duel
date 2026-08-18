# Wizard Duel - Mapa de memória

O Atari 2600 (6507) expõe 4 KiB de ROM (`$F000-$FFFF`), 128 bytes de RAM
RIOT (`$80-$FF`), os registradores do TIA (`$00-$3F`) e os registradores de
I/O/timer do RIOT (`$0280-$02FF`).

## Layout da ROM (`$F000-$FFFF`)

| Endereço | Conteúdo                                   |
| -------- | ------------------------------------------ |
| `$F000`  | Reset/inicialização (main.asm)             |
| `$F04F`  | `StartOfFrame` (loop de um quadro)         |
| `$F079`  | `WaitVBlank` (TIM64T + lógica do jogo)     |
| `$F100`  | `KernelLoop` (kernel de 192 linhas por eventos) |
| `$F142`  | `OverscanWait`                             |
| `$F14A`  | `UpdatePlayers` (input vertical do joystick) |
| `$F184`  | `UpdateBall` (movimento + quique)          |
| `$F1BB`  | `UpdateMissiles` (disparo, movimento, remoção) |
| `$F238`  | `PositionPlayers` (RESP0/1 + HMP0/1)       |
| `$F25B`  | `PositionBall` (RESBL + HMBL)              |
| `$F26D`  | `PositionMissiles` (RESM0/1 + HMM0/1)      |
| `$F298`  | `BuildEvents` (reconstrói a tabela de eventos) |
| `$F313`  | `AddEvent` (anexa um registro)             |
| `$F332`  | `SortEvents` (ordenação por inserção)      |
| `$F372`  | `EmitEvents` (escreve a tabela)            |
| `$F421`  | `BubbleOrder` (resolução de colisão)       |
| `$F454`  | `PosObject` (RESPx/HMPx genérico)          |
| `$F500`  | `fineAdjustBegin` (tabela HMP, alinhada a página) |
| `$FFFA`  | vetor NMI (`Reset`)                        |
| `$FFFC`  | vetor RESET (`Reset`)                      |
| `$FFFE`  | vetor IRQ (`Reset`)                        |

`fineAdjustBegin` é alinhado a página de propósito: `PosObject` indexa a
tabela com um resto em complemento de dois, e a passagem de página garantida
do `LDA` indexado mantém a escrita `RESPx` no ciclo exato exigido pelo
contrato de tempo da rotina de posicionamento.

Não existem tabelas de gráficos de sprites: os dois jogadores são retângulos
sólidos desenhados pela tabela de eventos (veja [timing.md](timing.md)). O uso
de ROM é medido pelo maior endereço emitido abaixo do bloco de vetores; o
preenchimento com `$FF` conta como espaço disponível. O build reporta ambos
os números. A Rodada 3 usa 1296 dos 4096 bytes.

## Layout da RAM (RAM RIOT `$80-$FF`, 128 bytes)

| Endereço | Nome       | Tam. | Finalidade                            |
| -------- | ---------- | ---- | ------------------------------------- |
| `$80`    | `P0Y`      | 1    | posição vertical do jogador 0 (0..179)|
| `$81`    | `P1Y`      | 1    | posição vertical do jogador 1 (0..179)|
| `$82`    | `joystate` | 1    | valor amostrado de `SWCHA`            |
| `$83`    | `ball_x`   | 1    | pixel visível mais à esquerda (0..156)|
| `$84`    | `ball_y`   | 1    | primeira linha de exibição (0..188)   |
| `$85`    | `ball_dx`  | 1    | passo horizontal (+1 / $FF)           |
| `$86`    | `ball_dy`  | 1    | passo vertical (+1 / $FF)             |
| `$87`    | `m0_x`     | 1    | posição horizontal do míssil 0        |
| `$88`    | `m0_y`     | 1    | linha do míssil 0 (fixa em voo)       |
| `$89`    | `m0_active`| 1    | flag de atividade do míssil 0         |
| `$8A`    | `m1_x`     | 1    | posição horizontal do míssil 1        |
| `$8B`    | `m1_y`     | 1    | linha do míssil 1 (fixa em voo)       |
| `$8C`    | `m1_active`| 1    | flag de atividade do míssil 1         |
| `$8D`    | `fire_prev`| 1    | estado de borda dos botões de fogo    |
| `$8E`    | `evCnt`    | 1    | kernel: scanlines até o próximo evento|
| `$8F`    | `evIdx`    | 1    | kernel: offset atual na tabela        |
| `$90`    | `scanCnt`  | 1    | kernel: contagem regressiva de 192    |
| `$91-$C7`| `evTbl`    | 55   | tabela de eventos (11 entradas x 5)   |
| `$C8-$E5`| `events`   | 30   | registros de eventos (até 10 x 3)     |
| `$E6`    | `evCount`  | 1    | número de registros deste quadro      |
| `$E7-$F0`| `evOrder`  | 10   | offsets dos registros, ordenados      |
| `$F1-$F8`| temporários| 8    | armazenamento de trabalho             |
| `$F9`    | `fire_sync`| 1   | sincronização de boot do input de fogo|
| `$FA-$FF`| -          | 6    | não alocado                          |

121 dos 128 bytes são usados na Rodada 3. As variáveis ficam na zero page
para que todos os acessos usem os modos de endereçamento curtos e rápidos de
zero page. A tabela de eventos (55 bytes) e os buffers de registros/ordem (40
bytes) são os maiores consumidores; o estado do jogo em si é compacto.

## Uso de registradores de hardware

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESM0/1`, `RESBL`, `GRP0/1`, `ENAM0/1`,
  `ENABL`, `HMOVE`, `HMP0/1`, `HMM0/1`, `HMBL`, `VDELP0/1`, `REFP0/1`
  (zerados).
* Leituras do TIA: `INPT4`/`INPT5` (botões de fogo).
* RIOT: `SWCHA` (leitura de joysticks), `SWACNT` (todos como entrada),
  `INTIM` (leitura do timer), `TIM64T` (escrita do timer, clock de 64 ciclos).

Nenhum outro recurso do TIA ou do RIOT é usado nesta rodada.
