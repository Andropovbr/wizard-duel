# Mudança: Ordem de escrita da bola (deslocamento vertical de 1 scanline)

## Objetivo

Corrigir um artefato visual relatado em `round-5-basic-hp`: a Bola apresenta
um pequeno deslocamento vertical (cerca de um scanline) em certos scanlines.
O deslocamento não é um estiramento na base nem tremor de quadro. Corrigir
apenas no branch atual (sem novo branch, sem merge para `main`), sem novo
gameplay: a Bola deve manter altura constante (`BALL_HEIGHT = 4`) em toda
posição X e independentemente de quais outros objetos compartilham suas
linhas.

## Sintoma

* A Bola aparece deslocada um scanline para baixo em certas linhas, na
  maioria das vezes no lado esquerdo da arena (relatado em torno de
  `ball_x` 15..27).
* O deslocamento aparece e desaparece conforme a bola se move e afeta apenas
  a bola (nos casos relatados, a bola compartilhava linha com P0 em x=16).

## Reprodução

Os quadros relatados foram reproduzidos com uma varredura baseada em modelo
sobre a semântica real do construtor de eventos do ROM: todas as 16.956
combinações de `ball_x` (0..156) x cenário (bola sozinha; +P0; +P1; +M0; +M1;
+M0+M1; linhas compartilhadas forçadas para ON/OFF da bola). Uma simulação de
jogo em 2.000 quadros confirmou a frequência: a bola ocupa a **segunda
escrita** de uma linha compartilhada em 88 quadros (4,4%), em valores de
`ball_x` abaixo e acima de 63.

A instrumentação do emulador determinístico forneceu os ciclos exatos de
escrita dentro de um scanline de evento:

| Slot de escrita   | Ciclo final | Limite do modelo de feixe |
| ----------------- | ----------- | ------------------------- |
| Primeira (dupla)  | 30          | x >= 21                   |
| Segunda (dupla)   | 44          | x >= 63                   |
| Única             | 33          | x >= 30                   |

## Causa raiz

Uma entrada dupla dispara duas escritas no mesmo scanline, mas em momentos
diferentes: a primeira cai no ciclo 30 da CPU e a segunda no ciclo 44. Uma
escrita no TIA só se aplica ao scanline atual se terminar antes de o feixe
passar pela posição X do objeto; caso contrário, aplica-se um scanline
depois. A segunda escrita fica ~42-49 pixels atrás da primeira, então um
objeto no segundo slot fica exposto sempre que seu X está abaixo do limite da
segunda escrita (x < 63 no modelo de feixe documentado).

Antes do Round 8, um merge na mesma linha mantinha a ordem de geração: o
evento existente virava a primeira escrita e o novo evento a segunda.
`BuildEvents` gera eventos na ordem P0, P1, Bola, M0, M1, portanto um evento
da bola que se fundia a uma única entrada de jogador ou míssil era sempre
escrito em **segundo**. Como o X da bola cobre toda a arena (0..156), sempre
que a bola compartilhava uma linha e ficava à esquerda do limite da segunda
escrita, seu ON/OFF disparava um scanline atrasado, deslocando toda a bola
uma linha para baixo (a altura permanecia 4; a posição mudava).

## Avaliação de políticas (abordagens rejeitadas)

Uma comparação quantitativa de três políticas de escalonamento foi executada
sobre a mesma varredura de 16.956 combinações:

| Política | Falhas da bola (de 16956) | Observações |
| -------- | ------------------------- | ----------- |
| Ordem de inserção (pré-fix) | 4957 | a bola ocupa o segundo slot nas linhas compartilhadas |
| Ordenação por deadline de X | 4429 | a ordenação pura por deadline não corrige o relato: P0 (x=16) está sempre à esquerda da bola para `ball_x > 16`, então a bola ainda ficaria em segundo nas linhas compartilhadas com P0 |
| Bola primeiro (adotada) | 2890 | mudanças de altura quase eliminadas; as falhas residuais são a faixa `x < 30` da bola sozinha e o co-objeto ocupando o segundo slot |

A ordenação pura por deadline foi rejeitada porque não corrige os quadros
relatados de colisão com P0 sem uma reestruturação completa do kernel, a um
custo real de ROM. "Bola primeiro" dá à bola a escrita mais cedo (ciclo 30)
em toda dupla; a única outra escrita possível é uma única (ciclo 33), então
seu pior caso cai do limite da segunda escrita (63) para os limites da
primeira/única (21/30).

## Correção

`InsertEvent` (`.mergeSingle`, src/main.asm) agora troca o evento de bola
fundido para a **primeira** escrita: após gravar reg2/val2 (o novo evento) e
reg1/val1 (a entrada única existente), se o novo registro for `EV_REG_ENABL`
os dois pares (reg, val) são trocados, com a flag de única removida do
registro que vira reg2. A troca é segura por construção: reg1 de um merge
nunca pode já ser ENABL (um merge só acontece em uma entrada única, e
`ball_y != ball_y + 4`). O co-objeto então ocupa a segunda escrita.

## Adicionado

* `tests/test_event_collision.py` - `TestBallWriteSlotInvariant` (3 testes)
  dirigindo o `BuildEvents` REAL do ROM em todas as colisões forçadas de
  linha bola/jogador e bola/míssil, além de uma varredura da bola por toda a
  arena, afirmando que nenhuma entrada dupla carrega ENABL no segundo slot e
  que toda tabela permanece livre de delta-0.
* `tests/test_events.py` - `TestBallBeamModel` (2 testes): uma regressão de
  modelo de feixe (modelo de feixe documentado + ciclos de escrita medidos)
  afirmando que ENABL nunca ocupa o segundo slot em toda a matriz de cenários
  e que a altura renderizada da bola é exatamente `BALL_HEIGHT` para todo
  `x >= 30` (acima do limite de escrita única), independentemente de quais
  objetos compartilham suas linhas.
