; =============================================================================
; Wizard Duel - Atari 2600
; main.asm
;
; Round 2 - paddles and a bouncing ball.
;
;   * stable NTSC frame, 262 scanlines
;   * two TIA players visible simultaneously (P0 left, P1 right)
;   * players rendered as simple vertical paddles (Pong-style rectangles)
;   * vertical-only movement, driven by joystick 1 and joystick 2
;   * a TIA Ball object moving continuously and bouncing off the arena edges
;   * the ball does NOT interact with the players yet (no collision,
;     collection, power-up, scoring or spells)
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
    LDA #BALL_COLOR
    STA COLUPF              ; the ball is drawn with the playfield/ball color
    LDA #BACKGR_COLOR
    STA COLUBK
    LDA #0
    STA NUSIZ0              ; player 0: 1 copy, normal size
    STA NUSIZ1              ; player 1: 1 copy, normal size
    STA VDELP0
    STA VDELP1
    LDA #BALL_SIZE_CTRLPF   ; CTRLPF D5:D4 = %10 -> 4-pixel ball
    STA CTRLPF
    LDA #0
    STA SWACNT              ; port A = all inputs (joysticks readable)

    ; Initial vertical positions (horizontal placement is fixed each frame)
    LDA #PLAYER1_Y_INIT
    STA P0Y
    LDA #PLAYER2_Y_INIT
    STA P1Y

    ; Initial ball state: centered, moving down-right at 1 px/frame
    LDA #BALL_X_INIT
    STA ball_x
    LDA #BALL_Y_INIT
    STA ball_y
    LDA #DIR_RIGHT
    STA ball_dx
    LDA #DIR_DOWN
    STA ball_dy

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
    JSR UpdateBall          ; move the ball and bounce it off the arena edges
    JSR PositionPlayers     ; fixed horizontal placement (RESP + HMP)
    JSR PositionBall        ; ball horizontal placement (RESBL + HMBL)

    ; Wait for the VBLANK timer to expire on the penultimate VBLANK line.
    ; The timer expires while line 39 is being drawn; the WSYNC below then
    ; syncs to line 40 so the HMOVE can immediately follow it. The Stella
    ; Programmer's Guide requires HMOVE to immediately follow a WSYNC so the
    ; motion registers act during horizontal blanking of the last VBLANK line.
WaitVBlank:
    LDA INTIM               ; 3
    BNE WaitVBlank          ; 2/3

    ; Last VBLANK line (line 40): apply the horizontal fine movement, enable
    ; the display and clear the sprite graphics for the first visible line.
    STA WSYNC               ; 3   sync to line 40
    STA HMOVE               ; 3   apply HMP0/HMP1 fine adjustments
    LDA #0                  ; 2
    STA VBLANK              ; 3   picture on from the next scanline
    STA GRP0                ; 3   first visible line shows a cleared sprite
    STA GRP1                ; 3
    LDX #0                  ; 2   scanline counter (0..191)
    ; A = 0 here: the first kernel line (X = 0) stores it to ENABL, so the
    ; very first visible scanline is always ball-free.

    ; ---- Visible kernel: 192 scanlines -----------------------------------
    ;
    ; Scanline budget: 76 cycles. The kernel is BRANCHLESS (the only branch
    ; is the tail BNE that loops back), so every scanline costs exactly the
    ; same 62 cycles regardless of player or ball state. Cycle accounting
    ; (verified by the automated test suite from the assembled listing):
    ;
    ;   STA WSYNC            3   start of scanline
    ;   STA ENABL            3   apply the enable computed in the tail
    ;
    ;   Player block (one player):
    ;     TXA                 2   scanline index
    ;     SEC                 2
    ;     SBC PLAYERxY        3   row = X - Y (borrow when X < Y)
    ;     CMP #PLAYER_HEIGHT  2   row >= height -> off the paddle
    ;     LDA #0              2
    ;     SBC #0              2   A = $FF on paddle rows, $00 elsewhere
    ;     AND #PADDLE_BITS    2   A = %00111100 / $00
    ;     STA GRPx            3
    ;     Subtotal           18
    ;
    ;   Tail (per scanline):
    ;     TXA                 2
    ;     SEC                 2
    ;     SBC ball_y          3
    ;     CMP #BALL_HEIGHT    2
    ;     LDA #0              2
    ;     SBC #0              2   A = BALL_ENABLE on ball rows, $00 otherwise
    ;     INX                 2
    ;     CPX #KERNEL_SCANLINES 2
    ;     BNE KernelLoop      3   (taken, backward, same page)
    ;     Subtotal           20
    ;
    ; Total: 3 + 3 + 18 + 18 + 20 = 62 cycles < 76. Slack = 14 cycles.
    ;
    ; ENABL timing: the TIA samples the ball enable bit at the ball's
    ; horizontal position, NOT by latching the register for the following
    ; scanline (contrary to an earlier comment in this file). The old kernel
    ; wrote ENABL late in the scanline (~cycle 67), so whether the ball drew
    ; with the current or the previous line's value depended on ball_x vs
    ; the beam position at the write: the ball jumped one scanline in some
    ; horizontal regions. The fix writes ENABL during the horizontal
    ; blanking of every scanline (STA ENABL right after STA WSYNC, completing
    ; at ~cycle 5, far before the first visible pixel at ~cycle 22.7). The
    ; value is PRE-COMPUTED in the tail of the previous scanline for the
    ; current line, so the ball draws on exactly BALL_HEIGHT consecutive
    ; lines regardless of ball_x: line L shows the ball iff L-1 was a ball
    ; row, i.e. L in ball_y+1 .. ball_y+BALL_HEIGHT.
    ;
    ; Player timing: GRP0/GRP1 must be written before the beam reaches the
    ; player's fixed position (P0 at x=16 -> ~cycle 28.3; P1 at x=136 ->
    ; ~cycle 68). The branchless rectangle block completes GRP0 at ~cycle 23,
    ; leaving a safe margin. A table-driven player (indexed LDA + JMP) could
    ; not fit after the ENABL write that must lead the scanline.
    ;
    ; Line 0 (X = 0) stores the A = 0 left over from the pre-kernel, so the
    ; first visible scanline is always ball-free.
    ;
    ; Every iteration starts with STA WSYNC, so each iteration is exactly
    ; one scanline regardless of the branch taken. The frame therefore
    ; stays at 262 scanlines whether a player is still, rising, descending,
    ; the ball is present on the line or not.
