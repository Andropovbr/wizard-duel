# Mudança: Registro de colisão Bola x Jogador (Rodada 6)

## Objetivo

Adicionar detecção de colisão bola x jogador na branch
`round-6-ball-player-collision` (sobre a Rodada 11, a correção do kernel
table-direct). Quando o TIA trava uma sobreposição Bola x P0 ou Bola x P1
durante o kernel visível, a passagem de colisão do overscan deve registrá-la
num byte legível pelo jogo para que uma rodada futura decida o que o contato
da bola *faz*. Esta rodada apenas *relata* o contato: não deve causar dano,
parar a bola, alterar mísseis ou mudar qualquer estado de jogo. A passagem
precisa permanecer de custo fixo e sem branches para que o quadro de 262
scanlines não mude, e o recurso deve ser validado contra a ROM real no
emulador determinístico.

## Hardware: os latches de colisão do TIA

Dois registradores relatam sobreposições com a bola (verificados no código do
Stella, o emulador de referência):

| Registrador | Endereço de leitura | Bit | Significado |
| ----------- | ------------------- | --- | ----------- |
| `CXP0FB`    | `$02` | D6 (`%01000000`) | P0 x Bola |
| `CXP1FB`    | `$03` | D6 (`%01000000`) | P1 x Bola |
| ambos       |             | D7 | P x Playfield (ignorado) |

`CXCLR` (`$2C`, escrita) limpa todos os latches de colisão. Os latches são
setados pelo feixe durante o kernel visível e persistem até a ROM limpá-los,
então o contrato de ler-depois-limpar do overscan é: ler os dois registradores
e então escrever `CXCLR`. Os bits D7 de jogador x playfield são
deliberadamente ignorados porque o playfield nunca é exibido (não há playfield
de fundo neste jogo).

## Ciclo de vida da colisão

`ball_contact_flags` é um **relatório por quadro**, exatamente como
`hit_flags`:

* o quadro N renderiza a sobreposição -> o TIA trava o bit durante o kernel;
* o overscan do quadro N executa `ProcessCollisions`, que empacota os latches
  em `ball_contact_flags` e escreve `CXCLR`;
* então um contato renderizado no quadro N é legível a partir do início do
  quadro N+1 e nunca se repete (o byte é reescrito para zero no próximo
  overscan).

Não há **debounce** nesta rodada: uma sobreposição que dura K quadros
consecutivos é relatada nos K quadros (medido, veja Testes). O flag é apenas
informação - nenhum quique de velocidade, dano, alteração de míssil ou
transição de estado é anexado a ele.

## Adicionado

* `src/constants.inc` - `CXP0FB = $02`, `CXP1FB = $03`,
  `BALL_HIT_P0 = %01000000` / `BALL_HIT_P1 = %01000000` (os bits D6 dos
  latches), `CONTACT_P0 = %00000001` / `CONTACT_P1 = %00000010` (os bits do
  byte de flags) e o bloco de comentário dos registradores de colisão do TIA
  atualizado.
* `src/main.asm` - o bullet de cabeçalho da Rodada 6 e o bloco de contato com
  a bola dentro de `ProcessCollisions`, colocado **antes** do `STA CXCLR`:
  ler `CXP0FB`, extrair D6 com o truque de duplo `ASL` para a carry,
  acumular em `ball_contact_flags`; repetir para `CXP1FB` (deslocado um bit
  para a esquerda para empacotar como bit 1). Custo fixo: 33 ciclos (14 + 19).
  `ProcessCollisions` total agora é 117 ciclos (era 84), ainda sem branches.
  VARS: `ball_contact_flags DS 1` em `$8E`; o comentário da RAM agora relata
  81 bytes ($80-$D0).
* `tests/test_ball_contact.py` - a suíte de aceitação da Rodada 6 (veja
  Testes): contato por jogador, sem contato/limpeza de stale, rejeição do bit
  de playfield, contato simultâneo, contato + acerto de míssil no mesmo
  quadro, sem contato de jogador morto (o portão de renderização), ciclo de
  vida dos latches / ordenação do CXCLR / sequências de contato, e uma rodada
  de 500 quadros de estresse máximo para timing de quadro.
* `tests/test_collision.py` - `CollisionHarness.set_collisions` estendido com
  `ball_p0`/`ball_p1` (injeta `cpu.cxp0fb`/`cpu.cxp1fb`), `state()` agora
  inclui `ball_contact_flags` e os dois latches, constantes `BALLP_P0 = 0x40`
  / `BALLP_P1 = 0x40` e a tabela de latches documentada no docstring do
  módulo.