* `tests/test_events.py` - `test_non_ball_merge_keeps_generation_order`
  (garante que apenas a bola é ordenada em reg1).

## Alterado

* `src/main.asm`, `InsertEvent` `.mergeSingle`: troca bola-primeiro (+~40
  bytes) e comentários atualizados. Os comentários de `BuildEvents` e do
  kernel documentam a nova regra de slot de escrita.
* `tests/test_events.py`: o modelo Python `insert()` implementa a mesma
  troca; `test_same_row_events_merge` agora afirma que Ball ON é a primeira
  escrita e P1 ON a segunda.
* `docs/en/architecture.md` e `docs/pt-BR/arquitetura.md`: seção Round 8
  sobre a ordem de escrita da bola.
* `docs/en/timing.md` e `docs/pt-BR/timing.md`: tabela de tempo de escrita
  corrigida (o texto anterior afirmava primeira/segunda escritas durante os
  ciclos 30..33 / 44..47 com limites x>=30/x>=72 e dizia que P0 em x=16
  estava "bem fora" dessas faixas, o que contradiz x>=30). Os valores
  corrigidos, medidos no emulador, são única=33 (limite 30), primeira=30
  (limite 21), segunda=44 (limite 63), com o conservadorismo do modelo
  anotado (P0 em x=16 renderiza corretamente no Round 3 com escritas únicas
  no ciclo 33, abaixo do limite x>=30 do modelo).

## Justificativa técnica

O limite da segunda escrita (63) é a maior exposição no conjunto de objetos,
e a bola é o único objeto cujo X pode alcançá-lo. Dar a ENABL a primeira
escrita reduz o pior caso da bola de 63 para 21 (primeiro slot) ou 30
(escrita única), os menores valores que a estrutura atual do kernel pode
produzir. A troca roda em VBLANK (InsertEvent), então o kernel visível não é
tocado e seu orçamento de ciclos não muda. O co-objeto que herda o segundo
slot é P0 nos quadros relatados (P1 é fixo em x=136, acima do limite da
segunda escrita); sua borda se desloca nessas raras linhas compartilhadas no
modelo documentado, trocando um pequeno artefato localizado de raquete pelo
deslocamento relatado de toda a bola. A correção definitiva (escritas cedo o
suficiente para todo X, incluindo as posições mais à esquerda da bola)
exigiria reestruturar o slot de escrita do kernel, fora do escopo deste
round.

## Impacto de tempo

Antes:
- Scanlines por quadro: 262
- Trabalho pior de VBLANK: 4485 ciclos, margem ~379
- Caminho pior do kernel: 65/76 ciclos, folga 11

Depois:
- Scanlines por quadro: exatamente 262 (todos os quadros de teste)
- Trabalho pior de VBLANK: 4486 ciclos (+1, o branch extra da troca no
  caminho de merge), margem ~378 (ainda bem dentro da expiração T=77 ~4864)
- Caminho pior do kernel: 65/76 ciclos, folga 11 (kernel intocado)

## Impacto de memória

Antes:
- ROM: 1296 bytes
- RAM: 51 bytes

Depois:
- ROM: 1552 bytes (+256: ~40 bytes de código de troca mais ~216 bytes de
  preenchimento de alinhamento de página exigido - o código de construção de
  eventos agora cruza o limite `$F500`, então o `ALIGN 256` antes da tabela
  de ajuste fino preenche uma página inteira; o alinhamento é um requisito
  deliberado de tempo, veja PosObject)
- RAM: 51 bytes (sem mudança)

## Testes

Adicionados: 5 testes (3 de slot de escrita no ROM, 2 de modelo de feixe),
1 teste atualizado (`test_same_row_events_merge`), 1 adicionado
(`test_non_ball_merge_keeps_generation_order`).
Executados: `python tools/test.py` - 207 testes, todos PASS. Gates de
qualidade (ROM <= 4096, RAM <= 128) PASS. `python tools/benchmark.py` PASS
(262 scanlines, kernel 65/76 folga 11, margem VBLANK 378). `python
tools/regression.py` PASS com um aviso (ROM +256 B vs origin/main,
preenchimento de alinhamento esperado). Todos os novos testes foram
verificados como FAIL contra o ROM pré-fix (3 falhas) antes da correção.

## Limitações conhecidas

* No modelo de feixe documentado (conservador), a escrita única da bola
  sozinha ainda se desloca para `ball_x < 30` e o primeiro slot para
  `ball_x < 21`. O modelo é ~14 pixels conservador (P0 do Round 3 em x=16
  renderiza corretamente com escritas únicas no ciclo 33), então a faixa
  residual real é provavelmente muito menor; ela não pode ser reduzida neste
  ambiente porque não há ferramenta de screenshot em nível de pixel
  (snapshots do Stella não disparam em modo headless e o depurador é apenas
  GUI). Etapas de verificação manual no Stella estão documentadas no
  relatório final.
* O co-objeto que herda o segundo slot fica exposto para `x < 63` no modelo;
  P0 (x=16) é o único membro de X fixo abaixo desse limite, então linhas
  compartilhadas raras deslocam a borda de uma raquete em vez da bola.

## Próximos passos lógicos

* Verificar por pixel as faixas residuais no depurador do Stella em uma
  sessão gráfica; se o limite real da segunda escrita for materialmente menor
  que 63, o residual do co-objeto pode ser inobservável.
* Se a faixa da bola sozinha na parede esquerda se mostrar visível em
  hardware, reestruturar o slot de escrita do kernel (escrever mais cedo por
  scanline) em vez de adicionar mais heurísticas ao construtor.