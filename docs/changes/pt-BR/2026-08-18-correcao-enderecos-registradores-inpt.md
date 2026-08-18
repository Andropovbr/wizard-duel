# Mudança: Correção dos endereços dos registradores INPT4/INPT5

## Objetivo

Fazer os botões de fogo dos joysticks funcionarem de fato no Stella (e em
hardware real). O gatilho de mísseis funcionava no emulador determinístico
dos testes unitários, mas nunca disparava no Stella, porque o jogo lia os
registradores errados do TIA.

## Causa raiz

`src/constants.inc` definia:

```asm
INPT4 = $04              ; P0 fire button (bit 7, active low)
INPT5 = $05              ; P1 fire button (bit 7, active low)
```

Mas `$04` e `$05` são **NUSIZ0** e **NUSIZ1** — registradores *somente de
escrita* do TIA. Os latches reais dos botões de fogo estão em:

```text
INPT4 = $3C   ; P0 fire button (bit 7, active low)
INPT5 = $3D   ; P1 fire button (bit 7, active low)
```

No barramento de dados do Atari 2600, ler um registrador somente de escrita
do TIA retorna o endereço do registrador no barramento (comportamento de
open bus). O Stella emula isso, então todo `LDA INPT4` / `LDA INPT5`
retornava `$04` / `$05` respectivamente, com o bit 7 sempre 0 — ou seja, o
software lia permanentemente "botão pressionado". A detecção de borda de
subida em `UpdateMissiles` nunca observava a transição
`liberado -> pressionado` e, portanto, nunca disparava.

O bug era invisível nos testes unitários porque `tools/emu6502.py`
modelava as leituras INPT nos *mesmos endereços errados* (`addr < 6`
retornava `inpt[addr]`), de modo que emulador e fonte concordavam entre si,
mas discordavam do hardware real do TIA e do Stella.

## Investigação

Probes baseadas no Stella estabeleceram os fatos antes da correção:

- Ler `$04`/`$05` retornava `$04`/`$05` (os próprios endereços) com bit 7
  sempre 0, tanto em repouso quanto segurando Space / Ctrl / Enter / X / Z.
- A tecla de fogo está mapeada corretamente (a configuração do Stella mapeia
  Space para `LeftJoystickFire`), e os direcionais funcionam: um probe em
  SWCHA mudou com as setas do teclado.
- Ler os endereços *corretos* `$3C`/`$3D` retorna bit 7 = 1 (liberado) em
  repouso e bit 7 = 0 (pressionado) segurando Space. O Stella 6.7.1 entrega
  normalmente o input de teclado para esses latches.

Ou seja, era um bug puro de endereço de registrador, não um problema de
entrega de input.

## Alterado

- `src/constants.inc`: `INPT4 = $3C`, `INPT5 = $3D`, com comentário
  explicando por que `$04`/`$05` (NUSIZ0/NUSIZ1) estariam errados.
- `tools/emu6502.py`: as leituras do TIA agora mapeiam INPT0-5 para
  `$38-$3D` (e o espelhamento `$78-$7D`) em vez de `$00-$05`. Escritas em
  `$38-$3D` são ignoradas (latches INPT são somente de leitura), como no TIA.

## Racional Técnico

O mapa de memória do TIA coloca os latches de entrada somente de leitura em
`$38-$3D`:

```text
$38-$3B  INPT0-INPT3   entradas de paddle/keypad
$3C      INPT4         botão de fogo do P0
$3D      INPT5         botão de fogo do P1
```

`$04`/`$05` são os registradores de tamanho dos sprites (NUSIZ0/NUSIZ1);
eles não são legíveis e não têm nenhum significado de botão de fogo. Manter
as definições antigas garantiria que o fogo nunca funcionasse fora do (errado)
modelo de teste.

## Impacto de Timing

Antes:
- Scanlines por quadro: 262
- Caminho crítico: 69/76 ciclos (kernel inalterado)

Depois:
- Scanlines por quadro: 262
- Caminho crítico: 69/76 ciclos (kernel inalterado)

Sem mudança de timing: `UpdateMissiles` continua rodando inteiramente no
VBLANK e o kernel visível não foi tocado.

## Impacto de Memória

Antes:
- ROM: 1296 bytes
- RAM: 122 bytes

Depois:
- ROM: 1296 bytes (mesmas instruções, endereços imediatos diferentes)
- RAM: 122 bytes

## Testes

- `python3 -m unittest tests.test_missile_fire -v`: 13/13 passam.
- Suite completa `python3 tools/test.py`: 131 testes passam.
- Quality gates de ROM/RAM passam.
- Validação em runtime no Stella (ROM compilada a partir da fonte corrigida):
  - sem input em repouso -> sem míssil, tela mostra apenas P0/P1/bola;
  - segurando Space -> um míssil M0 vermelho aparece e move para a direita;
  - segurando F (fogo do P1) -> um míssil M1 azul aparece e move para a
    esquerda;
  - antes, segurar qualquer tecla de fogo produzia uma tela byte-idêntica.

## Limitações Conhecidas

A lógica antiga de sincronização de boot `fire_sync` permanece e continua
correta: em hardware real os latches INPT podem ler como pressionados nos
primeiros quadros após o RESET, então adotar o estado de boot sem disparar
continua sendo necessário.

## Próximos Passos Lógicos

- Opcionalmente adicionar um teste automatizado de input baseado em Stella
  (por exemplo, script no Stella para verificar que uma captura de tela muda
  quando o fogo é segurado), de modo que essa classe de incompatibilidade
  entre emulador e teste seja detectada no CI.