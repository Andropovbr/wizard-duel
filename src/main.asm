; =============================================================================
; Wizard Duel - Atari 2600
; main.asm
;
; Round 1 - minimum technical base.
;
;   * stable NTSC frame, 262 scanlines
;   * two TIA players visible simultaneously (P0 left, P1 right)
;   * vertical-only movement, driven by joystick 1 and joystick 2
;   * no magic system, projectiles, HP, AI or collisions yet
;
; Frame structure (NTSC):
;
;   VSYNC     3 scanlines   (lines 1..3,   explicit WSYNC)
;   VBLANK   37 scanlines   (lines 4..40,  TIM64T = VBLANK_TIMER_VALUE)
;   KERNEL  192 scanlines   (lines 41..232, explicit WSYNC loop)
;   OVERSCAN 30 scanlines   (lines 233..262, TIM64T = OVERSCAN_TIMER_VALUE)
;   TOTAL   262 scanlines
;
; Gameplay input/update happens during VBLANK; the visible kernel only
; renders. See docs for the full timing analysis.
; =============================================================================

    PROCESSOR 6502
    INCLUDE "constants.inc"

    SEG
    ORG $F000

; =============================================================================
; Reset
; =============================================================================
Reset:
    SEI                     ; 2   disable interrupts (none exist on the 2600)
    CLD                     ; 2   decimal mode must be off
    LDX #$FF                ; 2
    TXS                     ; 2   stack at $01FF

    ; Clear zero page ($00-$FF). Addresses $00-$7F are TIA/RIOT mirrors
    ; (harmless to write) and $80-$FF is the RIOT RAM this game uses.
    LDA #0                  ; 2
.ClearRAM:
    STA $00,X               ; 4   X = $FF..$01
    DEX                     ; 2
    BNE .ClearRAM           ; 2/3
    STA $00                 ; 3   clear $00 as well

    ; ---- TIA setup ------------------------------------------------------
    LDA #PLAYER1_COLOR
    STA COLUP0
    LDA #PLAYER2_COLOR
    STA COLUP1
    LDA #BACKGR_COLOR
    STA COLUBK
    LDA #0
    STA NUSIZ0              ; player 0: 1 copy, normal size
    STA NUSIZ1              ; player 1: 1 copy, normal size
    STA VDELP0
    STA VDELP1
    STA CTRLPF
    STA SWACNT              ; port A = all inputs (joysticks readable)

    ; Initial vertical positions (horizontal placement is fixed each frame)
    LDA #PLAYER1_Y_INIT
    STA P0Y
    LDA #PLAYER2_Y_INIT
    STA P1Y

; =============================================================================
; StartOfFrame - one complete frame
; =============================================================================
StartOfFrame:
    ; ---- VSYNC: 3 scanlines ---------------------------------------------
    LDA #2                  ; 2
    STA VBLANK              ; 3   blank output during sync + vblank
    STA VSYNC               ; 3   assert vertical sync
    STA WSYNC               ; 3   scanline 1
    STA WSYNC               ; 3   scanline 2
    STA WSYNC               ; 3   scanline 3
    LDA #VBLANK_TIMER_VALUE ; 2
    STA TIM64T              ; 4   VBLANK countdown (43 * 64 = 2752 cycles)
    LDA #0                  ; 2
    STA VSYNC               ; 3   release vertical sync

    ; ---- VBLANK: game logic (input + movement + placement) --------------
    JSR UpdatePlayers       ; move both players vertically (see below)
    JSR PositionPlayers     ; fixed horizontal placement (RESP + HMP)

    ; Wait for the VBLANK timer to expire on the last VBLANK line (line 40).
