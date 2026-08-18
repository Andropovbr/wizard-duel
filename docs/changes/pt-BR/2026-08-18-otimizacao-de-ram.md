# Mudança: Otimização de RAM com entradas de evento de tamanho variável

## Objetivo

A Rodada 3 terminou com 122 de 128 bytes de RAM do RIOT usados (94,5%),
restando apenas 6 bytes livres. Esta rodada ("3.1") recupera RAM sem mudar
nenhum gameplay: o alvo era caber confortavelmente abaixo de 64 bytes para que
as próximas funcionalidades (ex.: colisões, placar) tenham espaço, preservando
todo o comportamento da Rodada 3 (jogadores, bola, dois mísseis, input de
fogo, 262 scanlines, kernel dentro de 76 ciclos, ROM dentro de 4 KiB).

## Adicionado

* **Entradas de evento de tamanho variável**: as entradas de `evTbl` não são
  mais registros fixos de 5 bytes com duas escritas. Uma entrada simples tem
  3 bytes `[delta, reg1|$80, val1]` (o bit 7 do índice do registrador marca
  isso); uma dupla tem 5 bytes `[delta, reg1, val1, reg2, val2]`. O kernel
  despacha no bit de flag com um único `BMI`; uma scanline que precisa de
  apenas uma escrita pula a segunda (54 ciclos em vez de 65).
* **Builder de inserção direta**: `BuildEvents` não anexa mais registros
  `(linha, reg, val)` nem ordena um array de ordem. Ele insere cada evento de
  fronteira de objeto direto no `evTbl` em ordem de linha, então o buffer de
  registros de 30 bytes, o array de ordem de 10 bytes e o contador de
  registros sumiram.
  * `InsertEvent` varre a tabela comparando linhas; em linha igual mescla uma
    simples em dupla (`ShiftBy2`, cauda deslocada em 2) ou incrementa a linha
    de uma já dupla em +1 e continua. Caso contrário `ShiftBy3` desloca a
    cauda em 3 e escreve uma nova simples.
  * `ConvertDeltas` reescreve as linhas armazenadas in-place como deltas do
    kernel (primeiro delta = linha+1, seguintes deltas = linha - linhaAnterior),
    deixando o terminador `$FF` no fim.
* **Estado de míssil compactado**: `m_active` guarda as duas flags ativas
  (bit0 M0, bit1 M1), substituindo `m0_active` e `m1_active`.
* **Estado de fogo compactado**: a sincronização de boot virou o bit 7 de
  `fire_prev` (`FIRE_SYNC`), substituindo o byte `fire_sync` separado.
* **Novo teste de tempo de execução do quadro** `tests/test_frame_timing.py`:
  dirige o emulador determinístico por muitos quadros e afirma a estabilidade
  do quadro (262 scanlines), que o comprimento da tabela nunca excede
  `EV_TBL_SIZE = 31` sob input de fogo agressivo e que os mísseis de fato
  aparecem e desaparecem pelo pipeline de eventos.
* **Portões de regressão de RAM** em `tools/regression.py`:
  `RAM_PRESSURE_WARN_PCT = 75.0` / `RAM_PRESSURE_STRONG_PCT = 90.0` (de um
  orçamento de projeto de 64 bytes) emitem avisos soft, e usar mais de
  `PROJECT_RAM_BUDGET = 64` bytes é falha hard no CI; o crescimento de RAM
  também é comparado por bytes absolutos e percentual.

## Alterado

* `src/main.asm`: kernel reescrito para entradas de tamanho variável (três
  caminhos: 18 / 54 / 65 ciclos, um `BMI` de despacho adicionado); os antigos
  `AddEvent`, `SortEvents`, `EmitEvents`, `BubbleOrder` foram substituídos por
  `InsertEvent`, `ShiftBy2`, `ShiftBy3`, `ConvertDeltas`; bloco de RAM reescrito
  para 48 bytes; `UpdatePlayers` relê `SWCHA` para cada direção (o byte
  `joystate` sumiu); `UpdateMissiles` usa a máscara `m_active` compactada e o
  bit `FIRE_SYNC`.
* `src/constants.inc`: `EV_TBL_SIZE = 31`, `EV_SINGLE_FLAG = $80`,
  `M0_BIT`/`M1_BIT`, `FIRE_SYNC`.
* `tools/emu6502.py`: adicionado `BMI` (opcode 0x30) ao emulador para que os
  testes de quadro possam executar o despacho do kernel.
