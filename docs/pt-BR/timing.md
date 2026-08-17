# Wizard Duel - Timing

Este documento registra a análise de timing em nível de ciclo do kernel e do
quadro da Rodada 2. Cada número abaixo foi derivado manualmente e depois
verificado contra o listing montado pela suíte de testes automatizada, ou
medido no depurador do Stella.

## Estrutura do quadro (NTSC)

| Região    | Scanlines | Como é produzida               |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | três `STA WSYNC` explícitos    |
| VBLANK    | 37        | contagem `TIM64T = 43`         |
| KERNEL    | 192       | loop explícito de `STA WSYNC`  |
| OVERSCAN  | 30        | contagem `TIM64T = 37`         |
| **Total** | **262**   |                                |

### Por que os valores do timer são 43 e 37

O timer do RIOT conta a cada 64 ciclos. Definir `TIM64T = N` parece exigir
`N * 64` ciclos, mas a implementação do M6532 no Stella (e no hardware real)
se comporta um pouco diferente:

* `mySubTimer` começa em `myDivider - 1`, então o primeiro tick acontece
  alguns ciclos antes;
* a contagem dá a volta quando atinge `(valor + 1) * 64` ciclos.

Por causa disso o timer expira em um ciclo anterior ao que um cálculo
ingênuo de `valor * 64` sugeriria. Empiricamente (medido com
`print _cyclesLo` no breakpoint `StartOfFrame` do depurador do Stella):

* `VBLANK_TIMER_VALUE = 43` faz a espera do VBLANK expirar na linha 39; o
  `STA WSYNC` seguinte sincroniza com a linha 40, onde `HMOVE` é escrito
  imediatamente após o `WSYNC` (exigido para que os registradores de
  movimento atuem durante o blanking horizontal da última linha do VBLANK);
* `OVERSCAN_TIMER_VALUE = 37` faz a espera do OVERSCAN expirar na última
  linha do quadro.

Uma leitura ingênua de `37 * 64 = 2368` ciclos para o overscan corresponde
a `2368 / 76 = 31,1` scanlines; o comportamento efetivo produz as 30
scanlines pretendidas.

## O kernel visível

Uma scanline = **76 ciclos de CPU**. Cada iteração do kernel começa com
`STA WSYNC`, então toda iteração é exatamente uma scanline; o quadro não
pode derivar quando um jogador se move.

### Contabilidade de ciclos (verificada no listing)

O kernel é **sem ramificações** (branchless): a única ramificação é o `BNE`
final que volta ao `KernelLoop`, então toda scanline custa exatamente o
mesmo, independentemente do estado dos jogadores ou da bola. Isso remove
todo timing dependente de dados do caminho de renderização.

Por scanline:

| Instrução           | Ciclos |
| ------------------- | ------ |
| `STA WSYNC`         | 3      |
| `STA ENABL`         | 3      |
| Bloco do P0 (retângulo) | 18  |
| Bloco do P1 (retângulo) | 18  |
| Fim (incl. `BNE`)   | 20     |
| **Total**           | **62** |

Bloco de jogador (um jogador):

| Instrução              | Ciclos |
| ---------------------- | ------ |
| `TXA`                  | 2      |
| `SEC`                  | 2      |
| `SBC PLAYERxY`         | 3      |
| `CMP #PLAYER_HEIGHT`   | 2      |
| `LDA #0`               | 2      |
| `SBC #0`               | 2      |
| `AND #PADDLE_BITS`     | 2      |
| `STA GRPx`             | 3      |
| **Subtotal**           | **18** |

A sequência `LDA #0 / SBC #0` é um teste "desenha ou apaga" sem ramificação:
após `CMP #PLAYER_HEIGHT` o carry está limpo exatamente nas linhas da
raquete (`PLAYERx_Y <= X < PLAYERx_Y + altura`), então `SBC #0` deixa
`A = $FF` lá e `A = $00` em todo o resto; `AND #PADDLE_BITS` mapeia isso
para o byte da linha `%00111100` ou 0.

Fim (por scanline):

| Instrução                | Ciclos |
| ------------------------ | ------ |
| `TXA`                    | 2      |
| `SEC`                    | 2      |
| `SBC ball_y`             | 3      |
| `CMP #BALL_HEIGHT`       | 2      |
| `LDA #0`                 | 2      |
| `SBC #0`                 | 2      |
| `INX`                    | 2      |
| `CPX #KERNEL_SCANLINES`  | 2      |
| `BNE KernelLoop`         | 3      |
| **Subtotal**             | **20** |

| Caminho                   | Ciclos |
| ------------------------- | ------ |
| Qualquer (kernel sem ramificações) | **62** |
| Orçamento da scanline     | 76     |
| Folga                     | **14 ciclos** |

