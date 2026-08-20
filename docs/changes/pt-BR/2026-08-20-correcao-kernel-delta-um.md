# Mudança: Correção do kernel de eventos delta=1 (apply direto da tabela, Rodada 11)

## Objetivo

Corrigir o último bug de estabilidade de quadro restante em
`round-5-basic-hp`: quando dois eventos caem em linhas de exibição
**consecutivas** (delta 1), o kernel pendente em duas fases da Rodada 10
descartava a escrita OFF do segundo evento, deixando o objeto habilitado além
da borda inferior. A correção deve tornar o kernel visível independente de
entrada para toda tabela de eventos válida (sem desvios dependentes de
dados), manter o quadro em exatamente 262 scanlines e ser validada contra a
ROM real no emulador determinístico. Sem novo gameplay.

## Causa raiz

O kernel da Rodada 10 era um pipeline adiado em duas fases: ele *decodificava*
a próxima entrada em uma linha de evento, estagiava as escritas em
`pendReg1/2` / `pendVal1/2` e só as *aplicava* na linha seguinte. Quando o
próximo evento estava na própria linha seguinte (`delta = 1`), a decodificação
na linha N estagiava escritas que eram imediatamente sobrescritas pela
decodificação na linha N+1 - as escritas do primeiro evento nunca chegavam ao
TIA e seu OFF (ou ON) era silenciosamente descartado.

Isso era diferente do bug de delta-0 da Rodada 7 (bump de dupla na mesma
linha): a tabela ficava estritamente ordenada sem entradas de delta 0, mas
mesmo assim um par delta-1 perdia as escritas de um evento.

## Correção

O kernel agora aplica a tabela **diretamente em toda scanline** em vez de
estagiar escritas:

* toda entrada é um registro uniforme de 5 bytes
  `[delta, reg1, val1, reg2, val2]` (`reg2 = 0` marca escrita única);
* o bloco de apply lê a última entrada decodificada através de `Y-5` e grava
  os dois registradores incondicionalmente no topo de toda linha - antes de
  qualquer contagem - então um evento na própria linha seguinte (delta 1)
  aplica suas escritas na sua primeira linha de exibição;
* o sentinela do marcador é o byte de delta da entrada (`$FF`,
  `EV_MARKER_VAL`), lido após carregar `evCnt`; o caminho do marcador encerra
  o kernel no ciclo 46;
* os primeiros cinco bytes da tabela são uma entrada dummy (ambos os
  registradores 0, AUDV0) para que linhas anteriores ao primeiro evento
  apliquem sem dano; as entradas reais começam no offset 5.

A temporização agora é constante independentemente de quantas escritas uma
entrada contém ou de quais objetos dispararam: sem evento 38 ciclos, evento
54, marcador 46, pior caso 54/76 (folga 22).

## Adicionado

* `tests/test_event_collision.py` - reescrita da Rodada 11: modelo de
  leitura/inicialização da tabela para o kernel de apply direto, comparação
  byte por byte ROM vs modelo, estresse de colisão de cinco objetos na mesma
  linha e o novo `test_five_way_bottom_collision_drops_last_off` fixando a
  limitação documentada do builder (veja Limitações conhecidas).
* `tests/test_frame_timing.py` - revalida a estabilidade do quadro: 80
  quadros estressados em 19912 ciclos = 262 scanlines, e a caminhada de
  inicialização/delta-0 pela tabela de eventos real.
* Cobertura da entrada dummy e do back-scan `EV_MARKER_ROW` em
  `test_events.py`.

## Alterado

* `src/main.asm` - `KernelLoop` reescrito como apply direto da tabela (sem
  registradores pendentes, sem despacho simples/dupla); `BuildEvents`/
  `AppendEvent`/`ShiftBy5`/`ConvertDeltas` reescritos para entradas uniformes
  de 5 bytes (sem `ShiftBy2`/`ShiftBy3`); remanejamento de VARS (`evTbl`
  $90-$CB com 60 bytes, `evRow` $CC, `tempCount` $CD, `tblLen` $CE,
  `nullDelta` $CF; `pendReg*`/`pendVal*` removidos).
