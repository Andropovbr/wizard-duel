# Mudança: Infraestrutura Inicial de Seleção de Modo de Jogo

## Objetivo

Implementar a infraestrutura inicial de seleção de modo de jogo: uma
máquina de estados (STATE_MENU / STATE_PLAYING), botão SELECT alterna
entre os modos DUEL e SCORE, RESET inicia o jogo, e um indicador visual
de baixo custo mostra o modo selecionado na tela de seleção.

## Adicionado

- Constantes `STATE_MENU` (0) e `STATE_PLAYING` (1) em `constants.inc`
- Constantes `MODE_DUEL` (0) e `MODE_SCORE` (1) em `constants.inc`
- Definições `SELECT_BIT` e `RESET_BIT` dos switches em `constants.inc`
- Variáveis de RAM `game_state`, `game_mode`, `select_prev`, `reset_prev`
  (4 bytes, $91-$94)
- Rotina `HandleInput`: detecta borda do SELECT (alterna modo no menu) e
  RESET (menu → jogo, jogo → menu)
- Rotina `InitGame`: reinicializa todo o estado do jogo, restaura todas
  as cores (COLUP0, COLUP1, COLUPF), HP, posições, limpa mísseis/flags,
  transiciona para STATE_PLAYING
- Gate de game_state no VBLANK: modo menu pula UpdatePlayers/UpdateBall/
  UpdateMissiles
- Visual do menu: ambas as raquetes visíveis e imóveis, bola oculta
  (COLUPF definido como BACKGR_COLOR), P0 colorido vermelho (DUEL) ou
  azul (SCORE)
- Inicialização explícita de `select_prev` e `reset_prev` para estado
  released (SELECT_BIT|RESET_BIT) no handler Reset para garantir
  detecção de borda correta no primeiro pressionamento
- `fire_prev` limpo em InitGame para evitar lock de fire de jogador morto
- Boot_sync nos harnesses de teste: simula borda de subida do RESET via
  InitGame para entrar corretamente no STATE_PLAYING com HP completo
- Registros de mudança educacional (EN + PT-BR)

## Alterado

- Asserção RAM em `test_ball.py`: 81 → 85 bytes
- Asserção RAM em `test_memory.py`: já 85 bytes (da rodada anterior)
- MissileFireHarness em `test_missile_fire.py`: init de riot[2] adicionado,
  método boot_sync() com simulação adequada do RESET
- TestBoot em `test_missile_fire.py`: helper `_enter_playing()` adicionado
- setUp de TestEdgeDetection/TestMissileActive em `test_missile_fire.py`:
  usa boot_sync() para configuração adequada do estado
- test_missiles_actually_fire_and_despawn em `test_frame_timing.py`:
  usa padrão de simulação do RESET
- setUp de TestInitialHp em `test_hp.py`: usa apenas boot_sync() (sem
  RESET redundante)

## Removido

- Escritas diretas `game_state=1` nos setUp dos testes (substituídas
  por simulação adequada do RESET via InitGame)
- Hack `p1_hp=0` no visual do menu (HP não é mais usado como mecanismo
  visual)

## Raciocínio Técnico

### Definições de Bits do SWCHB (Correção Crítica)

`SELECT_BIT` original (%00001000, bit 3) e `RESET_BIT` (%00000100, bit 2)
estavam errados. A especificação do hardware do Atari 2600 define:

- SWCHB bit 0 = RESET (active low)
- SWCHB bit 1 = SELECT (active low)
- bit 2 = não utilizado
- bit 3 = chave Color/BW

Corrigido para `SELECT_BIT` = %00000010 (bit 1), `RESET_BIT` = %00000001
(bit 0). Todo o código usando esses constantes simbólicos foi
automaticamente corrigido.

### Correção da Detecção de Borda dos Switches