WaitVBlank:
    LDA INTIM               ; 3
    BNE WaitVBlank          ; 2/3

    ; Last VBLANK line: apply the horizontal fine movement, enable the
    ; display and clear the sprite graphics for the first visible line.
    STA HMOVE               ; 3   apply HMP0/HMP1 fine adjustments
    LDA #0                  ; 2
    STA VBLANK              ; 3   picture on from the next scanline
    STA GRP0                ; 3   first visible line shows a cleared sprite
    STA GRP1                ; 3
    LDX #0                  ; 2   scanline counter (0..191)

    ; ---- Visible kernel: 192 scanlines -----------------------------------
    ;
    ; Scanline budget: 76 cycles. Cycle accounting (verified by the
    ; automated test suite from the assembled listing):
    ;
    ;   Sprite drawn path (one player):
    ;     TXA                 2
    ;     SEC                 2
    ;     SBC P0Y             3
    ;     CMP #PLAYER_HEIGHT  2
    ;     BCS .P0Blank        2   (not taken)
    ;     TAY                 2
    ;     LDA P0Sprite,Y      4   (tables fit inside one page -> no page cross)
    ;     JMP .P0Done         3
    ;     STA GRP0            3
    ;     Subtotal           23
    ;
    ;   Sprite blank path (one player):
    ;     TXA                 2
    ;     SEC                 2
    ;     SBC P0Y             3
    ;     CMP #PLAYER_HEIGHT  2
    ;     BCS .P0Blank        3   (taken, same page)
    ;     LDA #0              2
    ;     STA GRP0            3
    ;     Subtotal           17
    ;
    ;   Tail (per scanline):
    ;     INX                 2
    ;     CPX #KERNEL_SCANLINES 2
    ;     BNE KernelLoop      3   (taken, backward to same page)
    ;     STA WSYNC           3
    ;     Subtotal           10
    ;
    ; Worst case (both sprites drawn): 23 + 23 + 10 = 56 cycles < 76.
    ; Best case (both sprites blank):  17 + 17 + 10 = 44 cycles.
    ;
    ; The sprite tables are laid out so that every possible row index stays
    ; inside a single page, so the indexed LDA never costs the +1 page-cross
    ; penalty (unlike fineAdjustTable in PosObject, which is deliberately
    ; page-aligned to force that +1 cycle for deterministic RESP timing).
    ;
    ; Every iteration starts with STA WSYNC, so each iteration is exactly
    ; one scanline regardless of the branch taken. The frame therefore
    ; stays at 262 scanlines whether a player is still, rising, descending
    ; or both move at once.
    ;
    ; Graphics registers are written at ~cycle 24 (GRP0) and ~cycle 48
    ; (GRP1), comfortably inside the 76-cycle scanline, so both writes are
    ; latched for the following line.
KernelLoop:
    STA WSYNC               ; 3   start of scanline (physical line 41 + X)

    ; Player 0 (left): compute the sprite row for this scanline.
    TXA                     ; 2   scanline index
    SEC                     ; 2
    SBC P0Y                 ; 3   row = X - P0Y (borrow when X < P0Y)
    CMP #PLAYER_HEIGHT      ; 2   row >= height -> not part of the sprite
    BCS .P0Blank            ; 2/3
    TAY                     ; 2
    LDA P0Sprite,Y          ; 4(5)  row byte 0..11
    JMP .P0Done             ; 3
.P0Blank:
    LDA #0                  ; 2
.P0Done:
    STA GRP0                ; 3

    ; Player 1 (right): same logic, separate position and sprite table.
    TXA                     ; 2
    SEC                     ; 2
    SBC P1Y                 ; 3
    CMP #PLAYER_HEIGHT      ; 2
    BCS .P1Blank            ; 2/3
    TAY                     ; 2
    LDA P1Sprite,Y          ; 4(5)
    JMP .P1Done             ; 3
.P1Blank:
    LDA #0                  ; 2
.P1Done:
    STA GRP1                ; 3

    INX                     ; 2
    CPX #KERNEL_SCANLINES   ; 2
    BNE KernelLoop          ; 2/3

    ; ---- Overscan: 30 scanlines ------------------------------------------
    LDA #VBLANK_BLANK       ; 2
    STA VBLANK              ; 3   blank output again
    LDA #OVERSCAN_TIMER_VALUE ; 2
    STA TIM64T              ; 4   overscan countdown (36 * 64 = 2304 cycles)
