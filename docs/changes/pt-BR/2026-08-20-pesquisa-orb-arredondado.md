# Mudança: Pesquisa Orb Arredondado (R&D Spike)

## Objetivo

Investigar TODAS as técnicas TIA possíveis para produzir um "orb arredondado"
visualmente no jogo Wizard Duel. Produzir uma matriz de comparação com pelo
menos 3 alternativas concretas e recomendar uma solução. Este é um spike de
P&D -- nenhum código de produção é implementado ou mesclado.

## Adicionado

- `docs/changes/en/2026-08-20-rounded-orb-rd-spike.md` (inglês)
- `docs/changes/pt-BR/2026-08-20-pesquisa-orb-arredondado.md` (este arquivo)

## Mudado

Nenhum. Nenhum código fonte foi modificado.

## Removido

Nenhum.

## Raciocínio Técnico

### Renderização Atual da Bola

A bola atual é um bloco retangular 4x4:

```
XXXX
XXXX
XXXX
XXXX
```

- Largura: 4 clocks de cor (CTRLPF D5:D4 = `%10`)
- Altura: 4 scanlines (ENABL = 1 para 4 linhas)
- Cor: $0E (branco)
- Forma: fixa, configuração CTRLPF por frame

### Alvo: Orb Arredondado Visualmente

Um diamante (a melhor aproximação para "redondo" nesta resolução):

```
.XX.     2 pixels  (CTRLPF estreito)
XXXX     4 pixels  (CTRLPF largo)
XXXX     4 pixels  (CTRLPF largo)
.XX.     2 pixels  (CTRLPF estreito)
```

Ou uma versão de 6 linhas para melhor resolução vertical:

```
..X..    1 pixel   (CTRLPF mais estreito)
.XXX.    2 pixels  (CTRLPF estreito)
XXXXX    4 pixels  (CTRLPF largo)
XXXXX    4 pixels  (CTRLPF largo)
.XXX.    2 pixels  (CTRLPF estreito)
..X..    1 pixel   (CTRLPF mais estreito)
```

### Capacidades de Hardware Exploradas

| Registrador TIA | Endereço | Por Scanline? | Efeito |
|---|---|---|---|
| CTRLPF | $0A | Sim (D5:D4) | Largura da bola: 1/2/4/8 pixels |
| ENABL | $1F | Sim (bit 1) | Bola ligada/desligada por scanline |
| COLUPF | $08 | Sim | Cor da bola/playfield |
| RESBL | $14 | Sim (sinal START) | Reposicionamento horizontal da bola |
| HMBL | $24 | Só por frame | Movimento horizontal fino da bola |
| VDELBL | $27 | Por CLK | Atraso vertical da bola |
| PF0/PF1/PF2 | $0D-$0F | Sim | Forma do playfield (compartilha COLUPF) |
| NUSIZ0/1 | $04-$05 | Só por frame | Tamanho de players/mísseis |

Insight chave da pesquisa do subagente: RESBL gera um sinal START (diferente
de RESPn/RESMn), permitindo reposicionamento horizontal da bola por scanline.
Isto é incomum entre os registradores de posição TIA e permite abordagens
criativas.

---

## Família 1: Mudanças de Largura CTRLPF no Kernel de Eventos

**Abordagem**: Escrever CTRLPF na tabela de eventos para cada linha da bola
para mudar a largura por scanline. Combinar com ENABL ligado/desligado.

**Análise de ciclos**:

O kernel de eventos atual aplica escritas nos ciclos 15 (escrita 1) e 27
(escrita 2). CTRLPF ($0A) no offset 10 está abaixo do gate x >= 15 para
escrita 2. Portanto CTRLPF **deve ser escrita 1** em qualquer entrada de
evento.

Para um diamante de 4 linhas (2-4-4-2): 4 eventos de mudança de largura + 2
de restauração = 6 eventos para a bola. Mais 8 de players/mísseis = 14 total.
Excede EV_MAX_EVENTS = 10.

**RAM**: 0 bytes extras.
**ROM**: +20-40 bytes.
**Tabela de eventos**: +4 eventos. **Excede capacidade** sob estresse.
**Colisão**: Sem mudança significativa.
**Risco**: ALTO -- estouro da tabela de eventos.

