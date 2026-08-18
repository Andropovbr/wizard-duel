# Wizard Duel - Timing

Este documento registra a análise de timing em nível de ciclo do kernel
orientado a eventos e do quadro da Rodada 3.1. Cada número abaixo foi
derivado manualmente e depois verificado contra o listing montado pela suíte
de testes automatizada; o comprimento do quadro foi também verificado com um
emulador 6502 determinístico que modela as paradas de WSYNC e o timer do
RIOT.

## Estrutura do quadro (NTSC)

| Região    | Scanlines | Como é produzida               |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | três `STA WSYNC` explícitos    |
| VBLANK    | 57        | contagem `TIM64T = 69`         |
| KERNEL    | 192       | loop explícito de `STA WSYNC`  |
| OVERSCAN  | 10        | contagem `TIM64T = 11`         |
| **Total** | **262**   |                                |

O VBLANK cresceu de 37 (Rodada 2) para 57 linhas e o OVERSCAN encolheu de 30
para 10 linhas para dar espaço ao `BuildEvents` reconstruir a tabela de
eventos a cada quadro.

### Por que os valores do timer são 69 e 11

O timer do RIOT conta a cada 64 ciclos. A Rodada 2 usou `43`/`37` para uma
divisão de 37/30 linhas; os valores da Rodada 3 foram derivados do mesmo modo
(o timer expira alguns ciclos antes do valor ingênuo `valor * 64`, e o
`STA WSYNC` após cada espera sincroniza na linha correta) e depois ajustados
empiricamente para que o emulador reporte exatamente 262 scanlines por
quadro:

* `VBLANK_TIMER_VALUE = 69` expira na penúltima linha do VBLANK; o
  `STA WSYNC` seguinte sincroniza na última linha do VBLANK, onde `HMOVE` é
  escrito imediatamente após o `WSYNC` (exigido para que os registradores de
  movimento atuem durante o blanking horizontal da última linha do VBLANK);
* `OVERSCAN_TIMER_VALUE = 11` expira na última linha do quadro.

## O kernel visível

Um scanline = **76 ciclos de CPU**. Cada iteração do kernel começa com
`STA WSYNC`, então cada iteração é exatamente um scanline; o quadro não pode
derivar quando eventos disparam.

### Estrutura orientada a eventos

O kernel não calcula enables de objetos. `BuildEvents` (executado durante o
VBLANK) escreve uma tabela (`evTbl`) de entradas de tamanho variável. Cada
entrada começa com `delta` (scanlines até disparar) e `reg1` (índice da
primeira escrita; índices 1..5 endereçam GRP0..ENABL, índice 0 é um dummy
inofensivo em AUDV1). Se o bit 7 de `reg1` estiver setado, a entrada é uma
simples de 3 bytes `[delta, reg1|$80, val1]`; caso contrário, é uma dupla de
5 bytes `[delta, reg1, val1, reg2, val2]`.

O kernel despacha no bit de flag com um único `BMI`; o byte de valor de uma
simples nunca carrega bit 7 porque todo valor de escrita é um registrador de
enable (`$00`, `PADDLE_BITS`, `BALL_ENABLE` ou `MISSILE_ENABLE`). É isso que
permite a uma scanline que precisa de apenas uma escrita pular a segunda
escrita em vez de gastar um dummy inofensivo.

O kernel conta suas 192 linhas com uma contagem regressiva em RAM
(`scanCnt`). Isso é deliberado: o código de evento usa `TAX` como índice de
registrador, o que corromperia um contador de linhas em X a cada linha de
evento e esticaria o quadro.

### Contabilidade de ciclos (verificada no listing)

Existem três caminhos por scanline: sem evento, evento de escrita única,
evento de duas escritas.

Linha sem evento (o caso comum):

| Instrução           | Ciclos |
| ------------------- | ------ |
| `STA WSYNC`         | 3      |
| `DEC scanCnt`       | 5      |
| `BEQ .kernelEnd`    | 2      |
| `DEC evCnt`         | 5      |
| `BNE KernelLoop`    | 3      |
| **Total**           | **18** |

Linha de evento, escrita única (entrada de 3 bytes):

| Instrução           | Ciclos |
| ------------------- | ------ |
| `STA WSYNC`         | 3      |
| `DEC scanCnt`       | 5      |
| `BEQ .kernelEnd`    | 2      |
| `DEC evCnt`         | 5      |
| `BNE KernelLoop`    | 2      |
| `LDY evIdx`         | 3      |
| `LDA evTbl+1,Y`     | 4      |
| `TAX`               | 2      |
| `LDA evTbl+2,Y`     | 4      |
| `STA EV_WRITE_BASE,X` | 4    |
| `TYA` / `CLC` / `ADC #3` / `TAY` | 8 |
| `STY evIdx`         | 3      |
| `LDA evTbl,Y`       | 4      |
| `STA evCnt`         | 3      |
| `JMP KernelLoop`    | 3      |
| **Total**           | **54** |

Linha de evento, duas escritas (entrada de 5 bytes):

