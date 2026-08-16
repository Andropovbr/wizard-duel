# Mudança: Reforço da infraestrutura de validação

Data: 2026-08-16
Branch: `round-1-initial-kernel`
Commit: `0e22354`

## Objetivo

Reforçar a infraestrutura de validação da Rodada 1 sem tocar em gameplay:
corrigir uma verificação inválida de disponibilidade do DASM, descrever com
precisão a validação do Stella, registrar o kernel slack como métrica de
primeira classe e implementar comparação de regressão baseada em baseline com
limites centralizados, além de testes, mudanças de CI e documentação
bilíngue.

## Adicionado

- `tools/check_env.py`: verificação multiplataforma de que `dasm` e `stella`
  estão instalados **e** se comportam como a ferramenta real.
- `tools/regression.py`: resolução de baseline + comparação de regressão
  hard/soft com relatório legível (texto + JSON opcional), código de saída 1
  em regressão hard, 0 caso contrário.
- `docs/en/benchmarks.md` e `docs/pt-BR/benchmarks.md`: métricas, estratégia
  de baseline, limites, kernel slack e como ler o relatório do CI.
- `docs/benchmarks/baseline.json`: o baseline persistido da Rodada 1 (ROM
  528 B, RAM 3 B, 262 scanlines, pior caso do kernel 56/76, slack 20, melhor
  caso 44).
- `tests/test_regression.py`: cálculo de deltas, limites de aviso, regressões
  hard, kernel slack, migração do histórico e resolução de baseline.
- Helper `stella_rominfo()` em `tools/common.py`, que tenta novamente o
  `-rominfo` via `xvfb-run` em Linux sem tela.
- `python tools/benchmark.py --json` (métricas legíveis por máquina, usadas
  ao montar a branch base durante a regressão) e `--update-baseline`.

## Alterado

- `tools/common.py`: `tool()` agora executa uma verificação funcional
  determinística; `probe_dasm()`/`probe_stella()` rejeitam executáveis
  ausentes ou errados.
- `tools/build.py` e `tools/run.py`: usam as novas verificações.
- `tools/benchmark.py`: registra `kernel_slack`, migra `history.csv` no lugar
  (adiciona a coluna `kernel_slack`, calculando `slack = budget - worst`; a
  linha original da Rodada 1 vira 20) e gerencia `baseline.json`.
- `tests/test_build.py`: o teste do Stella agora usa `stella_rominfo()`
  (ciente do xvfb) e foram adicionados testes de verificação de DASM/Stella.
- `.github/workflows/ci.yml`: `fetch-depth: 0`, instala `xvfb`, busca a
  branch base em PRs, verifica as ferramentas com `check_env.py`, executa a
  comparação de regressão e publica o relatório no resumo do job e como
  artefato.
- `docs/en/{build,timing}.md` e `docs/pt-BR/{build,timing}.md`: descrições
  precisas do que o `-rominfo` valida e do que não valida, o status da
  validação de scanlines e os novos comandos.

## Removido

- A etapa do CI `dasm --version` (inválida; ver abaixo).
- A afirmação de que o `stella -rominfo` roda "headless" sem ressalvas (ele
  inicializa o SDL e exige dispositivo de vídeo).

## Por que `dasm --version` estava errado, e a correção

O DASM não tem opção `--version` nem `-h`. Executar `dasm --version` faz o
DASM tratar `--version` como arquivo-fonte, falhar ao abrir, imprimir
`Warning: Unable to open '--version'` e sair com **0** ("Complete"). Uma
verificação que olha apenas o código de saída passa mesmo quando o DASM está
quebrado, e a mensagem engana.

A verificação substituta executa `dasm` sem argumentos. O comportamento
documentado do DASM (manual do usuário) é imprimir o texto de ajuda curto
(`Usage: dasm sourcefile [options]`, que também contém o banner de versão
`DASM 2.20.14.1`) e sair com código não zero. A verificação confere se a
saída contém o texto de uso, ou seja, se o executável é realmente um DASM
funcional, e não apenas um arquivo chamado `dasm` no PATH. `stella -help` é
usado da mesma forma para o Stella (é uma opção real e funciona sem tela).

## Validar metadados da ROM vs executar a ROM

`stella -rominfo <rom>` lê as propriedades da ROM e reporta tipo de
bankswitch (`4K`), formato de exibição (`NTSC`) e controles detectados. É
valioso, mas apenas metadados: o cartucho nunca é executado, então nada sobre
comprimento do quadro em runtime, estabilidade de scanlines ou gameplay é
verificado. Pior: no Stella 6.6 o `-rominfo` inicializa o SDL e falha com
"Couldn't initialize SDL" quando não há dispositivo de vídeo; no CI ele deve
rodar sob `xvfb-run`. O tooling agora faz isso de forma transparente.

## Limitações reais da validação em runtime do Stella

