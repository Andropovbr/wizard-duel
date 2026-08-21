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
  (4 bytes, $81-$84)
- Rotina `HandleInput`: detecta borda do SELECT (alterna modo no menu) e
  RESET (menu → jogo, jogo → menu)
- Rotina `InitGame`: reinicializa todo o estado do jogo, restaura HP,
  limpa mísseis/flags, transiciona para STATE_PLAYING
- Gate de game_state no VBLANK: modo menu pula UpdatePlayers/UpdateBall/
  UpdateMissiles, define cor do indicador P0, define p1_hp=0 para ocultar P1
- Visual do menu: P0 colorido vermelho (DUEL) ou azul (SCORE), P1 oculto
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

## Raciocínio Técnico

### RESET do Atari 2600 É um Switch Legível

No Atari 2600, RESET NÃO é um reset de hardware — é um switch legível
(SWCHB bit 2). Apenas o ligamento da limpa a RAM via o vetor Reset.
Isso significa que `game_state` começa em 0 (STATE_MENU) a partir da
limpeza da RAM, e RESET deve ser detectado por borda para transitar
entre estados.

### Interação com o Lock de Fire de Jogador Morto

`ProcessHitEffects` é executado incondicionalmente durante o overscan.
Quando `p1_hp=0` (definido pelo visual do menu para ocultar P1), ele
OR `FIRE_P1` em `fire_prev`, bloqueando permanentemente o input de
fire do P1. Esse é o comportamento correto para jogadores mortos durante
o jogo, mas no modo menu fazia com que P1 nunca atirasse após a
transição para STATE_PLAYING.

Correção: `InitGame` limpa `fire_prev` ao entrar no estado de jogo, e
os harnesses de teste simulam a borda de subida do RESET para acionar
`InitGame` em vez de definir `game_state` diretamente.

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
- RAM: 85 bytes (+4: game_state, game_mode, select_prev, reset_prev)

## Testes

- 261 testes passam
- Todos os gates de qualidade passam (ROM ≤ 4096, RAM ≤ 128, 262 scanlines)
- Novos padrões de teste: simulação de RESET via borda de subida para
  transição adequada do InitGame nos harnesses de teste

## Limitações Conhecidas

- SELECT só funciona no STATE_MOUSE (por design)
- Sem feedback visual ainda para seleção de modo além da cor do P0
- Modo do jogo é preservado nas transições menu ↔ jogo

## Próximos Passos Lógicos

- Adicionar indicação visual para DUEL vs SCORE (ex: cor de fundo
  diferente, texto ou ícone)
- Implementar diferenças de gameplay no modo SCORE
- Adicionar texto ou animação na tela de seleção
- Considerar efeitos sonoros para feedback de SELECT/RESET