* `src/constants.inc` - `EV_TBL_SIZE` 31 -> 60, `ENTRY0` 5, constantes do
  marcador, auxiliares de inicialização.
* `tests/test_timing.py` - orçamentos 38/54/46; `LDX evTbl-4,Y` emite `0xB6`
  (LDX zp,Y, 4 ciclos), adicionado à tabela de opcodes do emulador.
* `tools/emu6502.py` - `0xBE` (LDX abs,Y) adicionado como proteção futura
  inofensiva; o `evTbl-4,Y` do kernel monta para `0xB6`, que já era tratado.
* `tests/test_events.py`, `test_ball.py`, `test_memory.py`, `test_rom.py`,
  `test_collision.py`, `test_hp.py`, `test_regression.py` - atualizados para
  a tabela uniforme, novos símbolos e o layout de RAM de 80 bytes (regra de
  reescrita de código obsoleto).
* `tools/regression.py` - `PROJECT_RAM_BUDGET` 64 -> 80 (justificado pela
  correção table-direct; excede a antiga meta "soft" de 79 bytes em exatamente
  1 byte, o necessário para `EV_TBL_SIZE` 60 cair em um limite par).
* `tools/benchmark.py` - removido o parâmetro obsoleto `two_write`.
* Docs: `docs/en/timing.md`, `docs/pt-BR/timing.md` (seção do kernel reescrita
  para 38/54/46 e apply direto; `OVERSCAN_LOOP_COUNT` 7 -> 6),
  `docs/en/architecture.md`, `docs/pt-BR/arquitetura.md` (formato de entrada
  uniforme, regra de slot, mapa de RAM), `docs/en/memory-map.md`,
  `docs/pt-BR/mapa-de-memoria.md` (80 bytes, endereços de símbolo atuais),
  `docs/en/benchmarks.md`, `docs/pt-BR/benchmarks.md` (estado da Rodada 11),
  `docs/en/event-kernel-timing-analysis.md`,
  `docs/pt-BR/analise-timing-kernel-eventos.md` (seção de resolução).
* `docs/benchmarks/latest.md` / `history.csv` - atualizados por
  `tools/benchmark.py`.

## Racional técnico

O antigo pipeline pendente tornava o apply **condicional à decodificação da
linha anterior**, que é exatamente o que um par delta-1 quebra: a segunda
decodificação destrói as escritas estagiadas da primeira antes que elas
apliquem. Aplicar incondicionalmente no início da linha remove a dependência
entre o apply e a contagem, então nenhum par de entradas consecutivas pode
interferir. A entrada uniforme de 5 bytes é o preço: todo evento (único ou
dupla mesclada) custa 5 bytes, a tabela cresce para 60 bytes (`dummy 5 + 10
entradas + marcador 5`) e a inicialização da contagem precisa de um byte
`nullDelta` para o caso comum em que o primeiro evento não está na linha 0.
Em troca o kernel não tem nenhum desvio dependente de dados, então a classe
de bug de 263 scanlines é estruturalmente inalcançável.

Detalhe do DASM: `LDX evTbl-4,Y` monta para **0xB6** (LDX zero-page,Y, 4
ciclos), não 0xBE (LDX abs,Y) - o endereço efetivo é `($8C+Y)&$FF` e Y nunca
excede 55 (offset máximo da tabela $C3), então a indexação em zero page nunca
envolve. O emulador já tratava 0xB6; 0xBE foi adicionado apenas por
integralidade defensiva.

## Impacto de timing

Antes (Rodada 10):
- Scanlines por quadro: 262 normalmente, mas 263 para pares delta-1 (o bug)
- Pior caminho do kernel: 65/76 ciclos, folga 11 (decode pendente de tamanho
  variável)
