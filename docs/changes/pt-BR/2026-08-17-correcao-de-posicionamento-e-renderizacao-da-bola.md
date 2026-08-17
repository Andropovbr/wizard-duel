# Mudança: Conclusão da renderização da bola e correção do posicionamento horizontal

## Objetivo

Concluir a bola da Rodada 2 para que seja um quadrado 4x4 e, principalmente,
para que renderize exatamente na posição horizontal solicitada (`ball_x`),
movendo-se continuamente 1 pixel por quadro. O estado anterior commitado
usava apenas o posicionamento grosseiro de 15 pixels: o ajuste fino
(`HMP0/HMP1/HMBL` + `HMOVE`) era escrito, mas nunca tinha efeito, então a
bola renderizada saltava em passos de 15 pixels a cada 15 quadros, em vez de
deslizar 1 pixel por quadro.

## Causa raiz

Dois defeitos independentes foram encontrados e corrigidos.

### 1. O `HMOVE` não seguia imediatamente um `WSYNC`

O Guia do Programador Stella exige:

> O comando `HMOVE` deve seguir imediatamente um `WSYNC` (Wait for SYNC)
> para garantir que a operação do HMOVE ocorra durante o blanking
> horizontal.

O código escrevia `HMOVE` logo após o loop de espera `LDA INTIM / BNE` do
VBLANK sair, ou seja, no meio da última scanline do VBLANK, e não depois de
um `WSYNC`. Comportamento medido: os offsets finos nunca eram aplicados.
Com a bola congelada em cada `ball_x` 0..16, `ball_x` 0..13 renderizava em
2 color clocks e `ball_x` 14..16 em 14; as raquetes renderizavam na grade
grosseira (`PLAYER1_X` 15..29 todas em 15). A "verificação" de 1 px/quadro
da rodada anterior usava amostragem esparsa de 0,09 s e não detectava os
saltos de 15 pixels.

Correção: `STA WSYNC` agora é executado imediatamente antes de
`STA HMOVE`, para que o movimento atue durante o blanking horizontal da
última linha do VBLANK (linha 40). `VBLANK_TIMER_VALUE` passou de 44 para
43 para que o loop de espera expire uma linha antes (linha 39) e o `WSYNC`
extra ainda leve o kernel para a linha 41, mantendo o quadro com exatamente
262 scanlines.

### 2. A rotina renderiza em `P - 7` (q >= 1) / `P - 4` (q = 0)

Com o movimento fino funcionando, a posição absoluta ainda estava errada: a
rotina PosObject compartilhada renderiza um jogador em

    15*q + (s - 7)    para q >= 1
    3 + (s - 7)       para q = 0

onde o loop de divisão executa `q + 1` subtrações e `s = P mod 15` indexa a
tabela `fineAdjustTable` (alinhada a página, valores +7..-7). A base do
q = 0 é 3 em vez de 0 porque o caminho mais curto da divisão aplica `RESP`
antes do ciclo 23 do TIA (peculiaridade de hardware). A bola ainda renderiza
1 pixel à esquerda de um jogador para a mesma entrada.

A compensação usada antes (`ball_x + 1`) não podia cancelar um offset que é
diferente para q = 0 e q >= 1. O `PositionBall` agora passa `ball_x + 8` (ou
`ball_x + 5` quando a soma fica abaixo de 15) e o `PositionPlayers` passa
`X + 7` (ou `X + 4`), o que cancela os dois offsets e o deslocamento de
1 pixel para a esquerda da bola em toda posição válida.

## Adicionado / Alterado

- `WaitVBlank`: `STA WSYNC` antes de `STA HMOVE` na última linha do VBLANK.
- `VBLANK_TIMER_VALUE = 43` (era 44) em `src/constants.inc`.
- `PositionBall`: compensação `ball_x + 8` / `ball_x + 5` (ramo no VBLANK;
  o `PosObject` ressincroniza com seu próprio `WSYNC`, então o timing do
  ramo é irrelevante).
- `PositionPlayers`: compensação `X + 7` / `X + 4` para os dois jogadores.
- Conclusão da bola quadrada 4x4: `BALL_HEIGHT = 4`,
  `BALL_SIZE_CTRLPF = %00100000` (4 color clocks; o valor commitado
  `%00010000` era 2), `BALL_Y_MAX = KERNEL_SCANLINES - BALL_HEIGHT - 1`, e o
  bloco da bola no kernel reescrito de `CMP ball_y / BNE` para
  `SEC / SBC ball_y / CMP #BALL_HEIGHT / BCS`, de modo que `ENABL` é escrito
  em `BALL_HEIGHT` scanlines consecutivas.