* `tools/emu6502.py` - o emulador agora modela `CXP0FB`/`CXP1FB` como latches
  de leitura que persistem até a ROM escrever `CXCLR` (que limpa os quatro
  latches de colisão), espelhando o contrato real do TIA.

## Alterado

* `tests/test_memory.py` e `tests/test_ball.py` - asserções de RAM atualizadas
  de 80 para 81, e os comentários explicam que o +1 byte é
  `ball_contact_flags`.
* `tools/regression.py` - `PROJECT_RAM_BUDGET` de 80 para 81, com a justificativa
  documentada na constante (veja Racional Técnico para as alternativas
  investigadas e rejeitadas).
* Docs (EN + PT-BR): `docs/en/memory-map.md` / `docs/pt-BR/mapa-de-memoria.md`
  (layout de 81 bytes, linha de `ball_contact_flags`, endereço corrigido de
  `newActiveTbl` `$F290` -> `$F2A0`, prosa de ROM/RAM atualizada),
  `docs/en/timing.md` / `docs/pt-BR/timing.md` (passagens do overscan agora
  medidas: o primeiro `WSYNC` do overscan cai no ciclo 304 da região para todo
  estado de colisão; revalidação de estresse máximo de 500 quadros; status da
  validação em tempo de execução), `docs/en/architecture.md` /
  `docs/pt-BR/arquitetura.md` (seção de colisão e contato com a bola, passagem
  de 117 ciclos, mapa da RAM), `docs/en/benchmarks.md` /
  `docs/pt-BR/benchmarks.md` (limiares do orçamento de 81 bytes, bloco de
  métricas da Rodada 6) e `docs/benchmarks/latest.md` / `history.csv`
  (RAM 81, ROM 1808).

## Racional Técnico

**Por que um byte separado** em vez de reutilizar bits livres? Cada candidato
foi investigado e rejeitado:

* bits livres de `fire_prev` e `m_active`: ambos são reescritos todo quadro
  (`UpdateMissiles` no VBLANK, `m_active` via `newActiveTbl` na passagem de
  colisão), então um contato armazenado lá seria sobrescrito antes de ser
  lido;
* `hit_flags`: misturar contato da bola no byte de acerto de míssil tornaria
  as duas *classes* de colisão indistinguíveis para a lógica do jogo, e a
  lógica de HP/morte da Rodada 5 lê `hit_flags` diretamente;
* empacotar `p0_hp`/`p1_hp`: um campo de HP de 2 bits por jogador refatorando
  lógica testada da Rodada 5 para economizar um byte - rejeitado como risco
  injustificado;
* aliasing de `nullDelta` com `evRow`: `ConvertDeltas` escreve `nullDelta` e
  depois usa `evRow` no mesmo loop, então seus tempos de vida se sobrepõem.

Um byte novo é o custo correto: **RAM 81 de 128** (47 livres). `PROJECT_RAM_BUDGET`
passou de 80 para 81 para que o CI continue medindo um limite real em vez de
um obsoleto.

**Por que o duplo ASL sem branches**: extrair D6 (`%01000000`) para o bit 0
com dois `ASL`s move a carry para o acumulador via `ADC #0`, e a sequência
inteira por latch (`LDA $02 / ASL / ASL / LDA #0 / ADC #0`) custa fixos 14
ciclos; a sequência do CXP1FB (`... / ASL / ORA`) custa 19. Sem branch
`BPL`/`BMI` não há variação de timing, então a propriedade de custo fixo de
`ProcessCollisions` é preservada e o overscan contado por WSYNC permanece
exato.

**Por que sem verificação de HP em `ProcessCollisions`**: um jogador morto não
é renderizado (`BuildEvents` pula seus eventos GRP), então o TIA nunca trava
uma sobreposição de bola x jogador morto. O portão de renderização já evita
contatos de jogadores mortos sem uma verificação de HP que custaria bytes na
passagem de colisão.

**ROM inalterada (1808 bytes)**: os 24 bytes de código adicionado foram
absorvidos pela folga dos `ALIGN` existentes antes de `newActiveTbl` e
`ProcessHitEffects`, então o maior endereço emitido não mudou.
`ProcessHitEffects` permaneceu em `$F300`.

## Impacto de Timing

Antes:
- Scanlines do quadro: 262 (Rodada 11, kernel table-direct)
- `ProcessCollisions`: 84 ciclos
- Fronteira do primeiro `WSYNC` do overscan: ciclo 304 da região (medido,
  todos os caminhos)

