# Wizard Duel - Build e validação

## Pré-requisitos

* Python 3.8+
* DASM 2.20.x no `PATH`
* Stella 6.x no `PATH` (para `tools/run.py` e o teste de detecção do Stella)

No Ubuntu/Debian:

```sh
sudo apt-get install dasm stella
```

## Comandos canônicos

```sh
python tools/build.py           # monta a ROM e reporta o uso de ROM
python tools/build.py --clean   # remove artefatos e depois monta
python tools/test.py            # suíte de validação determinística
python tools/test.py --build    # monta primeiro e depois testa
python tools/run.py             # executa a ROM no Stella
python tools/run.py --debug     # inicia no depurador do Stella
python tools/benchmark.py       # mede métricas e atualiza docs/benchmarks
```

`tools/common.py` verifica se os executáveis exigidos existem e falha com
uma mensagem clara se algum estiver ausente.

## Artefatos de saída

`build/` contém:

* `wizard-duel.bin` - ROM de 4096 bytes (4 KiB, sem bankswitching)
* `wizard-duel.lst` - listing do montador
* `wizard-duel.sym` - tabela de símbolos

Esses arquivos são gerados e não são commitados.

## O que a suíte de testes cobre

* **Build**: a ROM existe, tem exatamente 4096 bytes, vetores presentes e
  apontando para dentro da ROM; `-rominfo` do Stella reporta `4K`, NTSC e
  dois joysticks.
* **Memória**: uso de ROM <= 4096 bytes, uso de RAM <= 128 bytes (apenas 3
  usados).
* **Assembly**: símbolos exigidos existem, `Reset` em `$F000`,
  `fineAdjustBegin` alinhado a página, tabelas de sprite com 12 bytes e
  seguras quanto a página.
* **Timing**: soma das scanlines das regiões == 262; o caminho de pior caso
  do kernel é recalculado do listing com um percorredor (walker) de ciclos
  6502 determinístico e verificado <= 76 ciclos (pior = 56, melhor = 44).
* **Docs**: os pares de documentação EN/PT-BR exigidos existem.

## Lacuna de runtime no CI

As medições em runtime (quadro de exatamente 262 scanlines, comportamento
do movimento, ambos os jogadores visíveis) foram feitas no depurador do
Stella em uma sessão gráfica local. Automatizar o depurador gráfico do
Stella no CI não é confiável, então o CI valida a estrutura e o timing do
quadro estaticamente e documenta a lacuna em `docs/pt-BR/timing.md`; as
ferramentas determinísticas de análise do build são o substituto seguro
para o CI. O `-rominfo` do Stella ainda é exercitado de forma headless no CI
como verificação de formato da ROM.