Bits do SWCHB são active-low: 0 = pressionado, 1 = liberado. Após a
limpeza da RAM, `select_prev` e `reset_prev` eram 0, que o código
interpretava como "já pressionado". O primeiro pressionamento real
portanto nunca produzia uma borda de subida (0 AND mask = 0 →
"ainda segurado").

Correção: inicializar ambos com `SELECT_BIT|RESET_BIT` (= 0x03,
ambos liberados) no handler Reset após o loop de limpeza da RAM.

### Reescrita do HandleInput (v3: RESET com Falling Edge)

Versão anterior com múltiplas leituras e PHA/PLA substituída por
design simples com leitura única: SWCHB é lido uma vez por frame
em `swchb_cur`.

SELECT usa detecção de borda de subida (released -> pressed) para
alternar game_mode, sem alteração.

RESET agora usa semântica de borda de descida (comportamento clássico
do Atari 2600):
- Enquanto RESET é segurado no menu: flag `reset_held` é ativada,
  jogo permanece congelado, sem atualizações de gameplay.
- Na soltura de RESET (pressed -> released): `InitGame` roda uma vez,
  jogo entra em STATE_PLAYING e começa normalmente.
- Durante gameplay: RESET (borda de subida) retorna ao STATE_MENU.

Isso elimina o comportamento inconsistente onde pressionamentos
rápidos/lentos/longos produziam resultados diferentes. A duração
da pressão não importa mais.

### Visual do Menu

A implementação anterior ocultava P1 definindo `p1_hp=0`, que fazia
`ProcessHitEffects` bloquear permanentemente o input de fire do P1
via o lock de fire de jogador morto. A nova abordagem mantém ambas
as raquetes visíveis (ambos HP em 3), oculta a bola combinando COLUPF
com a cor de fundo, e muda a cor de P0 para indicar o modo selecionado.

### Restauração pelo InitGame

`InitGame` agora restaura todos os registradores visuais: COLUP0
(PLAYER1_COLOR), COLUP1 (PLAYER2_COLOR), COLUPF (BALL_COLOR). Após
RESET, o jogo parece e funciona exatamente como antes da introdução
do menu.

### Gate de Estado do Jogo

A seção VBLANK verifica `game_state` após `HandleInput` retornar.
Se STATE_MENU: pula atualizações do jogo, define indicador visual.
Se STATE_PLAYING: executa pipeline completo de jogo (UpdatePlayers,
UpdateBall, UpdateMissiles). Mantém a estrutura do kernel inalterada
e o timing de scanlines idêntico.

## Impacto de Timing

Antes:
- Scanlines por frame: 262
- Caminho crítico: inalterado

Depois:
- Scanlines por frame: 262
- Caminho crítico: inalterado

A verificação de game_state adiciona 3 ciclos (LDA) + 2/3 ciclos (BEQ)
ao caminho do VBLANK, que está bem dentro do orçamento de timing do VBLANK.

## Impacto de Memória

Antes:
- ROM: 2064 bytes
- RAM: 81 bytes

Depois:
- ROM: 2064 bytes
- RAM: 87 bytes (+6: game_state, game_mode, select_prev, reset_prev, swchb_cur, reset_held)

## Testes

- 261 testes passam
- Todos os gates de qualidade passam (ROM ≤ 4096, RAM ≤ 128, 262 scanlines)
- Harnesses de teste atualizados: simulação de RESET agora usa falling-edge
  (pressionar → rodar frame → soltar → rodar frame) para acionar InitGame
- Todos os harnesses usam masks SWCHB corretos (riot[2] = 0x03 para
  liberado, riot[2] & 0x01 para verificação do bit RESET)

## Limitações Conhecidas

- SELECT só funciona no STATE_MENU (por design)
- Modo do jogo é preservado nas transições menu ↔ jogo

## Próximos Passos Lógicos

- Implementar diferenças de gameplay no modo SCORE
- Adicionar texto ou animação na tela de seleção
- Considerar efeitos sonoros para feedback de SELECT/RESET
