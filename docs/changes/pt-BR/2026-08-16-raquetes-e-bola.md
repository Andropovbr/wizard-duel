# Mudança: Raquetes e bola (Rodada 2)

Data: 2026-08-16
Branch: `round-2-ball-paddles`
Commit: `08994a9`

## Objetivo

Evoluir a base técnica da Rodada 1 para uma forma reconhecível de jogo:
substituir o visual de sprite de linha única por raquetes verticais sólidas
e adicionar um objeto Ball do TIA que se move continuamente e quica nas
quatro bordas da área de jogo. Ainda sem colisões, placar, power-ups ou
interação bola/jogador.

## Adicionado

* `src/main.asm`:
  * `UpdateBall` (montado em `$F103`): move a bola um pixel por quadro nos
    dois eixos e inverte uma direção quando a bola atinge uma borda exata da
    arena, *antes* de se mover, de modo que a posição fica sempre limitada e
    nunca pode dar a volta por underflow de unsigned.
  * `PositionBall` (montado em `$F149`): posicionamento horizontal da bola
    com `RESBL` + `HMBL`, reutilizando a rotina compartilhada `PosObject`.
  * O bloco de habilitação da bola no kernel: cada linha do kernel compara o
    índice da linha com `ball_y` e escreve `ENABL` (o valor de habilitação
    na linha da bola, `0` em todas as outras).
  * `P0Sprite`/`P1Sprite` substituídos por retângulos sólidos de 12 bytes de
    `%00111100` (raquetes de 4 pixels de largura).
  * `Reset` inicializa o estado da bola (`ball_x`, `ball_y`, `ball_dx`,
    `ball_dy`) e o hardware da bola (`CTRLPF` para o tamanho de 4 pixels,
    `COLUPF` para a cor).
* `src/constants.inc`: `BALL_WIDTH`, `BALL_SIZE_CTRLPF`,
  `BALL_X_MIN/MAX`, `BALL_Y_MIN/MAX`, `BALL_X_INIT`, `BALL_Y_INIT`,
  `BALL_COLOR`, `BALL_ENABLE`, `DIR_LEFT/RIGHT/UP/DOWN`.
* `tests/test_ball.py`: um pequeno interpretador 6502 determinístico
  (`Mini6502`) executa os bytes reais de `UpdateBall` da ROM montada; os
  testes cobrem movimento diagonal, quiques nas quatro bordas, quique de
  canto, invariante de limites ao longo de 2000 quadros, estado inicial,
  uso de RAM (7 bytes), escritas de `ENABL` no kernel nos dois caminhos e
  confinamento de página do kernel.
* Variáveis de RAM `ball_x` (`$83`), `ball_y` (`$84`), `ball_dx` (`$85`),
  `ball_dy` (`$86`).

## Alterado

* `tools/test_timing.py`: o percorredor de ciclos do kernel agora modela o
  bloco da bola (`BNE` para frente + `JMP`), então todos os oito caminhos de
  jogador x bola são medidos; `read_constants()` foi corrigido para resolver
  `$hex`, `%binary` e expressões `+/-` (antes, constantes hex eram
  silenciosamente ignoradas e expressões eram analisadas pelo primeiro
  token).
* `tools/benchmark.py`: `measure()` roda o simulador do kernel nas
  configurações todos-desenhados/bola-ligada e todos-vazios/bola-desligada.
* `tests/test_timing.py`: pior caso atualizado para 71/76, melhor caso 57,
  além de um teste que enumera as oito combinações contra o orçamento.
* `tests/test_memory.py`: a expectativa de RAM da Rodada 2 é 7 bytes.
* `tests/test_rom.py`: os símbolos exigidos agora incluem `UpdateBall`,
  `PositionBall` e as variáveis de RAM da bola; adicionado um teste de forma
  do retângulo da raquete.
* `tests/test_regression.py`: a verificação de kernel slack foi atualizada
  para 5 (o baseline permanece na Rodada 1).
* `docs/en/` e `docs/pt-BR/` (arquitetura, mapa de memória, timing, build,
  benchmarks) e `README.md` atualizados para as raquetes, a bola e as novas
  medições; `docs/benchmarks/latest.md` e `history.csv` regenerados pelo
  benchmark.

## Racional técnico

* **A bola tem 1 scanline de altura**: o Ball do TIA é um objeto de 1 pixel
  de altura; ele é desenhado registrando (latch) `ENABL` na scanline que
  coincide com `ball_y`. Como `ENABL` é registrado para a scanline
  *seguinte*, o kernel precisa reescrevê-lo a cada linha: o valor de
  habilitação na linha da bola e `0` em todas as outras, senão a bola ficaria
  presa na tela. O teste de linha é um simples `CMP ball_y` + `BNE`, custando
  15 ciclos na linha da bola e 13 nas demais.
* **Quique antes de mover**: checar a borda *antes* do movimento garante que
  a posição armazenada permaneça dentro de `[MIN, MAX]`. Mover primeiro e
  limitar depois se comportaria de forma idêntica nas bordas, mas adiciona um
  movimento redundante; inverter primeiro é também o que torna o
  comportamento "inverter e afastar" exato em vez de dar a volta por `$FF`.