OverscanWait:
    LDA INTIM               ; 3
    BNE OverscanWait        ; 2/3

    JMP StartOfFrame        ; 3   next frame

; =============================================================================
; UpdatePlayers
;
; Moves each player up/down by one scanline per frame based on its joystick
; and clamps the position to the arena. Runs during VBLANK so the visible
; kernel stays branch-free regarding gameplay state.
;
; SWCHA bits (active low: 0 = pressed):
;   P0 (joystick 1, port 0): D4 up, D5 down
;   P1 (joystick 2, port 1): D0 up, D1 down
; Horizontal directions and fire buttons are intentionally ignored this round.
;
; Movement is applied only when the player is not already at the relevant
; boundary, which prevents the position from wrapping below PLAYER_Y_MIN or
; above PLAYER_Y_MAX.
; =============================================================================
UpdatePlayers:
    LDA SWCHA               ; 3   sample the joysticks once
    STA joystate            ; 3   (avoid repeated reads of the port)

    ; Player 0 - up
    LDA #JOY1_UP            ; 2
    BIT joystate            ; 3
    BNE .p0UpDone           ; 2/3
    LDA P0Y                 ; 3
    BEQ .p0UpDone           ; 2/3  already at the top of the arena
    DEC P0Y                 ; 5
.p0UpDone:

    ; Player 0 - down
    LDA #JOY1_DOWN          ; 2
    BIT joystate            ; 3
    BNE .p0DownDone         ; 2/3
    LDA P0Y                 ; 3
    CMP #PLAYER_Y_MAX       ; 2
    BCS .p0DownDone         ; 2/3  already at the bottom of the arena
    INC P0Y                 ; 5
.p0DownDone:

    ; Player 1 - up
    LDA #JOY2_UP            ; 2
    BIT joystate            ; 3
    BNE .p1UpDone           ; 2/3
    LDA P1Y                 ; 3
    BEQ .p1UpDone           ; 2/3
    DEC P1Y                 ; 5
.p1UpDone:

    ; Player 1 - down
    LDA #JOY2_DOWN          ; 2
    BIT joystate            ; 3
    BNE .p1DownDone         ; 2/3
    LDA P1Y                 ; 3
    CMP #PLAYER_Y_MAX       ; 2
    BCS .p1DownDone         ; 2/3
    INC P1Y                 ; 5
.p1DownDone:

    RTS                     ; 6

; =============================================================================
; PositionPlayers
;
; Horizontally places both players using the classic RESP0/RESP1 + HMP0/HMP1
; + HMOVE technique (routine by R. Mundschau, documented in the local
; reference "Atari 2600 Programming for Newbies", session 24). Positions are
; fixed every frame; the HMOVE that applies the fine adjustments is written
; on the last VBLANK line, just before the visible kernel.
;
; Because the TIA position counters only advance during the 160 visible
; color clocks of each scanline (one full counter period), a position set
; with RESP holds unchanged on every following scanline. Applying HMOVE
; later in VBLANK therefore only adds the fixed fine offset.
; =============================================================================
PositionPlayers:
    LDA #PLAYER1_X          ; 2
    LDX #0                  ; 2   object 0 = player 0
    JSR PosObject           ; 6
    LDA #PLAYER2_X          ; 2
    LDX #1                  ; 2   object 1 = player 1
    JSR PosObject           ; 6
    RTS                     ; 6

; =============================================================================
; PosObject - position object X (0..5) at horizontal pixel position A.
;
; Timing contract (from the reference):
;   - entering on or before cycle 73 of a scanline: consumes 1 scanline
;   - entering after cycle 73: consumes 2 scanlines
;   - returns on cycle 6 of the next scanline; X unchanged
;   - A = fine adjustment, Y = division remainder
;
; The fine-adjust table is page-aligned so that "LDA fineAdjustTable,Y"
; always crosses a page boundary (+1 cycle), keeping the RESP cycle exact.
; =============================================================================
PosObject:
    STA WSYNC               ; 3   sync to the next scanline
    SEC                     ; 2   no borrow during the division