- `tests/test_positioning.py` reescrito: o modelo agora corresponde ao
  comportamento medido no hardware (grosseiro `15*q`/`3`, fino `s - 7`,
  bola `-1`, e a compensação nos dois chamadores) e verifica
  renderizado == solicitado para todo `P`/`ball_x`, além de exatamente
  1 pixel de movimento por quadro em cada fronteira grosseiro/fino. Foi
  adicionado um teste para os offsets medidos.
- `docs/en/timing.md`, `docs/en/architecture.md`, `docs/pt-BR/timing.md`,
  `docs/pt-BR/arquitetura.md`, `docs/en/build.md`, `docs/pt-BR/build.md`,
  `docs/en/benchmarks.md`, `docs/pt-BR/benchmarks.md`: timer 43, HMOVE após
  WSYNC, contabilidade do kernel da bola 4x4 e a compensação de
  posicionamento.

## Validação

O mapeamento empírico foi medido congelando a bola (`ball_x`/`ball_y`
escritos a cada quadro) e as raquetes, compilando e capturando o Stella em
sessão gráfica, e lendo as colunas de color clock renderizadas:

- bola `ball_x` 0, 3, 6, 7, 8, 13, 14, 15, 22, 28, 29, 30, 45, 60, 100, 150,
  156: color clock esquerdo renderizado == `ball_x` em todos os casos,
  incluindo as fronteiras grosseiro/fino 6->7, 13->14 e 28->29 (sem salto,
  sem pausa).
- raquetes `PLAYER1_X` 7, 8, 13, 14, 15, 16, 22, 29, 30, 45, 150: bit 7
  renderizado == `PLAYER1_X` em todos os casos.

Higiene da medição: um `ball_y` congelado único era derivado de `ball_x`
para detectar capturas de janela obsoletas, e processos Stella órfãos eram
mortos com `pkill -9 -x stella` (uma instância vazada com `-snapsavedir` e o
caminho da ROM depois na linha de comando tinha contaminado capturas
anteriores).

## Impacto de Timing

Antes (Rodada 2 commitada, bola de 1 scanline):
- Scanlines do quadro: 262
- Pior/melhor caso do kernel: 71 / 57 ciclos (folga 5)
- Bloco da bola: 15 na linha da bola, 13 nas demais
- `GRP0`/`GRP1`/`ENABL` em ~ciclo 24/47/63

Depois (bola 4x4 + correção de posicionamento):
- Scanlines do quadro: 262 (inalterado)
- Pior/melhor caso do kernel: 74 / 61 ciclos (folga **2**)
- Bloco da bola: 18 numa linha da bola, 17 nas demais
- `GRP0`/`GRP1`/`ENABL` em ~ciclo 26/49/67
- `VBLANK_TIMER_VALUE` 43, `OVERSCAN_TIMER_VALUE` 37

A folga caiu de 5 para 2 ciclos: a bola 4x4 custa três ciclos a mais por
linha que a versão de 1 scanline. É o custo deliberado de um objeto 4x4
visível e fica bem dentro do orçamento de 76 ciclos.

## Impacto de Memória

Antes:
- ROM: 528 bytes
- RAM: 7 bytes

Depois:
- ROM: 528 bytes (a compensação e o bloco da bola continuam no padding de
  página)
- RAM: 7 bytes

## Testes

- `tests/test_positioning.py`: modelo reescrito + teste de offsets medidos.
- Suíte completa: **106 testes passam**; quality gates passam (ROM
  528/4096, RAM 7/128, 262 scanlines, pior 74/76, folga 2). Benchmark e
  regressão reexecutados em verde.

## Limitações Conhecidas

- A base grosseira 3 do q = 0 (RESP antes do ciclo 23 do TIA) é uma
  peculiaridade de hardware da rotina de divisão; ela é tratada pela
  compensação no chamador, em vez de alterar o `PosObject` compartilhado, o
  que mantém a rotina idêntica à referência.
- A verificação de posição absoluta é manual (capturas com quadro congelado);
  a suíte automatizada valida o mesmo mapeamento por meio do modelo de
  intérprete.