**Veredito**: REJEITADO -- estouro da tabela de eventos.

---

## Família 2: Mini-Loop Orb com CTRLPF

**Abordagem**: Inserir um "mini-loop orb" dedicado que roda exatamente
BALL_HEIGHT scanlines antes do kernel de eventos principal. Este mini-loop
lida com escritas ENABL + CTRLPF por linha com seu próprio orçamento de
ciclos, completamente separado da tabela de eventos.

**Análise de ciclos**:

| Caminho | Ciclos | Rest | Notas |
|---|---|---|---|
| Linha orb (bola ligada) | ~62 | 58 | CTRLPF+ENABL+NOPs+RESBL |
| Linha orb (bola desligada) | ~62 | 58 | Mesmo mas ENABL=0 |
| Linhas não-orb | ~38 | 34 | Kernel principal |

Pior caso: 62 ciclos (folga 14). Aceitável.

**Problema**: O padding NOP é fixo mas ball_x varia. Para ball_x pequeno,
RESBL dispara tarde demais e a bola desloca para a direita. O delay NOP
deve ser adaptativo.

**RAM**: 2 bytes (orb_row_idx, orb_delay).
**ROM**: +80-120 bytes.
**Tabela de eventos**: Sem mudança.
**Colisão**: Posição horizontal da bola pode mudar.
**Risco**: MÉDIO.

**Veredito**: VIÁVEL mas complexo.

---

## Família 3: Renderização Playfield (PF0/PF1/PF2)

**Abordagem**: Usar os registradores playfield para renderizar a forma do orb.

**Problema**: O playfield cobre a metade ESQUERDA da tela (pixels 0-79). A
bola está tipicamente em x=78 (centro). Com playfield espelhado: imagem
dupla. Sem espelhado: bola invisível na metade direita.

**Veredito**: REJEITADO -- playfield não pode renderizar na posição da bola.

---

## Família 4: Ilusão de Gradiente de Luminância

**Abordagem**: Mudar COLUPF por scanline para criar um gradiente de
luminância nas 4 linhas da bola, simulando profundidade/roundedez.

```
Linha 0: $0E (branco brilhante)  -- destaque
Linha 1: $0C (branco médio)      -- tom médio
Linha 2: $0A (branco escuro)     -- sombra
Linha 3: $08 (branco mais escuro)-- sombra profunda
```

**Análise de ciclos**: COLUPF no offset 8. Deve ser escrita 1 (abaixo do
gate x >= 15). 5 eventos necessários (4 cores + 1 restauração). Excede
EV_MAX_EVENTS sob estresse.

**Alternativa**: Usar o mini-loop orb (Família 2) com escritas COLUPF.
Simples, sem alinhamento RESBL necessário.

**RAM**: 5 bytes (orb_row_idx + tabela de cores).
**ROM**: +30-50 bytes.
**Tabela de eventos**: Eventos da bola removidos.
**Colisão**: Sem mudança -- bola continua 4x4 retangular.
**Risco**: BAIXO.

**Veredito**: VIÁVEL como técnica complementar. Não produz forma arredondada
mas adiciona interesse visual.

---

## Família 5: Multiplexação NUSIZ

**Abordagem**: Usar NUSIZ0/NUSIZ1 para criar múltiplas cópias de um player.

**Problema**: NUSIZ é por frame (só durante VBLANK). Não pode ser mudado por
scanline. Além disso, players P0/P1 estão ocupados pelos wizards.

**Veredito**: REJEITADO -- NUSIZ é por frame e players estão ocupados.

---

## Família 6: Reposicionamento RESP

**Abordagem**: Usar RESP0/RESP1 para reposicionar um player por scanline.

**Problema**: Players P0/P1 estão ocupados. RESP reposiciona o sprite
INTEIRO, não só a bola. Requer mudanças GRP por linha.

**Veredito**: REJEITADO -- players ocupados.

---

## Família 7: Bola + Gradiente de Cor (Combinado)

**Abordagem**: Combinar a bola retangular atual com gradiente COLUPF por
scanline para criar impressão visual de "roundedez".

