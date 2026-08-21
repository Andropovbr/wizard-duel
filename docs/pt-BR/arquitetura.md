# Wizard Duel - Arquitetura

A Rodada 3 adiciona projéteis básicos e substitui o kernel de exibição sem
desvios da Rodada 2 por um kernel orientado a eventos. A Rodada 3.1 reduz a
pegada de RAM de 122 para 48 bytes ao usar entradas de tabela de tamanho
variável e remover os buffers separados de registros/ordem. A Rodada 11
corrige um bug de delta=1 ao fazer o kernel aplicar a tabela de eventos
diretamente em toda scanline (entradas uniformes de 5 bytes, apply direto da
tabela) - veja
[analise-timing-kernel-eventos.md](analise-timing-kernel-eventos.md) para a
análise completa do bug. A Rodada 8 analisa a viabilidade de uma bola
visualmente "arredondada" e documenta por que o hardware Ball do TIA não
pode produzir uma forma não retangular com segurança - veja
[changes/pt-BR/2026-08-20-analise-bola-arredondada.md](../changes/pt-BR/2026-08-20-analise-bola-arredondada.md).

Funcionalidades:

* um quadro NTSC estável de exatamente 262 scanlines
* dois jogadores TIA visíveis simultaneamente (P0 à esquerda, P1 à direita),
  renderizados como raquetes verticais simples
* movimento apenas vertical controlado pelo joystick 1 (P0) e joystick 2 (P1)
* um objeto Bola TIA que se move continuamente e quica nas quatro bordas da
  arena
* cada jogador pode disparar um míssil com o botão de fogo do joystick
  (INPT4 para P0, INPT5 para P1); mísseis voam horizontalmente a 2 px/quadro
  e desaparecem nas bordas da arena
* colisões cruzadas (M0 -> P1, M1 -> P0) são detectadas pelos latches do TIA
  e consomem HP: cada jogador começa com `PLAYER_START_HP = 3` pontos de vida
  (Rodada 5)

Intencionalmente ainda não há sistema de magia, IA, placar ou HUD; as regras
de jogo devem evoluir nas próximas rodadas sem exigir mudanças arquiteturais.
A bola não interage com os mísseis. O contato bola x jogador é detectado pelos
latches do TIA (Rodada 6) e a bola é conduzida horizontalmente no contato
(Rodada 7): o P0 a envia para a direita, o P1 para a esquerda, com o movimento
vertical inalterado; o rebote é uma passagem de custo fixo e sem branches no
overscan. Um jogador morto
continua ocupando a arena, mas não é renderizado e não pode disparar; ainda
não há transição de vitória/fim de jogo.

## Kernel orientado a eventos

Com um segundo par de objetos (os mísseis), o kernel sem desvios da Rodada 2
não cabe mais no orçamento de 76 ciclos por scanline (precisava de ~98 ciclos
para dois jogadores, a bola e dois mísseis). Em vez de calcular o enable de
cada objeto em cada scanline, `BuildEvents` roda durante o VBLANK e escreve
uma tabela (`evTbl`) descrevendo as escritas de registradores que cada
scanline deve executar. O kernel então apenas conta os ciclos até a próxima
entrada e aplica as escritas, mantendo cada scanline bem abaixo de 76 ciclos
(54 no pior caso, veja [timing.md](timing.md)).

Cada entrada da tabela tem tamanho fixo de 5 bytes (Rodada 11):

| byte | significado                               |
| ---- | ----------------------------------------- |
| 0    | delta: scanlines até esta entrada disparar |
| 1    | índice do registrador da primeira escrita |
| 2    | valor da primeira escrita                 |
| 3    | índice do registrador da segunda escrita (0 = nenhuma) |
| 4    | valor da segunda escrita                  |

A entrada é de **escrita única** quando o byte 3 é 0 (essa segunda escrita é
um dummy inofensivo em AUDV0) e de **escrita dupla** caso contrário. Não há
entrada de tamanho variável nem despacho por bit 7: o kernel trata toda
entrada de forma idêntica, então a temporização é constante independentemente
de quantas escritas uma entrada contém.

