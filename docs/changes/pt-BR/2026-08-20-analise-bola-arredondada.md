# Mudanca: Analise da Bola Arredondada (Round 8)

## Objetivo

Investigar se o objeto Ball do TIA pode produzir uma forma visualmente
"arredondada" (ex.: um diamante: 2px-4px-2px) em vez do bloco retangular
4x4 atual, e implementa-lo com seguranca dentro da arquitetura table-direct
do kernel, se possivel.

## Adicionado

- `docs/changes/en/2026-08-20-rounded-ball-analysis.md` (ingles)
- `docs/changes/pt-BR/2026-08-20-analise-bola-arredondada.md` (este arquivo)

## Alterado

Nenhum. Nenhum codigo fonte foi modificado.

## Removido

Nenhum.

## Raciocinio Tecnico

### Limitacao do Hardware Ball do TIA

O objeto Ball do TIA e fundamentalmente uma **linha horizontal de pixels**:

- **Largura** e fixa por frame via `CTRLPF` D5:D4:
  - `%00` = 1 relogio de cor
  - `%01` = 2 relogios de cor
  - `%10` = 4 relogios de cor (configuracao atual)
  - `%11` = 8 relogios de cor
- **Altura** e controlada por `ENABL`: a bola e visivel nas linhas de varredura
  onde o bit 1 de `ENABL` esta configurado.
- **Forma**: estritamente retangular em qualquer largura `CTRLPF`. Nao ha suporte
  de hardware para variacao de largura por linha de varredura.

A forma "arredondada" requer larguras diferentes em linhas diferentes:

```
Linha 0: 2 pixels  .XX.
Linha 1: 4 pixels  XXXX
Linha 2: 2 pixels  .XX.
```

Isso so e possivel se `CTRLPF` puder ser alterado **durante o kernel visivel**
em cada linha da bola.

### Por que Mudancas de CTRLPF no Kernel Sao Inseguras

O kernel table-direct atual tem estas restricoes:

1. **Duas escritas por linha**: cada entrada de evento contem exatamente
   `reg1/val1` e `reg2/val2`. A entrada ON da bola ja usa ambos os slots para
   `ENABL`/`BALL_ENABLE`. Uma escrita em `CTRLPF` precisaria de um terceiro slot.

2. **Caminhos de custo constante**: o kernel tem tres caminhos (38/54/46 ciclos)
   sem branching dependente de dados. Adicionar uma escrita condicional em
   `CTRLPF` introduziria um caminho de custo variavel, violando o invariante
   de custo constante.

3. **Capacidade da tabela de eventos**: a bola usa atualmente 2 eventos
   (ON + OFF). Uma forma arredondada precisa de 2 eventos adicionais de
   `CTRLPF` (definir largura estreita, restaurar largura padrao) = 4 eventos
   total apenas para a bola. Sob estresse de colisao (ambos os jogadores +
   ambos os misseis + bola = 10 eventos no maximo), isso deixa apenas 6
   eventos para 4 objetos, o que pode transbordar `EV_MAX_EVENTS`.

4. **Regra do slot de escrita**: `CTRLPF` esta em `$0A`. A segunda escrita de
   um double deve ser concluida pelo ciclo 27 da CPU (beam gate `x >= 13`).
   `CTRLPF` propriamente esta no endereco `$0A` (x=10), que esta abaixo do
   gate — entao `CTRLPF` **nao pode ser a segunda escrita** de uma entrada
   double. Sempre precisaria ser slot 1, deslocando a propria escrita `ENABL`
   da bola.

5. **Integridade arquitetural**: a correcao delta=1 do Round 11 foi
   especificamente projetada para eliminar caminhos de custo variavel do
   kernel. Adicionar escritas de `CTRLPF` por linha reintroduz a exata classe
   de mudanca que causou o slip de 263 scanlines nos Rounds 7-10.

### Alternativas Avaliadas

#### Opcao A: Bola com largura fixa e altura ajustada