```
Linha 0: $0E  XXXX  (brilhante)
Linha 1: $0C  XXXX  (médio)
Linha 2: $0A  XXXX  (escuro)
Linha 3: $08  XXXX  (mais escuro)
```

**RAM**: 5 bytes.
**ROM**: +30-50 bytes.
**Tabela de eventos**: Eventos da bola removidos.
**Colisão**: Sem mudança.
**Risco**: BAIXO.

**Veredito**: VIÁVEL. Simples, baixo risco. Não é verdadeiramente "arredondado"
mas melhora a impressão visual.

---

## Família 8: Especialização de Kernel Orb (Mini-Loop com CTRLPF)

**Abordagem**: Um "mini-loop orb" dedicado rodando BALL_HEIGHT scanlines antes
do kernel principal, lidando com escritas ENABL + CTRLPF por linha. A posição
horizontal da bola é re-sincronizada com RESBL em cada scanline.

**Análise de ciclos**:

| Caminho | Ciclos | Rest | Notas |
|---|---|---|---|
| Linha orb (bola ligada) | ~66 | 62 | CTRLPF+ENABL+NOPs+RESBL+contagem |
| Linha orb (bola desligada) | ~66 | 62 | Mesmo mas ENABL=0 |
| Linhas não-orb (kernel) | 38 | 34 | Kernel de eventos padrão |

Pior caso: 66 ciclos (folga 10). Dentro do limite de perigo ≤70.

**Solução de posicionamento**: Calcular o delay adaptativamente no VBLANK
baseado em ball_x. Custo: ~30-40 bytes ROM, 1-2 bytes RAM.

**RAM**: 2 bytes.
**ROM**: +80-120 bytes.
**Tabela de eventos**: Eventos da bola removidos (economiza 2 eventos).
**Colisão**: Forma do hit box da bola muda por linha.
**Risco**: MÉDIO.

**Veredito**: VIÁVEL. Produz verdadeiro diamante.

---

## Matriz de Comparação

| Métrica | F1: Event CTRLPF | F2: Mini-Loop | F3: Playfield | F4: Cor | F5: NUSIZ | F6: RESP | F7: Bola+Cor | F8: Orb Mini-Loop |
|---|---|---|---|---|---|---|---|---|
| **Resultado visual** | Diamante | Diamante | N/A | Sombra | N/A | N/A | Sombra | Diamante |
| **Mudança de forma** | Sim | Sim | Não | Não | Não | Não | Não | Sim |
| **Pior kernel** | 54 | 62 | N/A | 68 | N/A | N/A | 50 | 66 |
| **Folga kernel** | 22 | 14 | N/A | 8 | N/A | N/A | 26 | 10 |
| **Delta RAM** | 0 | +2 | N/A | +5 | N/A | N/A | +5 | +2 |
| **Delta ROM** | +20-40 | +80-120 | N/A | +30-50 | N/A | N/A | +30-50 | +80-120 |
| **Tabela eventos** | +4 | Sem mudança | N/A | +3 | N/A | N/A | -2 | -2 |
| **Estouro eventos** | SIM (14>10) | Não | N/A | SIM (13>10) | N/A | N/A | Não | Não |
| **Mudança colisão** | Menor | Sim | N/A | Nenhuma | N/A | N/A | Nenhuma | Sim |
| **Risco timing** | ALTO | MÉDIO | N/A | BAIXO | N/A | N/A | BAIXO | MÉDIO |
| **Complexidade** | ALTA | MÉDIA | N/A | BAIXA | N/A | N/A | BAIXA | MÉDIA |
| **Viable** | NÃO | SIM | NÃO | SIM | NÃO | NÃO | SIM | SIM |

---

## 3 Alternativas Recomendadas

### Alternativa A: Mini-Loop Orb com CTRLPF (Família 8) -- RECOMENDADA

**Forma**: Verdadeiro diamante (2-4-4-2 pixels)
**Visual**:
```
.XX.     linha 0: CTRLPF estreito (2px), ENABL ligado
XXXX     linha 1: CTRLPF largo (4px), ENABL ligado
XXXX     linha 2: CTRLPF largo (4px), ENABL ligado
.XX.     linha 3: CTRLPF estreito (2px), ENABL ligado
```