O kernel aplica a tabela **diretamente em toda scanline** (esta é a correção
de delta=1 que substitui o pipeline pendente em duas fases da Rodada 10). `Y`
sempre aponta uma entrada além da última decodificada, então cada linha lê
suas duas escritas de `evTbl-4,Y` / `evTbl-3,Y` (escrita 1) e `evTbl-2,Y` /
`evTbl-1,Y` (escrita 2) e então conta `evCnt`:

* se `evCnt > 0` a linha é uma linha comum sem evento: 38 ciclos no total;
* se `evCnt == 0` um evento dispara: o kernel carrega o delta da próxima
  entrada em `evCnt`, avança `Y` em 5 e volta ao loop - 54 ciclos;
* se esse delta for `$FF` (`EV_MARKER_VAL`) o kernel termina nesta linha - 46
  ciclos.

Como o bloco de apply roda incondicionalmente no topo de toda linha - antes
de qualquer contagem - um evento na própria linha seguinte (delta 1) não pode
colidir com o evento anterior como acontecia com o pipeline pendente antigo:
cada entrada aplica suas escritas na primeira linha da própria linha de
exibição. Reaplicar a mesma entrada nas linhas entre eventos é idempotente e
inofensivo.

Os primeiros cinco bytes da tabela são uma **entrada dummy** (ambos os
registradores 0, as duas escritas vão para AUDV0), então o apply nas linhas
antes de o primeiro evento disparar toca apenas o registrador dummy
inofensivo. As entradas reais começam no offset 5.

Deltas: a primeira entrada dispara na linha `delta - 1`; cada entrada seguinte
dispara `delta` linhas depois da anterior, então `BuildEvents` calcula
`delta(primeira) = linha + 1` e `delta(próxima) = linha - linhaAnterior`. A
contagem `evCnt` cuida da primeira entrada (inicializada com `nullDelta`) e o
delta do marcador encerra o kernel na linha 185. O kernel não precisa de um
contador de linhas em registrador: a estrutura contagem + marcador fixa a
região visível em exatamente 185 linhas.

### Colisões na mesma linha e ordem de slot de escrita (Rodadas 7/8/11)

Até dez eventos podem cair na mesma linha de scanline (dois jogadores + bola
+ dois mísseis, ON e OFF de cada um). `InsertEvent` mantém a tabela ordenada
por linha e permite no máximo duas escritas por entrada:

* dois eventos na mesma linha se fundem em uma entrada dupla - como as
  entradas são registros uniformes de 5 bytes, o merge apenas preenche
  `reg2/val2` em `+3/+4`; não há deslocamento da cauda (o antigo `ShiftBy2`,
  que estendia uma simples de 3 bytes em dupla de 5, desapareceu);
* um terceiro evento em uma linha que já tem uma dupla é **deslocado para a
  linha+1** e a varredura continua - portanto nenhuma scanline precisa de mais
  de duas escritas, o que protege o orçamento do kernel.

A Rodada 7 corrigiu um bug no caminho de deslocamento: `.insertSingle`
gravava a linha original empilhada do evento mesmo depois do deslocamento. Um
terceiro evento colidindo com uma dupla então produzia **duas entradas na
mesma linha absoluta**, `ConvertDeltas` emitia **delta 0** e o `DEC evCnt` do
kernel virava `0 -> $FF`, de modo que esse evento OFF nunca disparava e o
objeto ficava habilitado até a borda inferior da tela (um estiramento
vertical). O gatilho realista era os dois jogadores vivos na mesma linha,
os dois mísseis voando e a bola cruzando as linhas dos mísseis.
`AppendEvent` agora descarta a linha original empilhada e grava o `evRow`
efetivo (possivelmente deslocado), mantendo a tabela estritamente ordenada
sem entradas de delta 0 em nenhum estado válido.

