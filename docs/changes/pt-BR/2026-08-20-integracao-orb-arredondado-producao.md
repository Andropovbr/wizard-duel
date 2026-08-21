# Mudança: Integração em Produção do Orb Arredondado

## Objetivo

Integrar o orb diamante (bola arredondada) no kernel de produção,
substituindo a bola retangular 4x4 com uma forma visual arredondada
de 2-4-4-2 pixels usando alterações de largura CTRLPF por linha e
posicionamento fino via HMBL.

## Adicionado

- **Mini-loop orb no kernel** (`src/main.asm:368-395`): Escreve CTRLPF e
  ENABL por linha do orb antes do bloco de aplicação de eventos.
  Forma diamante: estreito (1px) - largo (4px) - largo (4px) - estreito (1px).

- **Variável de estado orb** (`src/main.asm:1829`): `orb_row_idx` (1 byte)
  conta regressivamente de BALL_HEIGHT até 0 durante o mini-loop orb.

- **Tabela de largura orb** (`src/main.asm:971-974`): Tabela de busca
  de 4 bytes mapeando orb_row_idx para valores CTRLPF (estreito/largo).

- **Constantes orb** (`src/constants.inc:249-270`): ORB_CTRLPF_NARROW,
  ORB_CTRLPF_WIDE.

- **Testes de regressão orb** (`tests/test_orb.py`): 6 testes cobrindo
  ausência de eventos da bola, timing de frame e coexistência com
  eventos P0/P1.

## Alterado

- **BuildEvents** (`src/main.asm:1260-1270`): A bola é removida da
  máscara ativa.  Eventos da bola nunca são gerados; o mini-loop orb
  processa toda renderização da bola.

- **Entrada do kernel** (`src/main.asm:259-273`): Inicializa orb_row_idx
  baseado na visibilidade de ball_y.

- **Loop do kernel** (`src/main.asm:368-417`): Adicionada verificação
  de restauração CTRLPF (10 ciclos em linhas não-orb) e escritas orb
  (CTRLPF + ENABL) antes do bloco de aplicação de eventos.

- **emu6502.py**: Adicionado suporte a LDA abs,X (opcode $BD); limite
  de passos aumentado de 2M para 4M para kernel mais pesado.

- **test_timing.py**: Atualizado OPC_CYCLES com novos opcodes;
  atualizadas assertions de orçamento de ciclos (54/70/62 vs 38/54/46);
  atualizada contagem de branches (4 vs 2).

- **test_events.py**: Atualizado modelo Python de eventos para excluir
  bola do conjunto ativo; atualizadas expectations dos testes afetados.

- **test_memory.py / test_ball.py**: Atualizada assertion de RAM de
  81 para 82.

- **test_regression.py**: Atualizada assertion de slack do kernel de
  22 para 6.

## Removido

- Geração de eventos da bola do BuildEvents (sem eventos ENABL na tabela).

- Varredura da bola do loop de seleção do BuildEvents (código morto removido).

## Raciocínio Técnico

### Decisão de Design: HMBL em vez de RESBL

O protótipo R&D provou que posicionamento RESBL por linha é custoso demais:
o loop de atraso DEX/BNE custa 7 ciclos/iteração, excedendo o orçamento
do kernel para ball_x > ~15.  Posicionamento fino HMBL (definido uma vez
no VBLANK) elimina esse custo completamente.

### Timing da Escrita CTRLPF

CTRLPF é escrito no ciclo 10-16 (antes do feixe atingir ball_x em
~ciclo 49 para x=78).  ENABL é escrito no ciclo 13-21.  Ambos são
seguros para todas as posições X válidas dentro da área visível.

### Compatibilidade do Bloco de Aplicação de Eventos

O bloco de aplicação de eventos escreve em AUDV0 (entrada dummy, reg2=0)
e em registradores TIA específicos para eventos P0/P1/M0/M1.  Nunca
alvo ENABL, então a escrita ENABL do orb é segura contra sobreposição.

### Orçamento de Ciclos do Kernel

- Caminho sem evento: 54 ciclos (+16 do baseline 38)
- Caminho com evento: 70 ciclos (+16 do baseline 54)
- Caminho marcador: 62 ciclos (+16 do baseline 46)
- Todos dentro do orçamento de 76 ciclos (slack = 6 ciclos)

## Impacto de Timing

Antes:
- Scanlines do frame: 262
- Kernel pior caso: 54/76 ciclos (slack 22)

Depois:
- Scanlines do frame: 262 (verificado com 10000 frames)
- Kernel pior caso: 70/76 ciclos (slack 6)

## Impacto de Memória

Antes:
- ROM: 1808 bytes
- RAM: 81 bytes

Depois:
- ROM: 1808 bytes (mesmo - remoção de código de eventos da bola
  compensou adições do orb)
- RAM: 82 bytes (+1 para orb_row_idx)

## Testes

- 261 testes existentes: todos passam (assertions atualizadas)
- 6 novos testes orb: todos passam
- Teste de estabilidade de 10000 frames: todos com exatamente 262 scanlines

## Limitações Conhecidas

- Slack do kernel reduzido de 22 para 6 ciclos.  O caminho com evento
  a 70 ciclos deixa apenas 6 ciclos de margem.  Quaisquer adições
  futuras ao kernel devem ser cuidadosamente orçadas.

- Restauração CTRLPF executa em cada linha não-orb (10 ciclos de
  overhead).  Uma abordagem de restauração única poderia economizar
  ~5 ciclos por linha não-orb, mas adicionaria complexidade.
