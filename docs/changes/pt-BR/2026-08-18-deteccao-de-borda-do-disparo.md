# Mudança: Correção do input de fogo - um press = um tiro

## Objetivo

Corrigir a lógica de disparo dos mísseis da Rodada 3 para que exatamente um
tiro seja disparado por pressionamento do botão, sem tiro automático no boot
e sem re-disparo enquanto segura o botão ou enquanto o míssil ainda está
ativo.

## Causa raiz

Dois bugs independentes em `UpdateMissiles`:

1. **Disparo falso no boot.** Em hardware real (e no Stella) os latches
   INPT4/INPT5 do TIA leem as linhas de fogo como pressionadas (bit 7 = 0)
   nos primeiros quadros após o RESET. `fire_prev` é zerado pelo
   ClearRAM do Reset, então o `UpdateMissiles` do primeiro quadro viu
   "pressionado agora + não pressionado antes" e tratou o estado do latch de
   boot como borda de subida, disparando M0 e M1 sem nenhum botão
   pressionado. Depois disso, `fire_prev` ficou preso em "pressionado", então
   o próximo press real não gerava borda e o disparo ficou não confiável até
   um release completo.
2. **Sem guarda de míssil ativo.** A lógica de spawn só checava a borda; uma
   borda de subida com o míssil ainda voando re-criava o míssil (reiniciava a
   posição) em vez de ser ignorada.

## Semântica de fogo antes / depois

Antes:
- boot: os dois mísseis disparavam automaticamente
- press: não confiável (sem borda até o release, e press com míssil ativo
  reiniciava o míssil voando)

Depois (independente por jogador):
- boot com FIRE solto: sem tiro
- boot com FIRE segurado: sem tiro automático; soltar + pressionar é
  necessário
- solto -> pressionado com o míssil inativo: um tiro
- botão segurado: sem re-disparo
- pressionado -> solto: apenas rearmer a entrada
- um novo solto -> pressionado dispara novamente depois que o míssil
  desaparece
- um míssil que desaparece com FIRE ainda segurado NÃO re-dispara
  automaticamente

## Implementação

* `UpdateMissiles` amostra INPT4/INPT5 em bits independentes de `tempA`
  (bit 0 = P0, bit 1 = P1) e mantém o teste de borda de subida existente
  (`pressionado agora` e `não pressionado no quadro anterior`).
* Adicionada a flag `fire_sync` (RAM `$F9`). Na primeira chamada após o Reset
  ela é 0, então `UpdateMissiles` adota o estado real dos botões em
  `fire_prev` e pula o spawn inteiro, depois define `fire_sync`. Isso
  sincroniza o detector de borda com os botões reais, então a leitura de boot
  do INPT nunca pode parecer uma borda de subida.
* Adicionada a guarda de míssil ativo: uma borda de subida só cria míssil
  quando `m0_active`/`m1_active` é 0. Um press com o míssil voando não cria um
  segundo nem reinicia o existente, e não consome o estado de borda de forma
  errada (o press ainda é registrado em `fire_prev`).

## Comportamento de boot

`fire_sync` é zerado pelo Reset (junto com toda a RAM). No primeiro quadro,
`UpdateMissiles` apenas sincroniza, então:

- boot com FIRE solto -> sem tiro (o artefato do latch é absorvido);
- boot com FIRE segurado -> sem tiro; o jogador precisa soltar e pressionar
  novamente.

## Testes

Adicionados `tools/emu6502.py` (um emulador 6502 determinístico com modelagem
de WSYNC/timer e leituras INPT4/INPT5 controláveis) e
`tests/test_missile_fire.py` (13 testes) cobrindo:

- boot solto (com e sem o artefato do latch) -> sem mísseis
- boot segurado -> sem fogo automático, soltar + pressionar dispara
- solto -> pressionado P0/P1 -> cada míssil dispara exatamente uma vez
- segurado -> sem re-disparo
- solto -> apenas rearm
- segundo press após despawn -> dispara novamente
- despawn com botão segurado -> sem re-spawn automático
- independência P0/P1
- ambos pressionados simultaneamente -> ambos disparam uma vez
- nenhum input -> sem mísseis

Atualizado o teste de orçamento de RAM (121 -> 122 bytes para `fire_sync`).
Suíte completa: 131 testes passam.

## Timing / memória

ROM inalterada em 1296/4096 bytes. RAM 121 -> 122/128 bytes (um byte para
`fire_sync`). O kernel visível não foi tocado: pior caso 69/76 ciclos, quadro
com exatamente 262 scanlines (verificado em 30+ quadros), renderização de
bola/raquetes inalterada.

## Limitações conhecidas

Nenhuma nova. A detecção de borda agora atende ao contrato documentado de um
press = um tiro.