A temporização de escrita de uma dupla também importa (Rodada 8): o kernel
grava o primeiro registrador no ciclo 15 da CPU e o segundo no ciclo 27
(medidos no emulador determinístico). Uma escrita no TIA só se aplica ao
scanline atual se terminar antes de o feixe passar pela posição horizontal do
objeto. A segunda escrita exige portanto `x >= 13` no modelo conservador de
feixe. O X da bola cobre toda a arena (0..156) e M1 pode chegar a x = 2,
então eles nunca devem ocupar o segundo slot. `InsertEvent` impõe a regra de
slot:

* os eventos da bola e do M1 são inseridos **antes** dos jogadores e do M0,
  então em um merge de mesma linha eles naturalmente tomam a primeira escrita;
* a bola nunca é fundida com o M1 (ambos podem cair abaixo da porta da
  segunda escrita) - o evento posterior é deslocado para a linha+1,
  reutilizando o mecanismo de três-na-mesma-linha.

Com essas regras, toda segunda escrita tem como alvo GRP0 (x=16), GRP1
(x=136) ou ENAM0 (x >= 18), então a garantia horizontal vale para todos os
objetos em todas as posições.

## Layout do código

`src/main.asm` contém o programa completo em um único banco de ROM
`$F000-$FFFF` (4 KiB, sem bankswitching). `src/constants.inc` contém todos os
endereços de registradores de hardware e constantes de build.

| Endereço | Conteúdo                                        |
| -------- | ---------------------------------------------- |
| `$F000`  | `Reset` (inicialização)                        |
| `$F055`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F100`  | `KernelLoop` (kernel de exibição por eventos)  |
| `$F134`  | `OverscanWait` (colisão + efeitos de acerto + loop de WSYNC) |
| `$F148`  | `UpdatePlayers` (entrada do joystick + movimento) |
| `$F181`  | `UpdateBall` (movimento + quique da bola)      |
| `$F1B8`  | `UpdateMissiles` (botões de fogo, movimento)   |
| `$F24D`  | `ProcessCollisions` (custo fixo, sem branches) |
| `$F290`  | `newActiveTbl` (tabela de atualização do m_active) |
| `$F300`  | `ProcessHitEffects` (dano de HP + trava de disparo) |
| `$F338`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F35B`  | `PositionBall` (RESBL + HMBL)                  |
| `$F36D`  | `PositionMissiles` (RESM0/RESM1 + HMM)         |
| `$F39C`  | `BuildEvents` (insere eventos em ordem de linha) |
| `$F58A`  | `AppendEvent` (insere/mescla/desloca uma entrada) |
| `$F60F`  | `fineAdjustTable` (tabela HMP alinhada a página) |
| `$F648`  | `ShiftBy5` (desloca a cauda da tabela em 5)    |
| `$F65F`  | `ConvertDeltas` (linhas -> deltas do kernel)   |
| `$F68C`  | `PosObject` (RESPx/HMPx genérico)              |
| `$F700`  | `fineAdjustBegin` (tabela HMP alinhada a página) |
| `$FFFA`  | Vetores NMI / RESET / IRQ                      |

Não há tabelas de sprites: os dois jogadores são retângulos sólidos
`PADDLE_BITS` desenhados pela tabela de eventos. Os endereços exatos podem
mudar entre builds; os testes automatizados os resolvem pelos arquivos de
símbolos/listing em vez de valores fixos.

## Fluxo de execução por quadro

```
StartOfFrame
 ├─ VSYNC   3 scanlines  (três escritas explícitas em WSYNC)
 ├─ VBLANK 64 scanlines  (TIM64T = 77; gameplay e build de eventos aqui)
 │   ├─ UpdatePlayers    lê SWCHA, move P0/P1, limita à arena
 │   ├─ UpdateBall       move a bola, quica nas bordas
 │   ├─ UpdateMissiles   lê INPT4/INPT5, dispara/move/remove mísseis
 │   ├─ PositionPlayers  posicionamento grosso/fino RESP0/RESP1 + HMP0/HMP1
 │   ├─ PositionBall     posicionamento RESBL + HMBL
 │   ├─ PositionMissiles posicionamento RESM0/RESM1 + HMM0/HMM1
 │   └─ BuildEvents      reconstrói a tabela de eventos do kernel visível
 ├─ KERNEL 185 scanlines (loop explícito de WSYNC; apenas renderiza)
 └─ OVERSCAN 10 scanlines (ProcessCollisions + ProcessHitEffects + loop fixo de WSYNC; volta ao StartOfFrame)
```

