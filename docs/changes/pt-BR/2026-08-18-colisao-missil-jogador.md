# Mudança: Colisão míssil x jogador e overscan determinístico

## Objetivo

Implementar a Rodada 4 do Wizard Duel: os latches de colisão do TIA detectam
os acertos cruzados M0 -> P1 e M1 -> P0, registram o acerto num bitfield de
um byte (`hit_flags`), desativam o míssil que marcou e limpam os latches
para que um acerto nunca seja contado duas vezes. Uma restrição dura surgiu
durante o trabalho: o quadro atual ocasionalmente escorregava de 262 para
263 scanlines (o `INTIM` era lido no ciclo 4561 em vez de <= 4555), então a
feature também precisou tornar o timing do quadro determinístico sob carga
máxima de colisão.

## Adicionado

* **Detecção de colisão** (`ProcessCollisions`): lê CXM0P (M0 x P1, D7) e
  CXM1P (M1 x P0, D7), ignora os bits do próprio jogador (M0 x P0, M1 x P1),
  define `hit_flags` (bit 1 = P1 acertado, bit 0 = P0 acertado; acertos
  simultâneos são ambos registrados) e limpa o bit do míssil que marcou em
  `m_active`. `CXCLR` é escrito ao final de todo quadro, então um acerto
  renderizado no quadro N nunca é contado no quadro N+2.
* **Região de overscan fixa**: o overscan agora é exatamente
  `OVERSCAN_LOOP_COUNT = 8` escritas de `STA WSYNC` (um loop de contagem) em
  vez de uma espera `TIM64T`, e `ProcessCollisions` roda no início do
  overscan. O quadro tem 262 scanlines por construção.
* **Passagem de colisão sem branches e de custo fixo**: `ProcessCollisions`
  não tem branches e custa fixamente 84 ciclos. Os latches viram flags 0/1
  via carry (`ASL` + `ADC #0`), `hit_flags = 2*hit0 + hit1`, e a atualização
  de `m_active` é uma única busca na tabela de 16 bytes `newActiveTbl`
  indexada por `m_active + 4*hit0 + 8*hit1` (a tabela fica em uma fronteira
  de 16 bytes para que o `LDA` indexado nunca cruze uma página de 256 bytes
  no 6502 real).
* **Testes**: `tests/test_collision.py` (22 testes) roda o assembly real no
  emulador com valores de latch injetados; um novo teste de regressão em
  `tests/test_frame_timing.py` reproduz exatamente o cenário de estresse
  máximo que escorregava para 263 scanlines e garante que todo quadro tenha
  19912 ciclos.
* **`newActiveTbl`** (16 bytes de ROM) e o byte de RAM `hit_flags` (49 no
  total).

## Alterado

* `ProcessCollisions` saiu do início do VBLANK para o início do overscan (a
  desativação ainda ocorre antes do `UpdateMissiles` do próximo quadro).
* A espera de overscan `TIM64T = 11` foi removida e substituída pela
  contagem de WSYNC; `OVERSCAN_TIMER_VALUE` virou `OVERSCAN_LOOP_COUNT`.
* A métrica de benchmark `overscan_timer` foi renomeada para
  `overscan_loop`; a coluna de `docs/benchmarks/history.csv` foi migrada
  (linhas históricas em branco: os valores antigos eram de timer, não de
  contagem de loop, e não são comparáveis).
* Docs atualizadas (EN + pt-BR): timing, arquitetura, mapa de memória,
  benchmark.

## Raciocínio Técnico

### Por que a passagem de colisão não pode ficar no VBLANK

A região de VBLANK é mantida em exatamente 57 linhas por uma espera
`TIM64T` cuja expiração fica num ciclo fixo (~início do quadro + 4555). A
espera só segura a fronteira enquanto o trabalho pré-espera termina antes da
expiração; caso contrário, o `STA WSYNC` após o poll cai uma linha inteira
atrasado. Com a passagem de colisão no VBLANK, o quadro mais pesado (dois
mísseis acertando, duas bordas de disparo, dois mísseis re-gerados)
ocasionalmente empurrava o trabalho para depois da expiração (medido: o
primeiro `INTIM` era lido no ciclo 4561 nos quadros que escorregavam), e o
WSYNC de fim de VBLANK alinhava em 4636 em vez de 4560 -> 263 scanlines. Sob
a entrada de estresse máximo (ambos os latches assertados todo quadro +
disparo alternado) a taxa era de ~1% (2/300 quadros).

### Por que o overscan também não pode usar uma espera `TIM64T`

Uma espera por timer só é determinística quando o trabalho antes de armar o
timer é fixo. O timer do RIOT tem granularidade de 64 ciclos e `INTIM < 64`
pode sair até 63 ciclos antes da expiração nominal, então com uma passagem
de colisão de custo variável (34..66 ciclos) a região de overscan caía em
fronteiras de 76 ciclos diferentes e o quadro variava entre 261/262/263
linhas conforme o caminho de colisão executado.

### Por que a passagem de colisão é sem branches e baseada em tabela

