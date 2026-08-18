# Wizard Duel - Benchmarks e comparação de regressão

## Métricas acompanhadas

Medidas deterministicamente a partir dos artefatos do build (sem tela):

| Métrica           | Significado                                        |
| ----------------- | -------------------------------------------------- |
| ROM usada         | marca d'água alta do código/dados emitidos abaixo de $FFFA |
| RAM usada         | variáveis do RIOT alocadas via `DS`                |
| Scanlines do quadro | constante `FRAME_SCANLINES` (262 para NTSC)       |
| Pior caso do kernel | maior custo de scanline do kernel, recalculado do listing |
| Melhor caso do kernel | menor custo de scanline do kernel              |
| Kernel slack      | `kernel_budget - kernel_worst`                     |
| VBLANK/OVERSCAN   | valores ajustados do timer do RIOT (69 / 11)       |

## Kernel slack

Uma scanline NTSC tem 76 ciclos de CPU. O kernel da Rodada 3 é orientado a
eventos: uma linha sem evento custa 18 ciclos e uma linha de evento de duas
escritas (o pior caso) custa 69 ciclos, portanto:

```text
kernel slack = 76 - 69 = 7 ciclos
```

O slack é uma **métrica de primeira classe**: é registrado em `latest.md`,
em `history.csv`, em `baseline.json` e no relatório de regressão. Trabalho de
hardware que cresce o kernel consome diretamente o slack; um caminho de
scanline que atinja 76 ciclos é uma falha hard. Reduzir o slack é uma
regressão de performance mesmo que o quadro continue renderizando.

## Estratégia de baseline

`python tools/regression.py` resolve o baseline nesta ordem (a primeira
correspondência vence):

1. `--baseline <arquivo>`: arquivo JSON explícito com as métricas.
2. **Branch base, montada localmente**: em PRs, a branch base
   (`GITHUB_BASE_REF`) ou `origin/main` é verificada em um git worktree
   temporário, montada com o próprio tooling da base e medida. Esta é a
   comparação preferida: reflete o código real da base e não pode esconder
   regressões acumuladas dentro de uma branch. `fetch-depth: 0` é exigido no
   CI para isso funcionar.
3. **Baseline commitado da branch base**: `git show
   <base>:docs/benchmarks/baseline.json` quando a base não pode ser montada
   (ex.: ela é anterior ao tooling).
4. **Baseline persistido local**: `docs/benchmarks/baseline.json`, um ponto
   de referência deliberado, criado quando ausente e atualizado apenas
   explicitamente com `python tools/benchmark.py --update-baseline`. Rodadas
   de benchmark por branch nunca o reescrevem, então comparar contra ele
   mantém as regressões acumuladas visíveis.
5. Sem baseline: a comparação é pulada, o relatório diz isso e a ferramenta
   sai com código 0.

A comparação deliberadamente **não** usa a linha mais recente de
`history.csv`, porque ela é a última execução desta própria branch e poderia
esconder regressões acumuladas em vários commits da branch.

## Regressão hard vs soft

### Regressões hard (código de saída 1)

Violar um limite de hardware sempre reprova o CI:

* ROM > 4096 bytes
* RAM > 128 bytes
* pior caso do kernel > 76 ciclos por scanline
* contagem de scanlines do quadro != 262
* build quebrado, testes falhando, ferramentas exigidas indisponíveis

### Regressões soft (avisos, código de saída 0)

Crescimento que permanece dentro dos limites de hardware é reportado, mas
não reprova o CI. Os limites estão centralizados como constantes em
`tools/regression.py` (valores iniciais conservadores):

| Métrica           | Limite de aviso                              |
| ----------------- | -------------------------------------------- |
| Crescimento de ROM | > 32 bytes OU > 5,0%                        |
| Crescimento de RAM | > 4 bytes                                    |
| Pior caso do kernel | aumento > 4 ciclos                         |
| Kernel slack      | redução > 4 ciclos                            |

Esses valores são intencionalmente conservadores; servem para tornar
regressões significativas visíveis, não para falhar a cada byte. Atualize-os
somente com uma razão técnica documentada.

## Lendo o relatório do CI

`regression.py` imprime uma tabela de comparação:

```text
Metric             Baseline       Current        Delta
ROM used           528 B          612 B          +84 B (+15.9%)
RAM used           3 B            5 B            +2 B
Kernel worst case  56 cycles      60 cycles      +4 cycles
Kernel slack       20 cycles      16 cycles      -4 cycles
Frame scanlines    262            262            0

Hard limits: all PASS
Warnings:
  ROM used: ROM grew by 84 B (+15.9%)
Status: PASS with 1 warning
```

* `Delta` mostra a mudança absoluta e percentual (`0` vazio = sem mudança).
* Qualquer linha `FAIL - ...` significa regressão hard e código de saída não
  zero.
* `Status: PASS` - nada a fazer. `Status: PASS with N warnings` - dentro dos
  limites de hardware, mas revise os avisos. `Status: FAIL` - limites de
  hardware violados.

No CI o mesmo relatório é anexado ao resumo do job do GitHub Actions e salvo
como artefato `build/regression-report.txt` / `build/regression-report.json`.

## Histórico persistido

`docs/benchmarks/history.csv` registra uma linha por execução de benchmark
(`latest.md` reflete a execução mais recente). Na Rodada 1 o CSV ganhou a
coluna `kernel_slack`; `tools/benchmark.py` migra as linhas anteriores no
lugar, calculando `slack = kernel_budget - kernel_worst`, então nenhum dado
histórico é perdido.

## Baseline e estado atual

O baseline persistido `docs/benchmarks/baseline.json` foi criado a partir
do estado da Rodada 1 e é deliberadamente mantido como ponto de referência
(só é reescrito com `--update-baseline`):

```text
Baseline da Rodada 1:
ROM usada:          528 bytes
RAM usada:          3 bytes
Scanlines do quadro: 262
Pior caso do kernel: 56 / 76 ciclos
Kernel slack:       20 ciclos
Melhor caso do kernel: 44 ciclos

Rodada 2 atual (medida, após a correção de timing do ENABL):
ROM usada:          528 bytes   (tabelas removidas; o padding de página absorve)
RAM usada:          7 bytes
Scanlines do quadro: 262
Pior caso do kernel: 62 / 76 ciclos
Kernel slack:       14 ciclos
Melhor caso do kernel: 62 ciclos   (kernel sem ramificações: melhor == pior)

Rodada 3 atual (kernel orientado a eventos + mísseis):
ROM usada:          1296 bytes  (builder de eventos + mísseis)
RAM usada:          121 bytes   (tabela de eventos + registros + array de ordem)
Scanlines do quadro: 262
Pior caso do kernel: 69 / 76 ciclos   (linha de evento de duas escritas)
Kernel slack:       7 ciclos
Melhor caso do kernel: 18 ciclos   (linha sem evento)
```

Esses números são medidos a partir dos artefatos a cada execução, não
"verdade" fixada no tooling.