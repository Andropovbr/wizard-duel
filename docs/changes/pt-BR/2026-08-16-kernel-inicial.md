# Mudança: Kernel inicial e movimento dos jogadores (Rodada 1)

## Objetivo

Entregar a base técnica mínima do Wizard Duel: um quadro NTSC estável de
262 scanlines, dois jogadores TIA visíveis simultaneamente e movimento
apenas vertical controlado pelos dois joysticks, junto com um setup
reproduzível de build/testes/CI/documentação.

## Adicionado

* `src/main.asm` - o programa completo: Reset/inicialização, o loop de um
  quadro (VSYNC + VBLANK + kernel de 192 linhas + OVERSCAN), leitura e
  movimento de joystick, posicionamento RESP/HMP, tabelas de sprite e
  vetores.
* `src/constants.inc` - todos os endereços de TIA/RIOT e constantes de
  compilação (estrutura do quadro, valores do timer, geometria dos
  jogadores, máscaras de joystick).
* `tools/` - ferramentas Python multiplataforma:
  * `build.py` monta com DASM e reporta o uso de ROM;
  * `test.py` executa a suíte de validação determinística;
  * `run.py` inicia o Stella;
  * `benchmark.py` mede métricas e persiste o histórico;
  * `common.py` utilitários compartilhados e verificação de dependências.
* `tests/` - suíte determinística (formato da ROM, vetores, símbolos,
  endereços, alinhamento de página, uso de memória, orçamento de ciclos do
  kernel, pares de documentação EN/PT-BR).
* `docs/en` e `docs/pt-BR` - documentação de arquitetura, mapa de memória,
  timing e build; `docs/benchmarks/` histórico.
* `README.md` e o pipeline do GitHub Actions.

## Alterado

* Corrigidas as constantes de endereço do RIOT em `constants.inc`. Os
  registradores de I/O são `SWCHA=$0280`, `SWACNT=$0281`, `SWCHB=$0282`,
  `SWBCNT=$0283`. Eles estavam rotulados incorretamente (`SWCHA=$0281`,
  etc.), o que fazia `LDA SWCHA` ler `SWACNT` (um registrador de direção de
  dados que retorna 0). Todos os bits de direção pareciam "pressionados" e
  o movimento não produzia resultado visível. Corrigido, remontado e
  revalidado de ponta a ponta no depurador do Stella.

## Racional técnico

* **Ajuste do timer**: ingenuamente `TIM64T = valor` dura `valor * 64`
  ciclos, mas o M6532 inicia `mySubTimer` em `myDivider - 1` e dá a volta
  em `(valor + 1) * 64`. O timer roda um pouco mais curto. Valores de 44
  (VBLANK) e 37 (OVERSCAN) foram escolhidos para que cada espera expire na
  scanline final pretendida; quadro medido = 19912 ciclos = 262 scanlines.
* **Lógica no VBLANK**: decodificação de joystick e movimento são cheios de
  ramificações e dependem de dados; colocá-los no VBLANK mantém o kernel
  visível estável em uma scanline por iteração.
* **Custo fixo do kernel**: as tabelas de sprite ficam de modo que todos os
  12 índices de linha permaneçam numa única página; o `LDA` indexado nunca
  paga penalidade de passagem de página. Pior caso é 56 de 76 ciclos (20
  ciclos de folga).
* **`fineAdjustBegin` alinhado a página**: `PosObject` indexa a tabela HMP
  com um resto em complemento de dois; a passagem de página forçada mantém a
  escrita `RESPx` no ciclo exato exigido pelo contrato de tempo do
  posicionamento.

## Impacto de timing

Antes:
- Scanlines do quadro: 260 (timer de VBLANK mais curto); medido 19760
  ciclos.
- Pior caso do kernel: documentado 61/76 (recontado como 58 com penalidade
  de página de 4 ciclos que na prática não ocorre).

Depois:
- Scanlines do quadro: exatamente 262; medido 19912 ciclos em quadros
  consecutivos (delta 19912, 19912 via `print _cyclesLo`).
- Pior caso do kernel: 56/76 ciclos (verificado do listing pela suíte de
  testes); melhor caso 44; caminho com um desenhado 50.

## Impacto de memória

Antes: n/a (primeiro build).
Depois:
- ROM: 528 bytes usados de 4096 (12,9%).
- RAM: 3 bytes usados de 128 (P0Y, P1Y, joystate).

## Testes

* Suíte determinística: 37 testes cobrindo build/formato da ROM, `-rominfo`
  do Stella, vetores, símbolos, alinhamento de página, uso de memória,
  percorredor de ciclos do kernel e somas das regiões do quadro - todos
  PASS.
* Validação em runtime no depurador do Stella 6.6 (documentada, não no CI):
  * comprimento do quadro 262 scanlines via deltas de ciclos em
    `StartOfFrame`;
  * ambos os jogadores visíveis simultaneamente (P0 vermelho à esquerda,
    P1 azul à direita, via análise de pixels de screenshot);
  * movimento com entrada real de `SWCHA`: `joy0Up 0` + `joy1Down 0` moveu
    P0 48->47 e P1 128->129 e continuou entre quadros; direções inversas
    moveram de volta;
  * comportamento de limite (clamp) verificado definindo posições 1/178 e
    confirmando 0/179 sem wrap.

## Limitações conhecidas

* As verificações de runtime de comprimento do quadro/movimento exigem o
  depurador gráfico do Stella, que não é automatizado no CI. O CI depende da
  validação estática determinística; a lacuna está documentada nos docs de
  build/timing.
* Movimento de 1 pixel por quadro (sem suporte diagonal ou horizontal
  ainda).
* Apenas 3 variáveis na RAM; 125 bytes livres para rodadas futuras.

## Próximos passos lógicos

* Adicionar estado de jogo além das posições (ex.: magia, projéteis) sem
  tocar no timing do kernel.
* Estender regras de movimento ou adicionar detecção de colisão no
  VBLANK/overscan.
* Opcionalmente adicionar verificação headless de comprimento do quadro se
  o Stella expor um driver/CLI estável para o CI.