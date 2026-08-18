# Mudança: Projéteis básicos e kernel orientado a eventos

## Objetivo

Implementar a Rodada 3 "projéteis básicos" do Wizard Duel: cada jogador pode
disparar um míssil com o botão de fogo do joystick. Adicionar um segundo par
de objetos (os mísseis) tornou impossível o kernel de exibição sem desvios da
Rodada 2 (precisava de ~98 ciclos para dois jogadores, a bola e dois mísseis
contra o orçamento de 76 ciclos por scanline), então o kernel visível foi
redesenhado como um kernel orientado a eventos dirigido por uma tabela
reconstruída a cada quadro durante o VBLANK.

## Adicionado

* **Mísseis**: `UpdateMissiles` lê os botões de fogo (INPT4 para P0, INPT5
  para P1, bit 7 = 0 pressionado) e dispara um míssil na borda de subida do
  botão. Um míssil tem 2 px de largura (bits de tamanho de míssil do NUSIZ0/1)
  e 4 linhas de altura, nasce `MISSILE_SPAWN_OFFSET = 4` linhas abaixo do seu
  jogador, voa horizontalmente a `MISSILE_SPEED = 2` px/quadro e desaparece na
  borda da arena (M0 move-se para a direita a partir de x=18, M1 para a
  esquerda a partir de x=134). `fire_prev` guarda o estado do botão do quadro
  anterior para que segurar o botão não produza uma rajada de mísseis.
* **Kernel orientado a eventos**: o kernel visível não calcula mais enables
  de objetos. `BuildEvents` (VBLANK) escreve uma tabela (`evTbl`) de entradas
  de 5 bytes `[delta, reg1, val1, reg2, val2]`; o kernel conta até a próxima
  entrada e aplica suas duas escritas de registrador. A contagem regressiva
  de 192 linhas vive em RAM (`scanCnt`) para que o código de evento possa usar
  livremente `TAX` como índice de registrador.
* **Builder de eventos**: `AddEvent` anexa registros de 3 bytes `(linha, reg,
  val)`; `SortEvents` ordena por inserção um array de ordem de 1 byte
  (`evOrder`) por linha; `EmitEvents` percorre a ordem ordenada, mesclando no
  máximo dois registros da mesma linha em uma entrada e empurrando um terceiro
  registro patológico para linha+1 (`BubbleOrder` restaura a ordem). Uma
  entrada terminadora (`delta = $FF`) nunca pode disparar dentro do kernel de
  192 linhas.
* **Correção do BALL_ENABLE**: o valor de enable agora é `%00000010`. O TIA
  amostra apenas o bit 1 dos registradores de enable (verificado no
  código-fonte do Stella: `myEnam = value & 0x02`), então o `$FF` antigo era
  desnecessário.
* **Mudança de convenção da bola**: `ball_y` agora é a primeira linha de
  exibição (linhas `ball_y .. ball_y + 3`), `BALL_Y_MAX = 188`.

## Alterado

* Kernel de `src/main.asm` reescrito (orientado a eventos); os blocos de
  retângulo sem desvios e a cauda de enable da bola da Rodada 2 saíram.
* Estrutura do quadro: VBLANK 37 -> 57 linhas, OVERSCAN 30 -> 10 linhas
  (timers 43/37 -> 69/11) para dar espaço ao `BuildEvents` mantendo 262
  linhas.
* `tools/common.py` `ram_usage()` agora resolve tamanhos simbólicos de `DS`
  (ex.: `DS EV_TBL_SIZE`), que a RAM da Rodada 3 usa.
* `_resolve_constant` de `tests/test_timing.py` agora lida com `*` e sai em
  vez de recursar para sempre em expressões não resolvíveis.
* Testes atualizados para o novo kernel/constantes; um novo
  `tests/test_events.py` modela o builder de eventos (deltas, mesclagens,
  resolução de colisão).
* Documentação atualizada (EN + pt-BR).

## Raciocínio técnico

### Por que o kernel orientado a eventos

