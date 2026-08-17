# Wizard Duel - Build e validação

## Pré-requisitos

* Python 3.8+
* DASM 2.20.x no `PATH`
* Stella 6.x no `PATH` (para `tools/run.py` e o teste de detecção do Stella)
* `xvfb` (somente Linux) quando a verificação de metadados do Stella precisar
  rodar sem sessão gráfica (ex.: CI)

No Ubuntu/Debian:

```sh
sudo apt-get install dasm stella xvfb
```

## Comandos canônicos

```sh
python tools/check_env.py         # verifica se dasm + stella existem e funcionam
python tools/build.py             # monta a ROM e reporta o uso de ROM
python tools/build.py --clean     # remove artefatos e depois monta
python tools/test.py              # suíte de validação determinística
python tools/test.py --build      # monta primeiro e depois testa
python tools/run.py               # executa a ROM no Stella
python tools/run.py --debug       # inicia no depurador do Stella
python tools/benchmark.py         # mede métricas e atualiza docs/benchmarks
python tools/benchmark.py --json  # imprime métricas como JSON (sem persistir)
python tools/regression.py        # compara métricas atuais contra um baseline
```

`tools/common.py` verifica se os executáveis exigidos existem **e se
comportam como a ferramenta real**. Uma ferramenta encontrada no `PATH` que
não seja funcional é rejeitada com um erro claro.

### Verificação do DASM

O DASM não tem opção `--version` nem `-h`. Executar `dasm --version` faz o
DASM tentar abrir um arquivo chamado `--version`; ele imprime
`Warning: Unable to open '--version'` e sai com código 0. Esse código de
saída é um **falso positivo** e não prova nada sobre o DASM.

Em vez disso, `tools/common.py` executa `dasm` sem argumentos. O
comportamento documentado do DASM nesse caso é imprimir o texto de ajuda
curto (`Usage: dasm sourcefile [options]`) e sair com código não zero; essa é
a verificação determinística usada por `check_env.py`, pelo build e pela
suíte de testes.

### Verificação do Stella

`stella -help` é uma opção real que funciona sem dispositivo de vídeo e
imprime `Stella <versão>` além de `Usage: stella ...`. Ela é usada como a
verificação do Stella.

Observe que `stella -rominfo` é **diferente**: ele inicializa o SDL e,
portanto, exige um dispositivo de vídeo mesmo sem abrir janela. Em Linux sem
tela, `tools/common.py` tenta novamente o `-rominfo` via `xvfb-run -a`
automaticamente quando não há `DISPLAY` disponível. O CI instala o `xvfb` por
esse motivo.

## Artefatos de saída

`build/` contém:

* `wizard-duel.bin` - ROM de 4096 bytes (4 KiB, sem bankswitching)
* `wizard-duel.lst` - listing do montador
* `wizard-duel.sym` - tabela de símbolos
* `regression-report.txt` / `regression-report.json` - relatório de regressão

Esses arquivos são gerados e não são commitados.

## O que a suíte de testes cobre

* **Build**: a ROM existe, tem exatamente 4096 bytes, vetores presentes e
  apontando para dentro da ROM; `-rominfo` do Stella reporta `4K`, NTSC e
  dois joysticks.
* **Memória**: uso de ROM <= 4096 bytes, uso de RAM <= 128 bytes (7 usados).
* **Assembly**: símbolos exigidos existem, `Reset` em `$F000`,
  `fineAdjustBegin` alinhado a página, tabelas de sprite com 12 bytes e
  seguras quanto a página.
* **Timing**: soma das scanlines das regiões == 262; o caminho de pior caso
  do kernel é recalculado do listing com um percorredor (walker) de ciclos
  6502 determinístico e verificado <= 76 ciclos (pior = 71, melhor = 57;
  todos os 8 caminhos de jogador x bola).