| Instrução           | Ciclos |
| ------------------- | ------ |
| `STA WSYNC`         | 3      |
| `DEC scanCnt`       | 5      |
| `BEQ .kernelEnd`    | 2      |
| `DEC evCnt`         | 5      |
| `BNE KernelLoop`    | 2      |
| `LDY evIdx`         | 3      |
| `LDA evTbl+1,Y`     | 4      |
| `TAX`               | 2      |
| `LDA evTbl+2,Y`     | 4      |
| `STA EV_WRITE_BASE,X` | 4    |
| `LDA evTbl+3,Y`     | 4      |
| `TAX`               | 2      |
| `LDA evTbl+4,Y`     | 4      |
| `STA EV_WRITE_BASE,X` | 4    |
| `TYA` / `CLC` / `ADC #5` / `TAY` | 8 |
| `STY evIdx`         | 3      |
| `LDA evTbl,Y`       | 4      |
| `STA evCnt`         | 3      |
| `JMP KernelLoop`    | 3      |
| **Total**           | **65** |

| Caminho                    | Ciclos |
| -------------------------- | ------ |
| Linha sem evento           | **18** |
| Linha de evento (1 escrita)| **54** |
| Linha de evento (2 escritas)| **65** |
| Orçamento do scanline      | 76     |
| Folga (linha de 2 escritas)| **11 ciclos** |

O corpo do kernel é alinhado a página (`ALIGN 256` antes de `KernelLoop`)
para que todo desvio tenha tempo determinístico, e todos os acessos à tabela
são indexados em zero page (sem penalidades de passagem de página). O kernel
tem exatamente três desvios condicionais: o `BEQ` do fim da contagem de
linhas, o `BNE` da contagem de eventos e o `BMI` de despacho simples/dupla.

### Tempos de escrita dos registradores gráficos

Em uma linha de duas escritas, a primeira escrita de registrador executa
durante os ciclos de CPU 30..33 e a segunda durante 44..47; em uma linha de
escrita única, a escrita executa durante 30..33.

Uma escrita no TIA se aplica ao scanline atual apenas se terminar antes de o
feixe passar pela posição horizontal do objeto; caso contrário, aplica-se um
scanline depois. Usando o modelo padrão de feixe (o pixel `p` é atingido no
ciclo de CPU `~(p + 69) / 3`), as portas são portanto `x >= 30` para a
primeira escrita e `x >= 72` para a segunda. Os dois jogadores estão bem fora
dessas faixas (P0 em x=16, P1 em x=136) e se comportam exatamente como na
Rodada 3; apenas um objeto cuja posição caísse nas faixas de 3 pixels
`30..32` / `72..74` ganharia um scanline de margem, e nenhum objeto desta
rodada ocupa essas posições. O `delta` da próxima entrada é lido até o ciclo
65 no pior caminho, confortavelmente antes do `WSYNC` que inicia a próxima
linha.

## Orçamentos de VBLANK e OVERSCAN

O gameplay (decodificação do joystick + movimento + atualização dos mísseis +
posicionamento) e o build da tabela de eventos rodam no VBLANK entre a
liberação do VSYNC e a espera do timer. O pior caso (dois mísseis ativos,
alinhamento patológico de linhas) é ~4,1k ciclos de trabalho de CPU mais os
syncs de linha dos `PosObject`, confortavelmente dentro da janela do timer
`69 * 64 = 4416` ciclos (medido com o emulador determinístico: pior caso
~4135 ciclos, ~280 ciclos de folga).

O trabalho do OVERSCAN (blank da tela, limpar todos os registradores de
objeto, armar o timer, esperar, saltar) cabe na janela de 10 linhas.

## Comprimento medido do quadro

Verificado com um emulador 6502 determinístico que modela paradas de WSYNC e
o timer do RIOT:

* comprimento de quadro em estado estável: **19912 ciclos = exatamente 262
  scanlines**, estável em 30+ quadros para os estados sem mísseis, com dois
  mísseis e patológico;
* o kernel visível roda exatamente 192 iterações (a contagem `scanCnt`).

O primeiro quadro após ligar é alguns ciclos mais curto que o estado estável
porque os relógios da CPU e do TIA ainda não estão alinhados; todos os
quadros seguintes têm exatamente 19912 ciclos. Isso é comportamento normal de
reset.

### Status da validação em tempo de execução

A suíte automatizada valida a estrutura do quadro **estaticamente**
(constantes, listing, soma das regiões == 262, orçamento de ciclos do kernel)
e o builder da tabela de eventos com um modelo em Python (deltas, mesclagens,
resolução de colisões). Um teste de tempo de execução do quadro
(`tests/test_frame_timing.py`) dirige o emulador determinístico por muitos
quadros e afirma a estabilidade do quadro (262 scanlines), que o comprimento
da tabela nunca excede `EV_TBL_SIZE` sob entrada de fogo agressiva e que os
mísseis de fato aparecem e desaparecem pelo pipeline de eventos. O contador de
ciclos do emulador é aproximado (os totais de quadro único variam alguns
ciclos), então o teste de tempo de execução afirma a contagem de scanlines e o
comportamento, não totais de ciclos exatos.

## Por que isso importa

"Correção visual não é prova de correção de hardware": um quadro que parece
certo, mas deriva para 260 ou 263 scanlines, viola o contrato de timing NTSC.
Os valores do timer acima foram ajustados precisamente para que o quadro seja
exatamente 262 scanlines, e a contagem `scanCnt` do kernel mantém a região
visível em exatamente 192 linhas, independentemente de quantos eventos
disparam.
