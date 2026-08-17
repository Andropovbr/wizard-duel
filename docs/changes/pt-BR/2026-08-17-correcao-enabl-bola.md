# Change: Correção do timing do ENABL (deslocamento vertical da bola)

## Objetivo

Corrigir o defeito visual da Rodada 2 no qual o Ball do TIA aparecia
deslocado verticalmente em cerca de uma scanline em certas regiões
horizontais da tela, mantendo intactos o movimento fluido de 1 px/quadro da
bola e o quadro de 262 scanlines. Um objetivo secundário: recuperar a folga
de timing do kernel, que havia caído para 2 ciclos, e remover o timing
dependente de dados que restava no caminho de exibição.

## Causa raiz

O kernel antigo escrevia `ENABL` tarde na scanline (~ciclo 67, e entre ~ciclo
55 e 68 dependendo de quais caminhos de sprite dos jogadores eram tomados). O
projeto antes assumia que `ENABL` é travado (latched) para a scanline
seguinte, mas o TIA amostra o bit de habilitação da bola **na posição
horizontal da bola** ("This graphics bit is scanned (outputted) only when
triggered by its corresponding position counter" - Guia do Programador
Stella; escritas em `ENABL` têm "immediate effects" - notas TIA de Andrew
Towers). Consequentemente, se uma dada scanline desenhava a bola com o valor
de habilitação da linha atual ou da anterior dependia de `ball_x` em relação
à posição do feixe no momento da escrita. Como esse ciclo de escrita variava
com os caminhos dos jogadores, a bola pulava uma scanline em algumas regiões
horizontais e sua forma 4x4 ficava irregular.

Os jogadores não eram afetados por dois motivos: seus gráficos são escritos
bem antes de o feixe alcançar sua posição horizontal fixa (o P0 em x=16 é
alcançado em ~ciclo 28.3, enquanto `GRP0` é escrito em ~ciclo 25; o P1 em
x=136 em ~ciclo 68, enquanto `GRP1` é escrito em ~ciclo 49), e seu X é
constante, então o teste "antes ou depois do feixe" nunca muda para eles.

### Abordagem rejeitada: VDELBL

O uso de `VDELBL` foi analisado e rejeitado. Com `VDELBL = 1`, a saída da
bola usa o registrador "old" de `ENABL`, que é recarregado de "new" a cada
escrita de `GRP1`. Como `GRP1` é escrito no meio da scanline, o registrador
"old" ainda muda no meio da linha, então a saída da bola continuaria
dependente de `ball_x` (a transição apenas se move para o ponto da escrita de
`GRP1`). `VDELBL` não torna a renderização da bola independente do tempo e,
por isso, não é usado.

## Correção

O kernel agora escreve `ENABL` durante o blanking horizontal de toda
scanline: `STA ENABL` imediatamente após `STA WSYNC`, completando em ~ciclo
5, bem antes do primeiro pixel visível (~ciclo 22.7). O valor de habilitação
é **pré-calculado no fim da scanline anterior** para a linha atual e
transportado em `A` pela aresta de retorno do loop, então nenhum byte de RAM
é necessário. A bola passa a ser desenhada em exatamente `BALL_HEIGHT` linhas
consecutivas, independentemente de `ball_x`.

Isso forçou uma mudança estrutural: com `ENABL` abrindo a scanline, um
jogador dirigido por tabela (`LDA` indexado + `JMP`, 23 ciclos) não conseguiria
mais escrever `GRP0` antes de o feixe alcançar x=16 com folga segura. Os dois
jogadores são retângulos sólidos na Rodada 2, então passaram a ser
renderizados como retângulos constantes sem ramificações (18 ciclos cada)
usando a nova constante `PADDLE_BITS`.

## Adicionado

- Constante `PADDLE_BITS = %00111100` (`src/constants.inc`); o kernel usa
  `AND #PADDLE_BITS` após o teste "desenha ou apaga" `LDA #0 / SBC #0`.
- `LDA #0 / STA ENABL` explícito na inicialização do overscan, para que o
  registrador nunca possa manter 1 no overscan mesmo quando a bola está no
  fundo da arena.
- `BALL_ENABLE = $FF` (o valor produzido pelo truque `LDA #0 / SBC #0`; só o
  bit 0 importa ao TIA).
- Bloco de comentário no kernel documentando o timing corrigido do `ENABL`,
  a contabilidade sem ramificações e os prazos de escrita de cada objeto.

## Alterado

- `KernelLoop`: `STA ENABL` logo após `STA WSYNC`; os dois jogadores
  renderizados como retângulos sem ramificações; o fim do loop pré-calcula a
  habilitação da bola da próxima linha.
- Testes reescritos para o kernel sem ramificações (veja Testes).
- Documentação atualizada em EN e PT-BR: `timing.md`, `architecture.md` /
  `arquitetura.md`, `memory-map.md` / `mapa-de-memoria.md`, `benchmarks.md`,
  `latest.md`, `history.csv`.

## Removido