Com cinco objetos (2 jogadores + bola + 2 mísseis), o cálculo sem desvios de
enables por scanline precisa de ~98 ciclos > 76. O kernel de eventos converte
o trabalho por objeto em um build de tabela no VBLANK (onde há ciclos
disponíveis) e mantém o loop de exibição minúsculo: 18 ciclos em linha sem
evento e 69 em linha de evento de duas escritas (7 ciclos de folga).

### Por que a contagem regressiva em RAM

O código de evento do kernel usa `TAX` (índice de registrador para
`STA $1A,X`). Com um contador de linhas em X, isso corrompe o contador a cada
linha de evento, esticando o quadro (medido ~339 linhas). Mover a contagem de
192 linhas para RAM (`scanCnt`) mantém o quadro em exatamente 262 linhas.

### Por que a ordenação por array de ordem

O primeiro builder mantinha os registros ordenados no lugar (deslocamentos de
3 bytes), custando ~3,8k ciclos no pior caso, o que excedia a janela do VBLANK
junto com a outra lógica. Ordenar um array `evOrder` de 1 byte (deslocamentos
de 1 byte) mais um emit linear reduziu o builder para ~3,4k ciclos no pior
caso, cabendo na janela de `69 * 64 = 4416` ciclos com ~280 ciclos de folga.
Uma colisão de três objetos na mesma linha é empurrada para linha+1 para que
nenhuma scanline precise de mais de duas escritas.

### Por que o ajuste de timer/contagem de linhas

Os valores do timer foram ajustados empiricamente contra um emulador 6502
determinístico que modela paradas de WSYNC e o timer do RIOT. O quadro tem
exatamente 262 scanlines (19912 ciclos) e é estável em todos os estados
testados.

## Impacto de timing

Antes (Rodada 2):
- Scanlines do quadro: 262
- Pior caminho do kernel: 62 / 76 ciclos (sem desvios)

Depois (Rodada 3):
- Scanlines do quadro: 262 (estável, verificado em 30+ quadros no emulador)
- Pior caminho do kernel: 69 / 76 ciclos (linha de evento de duas escritas)
- Melhor caminho do kernel: 18 / 76 ciclos (linha sem evento)
- Folga: 7 ciclos na linha de evento

O kernel visível agora tem custo variável por linha (18 vs 69), mas cada
linha continua bem abaixo de 76 ciclos e a contagem total de linhas é fixa
pelo `scanCnt`.

## Impacto de memória

Antes (Rodada 2):
- ROM: 528 / 4096 bytes (12,9%)
- RAM: 7 / 128 bytes

Depois (Rodada 3):
- ROM: 1296 / 4096 bytes (31,6%)
- RAM: 121 / 128 bytes (94,5%)

A RAM cresceu bastante porque a tabela de eventos (55 bytes) e os buffers de
registros/ordem (40 bytes) são armazenamento de trabalho por quadro. Apenas 7
bytes permanecem livres; isso é legal, mas um ponto de pressão deliberado a
observar nas próximas rodadas.

## Testes

Adicionado `tests/test_events.py` (7 testes: deltas, linhas de disparo,
mesclagem, empurrão de colisão tripla, terminador, matemática por linha).
Atualizados `test_timing.py` (caminhador de ciclos do kernel de eventos),
`test_ball.py` (constantes da bola, RAM, estrutura do kernel), `test_rom.py`
(símbolos, escritas de registrador do kernel), `test_positioning.py`
(compensação dos mísseis), `test_memory.py` (RAM 121), `test_regression.py`
(métricas BASE). Todos os 111 testes passam.

## Limitações conhecidas

* RAM em 121/128 bytes; recursos futuros precisarão reutilizar ou recuperar o
  armazenamento de trabalho de eventos.
* A bola e os mísseis não interagem com os jogadores (sem colisões).
* Uma colisão de três objetos na mesma linha desloca um objeto um scanline
  naquele quadro (raro, documentado, determinístico).
* A validação de quadro em tempo de execução usa um emulador de
  desenvolvimento; o CI valida o quadro estaticamente.

## Próximos passos lógicos

* Colisões raquete/bola e míssil/jogador.
* Mover parte da lógica de jogo para o OVERSCAN se a pressão do VBLANK
  voltar.
* Recuperar RAM (ex.: compactar a tabela de eventos ou reutilizar o array de
  ordem).