Entrada, movimento e build de eventos acontecem durante o VBLANK; o kernel
visível apenas aplica as escritas pré-calculadas. O VBLANK é maior que na
Rodada 2 (64 vs 37 linhas) para dar espaço ao `BuildEvents`; o OVERSCAN
encolhe para 10 linhas para manter o quadro em 262.

## Entrada

Os joysticks são lidos da porta de E/S do RIOT `SWCHA` (`$0280`), ativa em
nível baixo: um bit é 0 quando a direção correspondente está pressionada.
Apenas as direções verticais são usadas nesta rodada:

| Porta | Direção | bit SWCHA |
| ---- | --------- | --------- |
| P0 (esquerda, joystick 1) | cima  | D4 |
| P0 (esquerda, joystick 1) | baixo | D5 |
| P1 (direita, joystick 2)  | cima  | D0 |
| P1 (direita, joystick 2)  | baixo | D1 |

`UpdatePlayers` amostra `SWCHA` e aplica no máximo um passo de cima/baixo por
jogador, protegendo as bordas da arena para que a posição nunca ultrapasse os
limites. O valor é consumido imediatamente; nenhuma variável RAM `joystate` é
necessária (uma economia de memória da Rodada 3.1).

## Mísseis

Cada jogador pode disparar um míssil com o botão de fogo. Os botões são lidos
pelos latches INPT do TIA: o bit 7 de `INPT4` (P0) e `INPT5` (P1) é 0 enquanto
pressionado. `UpdateMissiles` amostra os dois botões de forma independente a
cada quadro e dispara na **borda de subida** do botão (solto -> pressionado),
apenas enquanto o míssil daquele jogador estiver inativo:

* segurar o botão não produz uma rajada de mísseis (`fire_prev` guarda o
  estado do quadro anterior);
* uma borda de subida com o míssil ainda voando não cria um segundo míssil
  nem reinicia o existente;
* soltar o botão apenas rearmer a entrada, então a próxima transição solto ->
  pressionado dispara novamente.

O estado dos mísseis é compactado em dois bytes: `m_active` guarda as duas
flags ativas (bit 0 = M0, bit 1 = M1) e `fire_prev` compacta os dois bits dos
botões do quadro anterior mais o bit 7 como flag de sincronização de boot.

**Sincronização de boot**: em hardware real (e no Stella) os latches INPT do
TIA leem as linhas de fogo como pressionadas nos primeiros quadros após o
RESET. A primeira chamada de `UpdateMissiles` após ligar, portanto, apenas
adota o estado real dos botões em `fire_prev` (setando o bit 7 `FIRE_SYNC`),
nunca dispara. Isso garante que iniciar com FIRE solto não produza tiro, e
iniciar com FIRE segurado não produza tiro automático - o jogador precisa
soltar e pressionar novamente.

Um míssil tem `MISSILE_HEIGHT = 4` scanlines de altura e `MISSILE_WIDTH = 2`
pixels de largura (bits de tamanho de míssil do NUSIZ0/NUSIZ1). Ele nasce
`MISSILE_SPAWN_OFFSET = 4` linhas abaixo do seu jogador, mantém essa linha
enquanto voa, move-se horizontalmente a `MISSILE_SPEED = 2` px/quadro e
desaparece na borda da arena:

* M0 (jogador da esquerda): nasce em x = 18, move-se para a direita,
  desaparece em x > 158
* M1 (jogador da direita): nasce em x = 134, move-se para a esquerda,
  desaparece em x < 2

Os mísseis são renderizados na cor da bola (`COLUPF`) e, como a bola, usam a
compensação horizontal `input = x + 8` (são objetos Missile do TIA, não
objetos Player).

## Colisão e pontos de vida