**Impacto kernel**: +12 ciclos pior caso (54 -> 66). Folga 10. Aceitável.
**RAM**: +2 bytes.
**ROM**: +80-120 bytes.
**Colisão**: Hit box da bola muda por linha.
**Risco**: MÉDIO.

**Métricas esperadas**:
- ROM: ~1900-1930 / 4096 bytes
- RAM: 83 / 128 bytes
- Pior kernel: 66 / 76 ciclos (folga 10)
- Frame: 262 scanlines (inalterado)

### Alternativa B: Bola + Gradiente de Cor (Família 7) -- MAIS SIMPLES

**Forma**: Retangular (4x4) com gradiente de luminância
**Visual**:
```
XXXX     linha 0: $0E (brilhante)
XXXX     linha 1: $0C (médio)
XXXX     linha 2: $0A (escuro)
XXXX     linha 3: $08 (mais escuro)
```

**Impacto kernel**: -4 ciclos (eventos da bola removidos). Pior 50.
**RAM**: +5 bytes.
**ROM**: +30-50 bytes.
**Colisão**: Sem mudança.
**Risco**: BAIXO.

**Métricas esperadas**:
- ROM: ~1840-1860 / 4096 bytes
- RAM: 86 / 128 bytes
- Pior kernel: 50 / 76 ciclos (folga 26)
- Frame: 262 scanlines (inalterado)

### Alternativa C: Mini-Loop Orb Simplificado (Família 2) -- MEIO TERM

**Forma**: Diamante (2-4-4-2) com implementação mais simples
**Visual**: Igual à Alternativa A.

**Impacto kernel**: +8 ciclos (54 -> 62). Folga 14.
**RAM**: +2 bytes.
**ROM**: +80-120 bytes.
**Colisão**: Mesma da Alternativa A.
**Risco**: MÉDIO.

**Métricas esperadas**:
- ROM: ~1890-1930 / 4096 bytes
- RAM: 83 / 128 bytes
- Pior kernel: 62 / 76 ciclos (folga 14)
- Frame: 262 scanlines (inalterado)

---

## Recomendação

**Recomendação principal: Alternativa A (Família 8 -- Mini-Loop Orb com CTRLPF)**

Justificativa:
1. Produz **verdadeira forma de diamante** (não apenas sombreamento).
2. O pior caso do kernel (66 ciclos) está dentro do limite de perigo ≤70.
3. Custo RAM (+2 bytes) mínimo. Custo ROM (+80-120 bytes) aceitável.
4. Os eventos da bola são removidos da tabela, liberando 2 slots.
5. A mudança na forma de colisão é uma **feature** -- bola mais difícil de
   acertar nas pontas.

**Fallback: Alternativa B (Família 7 -- Bola + Gradiente de Cor)**

Se a complexidade do delay adaptativo da Alternativa A for julgada arriscada,
a Alternativa B fornece melhoria visual com risco mínimo.

---

## Limitações Conhecidas

1. **Mudança de forma de colisão**: Alternativas A e C mudam o hit box da
   bola por linha. Isto é uma mudança de gameplay que deve ser documentada.
2. **Delay adaptativo**: Alternativa A requer computar um delay por frame
   para alinhamento RESBL. Adiciona custo VBLANK e ROM.
3. **Offset horizontal**: Alternativa C aceita um offset fixo que varia com
   ball_x. Pode ser visualmente inaceitável para posições extremas.
4. **Gradiente de cor**: Alternativa B não muda a forma da bola, apenas sua
   sombreamento. Não é uma bola "arredondada" no sentido geométrico.
5. **Todas as abordagens**: O TIA Ball é fundamentalmente uma linha
   horizontal. Verdadeira redondez (bordas curvadas) é impossível. O
   diamante é a melhor aproximação nesta resolução.

## Testes

Nenhum teste foi adicionado porque nenhum código foi modificado.

## Próximos Passos Lógicos

1. Prototipar a Alternativa A (mini-loop orb com CTRLPF) em um ROM de teste.
2. Validar timing do kernel (66 ciclos pior caso) no emulador determinístico.
3. Validar semânticas de colisão com a nova forma da bola.
4. Validar timing do frame (262 scanlines) com o mini-loop orb.
5. Se bem-sucedido, implementar no jogo principal e documentar.