* `tools/benchmark.py`: a simulação de pior caso do kernel agora reporta o
  caminho de evento de duas escritas (65 ciclos).
* `tools/regression.py`: portões de pressão/orçamento de RAM (veja Adicionado).
* Testes atualizados: `test_timing.py` (três caminhos do kernel, walker de
  duas escritas), `test_events.py` (reescrito para modelar o builder de lista
  de bytes), `test_rom.py` (novos símbolos), `test_memory.py` (48 bytes),
  `test_ball.py` (comentário do orçamento de RAM), `test_missile_fire.py`
  (decodificação do estado compactado), `test_regression.py` (nova base de RAM
  + casos de pressão/orçamento).
* Documentação atualizada (EN + pt-BR).

## Removido

* Byte `joystate` (o input é relido da porta a cada uso).
* Byte `evIdx` (o kernel mantém o offset da tabela em Y pelo quadro inteiro em
  vez de armazená-lo entre linhas).
* Byte `fire_sync` (dobrado no bit 7 de `fire_prev`).
* Bytes `m0_active` / `m1_active` (dobrados na máscara `m_active`).
* `events` (30B), `evCount` (1B), `evOrder` (10B) e os temporários do builder
  (8B) - o builder de inserção direta não precisa de espaço de registros/ordem.
* Sub-rotinas `AddEvent` / `SortEvents` / `EmitEvents` / `BubbleOrder`.

## Raciocínio Técnico

### Por que entradas de tamanho variável

As entradas fixas de 5 bytes da Rodada 3 eram uma simplificação: "toda entrada
sempre faz duas escritas" mantinha o caminho de evento linear, mas obrigava
cada fronteira de objeto a consumir 5 bytes mesmo quando só um registrador
precisava de escrita, e empurrava o kernel para 69 ciclos. Duas observações
tornaram entradas variáveis baratas:

1. A tabela é construída em RAM a cada quadro e indexada por Y, então o kernel
   pode ler o bit de flag da própria entrada e ramificar uma vez (`BMI`). Um
   desvio condicional único no caminho de evento é aceitável: os dois
   desfechos são lineares, então ambos têm tempo fixo (54 vs 65 ciclos).
2. Todo valor de escrita é um registrador de enable (`$00`, `PADDLE_BITS`,
   `BALL_ENABLE`, `MISSILE_ENABLE`), nenhum seta o bit 7, então a flag pode
   morar no byte do índice do registrador sem roubar um bit de valor.

### Por que inserção direta em vez de registros + ordenação

O builder da Rodada 3 escrevia registros e ordenava um array de ordem
justamente para manter o custo por quadro dentro do VBLANK. Com entradas
variáveis não há tamanho fixo de registro para ordenar barato, e os 40 bytes
de scratch anulariam a meta de memória. Inserir direto na tabela custa mais
ciclos (deslocamentos de uma cauda variável), mas fica bem dentro da janela de
`69*64 = 4416` ciclos do VBLANK; os 40 bytes de RAM economizados valem muito
mais para o projeto do que os ciclos sobrando do VBLANK.

### Por que os loops ShiftBy usam `CPX`/`BNE` e não `CPX`/`BCS`

A primeira implementação contava deslocamentos com `DEX` e terminava com
`CPX tempCount; BCS`. `DEX` faz wrap de 0 para $FF, então quando o loop
chegava a zero (e com os valores de registrador envolvidos) o `BCS` nem sempre
terminava, causando loop infinito que corrompia memória e pilha.
`CPX tempCount; BNE` é a terminação correta: sai assim que X iguala o índice
salvo, independente do wrap do `DEX`.

### Por que `InsertEvent` empurra a linha

`InsertEvent` guarda a linha, o registrador e o valor atuais e pode chamar
`ShiftBy2`/`ShiftBy3`. Cada sub-rotina precisa do registrador/valor na pilha, e
o caminho de mescla precisa da linha de novo após o deslocamento para decidir
se avança a varredura. Um `PHA` ausente para a linha produziu desbalanceamento
de pilha: a rotina tirava mais bytes do que empurrava, retornando para um
endereço de retorno corrompido. Os três valores agora são empurrados e
retirados simetricamente em todos os caminhos.

### Por que a tabela é limitada a 31 bytes

