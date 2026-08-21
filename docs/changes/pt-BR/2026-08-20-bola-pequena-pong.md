# Mudança: Bola Estilo Pong Pequena

## Objetivo

Substituir a bola 4x4 por uma bola pequena 2x2 inspirada nos jogos clássicos
do Atari 2600 (Pong, Video Olympics). A abordagem de orb arredondada explorada
na branch `round-8-rounded-ball` mostrou que produzir um shape diamante
(2-4-4-2) exigia complexidade e custo de timing desproporcionais (mudanças
CTRLPF por scanline, mini-loop, penalidade de 16 ciclos no kernel). A solução
de produção final é uma bola pequena de largura fixa.

## Adicionado

- Nada.

## Modificado

- `BALL_WIDTH`: 4 → 2 (2 color clocks de largura)
- `BALL_HEIGHT`: 4 → 2 (2 scanlines de altura)
- `BALL_SIZE_CTRLPF`: `%00100000` (4 clocks) → `%00010000` (2 clocks)
- `BALL_X_MAX`: 156 → 158 (160 - BALL_WIDTH)
- `BALL_Y_MAX`: 181 → 183 (KERNEL_SCANLINES - BALL_HEIGHT)
- Modelo Python em `test_events.py`: `scene()` agora lê `BALL_HEIGHT` da
  tabela de símbolos do ROM em vez de hardcoded 4.
- Linhas esperadas atualizadas em 6 testes para corresponder à nova
  posição OFF da bola de 2 linhas.
- `test_ball.py`: `test_ball_is_small_2_by_2`, testes de bounce usam
  `BALL_X_MAX` em vez de 156 hardcoded.

## Removido

- Nada.

## Raciocínio Técnico

A bola é um objeto Ball do TIA. Sua largura é definida por CTRLPF D5:D4:
  - `%00` = 1 clock
  - `%01` = 2 clocks  ← escolhido
  - `%10` = 4 clocks  ← anterior
  - `%11` = 8 clocks

Uma bola 2x2 (2 color clocks × 2 scanlines) é o menor tamanho que
permanece claramente visível como um ponto intencional e não como um
artefacto subpixel. A altura de 2 scanlines garante sobreposição vertical
entre frames consecutivos em movimento de 1 px/frame, evitando efeitos
estroboscópicos.

A bola continua parte normal da tabela de eventos (ON em ball_y,
OFF em ball_y+2). Sem mini-loop, sem CTRLPF por scanline, sem caminho
especial no kernel. Isso mantém o kernel table-direct totalmente intacto.

## Impacto de Timing

Antes (bola 4x4):
- Frame: 262 scanlines
- Kernel pior caso: 54/76 ciclos
- Kernel slack: 22

Depois (bola 2x2):
- Frame: 262 scanlines
- Kernel pior caso: 54/76 ciclos
- Kernel slack: 22

Sem mudança de timing: a bola usa o mesmo mecanismo baseado em eventos;
apenas as constantes CTRLPF diferem.

## Impacto de Memória

Antes:
- ROM: 1808 bytes
- RAM: 81 bytes

Depois:
- ROM: 1808 bytes
- RAM: 81 bytes

Sem mudança no uso de ROM ou RAM.

## Testes

- `test_ball_is_small_2_by_2`: valida WIDTH=2, HEIGHT=2, CTRLPF=$10
- `test_ball_bounds_within_visible_area`: valida BALL_X_MAX=158
- `test_bounces_at_right_edge`: usa BALL_X_MAX em vez de 156
- `test_bounce_at_bottom_right_corner`: usa BALL_X_MAX em vez de 156
- `test_ball_events_are_height_apart`: valida HEIGHT=2
- `test_sorted_emission_preserves_rows`: lista de linhas atualizada
- `test_events_fire_on_their_rows`: lista de linhas atualizada
- `test_same_row_events_merge`: lista de linhas atualizada
- `test_non_ball_merge_keeps_scan_order`: lista de linhas atualizada
- `test_dead_player_and_inactive_missiles_contribute_nothing`: atualizado
- `test_ball_on_floor_drops_off_event`: atualizado (OFF em 183 agora mantido)
- Todos os 261 testes passam.

## Limitações Conhecidas

- A bola 2x2 tem uma área de colisão menor que a bola 4x4.
  Isso é esperado e aceitável — colisão TIA é baseada em pixels.

## Próximos Passos Lógicos

- Validação visual no Stella (comparação 2x2 vs 2x3)
- Ajuste de gameplay se a bola menor parecer difícil de acertar
