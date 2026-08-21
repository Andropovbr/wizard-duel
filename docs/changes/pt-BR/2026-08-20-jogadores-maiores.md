# Mudanca: Jogadores maiores (visual Round 7)

## Objetivo

Aumentar o tamanho visual de ambos os jogadores (P0 e P1) em aproximadamente
50% preservando timing, missiles, colisoes e todos os quality gates. Os
jogadores continuam sendo paddles retangulares simples; nao ha arte de
personagens.

## Dimensoes anteriores dos jogadores

* Altura: 12 scanlines (`PLAYER_HEIGHT = 12`)
* Largura: 4 pixels (`PADDLE_BITS = %00111100`)
* Intervalo vertical: 0..172 (`PLAYER_Y_MAX = KERNEL_SCANLINES - PLAYER_HEIGHT - 1`)
* Offset de spawn do missile: 4 linhas abaixo do topo do jogador

## Dimensoes novas dos jogadores

* Altura: 18 scanlines (`PLAYER_HEIGHT = 18`, +50%)
* Largura: 4 pixels (inalterada, `PADDLE_BITS = %00111100`)
* Intervalo vertical: 0..166 (`PLAYER_Y_MAX = 185 - 18 - 1`)
* Offset de spawn do missile: 7 linhas abaixo do topo do jogador (centralizado no paddle de 18 linhas)

## Tecnica escolhida

Aumento de altura via constante `PLAYER_HEIGHT` exclusivamente. Esta e a
abordagem mais segura porque:

1. `PLAYER_HEIGHT` e a unica fonte de verdade para a altura do paddle;
2. `PLAYER_Y_MAX` deriva automaticamente dele;
3. O construtor da tabela de eventos usa `PLAYER_HEIGHT` para calculo das
   linhas ON/OFF;
4. Nenhuma alteracao de codigo e necessaria - apenas o valor da constante muda.

A largura foi avaliada separadamente (ver analise NUSIZ abaixo) e
intencionalmente mantida em 4 pixels.

## Analise NUSIZ

Os registradores NUSIZ0/NUSIZ1 controlam tanto o tamanho do jogador quanto o
do missile:

```
Bits 5:4 do NUSIZ = tamanho do missile (00=1px, 01=2px, 10=4px, 11=8px)
Bits 3:1 do NUSIZ = tamanho do jogador (000=8x, 001=4x, 010=2x, 100=1x, 101=normal)
Bits 7,0 do NUSIZ = contagem de copias
```

Atualmente `NUSIZ0 = NUSIZ1 = %00010000` (missile 2px, jogador normal, 1
copia).

Definir os bits 3:1 como %101 dobraria a largura do jogador para 8 pixels
(aumento de 200%), o que e excessivo. Definir como %010 manteria o jogador
em largura 2x normal (ainda 4 pixels com PADDLE_BITS, sem mudanca visual).
Definir como %001 reduziria o jogador para metade (2 pixels).

Para atingir ~50% de aumento de largura (6 pixels), nenhuma configuracao
NUSIZ fornece o valor exato. A opcao mais proxima seria bits 3:1 = %101
(largura dupla = 8 pixels, +100%), o que e largo demais.

**Decisao: aumento de largura via NUSIZ e adiado.** O aumento apenas de
altura atinge a meta de ~50% de tamanho geral. Um round futuro pode explorar
jogadores mais largos atraves de uma combinacao de configuracao NUSIZ e padrao
PADDLE_BITS ajustado se necessario.

## Impacto nos missiles

`MISSILE_SPAWN_OFFSET` mudou de 4 para 7 para manter o missile spawnando no
centro vertical do paddle mais alto (18 linhas):

* Antes: spawn em player_y + 4 (centro do paddle de 12 linhas)
* Depois: spawn em player_y + 7 (centro do paddle de 18 linhas)

Tamanho, velocidade, trajetoria, comportamento de um-press-one-shot e
colisao do missile estao todos inalterados. O ajuste de spawn e minimo e
documentado.

## Impacto nas colisoes

Os latches de colisao do TIA sao baseados em pixels: um jogador maior
aumenta naturalmente a area de colisao. Este e o comportamento esperado:

* Ball x P0 / Ball x P1: area de sobreposicao maior, rebound inalterado
* M0 x P1 / M1 x P0: area de sobreposicao maior, dano de HP inalterado
* Nenhum bounding box em software necessario

A area de colisao maior pode causar contato da Ball por mais frames
consecutivos (o efeito "pianinho" documentado no Round 7). Isto e observado e
documentado, nao corrigido com debounce.

## Limites verticais

* `PLAYER_Y_MIN` = 0 (inalterado)
* `PLAYER_Y_MAX` = 166 (era 172)
* Jogadores permanecem completamente visiveis no topo e fundo da arena
* Posicoes iniciais (P0=48, P1=128) permanecem dentro dos limites

## Tabela de eventos

O jogador mais alto afeta:

* Linha ON do jogador: inalterada (player_y)
* Linha OFF do jogador: player_y + 18 (era player_y + 12)

O construtor da tabela de eventos ja lida com objetos de altura variavel via
a constante `PLAYER_HEIGHT`. O calculo de linhas ON/OFF em `BuildEvents` usa
`ADC #PLAYER_HEIGHT` que agora soma 18 em vez de 12.

Nenhuma nova coincidencia foi introduzida na tabela de eventos. A logica
existente de merge de mesma linha e bump lida com todos os casos corretamente
(verificado por 261 testes).

## Impacto no timing

Antes (baseline Round 7):
- Scanlines do frame: 262
- Kernel pior caso: 54 / 76 ciclos
- Slack do kernel: 22 ciclos
- Pior trabalho do VBLANK: 4528 ciclos
- Margem do VBLANK: 336 ciclos

Depois:
- Scanlines do frame: 262 (inalterado)
- Kernel pior caso: 54 / 76 ciclos (inalterado)
- Slack do kernel: 22 ciclos (inalterado)
- Pior trabalho do VBLANK: 4528 ciclos (inalterado)
- Margem do VBLANK: 336 ciclos (inalterado)

O timing e inalterado porque apenas constantes foram modificadas. Nenhum
caminho de codigo foi alterado.

## Impacto na memoria

Antes:
- ROM: 1808 bytes
- RAM: 81 bytes

Depois:
- ROM: 1808 bytes (inalterado - apenas constantes)
- RAM: 81 bytes (inalterado - nenhuma nova variavel)

## Testes

Executados: `python tools/test.py` - **261 testes, todos PASSARAM** (era 261).

Testes atualizados para refletir o novo PLAYER_HEIGHT = 18:

* `tests/test_timing.py` - `test_player_bounds_valid`: height 12 -> 18,
  PLAYER_Y_MAX 172 -> 166
* `tests/test_events.py` - funcao `scene()`: altura do jogador 12 -> 18 no
  dicionario objects
* `tests/test_events.py` - assertivas de linhas esperadas atualizadas para
  todos os testes onde linhas OFF do jogador mudaram (sorted emission,
  fire-on-rows, same-row merge, non-ball merge, ball-on-floor)
* `tests/test_rom.py` - constante `PLAYER_HEIGHT` 12 -> 18

Quality gates: ROM 1808 <= 4096, RAM 81 <= 128, frame 262 scanlines, kernel
54 <= 76. `python tools/benchmark.py` PASS. `python tools/regression.py`
PASS.

## Limitacoes conhecidas

* Largura permanece em 4 pixels. O registrador NUSIZ nao fornece uma opcao
  limpa de aumento de ~50% de largura; a mais proxima e largura dupla (8px,
  +100%). Um round futuro pode combinar NUSIZ com padrao PADDLE_BITS ajustado.
* O jogador mais alto aumenta a area de contato da Ball, o que pode causar
  mais frames de contato consecutivos (pianinho). Isto e documentado, nao
  corrigido com debounce.
* RAM 81 de 128; inalterado neste round.

## Proximos passos logicos

* Considerar aumento de largura via NUSIZ + PADDLE_BITS ajustado em round futuro.
* Avaliar se a area de colisao maior afeta o balanceamento do gameplay.
* Considerar arte de personagens (magos) agora que o paddle e maior.