KernelLoop:
    STA WSYNC               ; 3   start of scanline (physical line 41 + X)
    STA ENABL               ; 3   apply the enable precomputed in the tail

    ; Player 0 (left): solid rectangle of PADDLE_BITS on its rows.
    TXA                     ; 2
    SEC                     ; 2
    SBC P0Y                 ; 3   row = X - P0Y (borrow when X < P0Y)
    CMP #PLAYER_HEIGHT      ; 2   row >= height -> off the paddle
    LDA #0                  ; 2
    SBC #0                  ; 2   A = $FF on paddle rows, $00 elsewhere
    AND #PADDLE_BITS        ; 2   A = %00111100 on the paddle rows
    STA GRP0                ; 3

    ; Player 1 (right): same branchless rectangle, separate position.
    TXA                     ; 2
    SEC                     ; 2
    SBC P1Y                 ; 3   row = X - P1Y (borrow when X < P1Y)
    CMP #PLAYER_HEIGHT      ; 2
    LDA #0                  ; 2
    SBC #0                  ; 2
    AND #PADDLE_BITS        ; 2
    STA GRP1                ; 3

    ; Tail: precompute the ball enable for the NEXT scanline and loop back.
    ; On the ball rows (ball_y <= X < ball_y + BALL_HEIGHT) A becomes
    ; BALL_ENABLE ($FF), otherwise $00; the next iteration stores that value
    ; to ENABL at its top.
    TXA                     ; 2
    SEC                     ; 2
    SBC ball_y              ; 3   row = X - ball_y (borrow when X < ball_y)
    CMP #BALL_HEIGHT        ; 2   row >= height -> not a ball row
    LDA #0                  ; 2
    SBC #0                  ; 2   A = BALL_ENABLE on ball rows, $00 otherwise
    INX                     ; 2
    CPX #KERNEL_SCANLINES   ; 2
    BNE KernelLoop          ; 3   (taken; backward, same page)

    ; ---- Overscan: 30 scanlines ------------------------------------------
    LDA #VBLANK_BLANK       ; 2
    STA VBLANK              ; 3   blank output again
    LDA #0                  ; 2
    STA ENABL               ; 3   ball off during overscan: the last kernel
                            ;     line may have left ENABL = 1 when the ball
                            ;     rests at the bottom of the arena
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
; UpdateBall
;
; Moves the ball one pixel per frame on both axes (constant speed, no
; acceleration) and reverses a direction when the ball reaches an arena
; edge. Runs during VBLANK so the visible kernel stays branch-free.
;
; Bounce strategy: the ball moves exactly 1 pixel per frame, so it always
; lands exactly on a boundary pixel before reversing. Reversing AT the
; boundary (rather than clamping after an overshoot) keeps ball_x/ball_y
; inside [BALL_X_MIN..BALL_X_MAX] / [BALL_Y_MIN..BALL_Y_MAX] at all times;
; an unsigned wrap below the minimum can never occur.
;
; ball_dx/ball_dy hold the direction step (+1 = right/down, $FF = left/up).
; =============================================================================
UpdateBall:
    ; ---- Horizontal bounce (reverse at the exact left/right edges) ----
    LDA ball_x              ; 3
    CMP #BALL_X_MAX         ; 2   at the right edge?
    BNE .noRight            ; 2/3
    LDA #DIR_LEFT           ; 2
    STA ball_dx             ; 3   reverse horizontal direction
