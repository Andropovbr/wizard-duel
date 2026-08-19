# Mudança: correção do deslocamento de mesma linha na tabela de eventos (estiramento vertical)

## Objetivo

Corrigir um bug visual grave reportado em `round-5-basic-hp`: com os dois
jogadores vivos, quando um míssil cruzava visualmente a Ball, o(s)
Jogador(es), a Ball e/ou o Míssil ficavam verticalmente esticados até a
borda inferior da tela, como se um registrador de renderização tivesse sido
habilitado e seu evento OFF nunca tivesse acontecido. Corrigir apenas no
branch atual (sem branch novo, sem merge na main), sem nova jogabilidade: a
Ball não deve interagir logicamente com mísseis; a sobreposição visual é
simplesmente ignorada.

## Sintoma

* Os dois jogadores vivos e visíveis, um míssil ativo; quando o míssil
  cruzava/atingia visualmente a Ball, o(s) Jogador(es), a Ball e/ou o Míssil
  ficavam verticalmente esticados até a borda inferior da tela.
* Com apenas um jogador vivo/visível o problema não aparecia no cenário
  reportado.

## Reprodução

Reproduzido de forma determinística na ROM real (emulador executando
`BuildEvents` diretamente). Com `P0Y=88, P1Y=50, ball_y=96, m0_y=96,
m1_y=100` (M1 inativo), as linhas OFF coincidem: P0 OFF, Ball OFF e M0 OFF
caem todas na linha 100. O builder produziu uma tabela com uma entrada de
**delta 0** na linha 100 (M0 OFF), de modo que o míssil ficava habilitado da
linha 96 até o fundo da tela.

A investigação também confirmou que a variante com um jogador morto
reproduz a mesma causa raiz (`hp1=0` ainda gera um M0 OFF com delta 0),
portanto o invariante real é *quaisquer três eventos coincidindo numa linha
em que os dois primeiros já se fundiram numa dupla*, e não estritamente "os
dois jogadores vivos". O gatilho realista em jogo é os dois jogadores vivos
na mesma linha, os dois mísseis voando e a bola cruzando as linhas dos
mísseis.

## Causa raiz

`InsertEvent` funde dois eventos na mesma linha em uma entrada dupla (5
bytes, duas escritas) para que nenhuma scanline precise de mais de duas
escritas. Um terceiro evento numa linha que já contém uma dupla é deslocado
para a linha+1 (`INC evRow`) e a varredura continua. O bug estava em
`.insertSingle` (src/main.asm): quando a varredura terminava (terminador
alcançado, ou uma entrada posterior com linha maior), ele gravava a **linha
original empilhada** em vez do `evRow` efetivo (possivelmente deslocado).
Duas entradas de tabela caíam então na mesma linha absoluta. `ConvertDeltas`
calculava `delta = linha - linhaAnterior = 0` para a segunda, e no kernel o
`DEC evCnt` virava `0 -> $FF`, de modo que essa entrada nunca disparava: o
evento OFF era perdido e o registrador ficava habilitado até o fim do kernel
(a inicialização do overscan o limpa, mas o objeto era desenhado até a borda
inferior).

O modelo Python em `tests/test_events.py` estava correto (usa a linha
deslocada), por isso os testes de modelo passavam enquanto a ROM real estava
quebrada.

## Correção

`.insertSingle` agora remove e descarta a linha original empilhada e grava
`evRow` (a linha efetiva, possivelmente deslocada) na tabela. O caminho sem
deslocamento não muda (`evRow` é igual à linha empilhada nesse caso); o
caminho de fusão já estava correto. A tabela permanece estritamente ordenada,
então nenhuma entrada de delta 0 pode existir em estado válido.

Alternativa rejeitada: atualizar a linha empilhada a cada deslocamento com
truques de ponteiro de pilha. Mais complexo e mais lento sem benefício, pois
apenas `.insertSingle` consome a linha empilhada.

## Adicionado

* `tests/test_event_collision.py` (18 testes):
  * testes reproduce-first para as combinações exatas reportadas (dois
    vivos e um morto), verificando uma tabela válida e estritamente
    crescente;
  * validação semântica do `evTbl` após `BuildEvents` na ROM real: sem delta
    0, linhas de entrada estritamente crescentes, alternância ON-depois-OFF
    por registrador com valores de habilitação corretos, terminador único
    válido e deltas decodificados mapeando para as mesmas linhas absolutas do
    modelo Python validado;
  * testes de objeto esticado que executam o kernel real até KERNEL_SCANLINES
    rastreando GRP0/GRP1/ENABL/ENAM0/ENAM1 e verificam que cada registrador
    desliga exatamente na sua linha de evento OFF;
  * os seis cenários exigidos (P0+P1+Ball; +M0; +M1; +M0+M1; P0 morto; P1
    morto) em linhas coincidentes;
  * linhas de contorno perto de 0, 1, KERNEL_SCANLINES-2 e
    KERNEL_SCANLINES-1.
