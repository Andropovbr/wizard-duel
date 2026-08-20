# Mudança: Correção da detecção do Stella no Windows para builds GUI 7.x

## Objetivo

Fazer `python tools/run.py` (e `python tools/run.py --debug`) funcionar no
Windows 11 com Stella 7.0 no `PATH`. No Windows a ferramenta falhava na etapa
de verificação do Stella mesmo com `stella` funcionando direto pelo terminal:
o texto de ajuda aparecia no console do usuário, depois o `cmd.exe` reportava
"A sintaxe do nome do arquivo, do nome do diretório ou do rótulo do volume
está incorreta" e a verificação abortava com `FileNotFoundError` pelo
`stella-help.txt` nunca criado.

Branch: `fix/windows-stella-detection`.

## Causa raiz

Dois problemas independentes se acumulavam em `probe_stella()` /
`_probe_stella_windows_redirect()` em `tools/common.py`:

1. **Quoting de shell quebrado.** O fallback de Windows montava o comando
   `f'""{path}" -help > "{outfile}" 2>&1"'` e o executava com
   `subprocess.run(cmd, shell=True)`. No Windows, `shell=True` passa a string
   pelo `cmd.exe /c` com seu próprio tratamento convoluto de aspas, e o
   padrão `""...""` não é robusto entre versões do Python. No Python moderno
   (3.14) a linha de comando resultante fica malformada, o `cmd.exe` aborta
   com "A sintaxe do nome do arquivo ... está incorreta", o arquivo de
   redirecionamento nunca é criado e a verificação morre com
   `FileNotFoundError`.

2. **O redirecionamento nunca conseguiria capturar a saída do Stella 7.x de
   qualquer forma.** O Stella 7.x é um executável de subsistema GUI. Seu
   caminho de `-help` chama `AttachConsole(ATTACH_PARENT_PROCESS)` seguido de
   `freopen("CONOUT$", "w", stdout)`, o que re-aponta o `stdout` para o buffer
   de tela do console *independentemente do handle fornecido pelo processo
   pai*. O texto de ajuda vai direto para o terminal do usuário (exatamente o
   que foi observado) e não pode ser capturado por um pipe nem por
   redirecionamento para arquivo enquanto existir um console pai. O comentário
   anterior assumia que "um file handle real faz o CRT cair para WriteFile" —
   essa suposição não vale para o Stella 7.x real, porque o próprio Stella
   sobrescreve o `stdout`; o redirecionamento só fazia o texto de ajuda ser
   impresso uma segunda vez.

## Solução

`probe_stella()` mantém a captura nativa por pipe (funciona no
Linux/macOS/CI e para builds de subsistema console do Stella). Quando a
captura está vazia no Windows, o fallback não usa mais `cmd.exe`,
`shell=True`, redirecionamentos nem arquivos temporários. Ele reutiliza o
código de saída da execução de `-help` já realizada e inspeciona o próprio
executável via `_looks_like_stella()`: o arquivo deve ser um PE genuíno
(cabeçalhos `MZ` + `PE\0\0`) e seus bytes devem conter os marcadores
distintivos `Usage: stella` e `Stella version` (exatamente as strings que
`stella -help` imprimiria, embutidas como ASCII na seção `.rdata`). Isso é
deliberadamente forte o suficiente para rejeitar executáveis aleatórios que
apenas compartilham o nome `stella.exe`.

## Adicionado

* `tools/common.py` - `_looks_like_stella()`: varredura binária em blocos que
  verifica a estrutura PE (magic `MZ`, `e_lfanew` -> `PE\0\0`) mais os dois
  marcadores de uso, para não carregar executáveis grandes inteiros em
  memória.
* `tests/test_build.py` - adições em `TestStellaProbe` e a nova classe
  `TestStellaProbeWindows` (12 testes novos): um executável chamado `stella`
  que não é Stella é rejeitado; executáveis silenciosos com saída 0 são
  rejeitados no POSIX; "Stella" sem o marcador de uso é rejeitado; um texto
  de ajuda realista em caminho com espaços é aceito; e o cenário de Windows é
  simulado em qualquer plataforma com mocks de `os.name` e
  `subprocess.run` — `capture_output` vazio + saída 0 aceito somente quando o
  PE contém os marcadores, PE que não é Stella rejeitado, não-PE rejeitado,
  saída não zero rejeitada, saída capturada aceita sem o fallback, `OSError`
  reportado como "could not execute", e caminho de `stella.exe` com espaços
  aceito.