- Tabelas `P0Sprite`/`P1Sprite` (24 bytes de linhas idênticas). O padrão de
  linha agora é a constante `PADDLE_BITS`. As tabelas foram removidas porque o
  caminho de renderização com `LDA` indexado não cabe após a escrita de
  `ENABL` que deve abrir a scanline; como as duas linhas são barras sólidas
  idênticas, uma tabela não carregava informação.
- O comentário incorreto "ENABL é travado para a linha seguinte".

## Racional técnico

- **Orçamento da scanline**: o kernel sem ramificações custa 62 ciclos em
  toda scanline (WSYNC 3 + ENABL 3 + P0 18 + P1 18 + fim 20), deixando 14
  ciclos de folga (antes eram 2). Todas as oito combinações históricas de
  jogadores/bola agora custam os mesmos 62 ciclos, e o walker automatizado
  verifica que não sobra nenhuma ramificação condicional para frente no corpo
  do kernel.
- **Prazos de escrita dos objetos**: `ENABL` completa em ~ciclo 5 (primeiro
  pixel visível em ~ciclo 22.7), `GRP0` em ~ciclo 23 (posição do feixe do P0
  em ~ciclo 28.3), `GRP1` em ~ciclo 41 (posição do feixe do P1 em ~ciclo 68).
  Toda escrita acontece antes da posição horizontal do seu objeto.
- **Convenção de exibição preservada**: a bola continua aparecendo nas
  scanlines `ball_y + 1 .. ball_y + BALL_HEIGHT`. A linha 0 armazena o
  `A = 0` deixado pelo pré-kernel, então a primeira linha visível nunca mostra
  a bola.
- **Sem RAM extra**: o valor de habilitação vive em `A`, não em uma variável.
- **ROM inalterada**: remover as tabelas e encurtar o kernel liberou bytes
  dentro do preenchimento de página reservado para o `fineAdjustBegin`
  alinhado a página, então o uso de ROM permanece em 528 bytes.

## Impacto de timing

Antes:
- Scanlines do quadro: 262
- Pior/melhor caso do kernel: 74 / 61 ciclos (folga 2)
- `GRP0`/`GRP1`/`ENABL` em ~ciclo 26 / 49 / 67

Depois:
- Scanlines do quadro: 262 (inalterado)
- Pior/melhor caso do kernel: 62 / 62 ciclos (sem ramificações; folga **14**)
- `ENABL` em ~ciclo 5, `GRP0` em ~ciclo 23, `GRP1` em ~ciclo 41

## Impacto de memória

Antes:
- ROM: 528 bytes
- RAM: 7 bytes

Depois:
- ROM: 528 bytes (inalterado; bytes liberados absorvidos pelo padding de
  página)
- RAM: 7 bytes (inalterado; o valor de habilitação é transportado em `A`)

## Testes

- `tests/test_timing.py`: walker de ciclos simplificado para o kernel sem
  ramificações; todos os caminhos verificados em 62 ciclos; nova verificação
  de que o corpo do kernel não contém ramificações condicionais para frente.
- `tests/test_ball.py`: `BALL_ENABLE = $FF`; `ENABL` escrito exatamente uma
  vez por scanline no corpo do loop; novo teste de ordem relativa de escrita
  (`ENABL` deve vir imediatamente após `STA WSYNC`, depois `GRP0`, depois
  `GRP1`); novo teste de regressão verificando que o kernel nunca referencia
  `ball_x` (a extensão vertical é idêntica em toda posição horizontal); a
  limpeza do `ENABL` na inicialização do overscan é verificada
  estruturalmente (`A9 00 85 1F` na região do overscan); o teste "a última
  linha deve escrever ENABL = 0 por construção" foi substituído pelo
  invariante da limpeza explícita.
- `tests/test_rom.py`: testes de tabelas de sprite removidos (as tabelas não
  existem mais); adicionadas a verificação da constante `PADDLE_BITS` e a
  verificação estrutural "dois `AND #PADDLE_BITS` no kernel".
- `tests/test_regression.py`: folga esperada atualizada para 14.
- Suíte completa: **107 testes passam**; portões de qualidade passam (ROM
  528/4096, RAM 7/128, 262 scanlines, pior 62/76, folga 14). Benchmark e
  regressão regerados em verde (a regressão mostra dois avisos soft em relação
  ao baseline da Rodada 1: pior caso do kernel +6 e folga -6, ambos esperados;
  o pior caso, na verdade, melhorou em relação ao valor commitado da Rodada 2,
  74).

## Limitações conhecidas

- Os jogadores são retângulos constantes: arte de sprite com linhas
  arbitrárias não é possível sem reintroduzir tabelas de gráficos e um layout
  de kernel que ainda escreva `GRP0` a tempo após a escrita do `ENABL`.
- A validação de scanlines/visual em runtime continua sendo uma etapa manual
  no Stella (sem modo headless documentado de estatísticas de quadro); a
  suíte estática é o substituto seguro para o CI.

## Próximos passos lógicos

- A detecção de colisão bola vs. raquete pode agora usar os latches de
  colisão (`CXBLPF` etc.) contra um kernel determinístico.
- Reverificar a varredura de renderização da bola congelada no alvo/Stella
  para confirmar que o deslocamento vertical desapareceu para todo `ball_x`.