A folga subiu de 2 para 14 ciclos porque os caminhos ramificados do kernel
antigo (pior caso 74) desapareceram: o novo kernel é mais curto e totalmente
determinístico. O custo único desse projeto é que os dois jogadores precisam
ser renderizados como retângulos constantes: um jogador dirigido por tabela
(`LDA` indexado + `JMP`) não cabe após a escrita de `ENABL` que deve abrir a
scanline e ainda deixar `GRP0` com folga.

### Timing de habilitação da bola (a correção do deslocamento vertical)

O TIA amostra o bit de habilitação da bola na posição horizontal da bola; o
valor escrito em `ENABL` **não** é travado (latched) para a scanline
seguinte. O kernel anterior escrevia `ENABL` tarde na scanline (~ciclo 67),
então se uma dada scanline desenhava a bola com o valor da linha atual ou da
anterior dependia de `ball_x` em relação à posição do feixe no momento da
escrita. O resultado era uma bola que pulava uma scanline na vertical em
algumas regiões horizontais.

A correção escreve `ENABL` durante o blanking horizontal de toda scanline:
`STA ENABL` completa por volta do ciclo 5, bem antes do primeiro pixel
visível (~ciclo 22.7). O valor é pré-calculado no fim da scanline *anterior*
para a linha *atual*, então a bola é desenhada em exatamente `BALL_HEIGHT`
linhas consecutivas, independentemente de `ball_x`: a linha L mostra a bola
se L-1 for uma linha da bola, ou seja, L em `ball_y+1 .. ball_y+BALL_HEIGHT`
(a mesma convenção de exibição de antes). A linha 0 escreve o `A = 0` deixado
pelo pré-kernel, então a primeira linha visível nunca mostra a bola. `ENABL`
é limpo novamente na inicialização do overscan, de modo que o registrador
nunca pode manter 1 no overscan, mesmo quando a bola está no fundo da arena.

Como o valor de habilitação é transportado em `A` pela aresta de retorno do
loop, nenhum byte de RAM é necessário para ele.

### Horários de escrita dos registradores de gráficos

`ENABL` completa por volta do ciclo 5, `GRP0` por volta do ciclo 23 (antes de
o feixe alcançar o P0 em x=16, ~ciclo 28.3) e `GRP1` por volta do ciclo 41
(antes de o feixe alcançar o P1 em x=136, ~ciclo 68). As três escritas
acontecem antes da posição horizontal do respectivo objeto, então cada
objeto renderiza com o valor escrito na scanline atual.

## Orçamentos de VBLANK e OVERSCAN

A lógica de jogo (decodificação do joystick + movimento + atualização da
bola + posicionamento) roda no VBLANK entre a liberação do VSYNC e a espera
do timer. Seu custo é:

* `UpdatePlayers`: 3 + 3 + (2+3+2/3) + (2+3+2+2/3) + ... cerca de 60 ciclos
  no pior caso para os dois jogadores;
* `UpdateBall`: quatro checagens de quique + dois movimentos, cerca de 65
  ciclos no pior caso (ramo tomado em todas as checagens);
* `PositionPlayers`: duas chamadas `PosObject` consumindo 1-2 scanlines
  cada;
* `PositionBall`: uma chamada `PosObject`.

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
gráfico do Stella, então é documentada aqui em vez de automatizada no CI.

### Status da validação em runtime

**Não existe validação automatizada de scanlines em runtime** na pipeline
atual. O Stella 6.6 não oferece opção headless documentada que avance
quadros e exponha o contador de scanlines do TIA para a saída padrão; o
depurador e o overlay de estatísticas do quadro (Alt-L) exigem sessão
gráfica e entrada interativa, e a automação por teclas é frágil demais para
o CI. Consequentemente:

* o quadro de 262 scanlines foi medido **manualmente no depurador do Stella
  em uma sessão gráfica local** (deltas de `print _cyclesLo` de 19912
  ciclos);
* a pipeline do CI valida a estrutura do quadro **estaticamente**
  (constantes, listing, soma das scanlines das regiões == 262, orçamento de
  ciclos do kernel) e rejeita qualquer build cuja soma das scanlines das
  regiões difira de 262.

O projeto, portanto, não afirma que as scanlines foram "validadas em runtime
no CI"; a validação do quadro em runtime continua sendo uma etapa manual, e
a arquitetura mantém a suíte estática como substituto determinístico seguro
para o CI.

## Por que isso importa

"Correção visual não é prova de correção de hardware": um quadro que parece
correto mas deriva para 260 ou 261 scanlines viola o contrato de timing
NTSC. Os valores do timer acima foram ajustados precisamente para que o
quadro tenha exatamente 262 scanlines no emulador de referência.