Uma bola mais estreita ou mais curta (ex.: 2x2) ainda seria retangular. Isso
nao resolve o requisito de arredondamento visual.

#### Opcao B: Mudar CTRLPF entre linhas de varredura

Como analisado acima, isso requer:
- Escritas de `CTRLPF` por linha no kernel visivel (timing inseguro)
- Ou eventos de `CTRLPF` por linha na tabela (violacoes de capacidade e
  regra de slot)
- Ou reestruturar o kernel para suportar 3+ escritas por linha (quebra o
  orcamento de ciclos 54/76)

**Rejeitado**: inseguro dentro da arquitetura atual.

#### Opcao C: Combinacao de Bola + outro objeto TIA

- **Objetos Player**: tanto P0 quanto P1 ja sao usados para os magos.
  Repurporcionar um player para a bola removeria um mago da tela.
- **Objetos Missile**: M0 e M1 sao usados para projeteis. Reutilizar um
  missil para a forma da bola exigiria repensar o sistema de projeteis.
- **Playfield**: o playfield nao e exibido neste jogo, entao nao pode
  contribuir para a forma da bola.

**Rejeitado**: nenhum objeto TIA nao utilizado esta disponivel para moldagem
da bola.

#### Opcao D: Manter Bola retangular (recomendado)

A bola retangular 4x4 atual e a unica opcao segura. Ela:
- Preserva todos os invariantes de timing (pior caso do kernel 54/76)
- Preserva o frame de 262 scanlines
- Preserva semanticas de colisao
- Preserva a capacidade da tabela de eventos e regras de slot
- Nao requer alteracoes de codigo

### Impacto na Colisao

Nenhuma alteracao. A bola continua com 4x4 pixels. As latches de colisao
Ball x P0 e Ball x P1 comportam-se identicamente.

### Impacto na Tabela de Eventos

Nenhuma alteracao. A bola usa 2 eventos (ON/OFF) como antes. Nenhum evento
adicional e necessario.

### Impacto ROM/RAM

Nenhuma alteracao. Nenhum codigo foi modificado.

## Impacto no Timing

Antes (baseline):
- Scanlines do frame: 262
- Pior caso do kernel: 54 / 76 ciclos
- Folga do kernel: 22 ciclos
- Pior trabalho VBLANK: 4528 ciclos
- Margem VBLANK: 336 ciclos

Depois: identico (nenhum codigo alterado).

## Impacto na Memoria

Antes:
- ROM: 1808 bytes
- RAM: 81 bytes

Depois: identico (nenhum codigo alterado).

## Testes

Todos os 261 testes existentes passam. Nenhum novo teste foi adicionado
porque nenhum codigo foi modificado.

## Limitacoes Conhecidas

O objeto Ball do TIA e **intrinsecamente retangular**. Uma bola verdadeiramente
arredondada nao e possivel com o hardware Ball do TIA no Atari 2600. Esta e
uma limitacao fundamental da plataforma, nao do projeto.

A unica alternativa (mudar `CTRLPF` por linha de varredura) entra em conflito
com a arquitetura table-direct do kernel e reintroduziria a instabilidade de
timing que os Rounds 7-11 foram projetados para eliminar.

Se uma bola visualmente distinta for desejada no futuro, as opcoes sao:

1. **Gradiente de cor**: mudar `COLUPF` por linha de varredura para criar um
   efeito de profundidade visual (nao e arredondamento, mas interesse visual).
2. **Largura fixa diferente**: mudar `BALL_SIZE_CTRLPF` para 2 ou 8 pixels
   para uma forma retangular diferente.
3. **Usar um objeto Player**: repurporcionar um dos dois objetos player como
   bola com forma programavel (ao custo de um sprite de mago).

## Proximos Passos Logicos

- Continuar com a bola retangular 4x4 atual.
- Considerar uma bola baseada em Player em um round futuro se a forma
  programavel for priorizada em relacao a dois magos simultaneos.