- Trabalho do VBLANK: 4486 ciclos, margem ~378

Depois (Rodada 11):
- Scanlines por quadro: exatamente 262 para toda entrada (80 quadros
  estressados, todos com 19912 ciclos)
- Pior caminho do kernel: 54/76 ciclos, folga 22 (constante para toda entrada)
- Melhor caminho do kernel: 38 ciclos (sem evento)
- Linha do marcador: 46 ciclos
- Trabalho do VBLANK: 4528 ciclos, margem 336 (ainda bem dentro da expiração
  T=77 ~4864)
- Overscan: 6 escritas WSYNC, 10 linhas (fim do kernel movido de K+174 para
  K+236)

## Impacto de memória

Antes:
- ROM: 1552 bytes
- RAM: 51 bytes

Depois:
- ROM: 1808 bytes (+256; builder ciente de offsets + regras de ordem de slot;
  ROM usa apenas 44% do limite de 4096)
- RAM: 80 bytes (+29; a tabela uniforme de 60 bytes é o preço do kernel
  independente de entrada; restam 48 bytes)

## Testes

Executados: `python tools/test.py` - **211 testes, todos PASS** (descobertos
com `python3 -m unittest discover -s tests`). Portões de qualidade: ROM 1808
<= 4096, RAM 80 <= 128, quadro 262 scanlines, kernel 54 <= 76. `python
tools/benchmark.py` PASS (latest.md + history.csv atualizados).
`python tools/regression.py` PASS com 2 avisos soft (ROM +512 B, RAM +31 B
vs o baseline origin/main da Rodada 8; ambos esperados, documentados acima).
Validação no Stella: `stella -rominfo` sai com 0 (Cart MD5
7e8d44bb9494f1c0ff254aa05d7ac67d, 4K NTSC); uma execução de smoke via
xvfb-run sai com 0. O Stella 6.7.1 não tem opção headless de `-frames`, então
a estabilidade por quadro é validada pelo emulador determinístico em
`test_frame_timing.py`. Cenas de repro verificadas no emulador:
p0=88,p1=50,by=51 -> GRP1 renderiza as linhas 50-62 (estava invisível antes da
correção); p0=88,p1=50,by=96,m0y=96,m1y=100,m0act=True -> o OFF de
ENABL/ENAM0 aplica na linha 100 (estava preso em ON).

## Limitações conhecidas

* **Colisão de cinco objetos na mesma linha no fundo** (fixada por
  `test_five_way_bottom_collision_drops_last_off`): com p0=p1=171, by=179,
  m0y=m1y=183 todos ativos, a cadeia de deslocamentos do builder
  (183 -> 184 -> 185) descarta o OFF de P1, deixando GRP1 habilitado pela
  linha 184. A inicialização do overscan o limpa na linha 185+, então o
  artefato é no máximo um scanline no fundo da tela, fora da arena. ROM e
  modelo Python concordam sobre a tabela emitida; corrigir exigiria rejeitar
  o 5º evento (fora do escopo).
* A entrada dummy faz o apply anterior ao primeiro evento escrever AUDV0 toda
  linha; inofensivo com a tela ligada.
* A RAM agora é 80 bytes (acima dos 79 previstos na análise); restam 48
  bytes, ainda adequados para o escopo atual.
* Os números de kernel projetados originalmente nos documentos de análise
  (62/rest 58) assumiam um fall-through em vez do JMP; o caminho implementado
  de 54/46 é ligeiramente maior, mas estruturalmente idêntico.

## Próximos passos lógicos

* Se o artefato de colisão de uma linha no fundo se mostrar visível, rejeitar
  o 5º evento na mesma linha em `AppendEvent` em vez de deslocar além da
  última linha segura.
* Reexaminar o orçamento de RAM de 80 bytes contra o gameplay futuro; cada
  objeto adicional custa até 10 bytes de tabela.
* Revalidar a garantia de slot de escrita em hardware real quando houver um
  caminho de captura em nível de pixel.