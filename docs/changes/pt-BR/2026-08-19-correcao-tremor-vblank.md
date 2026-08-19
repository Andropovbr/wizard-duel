# Mudança: Correção do tremor de VBLANK (timing de branch realista)

## Objetivo

Corrigir um tremor de tela inteira que só aparece em hardware real. O
orçamento de VBLANK da Rodada 5 foi ajustado contra um emulador que dobrava
todo branch condicional em 2 ciclos. No silício real, um branch tomado custa
3 ciclos (4 ao cruzar uma fronteira de página), então o trabalho de VBLANK no
pior caso (~4919 ciclos) ultrapassava a expiração do timer T=69 (~4553
ciclos), `WaitVBlank` deixava de esperar na fronteira fixa `INTIM == 0`, e
quadros individuais esticavam para 263/264/265 scanlines. O quadro parecia
visualmente correto no Stella com timing abreviado, então o bug ficou
invisível até o emulador modelar os custos reais de branch.

## Adicionado

* **Custos de ciclo realistas em `tools/emu6502.py`**: `execute()` agora
  retorna ciclos extras que `step()` adiciona de volta - branch tomado é +1
  (mais +1 ao cruzar página) e `LDA abs,Y` é +1 em page crossing. `step()`
  também foi corrigido para adicionar os ciclos retornados **depois** de
  `execute()` terminar (o `self.cycles += self.execute(op)` anterior lia
  `self.cycles` antes da chamada, apagando silenciosamente as paradas de
  WSYNC e os novos custos de branch).
* **Teste de regressão de folga do VBLANK** (`tests/test_frame_timing.py`,
  `test_vblank_never_overruns_with_realistic_branch_timing`): 80 quadros de
  estresse máximo (dois mísseis + dois latches de colisão + disparo
  alternado, HP reposto) devem ser todos exatamente 19912 ciclos = 262
  scanlines.
* **Métricas de VBLANK no benchmark** (`tools/benchmark.py`): `vblank_work`
  (escrita do TIM64T -> primeiro `LDA INTIM`, pior caso, emulado) e
  `vblank_margin` (`(timer - 1) * 64 - vblank_work`), registradas em
  `docs/benchmarks/latest.md` e `history.csv`. O migrador de histórico ganhou
  as duas colunas (deixadas vazias para linhas anteriores à Rodada 6).

## Modificado

* `src/constants.inc`: `VBLANK_SCANLINES` 57 -> 64, `KERNEL_SCANLINES`
  192 -> 185, `VBLANK_TIMER_VALUE` 69 -> 77. O timer agora expira em ~4864
  ciclos, bem depois do pior caso medido de ~4455 ciclos (folga ~409), então
  o poll sempre sai na fronteira fixa do timer.
* `src/main.asm`: comentários atualizados para a estrutura 3/64/185/10
  (VSYNC/VBLANK/KERNEL/OVERSCAN), a escrita do TIM64T e as notas do
  kernel/overscan.
* Testes atualizados para as novas constantes: `tests/test_timing.py`
  (kernel 192 -> 185, VBLANK 57 -> 64, VBLANK+overscan 67 -> 74) e
  `tests/test_ball.py` (limites da bola agora derivam de `KERNEL_SCANLINES`
  em vez do 192 fixo).
* Documentação (EN + PT-BR) atualizada para a nova estrutura de quadro e uma
  nova seção "Rodada 6" documentando a causa raiz do tremor e a correção do
  emulador.

## Racional Técnico

Uma espera `TIM64T` só é determinística quando o trabalho anterior termina
confortavelmente antes de o timer expirar. O bug original era um erro de
**orçamento**, não de poll: o emulador subestimava o trabalho, então o valor
escolhido de T não cobria o pior caso verdadeiro. A Rodada 6 corrige o
orçamento (aumenta o VBLANK, encolhe o kernel, sobe o timer) e torna o
modelo honesto (custos reais de branch/page crossing) para que a regressão
seja detectável deterministicamente. O benchmark `vblank_margin` é o portão
hard: folga negativa significa que o comprimento do quadro depende da entrada
e deve reprovar o CI.

## Impacto de Timing

Antes (emulado com timing de branch realista, entrada de pior caso):
- Scanlines do quadro: 262/263/264/265 (tremor)
- Trabalho de VBLANK no pior caso: ~4919 ciclos (expiração T=69 ~4553,
  folga negativa)

Depois:
- Scanlines do quadro: exatamente 262, todos os quadros da regressão de
  estresse máximo
- Trabalho de VBLANK no pior caso: 4455 ciclos
- Folga do VBLANK: 409 ciclos (positiva)

## Impacto de Memória

Antes:
- ROM: 1296 bytes
- RAM: 51 bytes

Depois:
- ROM: 1296 bytes (kernel encolheu 7 linhas; custo de ROM inalterado)
- RAM: 51 bytes

## Testes

Adicionado: `test_vblank_never_overruns_with_realistic_branch_timing`
(80 quadros de estresse máximo, todos exatamente 19912 ciclos).
Modificado: `tests/test_timing.py` (3 asserções para as novas constantes),
`tests/test_ball.py` (2 asserções derivam de `KERNEL_SCANLINES`).
Executado: `python tools/test.py` - 182 testes, todos PASS. Portões de
qualidade (ROM <= 4096, RAM <= 128) PASS.

## Limitações Conhecidas

O emulador modela apenas os opcodes efetivamente usados pela ROM, então as
contagens de ciclo são exatas para as instruções executadas, mas o modelo não
simula todos os 256 opcodes. O comportamento de TIA em nível de pixel
continua validado separadamente via Stella.

## Próximos Passos Lógicos

Manter o teste de regressão de folga do VBLANK vivo conforme o gameplay
cresce; rodar o benchmark sempre que o trabalho de VBLANK mudar e confirmar
que a folga permanece positiva. Considerar uma auditoria de fronteiras de
página do código de VBLANK para que nenhum branch futuro ganhe um ciclo extra
de page crossing no silício real.