* **Comportamento da bola**: o `UpdateBall` montado é executado por um
  pequeno interpretador 6502 determinístico na suíte de testes - movimento,
  os quatro quiques de borda, o invariante de limites ao longo de 2000
  quadros e o estado inicial.
* **Regressão**: cálculo de deltas, limites hard/soft, kernel slack,
  resolução do baseline (ver `docs/pt-BR/benchmarks.md`).
* **Validação de ferramentas**: as verificações de DASM/Stella aceitam a
  ferramenta real e rejeitam executável ausente ou errado.
* **Docs**: os pares de documentação EN/PT-BR exigidos existem.

## O que o `stella -rominfo` valida

`stella -rominfo <rom>` inspeciona o **cabeçalho/propriedades** da ROM e
reporta metadados:

* tipo de bankswitch (`4K`)
* formato de exibição (`NTSC`)
* controles detectados (joysticks nas duas portas)
* se a ROM é reconhecida

Ele **não executa** o jogo. Não pode validar:

* comprimento real do quadro / contagem de scanlines em runtime
* estabilidade do quadro
* estado do TIA/CPU em runtime
* comportamento de gameplay

## Como as scanlines são validadas

Atualmente **não existe validação automatizada de scanlines em runtime**. O
Stella 6.6 não tem uma opção headless documentada que avance quadros e
imprima o contador de scanlines do TIA em um fluxo; o depurador e o overlay
de estatísticas do quadro exigem sessão gráfica e entrada interativa.
Conduzir isso com automação de teclas é frágil e deliberadamente não é usado
no CI.

O que é validado automaticamente em vez disso (determinístico, a partir dos
artefatos do build):

* a soma das scanlines das regiões do quadro é igual a `FRAME_SCANLINES`
  (262)
* o caminho de pior caso do kernel cabe no orçamento de 76 ciclos,
  recalculado do listing com um percorredor de ciclos
* os valores do timer (VBLANK 43, OVERSCAN 37) são as constantes ajustadas

O quadro de exatamente 262 scanlines foi, adicionalmente, medido no
depurador do Stella em uma sessão gráfica local (deltas de `print _cyclesLo`
de 19912 ciclos = 262 scanlines). Essa medição é **manual/de tempo de
desenvolvimento**, não uma verificação de CI; ver `docs/pt-BR/timing.md`. O
projeto não afirma que as scanlines foram "validadas em runtime pelo CI" -
elas foram medidas localmente no depurador e validadas estaticamente no CI.

## Comparação de regressão

`python tools/regression.py` compara as métricas atuais contra um baseline e
reporta falhas hard (código de saída 1) e avisos soft (código de saída 0).
Como o baseline é escolhido, quais limites são usados e como ler o relatório
estão documentados em `docs/pt-BR/benchmarks.md`.

## CI

O GitHub Actions (`/.github/workflows/ci.yml`) roda em PRs e pushes para
`main`. O checkout usa `fetch-depth: 0` para que a etapa de regressão possa
montar a branch base em um git worktree temporário; em PRs a branch base é
buscada explicitamente. O CI instala `dasm`, `stella` e `xvfb`, verifica as
ferramentas com `check_env.py`, monta de forma limpa, roda a suíte de testes,
gera o benchmark, executa a comparação de regressão e publica o relatório
tanto como resumo do job quanto como artefato.

### Lacuna de runtime no CI

As medições em runtime (quadro de exatamente 262 scanlines, comportamento
do movimento, ambos os jogadores visíveis) foram feitas no depurador do
Stella em uma sessão gráfica local. Automatizar o depurador gráfico do
Stella no CI não é confiável, então o CI valida a estrutura e o timing do
quadro estaticamente e documenta a lacuna em `docs/pt-BR/timing.md`; as
ferramentas determinísticas de análise do build são o substituto seguro
para o CI. O `-rominfo` do Stella é exercitado no CI (sob `xvfb`) apenas
como verificação de metadados da ROM.