A correção exigia uma rotina de colisão de custo fixo para que o overscan
contado por WSYNC (cuja contagem depende apenas da posição da primeira
escrita) seja exato. O emulador (e, importante, o timing do hardware real)
não pode aplicar uma máscara dinâmica com `AND` (só há `AND #imm`, e código
automodificável quebraria a proteção de escrita da ROM no emulador), então a
atualização de `m_active` é feita como uma única busca em tabela indexada em
vez de `AND #mask`. O índice empacota os bits do mask ativo atual (bits
0-1) e as duas flags de acerto (bits 2-3). Uma variante com branches
padded foi rejeitada: os quatro custos de caminho (34/49/51/66) diferem por
números ímpares, então `NOP`s não conseguem equalizá-los sem distorcer a
lógica.

### Matemática de alinhamento do overscan (verificada no emulador)

A partir do último WSYNC do kernel: epílogo 30 + JSR 6 + corpo de colisão 84
+ RTS 6 + `LDX` 2 + primeira escrita de WSYNC 3 = ciclo 131 da região. Isso
cai dentro do scanline 2 (76 < 131 <= 152), então `OVERSCAN_LOOP_COUNT = 8`
cobre as linhas 2..9 (152..684) e o `JMP` + preâmbulo de VSYNC alinham o
primeiro WSYNC de VSYNC do próximo quadro em exatamente 760. Qualquer corpo
fixo em (21, 97] ciclos é seguro para esta contagem.

## Abordagens rejeitadas

* Redução do VBLANK (ler `SWCHA` uma vez em vez de quatro vezes economiza
  12 ciclos/quadro) deixava apenas ~1 ciclo de folga no quadro mais pesado -
  frágil demais.
* Varredura do valor do timer de overscan (9..14): nenhum valor produz 262
  uniformes com trabalho de colisão de custo variável.
* Código automodificável para aplicar a máscara de desativação: bloqueado
  pela proteção de escrita da ROM no emulador.
* Versão com branches padded: os custos dos caminhos diferem por quantidades
  ímpares, impossível de equalizar com `NOP`s.

## Impacto de Timing

Antes (colisão no VBLANK, versão com branches):
- Quadro: 262 scanlines com ~1% dos quadros de estresse máximo escorregando
  para 263
- Overscan: espera `TIM64T = 11`, trabalho pré-timer variável (34..66
  ciclos)
- VBLANK: a passagem de colisão empurrava o trabalho até a fronteira da
  espera do timer

Depois (overscan fixo, colisão sem branches):
- Quadro: 262 scanlines (19912 ciclos) uniformemente em 600+ quadros de
  estresse máximo
- Overscan: 8 escritas de WSYNC + passagem de colisão fixa de 84 ciclos,
  exatamente 760 ciclos
- VBLANK: colisão removida; a espera do timer segura a região em 57 linhas
  com folga

## Impacto de Memória

Antes:
- ROM: 1296 (métrica); 1049 bytes honestos de código vs a baseline de
  origin/main
- RAM: 48

Depois:
- ROM: 1296 (métrica, inalterada - o `ALIGN 256` antes de `fineAdjustBegin`
  absorve o crescimento); 1127 bytes honestos de código (+78)
- RAM: 49 (+1: `hit_flags`)

## Testes

* `tests/test_collision.py`: 22 testes (M0->P1, M1->P0, próprio jogador
  ignorado, acertos simultâneos, persistência de latch, disparo
  one-shot atravessando um acerto) - PASS.
* `tests/test_frame_timing.py`: novo teste de regressão de quadro em
  estresse máximo (80 quadros com exatamente 19912 ciclos) - PASS.
* Suíte completa: 166 testes - PASS. Benchmark: ROM 1296 / RAM 49 / pior
  caso do kernel 65 de 76 (folga 11). Regressão vs origin/main: apenas RAM
  +1 byte, sem warnings, PASS.

## Limitações conhecidas

* O emulador não modela as penalidades de crossing de página do 6502, então
  o `ALIGN 16` em `newActiveTbl` é uma garantia só para o hardware (o
  emulador aceitaria uma tabela que cruza página; o silício real adicionaria
  um ciclo e quebraria o custo fixo).
* `hit_flags` é observável, mas nenhum HP/dano/pontuação usa isso ainda.
* As constantes `M0_HIT_P1` / `M1_HIT_P0` continuam em `constants.inc` como
  documentação de hardware, mas não são mais referenciadas pela rotina sem
  branches.
* O timer do VBLANK (69) agora é efetivamente um fallback: o trabalho do
  VBLANK não chega mais perto da expiração porque a colisão saiu de lá.
* `docs/benchmarks/baseline.json` ainda carrega o campo histórico
  `overscan_timer: 37` (informativo apenas; a ferramenta de regressão só
  compara ROM/RAM/kernel/scanlines).

## Próximos passos lógicos

* Colisão da bola com jogadores / com mísseis (a bola atualmente atravessa
  tudo).
* Usar `hit_flags` para HP, pontuação ou uma transição de rodada/fim de
  jogo.
* Uma medição da carga de trabalho do VBLANK para que futuras adições ao
  VBLANK fiquem dentro da janela do timer por construção.