A tabela começa como um terminador de 1 byte `$FF`. Dez fronteiras de objeto
são inseridas (P0/P1 on/off, bola on/off, M0/M1 on/off). Uma simples tem
3 bytes, uma dupla 5. O pior caso de tamanho é toda fronteira em linha própria
(sem mescla): 10 simples * 3 = 30 bytes mais o terminador de 1 byte = 31
bytes. Mesclar um par em dupla só reduz o total (2 simples = 6 bytes viram
5). `EV_TBL_SIZE = 31` é, portanto, um limite rígido exato; um teste de tempo
de execução afirma que o builder nunca o excede sob input de fogo agressivo.

### Por que o caminho de duas escritas ficou mais barato que a Rodada 3

O novo caminho duplo lê o byte de flag uma vez e, como o caminho simples é
mais curto, o caminho duplo não precisa mais do vai-e-volta `STY evIdx` entre
o par de escritas e o carregamento do próximo delta - Y fica vivo pelo quadro
inteiro. O pior caminho cai de 69 para 65 ciclos (folga 7 -> 11).

### Por que as portas de tempo de escrita mudaram para 30/72

Com as duas escritas agora nos ciclos 30..33 e 44..47 (caminho duplo), uma
escrita se aplica ao scanline atual apenas se o feixe ainda não passou pela
posição horizontal do objeto. Usando o modelo padrão de feixe (pixel p
atingido no ciclo ~(p+69)/3), as portas são x >= 30 e x >= 72. P0 (x=16) e P1
(x=136) estão bem fora das duas faixas, então seu comportamento é idêntico ao
da Rodada 3; nenhum objeto desta rodada fica nas faixas 30..32 / 72..74.

## Impacto de Timing

Antes (Rodada 3):
- Scanlines do quadro: 262
- Pior caminho do kernel: 69 / 76 ciclos (linha de duas escritas, folga 7)
- Melhor caminho do kernel: 18 / 76 ciclos (linha sem evento)

Depois (Rodada 3.1):
- Scanlines do quadro: 262 (estável; o teste de tempo de execução roda muitos quadros)
- Pior caminho do kernel: 65 / 76 ciclos (linha de duas escritas)
- Caminho de escrita única do kernel: 54 / 76 ciclos (novo)
- Melhor caminho do kernel: 18 / 76 ciclos (linha sem evento)
- Folga: 11 ciclos na pior linha de evento (era 7)

## Impacto de Memória

Antes (Rodada 3):
- ROM: 1296 / 4096 bytes (31,6%)
- RAM: 122 / 128 bytes (95,3%)

Depois (Rodada 3.1):
- ROM: 1296 / 4096 bytes (31,6%)
- RAM: 48 / 128 bytes (37,5%), 80 bytes livres

A RAM caiu 74 bytes (122 -> 48) sem crescimento de ROM: a tabela de tamanho
variável (31 vs 55 bytes), nenhum buffer de registros/ordem (40 bytes) e os
quatro bytes compactados contribuem. O jogo agora fica em 48 de um orçamento
de projeto de 64 bytes.

## Testes

Adicionado `tests/test_frame_timing.py` (estabilidade do quadro, limite da
tabela sob fogo agressivo, spawn/despawn de mísseis pelo pipeline de
eventos). Reescrito `tests/test_events.py` para modelar o builder de lista de
bytes (inserção, mescla simples em dupla, bump de linha dupla, deslocamento
2/3, conversão de deltas, linhas de disparo). Atualizados `test_timing.py`,
`test_rom.py`, `test_memory.py`, `test_ball.py`, `test_missile_fire.py`,
`test_regression.py`. Todos os 143 testes passam; o build reporta
1296 ROM / 48 RAM.

## Limitações Conhecidas

* `BuildEvents` custa algumas centenas de ciclos de VBLANK a mais que a
  Rodada 3 (deslocamentos de uma cauda variável); ainda bem dentro da janela
  do VBLANK.
* Um bump transitório de linha dupla (linha+1) ainda pode ocorrer durante a
  inserção, mas apenas uma vez por build e nunca além do limite da tabela.
* O teste de tempo de execução do quadro afirma contagem de scanlines e
  comportamento, não totais de ciclos exatos (o contador de ciclos do emulador
  é aproximado).
* O uso de RAM agora é medido em 48 bytes; a suíte de regressão compara com o
  baseline persistido da Rodada 1, então o pico de 122 bytes da Rodada 3 fica
  visível no histórico em vez de escondido.

## Próximos Passos Lógicos

* Colisões de míssil/jogador e bola/jogador agora têm 80 bytes de margem de
  RAM.
* Considerar um byte de estado de colisão separado ou um pequeno HUD.
* Mover parte do build de eventos para o OVERSCAN se a pressão do VBLANK
  voltar.