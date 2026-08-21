# Wizard Duel - Mapa de memória

O Atari 2600 (6507) expõe 4 KiB de ROM (`$F000-$FFFF`), 128 bytes de RAM
RIOT (`$80-$FF`), os registradores do TIA (`$00-$3F`) e os registradores de
I/O/timer do RIOT (`$0280-$02FF`).

## Layout da ROM (`$F000-$FFFF`)

| Endereço | Conteúdo                                   |
| -------- | ------------------------------------------ |
| `$F000`  | Reset/inicialização (main.asm)             |
| `$F055`  | `StartOfFrame` (loop de um quadro)         |
| `$F07F`  | `WaitVBlank` (TIM64T + lógica do jogo)     |
| `$F100`  | `KernelLoop` (kernel de 185 linhas por eventos) |
| `$F134`  | `OverscanWait` (colisão + efeitos de acerto + loop de WSYNC) |
| `$F148`  | `UpdatePlayers` (input vertical do joystick) |
| `$F181`  | `UpdateBall` (movimento + quique)          |
| `$F1B8`  | `UpdateMissiles` (disparo, movimento, remoção) |
| `$F24D`  | `ProcessCollisions` (custo fixo, sem branches) |
| `$F2A0`  | `newActiveTbl` (tabela de atualização do m_active) |
| `$F2B0`  | `ApplyBallRebound` (condução da bola, custo fixo, sem branches) |
| `$F2D0`  | `reboundTbl` (tabela do ball_dx, alinhada a 16 bytes) |
| `$F300`  | `ProcessHitEffects` (dano de HP + trava de disparo, alinhado a página) |
| `$F338`  | `PositionPlayers` (RESP0/1 + HMP0/1)       |
| `$F35B`  | `PositionBall` (RESBL + HMBL)              |
| `$F36D`  | `PositionMissiles` (RESM0/1 + HMM0/1)      |
| `$F39C`  | `BuildEvents` (insere eventos em ordem de linha) |
| `$F58A`  | `AppendEvent` (insere/mescla uma entrada)  |
| `$F60F`  | `fineAdjustTable` (tabela HMP)             |
| `$F648`  | `ShiftBy5` (desloca entradas em um slot)   |
| `$F65F`  | `ConvertDeltas` (linhas -> deltas do kernel) |
| `$F68C`  | `PosObject` (RESPx/HMPx genérico)          |
| `$F700`  | `fineAdjustBegin` (tabela HMP, alinhada a página) |
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
os números. A Rodada 6 usa 1808 dos 4096 bytes; o código de contato com a
bola adicionado na rodada (24 bytes) foi absorvido pela folga dos `ALIGN`
existentes, então o maior endereço emitido não mudou.

## Layout da RAM (RAM RIOT `$80-$FF`, 128 bytes)

A Rodada 12 usa 87 bytes ($80-$D6). A tabela de eventos é um bloco fixo de 60
bytes: um dummy de 5 bytes no offset 0, até 10 entradas reais de 5 bytes e o
marcador de fim de 5 bytes. O kernel lê as entradas diretamente (apply direto
da tabela), então os registradores pendentes da Rodada 10 e os buffers de
registros/ordem, `evIdx`, `joystate`, `scanCnt` e as flags separadas de
míssil foram removidos. A Rodada 12 adiciona 6 bytes para estado, modo do
jogo, leitura de switches e controle de reset (`game_state`, `game_mode`,
`select_prev`, `reset_prev`, `swchb_cur`, `reset_held`).

| Endereço | Nome        | Tam. | Finalidade                            |
| -------- | ----------- | ---- | ------------------------------------- |
| `$80`    | `P0Y`       | 1    | posição vertical do jogador 0 (0..166)|
| `$81`    | `P1Y`       | 1    | posição vertical do jogador 1 (0..166)|
| `$82`    | `p0_hp`     | 1    | pontos de vida do jogador 0 (0..3)    |
| `$83`    | `p1_hp`     | 1    | pontos de vida do jogador 1 (0..3)    |
| `$84`    | `ball_x`    | 1    | pixel visível mais à esquerda (0..156)|
| `$85`    | `ball_y`    | 1    | primeira linha de exibição (0..181)   |
| `$86`    | `ball_dx`   | 1    | passo horizontal (+1 / $FF)           |
| `$87`    | `ball_dy`   | 1    | passo vertical (+1 / $FF)             |
| `$88`    | `m0_x`      | 1    | posição horizontal do míssil 0        |
| `$89`    | `m0_y`      | 1    | linha do míssil 0 (fixa em voo)       |
| `$8A`    | `m1_x`      | 1    | posição horizontal do míssil 1        |
| `$8B`    | `m1_y`      | 1    | linha do míssil 1 (fixa em voo)       |
| `$8C`    | `m_active`  | 1    | máscara ativa compactada (bit0 M0, bit1 M1) |
| `$8D`    | `hit_flags` | 1    | resultado de acerto de míssil (bit0 P0, bit1 P1) |
| `$8E`    | `ball_contact_flags` | 1 | registro de contato da bola (bit0 P0, bit1 P1) |
| `$8F`    | `fire_prev` | 1    | borda de fogo compactada (bit7 = sync)|
| `$90`    | `evCnt`     | 1    | kernel: scanlines até o próximo evento|
| `$91`    | `game_state`| 1    | STATE_MENU (0) ou STATE_PLAYING (1)   |
| `$92`    | `game_mode` | 1    | MODE_DUEL (0) ou MODE_SCORE (1)      |
| `$93`    | `select_prev`| 1   | bit SELECT do quadro anterior (bit 1) |
| `$94`    | `reset_prev`| 1    | bit RESET do quadro anterior (bit 0)  |
| `$95`    | `swchb_cur` | 1    | snapshot SWCHB do quadro atual       |
| `$96`    | `reset_held`| 1    | nonzero enquanto RESET é segurado no menu |
| `$97-$D2`| `evTbl`     | 60   | dummy (5B) + entradas (máx. 10 x 5B) + marcador (5B) |
| `$D3`    | `evRow`     | 1    | builder: linha atual do evento        |
| `$D4`    | `tempCount` | 1    | builder: ponto de deslocamento / prevRow |
| `$D5`    | `tblLen`    | 1    | builder: número de entradas reais     |
| `$D6`    | `nullDelta` | 1    | delta da primeira entrada (185 se vazia) |
| `$D7-$FF`| -           | 41   | não alocado                          |

As variáveis ficam na zero page para que todos os acessos usem os modos de
endereçamento curtos e rápidos de zero page. A tabela de eventos (60 bytes) é
o maior bloco único e fica deliberadamente na página 0: o kernel indexa
`evTbl-4,Y` (base de zero page) com Y de até 55, então nenhum acesso indexado
pode cruzar uma fronteira de página e cada escrita do kernel tem tempo
determinístico. Os 43 bytes livres extras são a margem para as próximas
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