As colisões cruzadas são detectadas pelos latches de colisão do TIA e
resolvidas no overscan, mantendo o kernel visível puramente de renderização:

* **Detecção** (`ProcessCollisions`, início do overscan): lê CXM0P/CXM1P,
  registra os acertos cruzados M0 -> P1 e M1 -> P0 no bitfield de um byte
  `hit_flags` (bit 0 = P0, bit 1 = P1; acertos simultâneos contam os dois),
  limpa o bit do míssil que marcou em `m_active` e escreve `CXCLR` para que um
  acerto nunca seja contado duas vezes. Bits do próprio jogador (M0 x P0,
  M1 x P1) são ignorados. A passagem é sem branches e de custo fixo (117
  ciclos: 84 do caminho de acerto de míssil, +33 do caminho de contato com a
  bola) para que o overscan contado por WSYNC permaneça exato.
* **Contato com a bola** (mesma passagem `ProcessCollisions`, antes do
  `CXCLR`): lê `CXP0FB`/`CXP1FB` e registra Bola x P0 / Bola x P1 (D6 de cada
  latch, `BALL_HIT_P0`/`BALL_HIT_P1`) no byte separado
  `ball_contact_flags` (CONTACT_P0 no bit 0, CONTACT_P1 no bit 1; contatos
  simultâneos contam os dois). Os bits D7 de jogador x playfield são
  ignorados (o playfield nunca é exibido). Contato é apenas informação: sem
  dano, sem alteração de míssil, sem quique da bola, sem mudança em
  `hit_flags`/`m_active`. O byte é deliberadamente separado porque um contato
  da bola não é um acerto de míssil e os bits livres de `m_active`/`fire_prev`
  são reescritos a cada quadro. O registro é sobrescrito a cada overscan,
  então um contato renderizado no quadro N fica visível para o quadro N+1 e
  nunca se repete. Um jogador morto não é renderizado (`BuildEvents` pula
  seus eventos), então o TIA nunca trava um contato de bola x jogador morto e
  nenhuma verificação de HP é necessária.
* **Dano** (`ProcessHitEffects`, mesmo overscan, depois das colisões):
  remove um HP do jogador acertado (sem underflow abaixo de 0; `hit_flags` é
  lido, mas não limpo aqui - `ProcessCollisions` o sobrescreve no próximo
  quadro, então cada acerto é consumido exatamente uma vez) e força o bit de
  FIRE de um jogador morto em `fire_prev` para "pressionado", de modo que
  `UpdateMissiles` nunca veja uma borda de subida (a trava é recalculada todo
  overscan porque `UpdateMissiles` reescreve `fire_prev` todo VBLANK). A
  rotina é alinhada a página e tem branches, mas fica limitada a uma janela
  de 60..80 ciclos que ainda coloca o primeiro WSYNC do overscan na mesma
  fronteira em todos os caminhos.
* **Morte**: um jogador com 0 HP não é renderizado (`BuildEvents` pula seus
  eventos P0/P1) e não pode disparar, mas mantém posição e movimento; um
  míssil que já estava voando sobrevive à morte do dono. Ainda não há
  transição de vitória/fim de jogo - a rodada simplesmente continua.

## Renderização

O kernel visível é orientado a eventos (veja acima). Os dois jogadores são
sprites TIA de cópia única com cores diferentes: P0 é vermelho
(`COLUP0 = $46`) e P1 é azul (`COLUP1 = $84`). Cada sprite é um retângulo
sólido de `%00111100` (raquete de 4 pixels de largura) com `PLAYER_HEIGHT = 18`
linhas. A bola é o objeto Ball do TIA, 4 pixels de largura (CTRLPF D5:D4 =
`%10`) e 4 linhas de altura. A bola é retangular por limitação do hardware
do TIA: o objeto Ball é uma linha horizontal cuja largura é fixa por frame
via CTRLPF, sem suporte a variação de largura por scanline. Uma bola
"arredondada" foi investigada na Rodada 8, mas considerada inviável dentro
da arquitetura table-direct do kernel (veja
[changes/pt-BR/2026-08-20-analise-bola-arredondada.md](../changes/pt-BR/2026-08-20-analise-bola-arredondada.md)).
Os mísseis são os objetos Missile do TIA, 2
pixels de largura e 4 linhas de altura.

