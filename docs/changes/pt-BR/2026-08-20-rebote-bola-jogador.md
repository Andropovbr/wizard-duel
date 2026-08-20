# Mudança: Rebote mínimo Bola x Jogador (Rodada 7)

## Objetivo

Dar ao registro de contato bola x jogador da Rodada 6 uma *resposta* de jogo na
branch `round-6-ball-player-collision`: quando o TIA trava uma sobreposição
Bola x P0, a bola deve ser conduzida para a direita; em Bola x P1, para a
esquerda; `ball_dy` inalterado; sem dano, sem HP, sem alteração de mísseis,
sem remoção da bola, sem debounce, sem power-ups. A resposta precisa ser uma
passagem de custo fixo e sem branches no overscan para que o quadro de 262
scanlines não mude, validada contra a ROM real no emulador determinístico, e o
comportamento de contato repetido ("pianinho") deve ser observado e
documentado em vez de corrigido silenciosamente.

## Adicionado

* `src/main.asm` - `ApplyBallRebound` (JSR a partir de `OverscanWait`
  imediatamente após `ProcessCollisions`, antes de `ProcessHitEffects`): lê
  `ball_contact_flags`, deriva um índice de tabela `(old_dx_slot * 4) |
  contact_flags` com um único `ROL` e busca o novo `ball_dx` em `reboundTbl`.
  Corpo sem branches: 27 ciclos incluindo o `RTS` (JSR 6 + corpo 27 + RTS 6 =
  39 ciclos fixos adicionados ao epílogo do overscan). Bola x P0 ->
  `DIR_RIGHT` ($01), Bola x P1 -> `DIR_LEFT` ($FF), ambos os jogadores ->
  `DIR_LEFT` (precedência do P1), sem contato -> `ball_dx` inalterado. A linha
  VARS do comentário de RAM foi atualizada.
* `src/main.asm` - `reboundTbl`: tabela de 8 entradas alinhada a 16 bytes em
  `$F2D0`. Layout do índice (slots na ordem da fonte: slot 0 de dx =
  `DIR_LEFT`, slot 1 = `DIR_RIGHT`; bit 0 de flag = `CONTACT_P0`, bit 1 =
  `CONTACT_P1`): `[no-op] [->RIGHT] [->LEFT] [->LEFT]` para o slot de
  movimento para a esquerda, e `[no-op] [no-op] [->LEFT] [->LEFT]` para o
  slot de movimento para a direita. A face bola-entra-raquete (dx R + P0, dx L
  + P1) é o único rebote com significado; os casos de lado errado (dx L + P0,
  dx R + P1) são deliberadamente no-ops para que uma bola que entrou por trás
  mantenha sua direção em vez de ser reconduzida para dentro da raquete a cada
  quadro (veja Limitações Conhecidas).
* `src/constants.inc` - `OVERSCAN_LOOP_COUNT = 5` (antes 6) com um bloco de
  comentário da Rodada 7 explicando por que o contador caiu (veja Raciocínio
  Técnico).
* `tests/test_ball_rebound.py` - a suíte de aceitação da Rodada 7 (17 testes):
  condução por jogador para ambas as direções de entrada, `ball_dy`
  intocado, sem contato inalterado, contato com ambos os jogadores ->
  `DIR_LEFT`, sem efeitos colaterais em HP / `hit_flags` / mísseis / remoção
  da bola, coerência de contatos consecutivos (a rajada de contato reconduz na
  mesma direção a cada quadro), saída limpa após o contato, acerto de míssil +
  contato de bola no mesmo quadro, e uma execução de 100 quadros de estresse
  máximo afirmando 19912 ciclos / 262 scanlines em todos os quadros.
* `tools/common.py` - `probe_stella` reforçado para que a verificação no
  Windows 11 / Stella 7.0 funcione: decodificação explícita utf-8/replace,
  uma nova tentativa apenas no Windows que redireciona o stderr para um
  arquivo temporário via `cmd.exe /c`, e um fallback final que aceita um
  executável PE (magic `MZ`) com exit 0 quando a captura de console fica vazia
  (no Windows o Stella é um aplicativo de subsistema GUI; `-help` vai para o
  console via WriteConsole, que não aparece no pipe).

## Alterado

* `src/main.asm` - comentário do epílogo de `OverscanWait`: o primeiro `WSYNC`
  do overscan agora cai no ciclo 380 da região (antes 304) após o JSR de
  `ApplyBallRebound`; contador 5; janela de escrita ~K+306..K+326 permanece
  dentro do slot `(K+304, K+380]` em todos os caminhos.
