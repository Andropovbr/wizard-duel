# Wizard Duel - Timing

Este documento registra a análise de timing em nível de ciclo do kernel e do
quadro da Rodada 1. Cada número abaixo foi derivado manualmente e depois
verificado contra o listing montado pela suíte de testes automatizada, ou
medido no depurador do Stella.

## Estrutura do quadro (NTSC)

| Região    | Scanlines | Como é produzida               |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | três `STA WSYNC` explícitos    |
| VBLANK    | 37        | contagem `TIM64T = 44`         |
| KERNEL    | 192       | loop explícito de `STA WSYNC`  |
| OVERSCAN  | 30        | contagem `TIM64T = 37`         |
| **Total** | **262**   |                                |

### Por que os valores do timer são 44 e 37

O timer do RIOT conta a cada 64 ciclos. Definir `TIM64T = N` parece exigir
`N * 64` ciclos, mas a implementação do M6532 no Stella (e no hardware real)
se comporta um pouco diferente:

* `mySubTimer` começa em `myDivider - 1`, então o primeiro tick acontece
  alguns ciclos antes;
* a contagem dá a volta quando atinge `(valor + 1) * 64` ciclos.

Por causa disso o timer expira em um ciclo anterior ao que um cálculo
ingênuo de `valor * 64` sugeriria. Empiricamente (medido com
`print _cyclesLo` no breakpoint `StartOfFrame` do depurador do Stella):

* `VBLANK_TIMER_VALUE = 44` faz a espera do VBLANK expirar na última
  scanline do VBLANK (linha 40 do quadro);
* `OVERSCAN_TIMER_VALUE = 37` faz a espera do OVERSCAN expirar na última
  linha do quadro.

Uma leitura ingênua de `37 * 64 = 2368` ciclos para o overscan corresponde
a `2368 / 76 = 31,1` scanlines; o comportamento efetivo produz as 30
scanlines pretendidas.

## O kernel visível

Uma scanline = **76 ciclos de CPU**. Cada iteração do kernel começa com
`STA WSYNC`, então toda iteração é exatamente uma scanline,
independentemente de ramificações; o quadro não pode derivar quando um
jogador se move.

### Contabilidade de ciclos (verificada no listing)

Caminho desenhado por jogador (linha do sprite escrita):

| Instrução          | Ciclos |
| ------------------ | ------ |
| `TXA`              | 2      |
| `SEC`              | 2      |
| `SBC P0Y`          | 3      |
| `CMP #altura`      | 2      |
| `BCS .P0Blank`     | 2 (não tomado) |
| `TAY`              | 2      |
| `LDA P0Sprite,Y`   | 4      |
| `JMP .P0Done`      | 3      |
| `STA GRP0`         | 3      |
| **Subtotal**       | **23** |

Caminho vazio por jogador (nenhuma linha do sprite nesta linha):

| Instrução          | Ciclos |
| ------------------ | ------ |
| `TXA`              | 2      |
| `SEC`              | 2      |
| `SBC P0Y`          | 3      |
| `CMP #altura`      | 2      |
| `BCS .P0Blank`     | 3 (tomado) |
| `LDA #0`           | 2      |
| `STA GRP0`         | 3      |
| **Subtotal**       | **17** |

Fim (por scanline): `INX` 2 + `CPX #192` 2 + `BNE` 3 + `STA WSYNC` 3
= **10**.

| Caminho                  | Ciclos |
| ------------------------ | ------ |
| Ambos os sprites desenhados | 23+23+10 = **56** |
| Ambos os sprites vazios   | 17+17+10 = **44** |
| Um desenhado, um vazio    | 23+17+10 = **50** |
| Orçamento da scanline     | 76     |
| Folga no pior caso        | **20 ciclos** |

As tabelas de sprite estão dispostas de modo que todo índice possível de
linha (0..11) permaneça dentro de uma única página; o `LDA` indexado nunca
paga a penalidade de +1 de passagem de página. Isso é verificado pela suíte
de testes.

`GRP0` é escrito por volta do ciclo 23 da sua scanline e `GRP1` por volta
do ciclo 46; ambos são travados (latched) para a linha seguinte, bem antes
do limite de 76 ciclos.

## Orçamentos de VBLANK e OVERSCAN

A lógica de jogo (decodificação do joystick + movimento + posicionamento)
roda no VBLANK entre a liberação do VSYNC e a espera do timer. Seu custo é:

* `UpdatePlayers`: 3 + 3 + (2+3+2/3) + (2+3+2+2/3) + ... cerca de 60 ciclos
  no pior caso para os dois jogadores;
* `PositionPlayers`: duas chamadas `PosObject` consumindo 1-2 scanlines
  cada.

Isso está muito abaixo do orçamento de 37 linhas do VBLANK e nunca interfere
no kernel visível.

## Comprimento do quadro medido

Medido no Stella 6.6 com o depurador:

* `print _cyclesLo` em breakpoints `StartOfFrame` em quadros consecutivos:
  deltas de estado estável de **19912 ciclos** cada.
* `19912 / 76 = 262` scanlines exatamente.

O primeiro quadro após ligar é cerca de 55 ciclos mais curto que o estado
estável porque os clocks da CPU e do TIA ainda não estão alinhados; todos
os quadros seguintes têm exatamente 19912 ciclos. Isso é comportamento
normal de reset.

A medição do comprimento do quadro é determinística, mas exige o depurador
gráfico do Stella, então é documentada aqui em vez de automatizada no CI. O
CI valida a estrutura do quadro estaticamente (constantes, listing) e
rejeita qualquer build cuja soma das scanlines das regiões difira de 262.

## Por que isso importa

"Correção visual não é prova de correção de hardware": um quadro que parece
correto mas deriva para 260 ou 261 scanlines viola o contrato de timing
NTSC. Os valores do timer acima foram ajustados precisamente para que o
quadro tenha exatamente 262 scanlines no emulador de referência.