A tabela de eventos registra um evento ON (liga o registrador) e um evento
OFF (desliga) nas linhas de exibição de cada objeto:

| objeto | evento ON                              | evento OFF                       |
| ------ | ------------------------------------- | ------------------------------- |
| P0     | `(P0Y, GRP0, PADDLE_BITS)`            | `(P0Y+18, GRP0, 0)`             |
| P1     | `(P1Y, GRP1, PADDLE_BITS)`            | `(P1Y+18, GRP1, 0)`             |
| Bola   | `(ball_y, ENABL, BALL_ENABLE)`        | `(ball_y+4, ENABL, 0)`          |
| M0     | `(m0_y, ENAM0, MISSILE_ENABLE)`       | `(m0_y+4, ENAM0, 0)`            |
| M1     | `(m1_y, ENAM1, MISSILE_ENABLE)`       | `(m1_y+4, ENAM1, 0)`            |

`BALL_ENABLE` e `MISSILE_ENABLE` são `%00000010`: o TIA amostra apenas o bit 1
dos registradores de enable (verificado no código-fonte do Stella), então o
valor `$FF` antigo era desnecessário.

O posicionamento horizontal é fixado a cada quadro com a técnica clássica
RESP0/RESP1/RESM0/RESM1/RESBL + HMP + HMOVE: um strobe grosso posiciona o
objeto em até 15 pixels e um deslocamento fino `HMPx`/`HMMx`/`HMBL` da tabela
`fineAdjustTable` alinhada a página finaliza o trabalho. O `HMOVE` que aplica
os deslocamentos é escrito imediatamente após um `STA WSYNC` na última linha
do VBLANK, como exige o Guia do Programador Stella.

Medido no alvo (TIA/Stella), a rotina renderiza um jogador em
`15*q + (s - 7)` para `q >= 1` e em `3 + (s - 7)` para `q = 0`, onde
`q = input / 15` e `s = input mod 15`. A bola e os mísseis renderizam 1 pixel
à esquerda de um jogador para a mesma entrada, então `PositionBall`/
`PositionMissiles` passam `x + 8` (ou `x + 5` quando abaixo de 15) e os
jogadores passam `X + 7` (ou `X + 4`).

## Movimento e quique da bola

`UpdateBall` move a bola um pixel por quadro nos dois eixos em velocidade
constante. `ball_dx`/`ball_dy` guardam o passo de direção (+1 ou $FF). O
quique é implementado invertendo a direção quando a bola atinge uma borda
exata da arena antes de se mover, então a posição fica sempre dentro do
intervalo válido e nunca pode estourar por underflow sem sinal. `ball_y` é a
primeira linha de exibição; a bola ocupa as linhas `ball_y .. ball_y + 3`. A
bola não colide com os jogadores nem com os mísseis; quica apenas nas quatro
bordas da área de jogo.

## Builder da tabela de eventos

A Rodada 11 usa um builder de inserção direta: `BuildEvents` escreve uma
entrada dummy no offset 0 do `evTbl` e então insere os eventos ON/OFF de cada
objeto direto na tabela em ordem de linha, então não existem buffers
separados de registros ou ordem. Como as entradas são registros uniformes de
5 bytes, a inserção é uma inserção ordenada simples com deslocamento fixo de
5 bytes:

1. `AppendEvent` varre a tabela comparando as linhas das entradas. Em uma
   linha igual, mescla: preenche `reg2/val2` em `+3/+4` (sem deslocamento - a
   entrada já tem 5 bytes de largura). Em uma linha já dupla, desloca o evento
   para linha+1 e continua a varredura (isso só pode acontecer
   transitoriamente durante um único build, então a tabela nunca excede seu
   limite). Caso contrário, desloca a cauda em 5 (`ShiftBy5`) e escreve uma
   nova entrada de 5 bytes. A ordem de inserção codifica a regra de slot: a
   bola e o M1 são inseridos primeiro, então em um merge eles tomam a primeira
   escrita; a bola nunca é fundida com o M1 (deslocada).
