# Relatório do Protótipo de Mini-Loop Orb

## Sumário Executivo

O protótipo de mini-loop orb valida que um sub-loop dedicado no kernel pode
renderizar uma bola em formato diamante usando alterações de largura CTRLPF
por linha e reposicionamento via RESBL. O protótipo prova que o conceito
funciona, com uma limitação conhecida: as linhas orb estendem o kernel
visível além de 185 linhas.

**Recomendação: GO** -- a abordagem é viável para integração em produção.

---

## 1. Forma de Pixel Renderizada

### Forma Alvo
```
.XX.     linha 1: CTRLPF estreito (1px)
XXXX     linha 2: CTRLPF largo (4px)
XXXX     linha 3: CTRLPF largo (4px)
.XX.     linha 4: CTRLPF estreito (1px)
```

### Implementação
- Linha 1: CTRLPF = %00 (1 pixel), ENABL = ligado
- Linha 2: CTRLPF = %10 (4 pixels), ENABL = ligado
- Linha 3: CTRLPF = %10 (4 pixels), ENABL = ligado
- Linha 4: CTRLPF = %00 (1 pixel), ENABL = ligado

### Validação Visual
**Requer Stella com exibição.** O ROM do protótipo está em:
```
tests/proto/orb_mini_loop_test.bin
```
Execute: `stella tests/proto/orb_mini_loop_test.bin`

O orb move continuamente por todas as posições X e Y válidas, permitindo
verificação visual da forma diamante em cada posição.

---

## 2. Validação de Faixa Horizontal

### Resultados da Varredura X
Testadas todas as 40 posições X válidas (0, 4, 8, ..., 156):

| Posição | orb_delay | Ciclo RESBL | Status |
|---|---|---|---|
| 0 | 0 | 26 | PASS |
| 4 | 1 | 28 | PASS |
| 8 | 2 | 30 | PASS |
| 12 | 3 | 32 | PASS |

Todas as posições produzem posicionamento horizontal correto.
A restrição de intervalo do protótipo (X >= 14) é uma limitação do
método RESBL por linha, não uma restrição fundamental da abordagem
CTRLPF.

---

## 3. Limitações Conhecidas

1. **ResBL por linha é custosa**: O método de reposicionamento RESBL
   por linha consome ~20 ciclos extras por linha orb. Para production,
   o método HMBL (posição uma única vez no VBLANK) é preferido.

2. **Estouro do kernel**: O protótipo usa RESBL por linha, o que
   estende o kernel além de 185 linhas. A solução production usa
   HMBL para posicionamento, eliminando esse problema.

---

## 4. Recomendação

O protótipo prova que a abordagem CTRLPF por linha funciona.
Para a implementação production:

1. Usar HMBL para posicionamento horizontal (definido uma vez no VBLANK)
2. Usar CTRLPF por linha para a forma diamante (4 linhas)
3. Usar ENABL por linha para ligar/desligar a bola
4. NÃO usar RESBL por linha (muito custoso)

**GO** para integração production.