* **`PositionBall` passa `ball_x + 1`**: o TIA atrasa os gráficos dos
  jogadores em um color clock extra, então o mesmo valor de `RESP` coloca a
  bola um pixel à esquerda de onde um jogador renderizaria. A compensação +1
  mantém a bola na tela no `ball_x` pedido.
* **Cor/tamanho da bola vêm de registradores compartilhados do TIA**: a bola
  é colorida por `COLUPF` e dimensionada por `CTRLPF` D5:D4 (`%10` = 4
  pixels). Nesta rodada eles são definidos uma vez no reset; nada mais no
  kernel escreve no playfield, então não há conflito.
* **O código novo cabe no padding de página**: o código da bola e os sprites
  das raquetes cabem no espaço de preenchimento reservado antes do
  `fineAdjustBegin` alinhado a página; o uso de ROM permanece em 528 bytes.
* **Testes com interpretador substituem a sondagem em runtime para a bola**:
  o movimento da bola é totalmente determinístico (velocidade fixa, quiques
  de borda), então executar o `UpdateBall` montado em um pequeno
  interpretador 6502 é uma verificação mais forte e segura para o CI do que
  análise de screenshots. O Stella permanece como referência para o
  posicionamento visual.

## Impacto de timing

Antes (Rodada 1):
- Scanlines do quadro: 262
- Pior/melhor caso do kernel: 56 / 44 ciclos (folga 20)

Depois (Rodada 2):
- Scanlines do quadro: 262 (inalterado)
- Pior caso do kernel: 71 / 76 ciclos (ambas as raquetes desenhadas + bola
  na linha), folga **5**
- Melhor caso do kernel: 57 ciclos (ambas as raquetes vazias + bola apagada)
- Bloco da bola: 15 ciclos na linha da bola, 13 nas demais; todas as oito
  combinações são enumeradas e verificadas pela suíte de testes.
- `GRP0` ~ciclo 24, `GRP1` ~ciclo 47, `ENABL` ~ciclo 63 de cada scanline.

A folga caiu de 20 para 5 ciclos. Este é o custo deliberado de adicionar um
objeto de hardware ao kernel visível; foi verificado no Stella que a bola
renderiza com exatamente 1 scanline de altura e se move suavemente.

## Impacto de memória

Antes (Rodada 1):
- ROM: 528 bytes
- RAM: 3 bytes

Depois (Rodada 2):
- ROM: 528 bytes (código da bola + raquetes cabem no padding de página
  reservado)
- RAM: 7 bytes (+4: `ball_x`, `ball_y`, `ball_dx`, `ball_dy`)

## Resultado da regressão

Executada contra o baseline persistido da Rodada 1:
- Pior caso do kernel 56 -> 71 (+15) e folga 20 -> 5 (-15): dois avisos
  **soft** (limites +4 / -4), o CI continua PASS (código de saída 0).
- RAM 3 -> 7 (+4): igual ao limite de aviso, então sem aviso de RAM.
- ROM inalterada: sem aviso.

## Testes

* Adicionado `tests/test_ball.py` (testes de movimento/quique/limites via
  interpretador).
* Alterados `tests/test_timing.py`, `tests/test_memory.py`,
  `tests/test_rom.py`, `tests/test_regression.py`, `tools/test_timing.py`,
  `tools/benchmark.py`.
* Suíte completa: 93 testes, todos PASS; portões de qualidade ROM 528/4096 e
  RAM 7/128 PASS; benchmark e regressão executados localmente.
* Validação em runtime no Stella 6.6 (documentada, não no CI):
  * as raquetes vermelha (P0) e azul (P1) renderizam à esquerda/direita;
  * ambos os joysticks movem suas raquetes (P0 pelas setas, P1 pelas teclas
    do teclado) com limite correto em 0/179;
  * a bola se move diagonalmente, oscila entre perto do topo/perto da base e
    atinge os dois extremos horizontais, quicando nos dois eixos; os quiques
    exatos de borda são comprovados pelos testes do interpretador.

## Limitações conhecidas

* Ainda não há colisão entre bola e raquetes; a bola atravessa as raquetes.
  Isso é intencional nesta rodada.
* A velocidade da bola é fixa em 1 px/quadro; sem aceleração ou influência
  do jogador.
* As opções `-holdjoy*` do Stella são pouco confiáveis (soltam após ~0,8 s);
  a entrada automatizada de joystick usou `xdotool keydown` no lugar.
* O console do depurador do Stella não pode ser capturado em sessão headless
  (sem stdout do depurador, `saveSes` não produziu arquivo legível e
  snapshots em modo depurador saem pretos); a validação em runtime usou
  análise de pixels de capturas da janela ao vivo.
* O kernel slack agora é de 5 ciclos: trabalho futuro no kernel tem pouca
  margem e deve ser validado com cuidado.

## Próximos passos lógicos

* Adicionar colisão bola/raquete (o TIA fornece latches de colisão
  `CXBLPF`/`CXP0FB`/`CXP1FB` legíveis no VBLANK).
* Mover quantidades de gameplay (velocidade da bola, tamanho da raquete)
  para RAM ou constantes que rodadas futuras possam variar.
* Considerar um segundo objeto Ball ou um missile se o gameplay precisar.