* `src/main.asm` - bullet da Rodada 7 no cabeçalho; comentário de
  `ProcessHitEffects` atualizado (B em [60,80] no emulador / [62,80] no
  hardware real, margens >= 20 ciclos).
* Documentação (EN + PT-BR): `docs/en/timing.md` / `docs/pt-BR/timing.md`
  (contador do overscan 6 -> 5, primeira escrita de `WSYNC` 304 -> 380, a
  explicação dos 39 ciclos nas duas passagens do overscan),
  `docs/en/memory-map.md` / `docs/pt-BR/mapa-de-memoria.md`
  (`ApplyBallRebound` em `$F2B0`, `reboundTbl` em `$F2D0`),
  `docs/en/architecture.md` / `docs/pt-BR/arquitetura.md` (a bola deixou de
  ser "não interage com os jogadores": contato e condução horizontal agora
  documentados), e `docs/benchmarks/latest.md` / `history.csv` (loop do
  overscan 6 -> 5).
* Arquivos gerados por `tools/benchmark.py` atualizados ao rodar
  `python tools/benchmark.py`.

## Removido

* Os 8 ciclos de folga do `ALIGN 16` entre `newActiveTbl` (`$F2A0`) e
  `ProcessHitEffects` (`$F300`) - absorvidos pela nova rotina
  `ApplyBallRebound` e pela `reboundTbl`. Nada foi apagado: a folga era
  padding não utilizado.

## Raciocínio Técnico

**Por que sem branches + tabela**: a região do overscan é contada por WSYNC,
não por timer (uma passagem de custo variável, `ProcessHitEffects`, roda entre
o kernel e a espera). Cada ciclo adicionado antes do primeiro `WSYNC` do
overscan desloca sua fronteira de queda. Um rebote com branches (BNE/BPL)
variaria o custo no caminho de contato e quebraria a queda fixa. Indexar uma
tabela com `(old_dx_slot * 4) | contact_flags` transforma toda a decisão em um
ROL + LDA: determinístico, 27 ciclos, sem branches.

**Por que OVERSCAN_LOOP_COUNT 6 -> 5**: a Rodada 6 mediu o primeiro `WSYNC`
do overscan no ciclo 304 da região (scanline 4 do overscan). Os 39 ciclos fixos
da Rodada 7 o empurraram para fora do slot de escrita `(K+228, K+304]`; a queda
medida pós-stall agora é o ciclo 380 da região = scanline 5 do overscan.
Reduzir o loop de 6 para 5 WSYNCs de contagem reancora a sequência para que a
região continue somando exatamente 10 linhas e o `JMP` + preâmbulo de VSYNC
ainda alinhe o primeiro `WSYNC` de VSYNC do próximo quadro em 760 ciclos após a
última linha do kernel. O quadro permanece exatamente 19912 ciclos = 262
scanlines, verificado em 100 quadros de estresse máximo e cruzado com
instrumentação dedicada de queda do overscan.

**ROM de alto uso inalterada (1808)**: os ~39 bytes de código novo mais o
alinhamento couberam na folga `$FF` antes vazia entre `newActiveTbl` e
`ProcessHitEffects`; nenhum símbolo se moveu e o topo da ROM não cresceu.

**RAM inalterada (81)**: o rebote consome o byte `ball_contact_flags`
existente; `reboundTbl` vive na ROM. Nenhuma variável nova.

**A observação do "pianinho" (documentada, não corrigida)**: a 1 px/quadro a
bola leva de 2 a 5 quadros consecutivos para sair da sobreposição com a
raquete, e cada um desses quadros trava o contato novamente. Como o rebote não
é um quique por velocidade (sem reflexão), o primeiro quadro de contato define
a direção de saída e todos os quadros seguintes reaplicam a mesma direção -
então a raquete emite uma rajada curta e auto-limitante de tic-tic-tic, nunca
uma oscilação infinita e nunca uma inversão reversa. Execuções do emulador
determinístico capturaram sequências exatas de quadros, ex.: uma batida para a
direita na face esquerda do P1: quadros de contato 5-7 (bx 136, 135, 134; dx
-> L após o quadro 5), sem contato a partir do quadro 8 -> rajada de 3 taps;
um toque raso produziu 5 quadros consecutivos de contato. A execução headless
do Stella sob xvfb rodou a ROM de forma estável por 10 s; a ROM é reconhecida
como 4K NTSC. Conforme a diretriz do projeto, o pianinho é mantido como está e
registrado aqui para rodadas futuras.

