# Wizard Duel - Arquitetura

A Rodada 1 estabelece a base técnica mínima de um jogo para Atari 2600:

* um quadro NTSC estável com exatamente 262 scanlines
* dois jogadores TIA visíveis simultaneamente (P0 à esquerda, P1 à direita)
* movimento apenas vertical, dirigido pelo joystick 1 (P0) e joystick 2 (P1)

Propositalmente ainda não há sistema de magia, projéteis, HP, IA, colisões
ou HUD; as regras de jogo devem evoluir em rodadas futuras sem exigir
mudanças de arquitetura.

## Organização do código

`src/main.asm` contém o programa completo em um único banco de ROM
`$F000-$FFFF` (4 KiB, sem bankswitching). `src/constants.inc` concentra os
endereços dos registradores de hardware e as constantes de compilação.

| Endereço | Conteúdo                                        |
| -------- | ----------------------------------------------- |
| `$F000`  | `Reset` (inicialização)                         |
| `$F016`  | `StartOfFrame` (VSYNC + VBLANK + kernel + overscan) |
| `$F09B`  | `UpdatePlayers` (entrada de joystick + movimento) |
| `$F0D5`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)   |
| `$F0F4`  | `P0Sprite` / `P1Sprite` (12 bytes cada)         |
| `$F200`  | `fineAdjustBegin` (tabela HMP alinhada a página) |
| `$FFFA`  | vetores NMI / RESET / IRQ                       |

Os endereços exatos podem mudar entre builds; os testes automatizados os
resolvem a partir dos arquivos de símbolos/listing em vez de fixá-los.

## Fluxo de execução por quadro

```
StartOfFrame
 ├─ VSYNC    3 scanlines  (três WSYNC explícitos)
 ├─ VBLANK  37 scanlines  (TIM64T = 44; lógica de jogo roda aqui)
 │   ├─ UpdatePlayers     lê SWCHA, move P0/P1 e limita à arena
 │   └─ PositionPlayers   posicionamento horizontal RESP0/RESP1 + HMP0/HMP1
 ├─ KERNEL 192 scanlines  (loop explícito de WSYNC; só renderiza)
 └─ OVERSCAN 30 scanlines (TIM64T = 37; volta ao StartOfFrame)
```

Entrada e atualização de estado ocorrem durante o VBLANK; o kernel visível
apenas desenha os dois sprites. Isso segue a regra do projeto de manter o
código de exibição previsível em termos de tempo e fora da lógica de jogo.

## Entrada

Os joysticks são lidos da porta de I/O `SWCHA` do RIOT (`$0280`), que é
ativa em nível baixo: um bit é 0 quando a direção correspondente está
pressionada. Nesta rodada só são usadas as direções verticais:

| Porta | Direção | Bit SWCHA |
| ----- | ------- | --------- |
| P0 (esquerda, joystick 1) | cima  | D4 |
| P0 (esquerda, joystick 1) | baixo | D5 |
| P1 (direita, joystick 2)  | cima  | D0 |
| P1 (direita, joystick 2)  | baixo | D1 |

`UpdatePlayers` amostra `SWCHA` uma vez por quadro na variável `joystate`
(RAM) e aplica no máximo um passo de subida/descida por jogador, protegendo
os limites da arena para que a posição nunca dê a volta (wrap).

## Renderização

Os dois jogadores são sprites TIA de cópia única (`NUSIZ0/1 = 0`) com cores
diferentes: P0 é vermelho (`COLUP0 = $46`) e P1 é azul (`COLUP1 = $84`). O
kernel calcula, por scanline, se o índice da linha atual pertence ao sprite
de 12 linhas de um jogador e escreve o byte correspondente em `GRP0`/`GRP1`.

O posicionamento horizontal é fixado a cada quadro com a técnica clássica
RESP0/RESP1 + HMP0/HMP1 + HMOVE: um `RESPx` grosseiro coloca o sprite dentro
de 15 pixels e um ajuste fino `HMPx` vindo da tabela `fineAdjustTable`
(alinhada a página) completa o trabalho. O `HMOVE` que aplica os offsets é
escrito na última linha do VBLANK.

## Alocação de variáveis

Apenas três variáveis de zero page são usadas (3 de 128 bytes de RAM RIOT):

| Endereço | Nome       | Finalidade                  |
| -------- | ---------- | --------------------------- |
| `$80`    | `P0Y`      | posição vertical do jogador 0 |
| `$81`    | `P1Y`      | posição vertical do jogador 1 |
| `$82`    | `joystate` | valor amostrado de SWCHA      |

## Por que a lógica fica no VBLANK

O kernel visível tem orçamento de 76 ciclos por scanline. Executar a
decodificação do joystick e o movimento lá introduziria ramificações com
tempo dependente de dados em um caminho de renderização que precisa ser
determinístico. Movendo-a para o VBLANK (ver [timing.md](timing.md)) o
kernel permanece estável em exatamente uma scanline por iteração,
independentemente da entrada.