* `tests/test_frame_timing.py`:
  * `run_frame(inject_at=..., inject_fn=...)` para que os testes possam
    forçar o estado do jogo exatamente quando a CPU atinge BuildEvents (após
    o movimento do VBLANK);
  * `test_no_stretched_objects_when_missiles_cross_ball`: 60 quadros reais
    com o estado de colisão tripla injetado em BuildEvents a cada quadro,
    todos com exatamente 19912 ciclos = 262 scanlines e tabela sem delta 0.

## Modificado

* `src/main.asm`, `.insertSingle`: gravar o `evRow` efetivo em vez da linha
  original empilhada (+2 bytes emitidos, absorvidos pelo padding do ALIGN).
* `docs/en/architecture.md`, `docs/en/timing.md`,
  `docs/pt-BR/arquitetura.md`, `docs/pt-BR/timing.md`: seções da Rodada 7
  documentando a política de colisão de mesma linha, a causa raiz e a
  correção.

## Raciocínio Técnico

A política de deslocamento é deliberada: uma entrada nunca contém três
escritas, o que quebraria o orçamento de 76 ciclos do kernel. O bug era que o
deslocamento avançava `evRow` para a *varredura* mas a *inserção* usava a
linha empilhada obsoleta. Gravar `evRow` restaura o invariante pretendido
(linhas de entrada estritamente crescentes => deltas positivos => cada evento
dispara exatamente uma vez). Isso roda no VBLANK, então o kernel visível não
é tocado e seu timing não muda.

## Impacto de Timing

Antes:
- Scanlines por quadro: 262 (objetos esticados eram artefato visual, não bug
  de comprimento de quadro)
- Trabalho de pior caso do VBLANK: 4455 ciclos
- Margem do VBLANK: 409 ciclos
- Pior caminho do kernel: 65/76 ciclos, folga 11

Depois:
- Scanlines por quadro: exatamente 262, todos os 60 quadros de runtime
- Trabalho de pior caso do VBLANK: 4485 ciclos (+30, um `LDA evRow` extra
  zero-page por `insertSingle` no pior caminho)
- Margem do VBLANK: 379 ciclos (ainda bem dentro da expiração T=77 ~4864)
- Pior caminho do kernel: 65/76 ciclos, folga 11 (kernel intocado)

## Impacto de Memória

Antes:
- ROM: 1296 bytes
- RAM: 51 bytes

Depois:
- ROM: 1296 bytes (os +2 bytes emitidos caem antes da fronteira de página do
  `ALIGN 256` que precede `fineAdjustBegin`, então o high-water mark
  reportado não muda)
- RAM: 51 bytes (sem mudança)

## Testes

Adicionados: `tests/test_event_collision.py` (18 testes), além de
`test_no_stretched_objects_when_missiles_cross_ball` em
`tests/test_frame_timing.py`.
Executados: `python tools/test.py` - 201 testes, todos PASS. Gates de
qualidade (ROM <= 4096, RAM <= 128) PASS. `python tools/benchmark.py` e
`python tools/regression.py` PASS (ROM inalterado vs baseline, RAM +2, folga
do kernel inalterada). Ambos os testes novos foram verificados FALHANDO na
ROM anterior à correção (cobertura de regressão confirmada).

## Limitações Conhecidas

A renderização em pixels é validada no Stella em sessão gráfica local; a
suíte determinística valida a semântica da tabela de eventos e as escritas de
registradores do kernel. Nesta sessão o Stella carregou a ROM headless com
código de saída 0 e renderizou continuamente sob Xvfb (saída de quadros
sustentada, sem crash); capturas em nível de pixel não foram feitas porque
nenhuma ferramenta de snapshot/screenshot está disponível no ambiente de CI.
A variante com um jogador morto ainda pode produzir a mesma causa raiz em
princípio (quaisquer três eventos numa linha), mas é muito mais rara na
prática, pois um jogador morto não contribui eventos.

## Próximos Passos Lógicos

Considerar uma busca por força bruta sobre todas as posições válidas dos
objetos verificando que nenhuma tabela tem delta 0 (a varredura atual cobre
uma grade direcionada). Manter os testes de regressão de delta 0 vivos
conforme novas jogabilidades forem adicionadas, para que um futuro gerador de
eventos não reintroduza silenciosamente a violação do invariante.