2. Depois que todos os eventos são inseridos, `ConvertDeltas` reescreve as
   linhas in-place como deltas do kernel (primeiro delta = linha+1, próximos
   deltas = linha - linhaAnterior, avançando em 5 incondicionalmente) e anexa
   a entrada do marcador cujo delta é `$FF` (`EV_MARKER_VAL`).

Todo evento (único ou dupla mesclada) é uma entrada de 5 bytes, então o
tamanho máximo da tabela é `dummy(5) + 10 * 5 + marcador(5) = 60` bytes.
`EV_TBL_SIZE = 60` é um limite rígido; `tblLen` rastreia o comprimento atual
e um teste afirma que ele nunca excede o limite sob entrada de fogo agressiva.

O delta do marcador (`$FF`) nunca pode disparar dentro do kernel de 185
linhas: é o valor da contagem lido na linha que encerra o kernel.

## Alocação de variáveis

81 de 128 bytes de RAM do RIOT são usados (o kernel de delta=1 e a tabela
uniforme de 60 bytes custam 29 bytes sobre o layout da Rodada 10; documentado
no changelog). O +1 byte em relação à Rodada 11 é `ball_contact_flags`, o
registro de contato bola x jogador da Rodada de contato, deliberadamente
separado de `hit_flags`:

| Endereço  | Nome        | Propósito                              |
| --------- | ----------- | -------------------------------------- |
| `$80`     | `P0Y`       | posição vertical do jogador 0          |
| `$81`     | `P1Y`       | posição vertical do jogador 1          |
| `$82`     | `p0_hp`     | pontos de vida do jogador 0 (0 = morto)|
| `$83`     | `p1_hp`     | pontos de vida do jogador 1 (0 = morto)|
| `$84`     | `ball_x`    | pixel visível mais à esquerda da bola  |
| `$85`     | `ball_y`    | primeira linha de exibição da bola     |
| `$86`     | `ball_dx`   | passo de direção horizontal            |
| `$87`     | `ball_dy`   | passo de direção vertical              |
| `$88-$89` | `m0_x/m0_y` | posição do míssil 0                    |
| `$8A-$8B` | `m1_x/m1_y` | posição do míssil 1                    |
| `$8C`     | `m_active`  | máscara ativa compactada (M0/M1)       |
| `$8D`     | `hit_flags` | resultado de acerto de míssil (bits P0/P1) |
| `$8E`     | `ball_contact_flags` | registro de contato da bola (bits P0/P1) |
| `$8F`     | `fire_prev` | borda de fogo compactada + sync de boot|
| `$90`     | `evCnt`     | contagem regressiva de eventos do kernel |
| `$91-$CC` | `evTbl`     | tabela de eventos (dummy + 10 entradas + marcador, 60B) |
| `$CD`     | `evRow`     | temporário do builder                  |
| `$CE`     | `tempCount` | temporário do builder                  |
| `$CF`     | `tblLen`    | temporário do builder                  |
| `$D0`     | `nullDelta` | valor de inicialização do primeiro delta |

As economias vêm de: flags de míssil compactadas (um byte para dois), nenhum
`fire_sync` separado (bit 7 de `fire_prev`) e nenhum `evIdx` (o kernel lê a
tabela via `Y`, que sempre aponta uma entrada além da última decodificada). Os
bytes dos registradores pendentes do kernel da Rodada 10 sumiram porque o
apply lê direto da tabela.

## Por que VBLANK para gameplay

O kernel visível tem um orçamento de 76 ciclos por scanline. Executar a
decodificação do joystick, o movimento, os quiques e o build da tabela de
eventos lá adicionaria temporização dependente de dados a um caminho de
renderização que precisa ser determinístico. Movê-los para o VBLANK (veja
[timing.md](timing.md)) mantém o kernel estável em exatamente um scanline por
iteração, independentemente da entrada ou do estado do jogo.