## Impacto de Timing

Antes:
- Scanlines por quadro: 262 / 19912 ciclos (Rodada 6)
- Contador do loop do overscan: 6
- Fronteira do primeiro `WSYNC` do overscan: ciclo 304 da região = scanline 4

Depois:
- Scanlines por quadro: exatamente 262 / 19912 ciclos para todo estado de
  colisão (medido em 100 quadros consecutivos de estresse máximo)
- Contador do loop do overscan: 5
- Fronteira do primeiro `WSYNC` do overscan: ciclo 380 da região = scanline 5
  (todos os cinco estados medidos)
- Custo adicionado ao epílogo do overscan: 39 ciclos fixos (JSR 6 + corpo 27 +
  RTS 6)
- Pior caso do kernel: inalterado 54/76 (kernel intocado nesta rodada)
- VBLANK: inalterado (timer 77, trabalho 4528, margem 336)

## Impacto de Memória

Antes:
- ROM: 1808 bytes
- RAM: 81 bytes ($80-$D0)

Depois:
- ROM: 1808 bytes (inalterada - a folga de padding absorveu o crescimento)
- RAM: 81 bytes (inalterada - nenhuma variável nova)

## Testes

Executado: `python tools/test.py` - **250 testes, todos PASS** (antes 233).
Adicionado: `tests/test_ball_rebound.py` (17 testes):

* Bola x P0 -> `ball_dx = DIR_RIGHT`; Bola x P1 -> `ball_dx = DIR_LEFT`,
  para ambas as direções de entrada.
* `ball_dy` intocado por qualquer rebote.
* Sem contato -> `ball_dx` inalterado.
* Contato simultâneo P0 + P1 -> `DIR_LEFT` (precedência do P1).
* Sem efeitos colaterais: HP, `hit_flags`, estado dos mísseis e `m_active`
  inalterados; a bola nunca é removida.
* Coerência de contatos consecutivos: uma rajada de contato de 4 quadros
  reconduz na mesma direção a cada quadro (a rajada do pianinho), seguida de
  saída limpa quando a bola deixa a sobreposição.
* Acerto de míssil + contato de bola no mesmo quadro: `ProcessHitEffects` e
  `ApplyBallRebound` ambos se aplicam, de forma independente.
* 100 quadros de estresse máximo: todo quadro = 19912 ciclos (262 scanlines)
  com os dois latches de míssil + os dois de bola afirmados.

Gates de qualidade: ROM 1808 <= 4096, RAM 81 <= 128, quadro 262 scanlines,
kernel 54 <= 76. `python tools/benchmark.py` PASS (latest.md + history.csv
atualizados, loop do overscan 6 -> 5). `python tools/regression.py` PASS vs
origin/main. Validação no Stella: `stella -rominfo` carrega a ROM como 4K NTSC;
execução headless de 10 s sob xvfb estável (exit 124 = morta por timeout, ou
seja, rodou sem travar). A estabilidade por quadro é validada pelo emulador
determinístico.

## Limitações Conhecidas

* Sem quique por velocidade: o rebote é uma *condução* horizontal (`ball_dx`
  definido para LEFT/RIGHT), não uma reflexão. Uma bola que entra na raquete
  por trás (lado errado) é um no-op deliberado e mantém a direção, então ela
  atravessa.
* O pianinho (2-5 quadros consecutivos de contato na mesma raquete enquanto a
  bola sai da sobreposição) não é debounced de propósito; é inofensivo,
  auto-limitante e agora documentado com sequências exatas de quadros.
* Sem dano no contato da bola ainda - esta rodada apenas conduz a bola.
* RAM 81 de 128; cada novo byte de jogo aproxima o limite de hardware de 128
  bytes e o gate de CI de 81 bytes.

## Próximos Passos Lógicos

* Decidir se o contato da bola também deve causar dano (reutilizando o padrão
  de `hit_flags`/`ProcessHitEffects`) ou se a condução sozinha define o
  comportamento da Rodada 8.
* Se a travessia por lado errado importar, detectar a direção de entrada antes
  de aplicar o rebote (dado espacial ou direcional de contato).
* Reexecutar a suíte de estresse máximo de timing e a comparação de regressão
  após o commit, para que a linha de base origin/main use as métricas reais da
  Rodada 7 (ROM 1808 / RAM 81).