.DivideBy15:
    SBC #15                 ; 2   subtract one 15-pixel step
    BCS .DivideBy15         ; 2/3
    TAY                     ; 2   remainder -> table index
    LDA fineAdjustTable,Y   ; 4(5)  fine movement (page boundary = +1)
    STA HMP0,X              ; 4   fine movement register for object X
    STA RESP0,X             ; 4   coarse position for object X
    RTS                     ; 6

; =============================================================================
; Sprite graphics
;
; One byte per scanline, drawn top to bottom. Bit 7 is the leftmost pixel.
; Player 0 is drawn as a "wizard" (pointed hat), player 1 as a "duelist"
; (rounded head and shoulders); colors also differ (red vs blue).
; =============================================================================
P0Sprite:
    DC.B %00011000          ; row 0 - hat tip
    DC.B %00011000          ; row 1 - hat
    DC.B %00111100          ; row 2 - hat brim
    DC.B %01111110          ; row 3 - head
    DC.B %01111110          ; row 4 - head
    DC.B %00111100          ; row 5 - neck
    DC.B %00111100          ; row 6 - body
    DC.B %00111100          ; row 7 - body
    DC.B %00011000          ; row 8 - body
    DC.B %00011000          ; row 9 - body
    DC.B %00011000          ; row 10 - body
    DC.B %00111100          ; row 11 - base

P1Sprite:
    DC.B %00011000          ; row 0 - head
    DC.B %00111100          ; row 1 - head
    DC.B %00111100          ; row 2 - head
    DC.B %00111100          ; row 3 - head
    DC.B %01111110          ; row 4 - shoulders
    DC.B %11000011          ; row 5 - arms out
    DC.B %10000001          ; row 6 - body
    DC.B %10000001          ; row 7 - body
    DC.B %10000001          ; row 8 - body
    DC.B %01111110          ; row 9 - body
    DC.B %00111100          ; row 10 - legs
    DC.B %00111100          ; row 11 - legs

; =============================================================================
; Fine horizontal adjustment table (from the reference, session 24).
; Must be page-aligned: see the note in PosObject.
; =============================================================================
    ALIGN 256
fineAdjustBegin:
    DC.B %01110000          ; left 7
    DC.B %01100000          ; left 6
    DC.B %01010000          ; left 5
    DC.B %01000000          ; left 4
    DC.B %00110000          ; left 3
    DC.B %00100000          ; left 2
    DC.B %00010000          ; left 1
    DC.B %00000000          ; no movement
    DC.B %11110000          ; right 1
    DC.B %11100000          ; right 2
    DC.B %11010000          ; right 3
    DC.B %11000000          ; right 4
    DC.B %10110000          ; right 5
    DC.B %10100000          ; right 6
    DC.B %10010000          ; right 7
fineAdjustTable EQU fineAdjustBegin - %11110001
    ; fineAdjustTable = fineAdjustBegin - 241. Indexing with the two's
    ; complement remainder ($F1..$FF, i.e. -15..-1) reaches the 15 real
    ; table bytes and always crosses a page boundary.

; =============================================================================
; Zero page RAM (RIOT RAM, $80-$FF)
; =============================================================================
    SEG.U VARS
    ORG $80
P0Y         DS 1            ; player 0 vertical position (0..PLAYER_Y_MAX)
P1Y         DS 1            ; player 1 vertical position (0..PLAYER_Y_MAX)
joystate    DS 1            ; sampled SWCHA value

; =============================================================================
; 6502 vectors
; =============================================================================
    SEG
    ORG $FFFA
    .WORD Reset             ; NMI (unused)
    .WORD Reset             ; RESET
    .WORD Reset             ; IRQ (unused)