## Removido

* `_probe_stella_windows_redirect()`: o redirecionamento via `cmd.exe` /
  `shell=True` para arquivo temporário. Removido porque era tanto quebrado
  (quoting) quanto comprovadamente ineficaz para builds GUI do Stella 7.x
  (CONOUT$ re-aponta o `stdout`; redirecionar para arquivo não captura nada e
  só reimprime a ajuda).
* `_is_pe_executable()`: incorporado em `_looks_like_stella()`, que faz a
  verificação mais forte de PE + marcadores.

## Raciocínio Técnico

- O princípio do projeto "correção visual não é prova de correção de
  hardware" se aplica aqui por analogia: o fallback anterior *parecia* ter um
  mecanismo plausível (file handle -> WriteFile do CRT), mas o código-fonte
  real do Stella mostra que `attachConsole()` reabre `stdout` em CONOUT$ de
  forma incondicional, então nenhum redirecionamento pode capturar a saída. A
  correção é baseada no comportamento verificado no `src/common/main.cxx` do
  Stella 7.0.
- Só é usada a invocação nativa do `subprocess` em forma de lista (sem
  `shell=True`), então o quoting de caminhos com espaços é tratado pelo
  Python, sem metacaracteres de shell, com comportamento consistente em
  Python 3.8+ e em Windows/Linux/macOS.
- O fallback reutiliza o código de saída da única execução de `-help`, então
  não é preciso um segundo subprocess (nem um segundo despejo de ajuda no
  console).
- A verificação estrita por texto continua sendo a única sentença no
  Linux/macOS e no CI, então essas plataformas não são enfraquecidas em nada.

## Impacto de Timing

Nenhum. Nenhum código de jogo, ROM, kernel ou timing foi tocado.

Antes:
- Scanlines por quadro: n/a (inalterado)
- Caminho crítico: n/a (inalterado)

Depois:
- Scanlines por quadro: 262 (inalterado)
- Caminho crítico: inalterado

## Impacto de Memória

Antes:
- ROM: 1808 bytes usados (inalterado)
- RAM: 81 bytes usados (inalterado)

Depois:
- ROM: 1808 bytes usados
- RAM: 81 bytes usados

Sem impacto de ROM/RAM; a mudança é apenas de ferramentas Python.

## Testes

Executados:

```sh
python3 tools/check_env.py          # probes reais de dasm + stella passam
python3 tools/build.py              # ROM monta, 1808 bytes usados
python3 tools/test.py               # suíte completa
```

Resultados:
- `tools/test.py`: 261 testes, todos OK (incluindo os 12 novos testes do
  probe do Stella).
- `tools/check_env.py`: "Tool availability OK: dasm, stella".

## Limitações Conhecidas

- No Windows, com Stella GUI e console pai, `stella -help` imprime o texto de
  ajuda no terminal do usuário como efeito colateral da verificação (quem
  escreve no CONOUT$ é o próprio Stella; não há como suprimir sem um processo
  pai sem console). O probe agora faz uma única execução, então a ajuda é
  impressa apenas uma vez.
- A saída de `stella -rominfo` tem a mesma limitação de CONOUT$ no Windows,
  então as verificações de metadados via `-rominfo` continuam exclusivas de
  CI/Linux. É um comportamento pré-existente e não foi alterado.
- O fallback de Windows valida "Stella genuíno" via estrutura PE + marcadores
  + código de saída em vez de texto capturado; isso é inerente ao
  comportamento de CONOUT$ e está documentado em `tools/common.py`.

## Próximos Passos Lógicos

- Executar `python tools/run.py` e `python tools/run.py --debug` em uma
  máquina Windows 11 real com Stella 7.0 para confirmar o fluxo de ponta a
  ponta.
- Se desejado, exercitar `stella -rominfo` no Windows (ex.: com lançamento
  sem console) para decidir se os testes de metadados da ROM podem rodar lá
  também.