O Stella 6.6 não tem opção headless documentada que avance quadros e imprima
o contador de scanlines do TIA na saída padrão. O depurador e o overlay de
estatísticas do quadro (Alt-L) exigem sessão gráfica e entrada interativa;
conduzi-los com automação de teclas é frágil e deliberadamente não é usado no
CI. Portanto:

- o quadro de exatamente 262 scanlines foi medido **manualmente** no
  depurador do Stella em sessão local (deltas de `print _cyclesLo` de 19912
  ciclos);
- o CI valida a estrutura do quadro **estaticamente** (constantes, listing,
  soma das scanlines das regiões == 262, orçamento de ciclos do kernel).

O projeto não afirma que as scanlines foram validadas em runtime pelo CI;
esse limite está documentado explicitamente nos dois idiomas.

## Por que regressões dentro dos limites ainda importam

Uma ROM que cresce de 528 para 700 bytes ainda cabe em 4 KiB, mas isso é
significativo: mostra para onde o código está indo e pode alertar sobre a
aproximação do teto antes de uma mudança futura quebrar o build. O mesmo vale
para RAM e ciclos do kernel. Por isso a pipeline distingue **regressões
hard** (limites de hardware violados; o CI falha) de **regressões soft**
(crescimento dentro dos limites; reportado como avisos com limites
centralizados: ROM +32 B ou +5%, RAM +4 B, pior caso do kernel +4 ciclos,
slack -4 ciclos). Avisos não reprovam o CI, mas tornam visível toda mudança
significativa, em vez de deixar o crescimento acumulado se esconder.

## Como o baseline é escolhido

Prefere-se a **branch base**, montada em um git worktree temporário com o
próprio tooling da base (exige `fetch-depth: 0` no CI); em PRs a branch base
é `GITHUB_BASE_REF`. Quando a base não pode ser montada (ex.: ela é anterior
ao tooling, como `main` antes desta rodada), recai-se no `baseline.json`
commitado da base, depois no `docs/benchmarks/baseline.json` persistido
local, e finalmente reporta-se "sem baseline" sem falhar. A comparação nunca
usa a linha mais recente de `history.csv` da branch, porque ela é a última
execução da própria branch e poderia esconder regressões acumuladas em vários
commits. Nesta rodada, `main` ainda não pode ser montada, então é usado o
`baseline.json` persistido da Rodada 1 (baseline == atual); é o primeiro
baseline que o projeto registra.

## Por que o kernel slack é uma métrica de primeira classe

Uma scanline NTSC tem 76 ciclos de CPU; o pior caminho do kernel (ambos os
jogadores desenhados) custa 56, deixando **20 ciclos de folga**. O slack é a
margem de segurança para trabalho futuro de gameplay dentro do kernel
visível, e nesta plataforma correção de timing é um requisito, não uma
preferência. Registrar o slack (`kernel_budget - kernel_worst`) no benchmark,
histórico, baseline e relatório de regressão torna imediatamente visível uma
redução como regressão de performance, mesmo quando o quadro ainda
renderiza.

## Impacto de timing

Antes:
- Scanlines do quadro: 262
- Pior/melhor caso do kernel: 56 / 44 ciclos

Depois:
- Scanlines do quadro: 262 (sem mudanças de gameplay ou timing; só tooling)
- Pior/melhor caso do kernel: 56 / 44 ciclos
- Kernel slack: 20 ciclos (agora registrado)

## Impacto de memória

Antes:
- ROM: 528 bytes
- RAM: 3 bytes

Depois:
- ROM: 528 bytes (só tooling/docs; ROM inalterada)
- RAM: 3 bytes

## Testes

Adicionado `tests/test_regression.py` (deltas, formatação, limites,
regressões hard, kernel slack, migração do histórico, resolução de
baseline). Estendido `tests/test_build.py` com testes de verificação de
DASM/Stella e o teste de metadados da ROM ciente de xvfb. Atualizado
`tests/test_docs.py` para o novo par de documentação de benchmarks. Resultado
da suíte completa: todos passam (ver relatório).

## Limitações conhecidas

- Não há validação automatizada de scanlines em runtime; o quadro de 262
  scanlines continua sendo uma medição manual no depurador (documentada, não
  afirmada pelo CI).
- O primeiro baseline é autorreferente (baseline == atual) porque a branch
  base é anterior ao tooling; ele se torna significativo a partir da próxima
  mudança.
- Os limites de regressão soft são intencionalmente conservadores e
  centralizados em `tools/regression.py`; podem precisar ser revistos à
  medida que o jogo cresce.

## Próximos passos lógicos

- Reexecutar as medições no depurador do Stella após qualquer mudança de
  kernel/VBLANK e registrá-las na documentação de timing.
- Revisar os limites quando código real de gameplay começar a consumir ROM e
  ciclos do kernel.
- Se uma futura versão do Stella expuser uma interface headless estável de
  quadro/scanline, adicionar validação em runtime à pipeline e remover a
  lacuna manual.