.noRight:
    LDA ball_x              ; 3
    CMP #BALL_X_MIN         ; 2   at the left edge?
    BNE .noLeft             ; 2/3
    LDA #DIR_RIGHT          ; 2
    STA ball_dx             ; 3
.noLeft:

    ; ---- Vertical bounce (reverse at the exact top/bottom edges) ------
    LDA ball_y              ; 3
    CMP #BALL_Y_MAX         ; 2   at the bottom edge?
    BNE .noBottom           ; 2/3
    LDA #DIR_UP             ; 2
    STA ball_dy             ; 3   reverse vertical direction
.noBottom:
    LDA ball_y              ; 3
    CMP #BALL_Y_MIN         ; 2   at the top edge?
    BNE .noTop              ; 2/3
    LDA #DIR_DOWN           ; 2
    STA ball_dy             ; 3
.noTop:

    ; ---- Move one pixel on both axes ----
    LDA ball_x              ; 3
    CLC                     ; 2
    ADC ball_dx             ; 3
    STA ball_x              ; 3
    LDA ball_y              ; 3
    CLC                     ; 2
    ADC ball_dy             ; 3
    STA ball_y              ; 3
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
    CLC                     ; 2
    ADC #7                  ; 2   q >= 1 compensation
    CMP #15                 ; 2   X + 7 >= 15  <=>  X >= 8
    BCS PositionP1          ; 2/3
    SEC                     ; 2
    SBC #3                  ; 2   q = 0 compensation (X + 4)
PositionP1:
    LDX #0                  ; 2   object 0 = player 0
    JSR PosObject           ; 6
    LDA #PLAYER2_X          ; 2
    CLC                     ; 2
    ADC #7                  ; 2
    CMP #15                 ; 2
    BCS PositionP2          ; 2/3
    SEC                     ; 2
    SBC #3                  ; 2
PositionP2:
    LDX #1                  ; 2   object 1 = player 1
    JSR PosObject           ; 6
    RTS                     ; 6

; =============================================================================
; PositionBall
;
; Horizontally places the ball with the same PosObject routine (object 4 =
; ball: RESBL + HMBL), using the HMBL fine value and the shared HMOVE on the
; last VBLANK line.
;
; Measured on the target (TIA/Stella): PosObject renders a player at
;   15*q + (s - 7)          for q >= 1
;   3 + (s - 7)             for q = 0   (RESP strobe before cycle 23)
; where the divide loop runs q+1 subtractions and s = input mod 15 is the
; fine-adjust table index. The ball additionally renders 1 pixel left of a
; player for the same input. To make the ball render at exactly ball_x:
;   ball_x >= 7  -> input = ball_x + 8  (q >= 1)
;   ball_x <= 6  -> input = ball_x + 5  (q = 0, coarse base is 2 not 0)
; so every ball_x in BALL_X_MIN..BALL_X_MAX maps to itself.
; =============================================================================
PositionBall:
    LDA ball_x              ; 3   visible left pixel
    CLC                     ; 2
    ADC #8                  ; 2   q >= 1 compensation
    CMP #15                 ; 2   ball_x + 8 >= 15  <=>  ball_x >= 7
    BCS PositionBallOk      ; 2/3
    SEC                     ; 2
    SBC #3                  ; 2   q = 0 compensation (ball_x + 5)
PositionBallOk:
    LDX #4                  ; 2   object 4 = ball
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
ball_x      DS 1            ; ball visible left pixel (BALL_X_MIN..BALL_X_MAX)
ball_y      DS 1            ; ball ENABL write scanline (BALL_Y_MIN..BALL_Y_MAX)
ball_dx     DS 1            ; horizontal step (+1 = right, $FF = left)
ball_dy     DS 1            ; vertical step (+1 = down, $FF = up)

; =============================================================================
; 6502 vectors
; =============================================================================
    SEG
    ORG $FFFA
    .WORD Reset             ; NMI (unused)
    .WORD Reset             ; RESET
    .WORD Reset             ; IRQ (unused)