Depois:
- Scanlines do quadro: exatamente 262 / 19912 ciclos para todo estado de
  colisão (medido em 500 quadros consecutivos de estresse máximo com os
  latches dos dois mísseis E os dois latches da bola assertados todo quadro)
- `ProcessCollisions`: 117 ciclos (+33, contato com a bola sem branches de
  custo fixo)
- Fronteira do primeiro `WSYNC` do overscan: ainda o ciclo 304 da região nos
  cinco estados medidos (sem colisão, acertos dos dois mísseis, contatos da
  bola, todas as colisões, ambos os jogadores mortos) - a região do overscan
  permanece exatamente 10 linhas
- Pior caso do kernel: inalterado 54/76 (kernel intocado nesta rodada)
- VBLANK: inalterado (timer 77, trabalho 4528, folga 336)

## Impacto de Memória

Antes:
- ROM: 1808 bytes
- RAM: 80 bytes ($80-$CF, 48 livres)

Depois:
- ROM: 1808 bytes (inalterada - a folga dos ALIGN absorveu o crescimento)
- RAM: 81 bytes ($80-$D0, 47 livres; +1 = `ball_contact_flags`)

## Testes

Executado: `python tools/test.py` - **233 testes, todos PASS** (eram 211).
Adicionado: `tests/test_ball_contact.py` (22 testes):

* Bola x P0 -> `CONTACT_P0`; Bola x P1 -> `CONTACT_P1`; nunca cruzam os bits.
* Sem contato -> 0; um byte stale 0xFF é deterministicamente zerado; os bits
  D7 de P x Playfield são ignorados (nunca se passam por contato).
* Bola x P0 + Bola x P1 simultâneos -> os dois bits.
* Contato da bola + acerto M0 x P1 no mesmo quadro: `hit_flags` e
  `ball_contact_flags` são independentes, o míssil que marcou ainda
  desativa, e um contato nunca desativa um míssil.
* Jogador morto: não renderizado (sem eventos GRP0) e nunca produz contato.
* Ciclo de vida dos latches: contato registrado uma vez, limpo no próximo
  quadro; `CXCLR` limpa `CXP0FB`/`CXP1FB`; os latches persistem até a ROM
  limpá-los; uma sequência de contato (4 quadros) acompanha a geometria
  injetada exatamente, e a sequência máxima medida iguala o comprimento
  injetado.
* Estresse máximo de 500 quadros: todo quadro = 19912 ciclos (262 scanlines)
  com os latches dos dois mísseis + dois da bola assertados, disparo
  alternado, HP mantido no máximo.

Portões de qualidade: ROM 1808 <= 4096, RAM 81 <= 128, quadro 262 scanlines,
kernel 54 <= 76. `python tools/benchmark.py` PASS (latest.md + history.csv
atualizados). `python tools/regression.py` PASS (2 avisos leves contra o
baseline persistido obsoleto da Rodada 1; a comparação com origin/main após o
commit será RAM +1 sem falha hard). Validação no Stella: `stella -rominfo`
carrega a ROM como 4K NTSC (MD5 `1dc4839d390acba1d7677b65dd07a243`); o
Stella 6.7.1 não tem opção headless `-frames`, então a estabilidade por quadro
é validada pelo emulador determinístico (execução de 500 quadros em
`test_ball_contact.py`).

## Limitações Conhecidas

* `ball_contact_flags` é um *relatório* por quadro: sem debounce, sem detecção
  de borda, sem efeito de jogo ainda. Uma rodada futura decide o que o contato
  faz (dano, quique da bola, etc.) lendo o flag.
* O registro é global (um bit por jogador) - não carrega informação espacial
  (onde a bola bateu, ângulo). Dados espaciais precisariam da posição da bola
  lida no mesmo quadro.
* A RAM está em 81 bytes; 47 permanecem. Cada novo byte de jogo se aproxima do
  limite de hardware de 128 e do portão de CI de 81 bytes.

## Próximos Passos Lógicos

* Decidir o que o contato da bola *faz* em termos de jogo (dano é o primeiro
  candidato óbvio, reutilizando o padrão de `hit_flags`/`ProcessHitEffects`).
* Se o contato precisar de dados espaciais, investigar a leitura da posição da
  bola no momento do contato (captura no VBLANK do quadro sinalizado) em vez
  de por quadro.
* Reexecutar a suíte de timing de estresse máximo e a comparação de regressão
  após o commit, para que a comparação com origin/main use as métricas reais
  da Rodada 11 (ROM 1808 / RAM 80) em vez do baseline obsoleto da Rodada 1.