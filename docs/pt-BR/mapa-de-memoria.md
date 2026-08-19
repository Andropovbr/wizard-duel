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
| `$F150`  | `OverscanWait` (colisão + loop de WSYNC)   |
| `$F15D`  | `UpdatePlayers` (input vertical do joystick) |
| `$F196`  | `UpdateBall` (movimento + quique)          |
| `$F1CD`  | `UpdateMissiles` (disparo, movimento, remoção) |
| `$F262`  | `ProcessCollisions` (custo fixo, sem branches) |
| `$F2A0`  | `newActiveTbl` (tabela de atualização do m_active) |
| `$F2B0`  | `PositionPlayers` (RESP0/1 + HMP0/1)       |
| `$F2D3`  | `PositionBall` (RESBL + HMBL)              |
| `$F2E5`  | `PositionMissiles` (RESM0/1 + HMM0/1)      |
| `$F314`  | `BuildEvents` (insere eventos em ordem de linha) |
| `$F394`  | `InsertEvent` (insere/mescla uma entrada)  |
| `$F40A`  | `ShiftBy2` (estende uma simples em dupla)  |
| `$F418`  | `ShiftBy3` (insere uma nova entrada simples) |
| `$F426`  | `ConvertDeltas` (linhas -> deltas do kernel) |
| `$F457`  | `PosObject` (RESPx/HMPx genérico)          |
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
os números. A Rodada 3.1 usa 1296 dos 4096 bytes.

## Layout da RAM (RAM RIOT `$80-$FF`, 128 bytes)

A Rodada 3.1 usa 48 bytes. A tabela de eventos agora tem tamanho variável
(entradas com uma ou duas escritas) e o builder insere os eventos diretamente
nela, então a tabela fixa de 55 bytes, os buffers de registros/ordem,
`evIdx`, `joystate`, as duas flags separadas de míssil e `fire_sync` foram
removidos.

| Endereço | Nome        | Tam. | Finalidade                            |
| -------- | ----------- | ---- | ------------------------------------- |
| `$80`    | `P0Y`       | 1    | posição vertical do jogador 0 (0..179)|
| `$81`    | `P1Y`       | 1    | posição vertical do jogador 1 (0..179)|
| `$82`    | `ball_x`    | 1    | pixel visível mais à esquerda (0..156)|
| `$83`    | `ball_y`    | 1    | primeira linha de exibição (0..188)   |
| `$84`    | `ball_dx`   | 1    | passo horizontal (+1 / $FF)           |
| `$85`    | `ball_dy`   | 1    | passo vertical (+1 / $FF)             |
| `$86`    | `m0_x`      | 1    | posição horizontal do míssil 0        |
| `$87`    | `m0_y`      | 1    | linha do míssil 0 (fixa em voo)       |
| `$88`    | `m1_x`      | 1    | posição horizontal do míssil 1        |
| `$89`    | `m1_y`      | 1    | linha do míssil 1 (fixa em voo)       |
| `$8A`    | `m_active`  | 1    | máscara ativa compactada (bit0 M0, bit1 M1) |
| `$8B`    | `fire_prev` | 1    | borda de fogo compactada (bit7 = sync)|
| `$8C`    | `evCnt`     | 1    | kernel: scanlines até o próximo evento|
| `$8D`    | `scanCnt`   | 1    | kernel: contagem regressiva de 192    |
| `$8E-$AC`| `evTbl`     | 31   | tabela de eventos (tamanho variável, máx. 31B) |
| `$AD`    | `evRow`     | 1    | builder: linha atual do evento        |
| `$AE`    | `tempCount` | 1    | builder: ponto de deslocamento / prevRow |
| `$AF`    | `tblLen`    | 1    | builder: tamanho da tabela em bytes   |
| `$B0-$FF`| -           | 80   | não alocado                          |

As variáveis ficam na zero page para que todos os acessos usem os modos de
endereçamento curtos e rápidos de zero page. A tabela de eventos (no máximo
31 bytes) é o maior bloco único; o estado do jogo em si é compacto. Os 80
bytes livres extras são a margem que esta otimização compra para as próximas
rodadas.

## Uso de registradores de hardware

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESM0/1`, `RESBL`, `GRP0/1`, `ENAM0/1`,
  `ENABL`, `HMOVE`, `HMP0/1`, `HMM0/1`, `HMBL`, `VDELP0/1`, `REFP0/1`
  (zerados).
* Leituras do TIA: `INPT4`/`INPT5` (botões de fogo).
* RIOT: `SWCHA` (leitura de joysticks), `SWACNT` (todos como entrada),
  `INTIM` (leitura do timer), `TIM64T` (escrita do timer, clock de 64 ciclos).

Nenhum outro recurso do TIA ou do RIOT é usado nesta rodada.
