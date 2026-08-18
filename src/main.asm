; =============================================================================
; Wizard Duel - Atari 2600
; main.asm
;
; Round 3 - basic projectiles and an event-driven kernel.
;
;   * stable NTSC frame, 262 scanlines
;   * two TIA players visible simultaneously (P0 left, P1 right)
;   * players rendered as simple vertical paddles (Pong-style rectangles)
;   * vertical-only movement, driven by joystick 1 and joystick 2
;   * a TIA Ball object moving continuously and bouncing off the arena edges
;   * each player can fire one missile with the joystick fire button
;     (INPT4 for P0, INPT5 for P1); missiles fly horizontally and despawn
;     at the arena edges
;   * the ball does NOT interact with the players or missiles yet (no
;     collision, collection, power-up, scoring or spells)
;
; The visible kernel is EVENT-DRIVEN. Round 2 rendered every object every
; scanline with a branchless "compute enable, write register" block; with a
; second pair of objects (the missiles) that no longer fits in the 76-cycle
; scanline budget. Instead, BuildEvents runs during VBLANK and writes a small
; table (evTbl) describing the register writes each scanline must perform.
; The kernel then only has to count down to the next event and apply its
; writes, which keeps every scanline well under 76 cycles (see the kernel
; comment below for the exact budget).
;
; Frame structure (NTSC):
;
;   VSYNC     3 scanlines   (lines 1..3,    explicit WSYNC)
;   VBLANK   57 scanlines   (lines 4..60,   TIM64T = VBLANK_TIMER_VALUE)
;   KERNEL  192 scanlines   (lines 61..252, explicit WSYNC loop)
;   OVERSCAN 10 scanlines   (lines 253..262, TIM64T = OVERSCAN_TIMER_VALUE)
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
    STA COLUPF              ; the ball and the missiles share this color
    LDA #BACKGR_COLOR
    STA COLUBK
    LDA #0
    STA NUSIZ0              ; player 0: 1 copy, normal size
    STA NUSIZ1              ; player 1: 1 copy, normal size
    STA VDELP0
    STA VDELP1
    LDA #MISSILE_NUSIZ      ; missiles 2 pixels wide (NUSIZ D5:D4 = %01)
    STA NUSIZ0
    STA NUSIZ1
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

    ; fire_prev is cleared by the RAM zeroing above, so the first button
    ; press after power-on is always treated as a fresh edge.

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
    STA TIM64T              ; 4   VBLANK countdown (56 * 64 = 3584 cycles)
    LDA #0                  ; 2
    STA VSYNC               ; 3   release vertical sync

    ; ---- VBLANK: game logic (input + movement + placement) --------------
    JSR UpdatePlayers       ; move both players vertically (see below)
    JSR UpdateBall          ; move the ball and bounce it off the arena edges
    JSR UpdateMissiles      ; fire, move and despawn both missiles
    JSR PositionPlayers     ; fixed horizontal placement (RESP + HMP)
    JSR PositionBall        ; ball horizontal placement (RESBL + HMBL)
    JSR PositionMissiles    ; missile horizontal placement (RESM + HMM)
    JSR BuildEvents         ; rebuild the event table for the visible kernel

    ; Wait for the VBLANK timer to expire on the penultimate VBLANK line.
    ; The timer expires while the second-to-last VBLANK line is being drawn;
    ; the WSYNC below then syncs to the last VBLANK line so the HMOVE can
    ; immediately follow it. The Stella Programmer's Guide requires HMOVE to
    ; immediately follow a WSYNC so the motion registers act during
    ; horizontal blanking of the last VBLANK line.
WaitVBlank:
    LDA INTIM               ; 3
    BNE WaitVBlank          ; 2/3

    ; Last VBLANK line: apply the horizontal fine movement, enable the
    ; display, clear every sprite/missile/ball output (the event table only
    ; turns objects on, it never blanks a full scanline) and prime the event
    ; kernel with the first entry's delta.
    STA WSYNC               ; 3   sync to the last VBLANK line
    STA HMOVE               ; 3   apply all HMP0..HMBL fine adjustments
    LDA #0                  ; 2
    STA VBLANK              ; 3   picture on from the next scanline
    STA GRP0                ; 3   clear objects for the first visible line
    STA GRP1                ; 3
    STA ENAM0               ; 3
    STA ENAM1               ; 3
    STA ENABL               ; 3
    LDA #KERNEL_SCANLINES   ; 2   prime the kernel line countdown
    STA scanCnt             ; 3
    LDY #0                  ; 2
    STY evIdx               ; 3   first table entry
    LDA evTbl               ; 3   first delta
    STA evCnt               ; 3
    JMP KernelLoop          ; 3

; =============================================================================
; Visible kernel: 192 scanlines.
;
; Scanline budget: 76 cycles. The kernel is event-driven: each scanline just
; counts down evCnt and, when it reaches zero, applies the two register
; writes of the current entry (evTbl + evIdx) and reloads the next delta.
; Because the writes are always present in the table entry (a single-write
; entry writes a harmless audio register as its second write), the event path
; is straight-line code with no conditional branches.
;
; The kernel counts exactly KERNEL_SCANLINES lines with a RAM countdown
; (scanCnt, primed to 192 before the kernel).  The line counter deliberately
; lives in RAM rather than in X: the event code uses X (TAX) as the register
; index, so an X line counter would be clobbered on every event line and the
; frame would drift longer than 262 scanlines.
;
; Worst case (a scanline where a two-write entry fires):
;   STA WSYNC            3   start of scanline
;   DEC scanCnt          5   kernel line countdown
;   BEQ .kernelEnd       2   (192 lines done)
;   DEC evCnt            5   count down to the next event
;   BNE KernelLoop       2   event line: not taken
;   LDY evIdx            3
;   LDA evTbl+1,Y        4   register index 1
;   TAX                  2
;   LDA evTbl+2,Y        4   value 1
;   STA EV_WRITE_BASE,X  4   GRP0..ENABL (or harmless AUDV1)
;   LDA evTbl+3,Y        4   register index 2
;   TAX                  2
;   LDA evTbl+4,Y        4   value 2
;   STA EV_WRITE_BASE,X  4
;   TYA                  2   advance to the next entry
;   CLC                  2
;   ADC #5               2
;   TAY                  2
;   STY evIdx            3
;   LDA evTbl,Y          4   next delta
;   STA evCnt            3
;   JMP KernelLoop       3
;   Total               69   < 76, slack = 7
;
; Best case (no event on the line): 3 + 5 + 2 + 5 + 3 = 18 cycles.
;
; Write timing: all object registers (GRP0..ENABL, EV_WRITE_BASE+X) are
; written early in the scanline, long before the beam reaches any object's
; horizontal position (P0 is leftmost at x=16 -> ~cycle 28), so the values
; always apply to the current line. This is the same invariant the Round 2
; kernel relied on for the ball enable.
;
; The kernel body is kept inside a single 256-byte page (ALIGN 256 before
; KernelLoop) so the backward branches have deterministic timing.
; =============================================================================
    ALIGN 256
KernelLoop:
    STA WSYNC               ; 3   start of scanline
    DEC scanCnt             ; 5   kernel line countdown (192 lines total)
    BEQ .kernelEnd          ; 2/3  192 lines drawn -> overscan
    DEC evCnt               ; 5   count down to the next event
    BNE KernelLoop          ; 2/3  not an event line -> loop back
    ; ---- event line: apply the current entry ----
    LDY evIdx               ; 3
    LDA evTbl+1,Y           ; 4   register index 1
    TAX                     ; 2
    LDA evTbl+2,Y           ; 4   value 1
    STA EV_WRITE_BASE,X     ; 4   write GRP0..ENABL
    LDA evTbl+3,Y           ; 4   register index 2
    TAX                     ; 2
    LDA evTbl+4,Y           ; 4   value 2
    STA EV_WRITE_BASE,X     ; 4
    TYA                     ; 2   advance the table pointer by one entry
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2
    STY evIdx               ; 3
    LDA evTbl,Y             ; 4   next delta
    STA evCnt               ; 3
    JMP KernelLoop          ; 3

    ; ---- Overscan: 10 scanlines ------------------------------------------
.kernelEnd:
    LDA #VBLANK_BLANK       ; 2
    STA VBLANK              ; 3   blank output again
    LDA #0                  ; 2
    STA GRP0                ; 3   clear every object: the last kernel lines
    STA GRP1                ; 3   may have left a register enabled (e.g. the
    STA ENAM0               ; 3   ball OFF event at row 192 is dropped), and
    STA ENAM1               ; 3   the display must never bleed into overscan
    STA ENABL               ; 3
    LDA #OVERSCAN_TIMER_VALUE ; 2
    STA TIM64T              ; 4   overscan countdown (22 * 64 = 1408 cycles)
OverscanWait:
    LDA INTIM               ; 3
    BNE OverscanWait        ; 2/3

    JMP StartOfFrame        ; 3   next frame

; =============================================================================
; UpdatePlayers
;
; Moves each player up/down by one scanline per frame based on its joystick
; and clamps the position to the arena. Runs during VBLANK so the visible
; kernel stays free of gameplay state.
;
; SWCHA bits (active low: 0 = pressed):
;   P0 (joystick 1, port 0): D4 up, D5 down
;   P1 (joystick 2, port 1): D0 up, D1 down
; Horizontal directions are intentionally ignored this round.
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
; edge. Runs during VBLANK so the visible kernel stays free of gameplay
; state.
;
; Bounce strategy: the ball moves exactly 1 pixel per frame, so it always
; lands exactly on a boundary pixel before reversing. Reversing AT the
; boundary (rather than clamping after an overshoot) keeps ball_x/ball_y
; inside [BALL_X_MIN..BALL_X_MAX] / [BALL_Y_MIN..BALL_Y_MAX] at all times;
; an unsigned wrap below the minimum can never occur.
;
; ball_dx/ball_dy hold the direction step (+1 = right/down, $FF = left/up).
; ball_y is the first scanline on which the ball is displayed (rows
; ball_y .. ball_y + BALL_HEIGHT - 1).
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
; UpdateMissiles
;
; Reads the two joystick fire buttons (INPT4 = P0, INPT5 = P1, bit 7 is 0
; while pressed) and spawns a missile on the falling edge of the button
; (button released, then pressed). A spawned missile keeps its spawn row
; (player row + MISSILE_SPAWN_OFFSET), moves horizontally at MISSILE_SPEED
; pixels per frame and despawns when it leaves the arena.
;
;   M0 (left player): x = M0_X_INIT (18), moves right, despawns at x > 158
;   M1 (right player): x = M1_X_INIT (134), moves left, despawns at x < 2
;
; fire_prev stores the previous frame's button state (bit 0 = P0, bit 1 =
; P1, 1 = pressed) so a fire is detected on the rising edge only; holding
; the button does not produce a stream of missiles.
; =============================================================================
UpdateMissiles:
    ; ---- sample both fire buttons into tempA (1 = pressed) ----
    LDA #0                  ; 2
    STA tempA               ; 3
    LDA INPT4               ; 3   P0 fire button
    AND #$80                ; 2
    BNE .p0NotPressed       ; 2/3
    LDA tempA               ; 3
    ORA #FIRE_P0            ; 2
    STA tempA               ; 3
.p0NotPressed:
    LDA INPT5               ; 3   P1 fire button
    AND #$80                ; 2
    BNE .p1NotPressed       ; 2/3
    LDA tempA               ; 3
    ORA #FIRE_P1            ; 2
    STA tempA               ; 3
.p1NotPressed:

    ; ---- M0: spawn on rising edge of the P0 fire button ----
    LDA tempA               ; 3
    AND #FIRE_P0            ; 2
    BEQ .m0NoSpawn          ; 2/3  not pressed this frame
    LDA fire_prev           ; 3
    AND #FIRE_P0            ; 2
    BNE .m0NoSpawn          ; 2/3  was already pressed -> no new edge
    LDA #1                  ; 2
    STA m0_active           ; 3
    LDA #M0_X_INIT          ; 2
    STA m0_x                ; 3
    LDA P0Y                 ; 3
    CLC                     ; 2
    ADC #MISSILE_SPAWN_OFFSET ; 2
    STA m0_y                ; 3
.m0NoSpawn:

    ; ---- M1: spawn on rising edge of the P1 fire button ----
    LDA tempA               ; 3
    AND #FIRE_P1            ; 2
    BEQ .m1NoSpawn          ; 2/3
    LDA fire_prev           ; 3
    AND #FIRE_P1            ; 2
    BNE .m1NoSpawn          ; 2/3
    LDA #1                  ; 2
    STA m1_active           ; 3
    LDA #M1_X_INIT          ; 2
    STA m1_x                ; 3
    LDA P1Y                 ; 3
    CLC                     ; 2
    ADC #MISSILE_SPAWN_OFFSET ; 2
    STA m1_y                ; 3
.m1NoSpawn:

    ; ---- remember this frame's button state ----
    LDA tempA               ; 3
    STA fire_prev           ; 3

    ; ---- M0: move right, despawn past the right edge ----
    LDA m0_active           ; 3
    BEQ .m0MoveDone         ; 2/3
    LDA m0_x                ; 3
    CLC                     ; 2
    ADC #MISSILE_SPEED      ; 2
    STA m0_x                ; 3
    CMP #M0_X_MAX + 1       ; 2   keep while x <= M0_X_MAX (fully visible)
    BCC .m0MoveDone         ; 2/3
    LDA #0                  ; 2
    STA m0_active           ; 3
.m0MoveDone:

    ; ---- M1: move left, despawn past the left edge ----
    LDA m1_active           ; 3
    BEQ .m1MoveDone         ; 2/3
    LDA m1_x                ; 3
    SEC                     ; 2
    SBC #MISSILE_SPEED      ; 2
    STA m1_x                ; 3
    CMP #M1_X_MIN           ; 2   keep while x >= M1_X_MIN
    BCS .m1MoveDone         ; 2/3
    LDA #0                  ; 2
    STA m1_active           ; 3
.m1MoveDone:

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
; PositionMissiles
;
; Horizontally places the two missiles with PosObject. Missiles are TIA
; Missile objects and, like the ball, render 1 pixel left of a player for the
; same input, so the compensation is identical to PositionBall (input = x + 8
; or x + 5 for the first 15-pixel region). Objects 2 (M0) and 3 (M1) map to
; RESM0/HMM0 and RESM1/HMM1.
;
; Inactive missiles are skipped: without a RESP write their position counter
; holds a stale value, but the event table never enables them, so they remain
; invisible.
; =============================================================================
PositionMissiles:
    LDA m0_active           ; 3
    BEQ .m0PosDone          ; 2/3
    LDA m0_x                ; 3
    CLC                     ; 2
    ADC #8                  ; 2   q >= 1 compensation (ball/missile offset)
    CMP #15                 ; 2
    BCS .m0PosOk            ; 2/3
    SEC                     ; 2
    SBC #3                  ; 2   q = 0 compensation
.m0PosOk:
    LDX #2                  ; 2   object 2 = missile 0
    JSR PosObject           ; 6
.m0PosDone:
    LDA m1_active           ; 3
    BEQ .m1PosDone          ; 2/3
    LDA m1_x                ; 3
    CLC                     ; 2
    ADC #8                  ; 2
    CMP #15                 ; 2
    BCS .m1PosOk            ; 2/3
    SEC                     ; 2
    SBC #3                  ; 2
.m1PosOk:
    LDX #3                  ; 2   object 3 = missile 1
    JSR PosObject           ; 6
.m1PosDone:
    RTS                     ; 6

; =============================================================================
; BuildEvents
;
; Rebuilds the event table (evTbl) for the visible kernel from the current
; positions of the players, ball and missiles. Runs during VBLANK after all
; movement and horizontal placement, so the table always describes exactly
; the frame about to be rendered.
;
; Phase 1 - generate records. Every object contributes an ON event (turn the
;   register on) and an OFF event (turn it off) at its display rows:
;
;     P0   ON (P0Y, GRP0, PADDLE_BITS)          OFF (P0Y+12, GRP0, 0)
;     P1   ON (P1Y, GRP1, PADDLE_BITS)          OFF (P1Y+12, GRP1, 0)
;     Ball ON (ball_y, ENABL, BALL_ENABLE)      OFF (ball_y+4, ENABL, 0)
;     M0   ON (m0_y, ENAM0, MISSILE_ENABLE)     OFF (m0_y+4, ENAM0, 0)
;     M1   ON (m1_y, ENAM1, MISSILE_ENABLE)     OFF (m1_y+4, ENAM1, 0)
;
;   Inactive missiles contribute nothing. AddEvent inserts each record into
;   the scratch buffer (events, 3 bytes each: row, reg, val) keeping it sorted
;   by row, and enforces the invariant that no row holds more than two
;   records (a third event on a full row is shifted to row+1).
;
; Phase 2 - emit. EmitEvents walks the sorted records once (linear), merging
;   at most two same-row records into a single entry (two writes) and writing
;   the deltas.  This is O(records), so the whole builder stays well inside
;   the VBLANK timer budget.
;
;   Deltas follow the kernel convention: delta(first) = row + 1 and
;   delta(next) = row - prevRow. Events with a row >= KERNEL_SCANLINES are
;   emitted harmlessly: their delta never reaches zero inside the 192-line
;   kernel. A terminator entry with delta = EV_TERMINATOR_DELTA ($FF) closes
;   the table so the kernel never reads past it.
;
; The builder runs in VBLANK (up to ~56*64 cycles available), so its own
; cycle count is not display-critical.
; =============================================================================
BuildEvents:
    ; ---- Phase 1: generate records ----
    LDA #0                  ; 2
    STA evCount             ; 3   reset the record count
    ; P0 ON / OFF
    LDA P0Y                 ; 3
    LDX #EV_REG_GRP0        ; 2
    LDY #PADDLE_BITS        ; 2
    JSR AddEvent            ; 6
    LDA P0Y                 ; 3
    CLC                     ; 2
    ADC #PLAYER_HEIGHT      ; 2
    LDX #EV_REG_GRP0        ; 2
    LDY #0                  ; 2
    JSR AddEvent            ; 6
    ; P1 ON / OFF
    LDA P1Y                 ; 3
    LDX #EV_REG_GRP1        ; 2
    LDY #PADDLE_BITS        ; 2
    JSR AddEvent            ; 6
    LDA P1Y                 ; 3
    CLC                     ; 2
    ADC #PLAYER_HEIGHT      ; 2
    LDX #EV_REG_GRP1        ; 2
    LDY #0                  ; 2
    JSR AddEvent            ; 6
    ; Ball ON / OFF
    LDA ball_y              ; 3
    LDX #EV_REG_ENABL       ; 2
    LDY #BALL_ENABLE        ; 2
    JSR AddEvent            ; 6
    LDA ball_y              ; 3
    CLC                     ; 2
    ADC #BALL_HEIGHT        ; 2
    LDX #EV_REG_ENABL       ; 2
    LDY #0                  ; 2
    JSR AddEvent            ; 6
    ; M0 ON / OFF (only while active)
    LDA m0_active           ; 3
    BEQ .m0EventsDone       ; 2/3
    LDA m0_y                ; 3
    LDX #EV_REG_ENAM0       ; 2
    LDY #MISSILE_ENABLE     ; 2
    JSR AddEvent            ; 6
    LDA m0_y                ; 3
    CLC                     ; 2
    ADC #MISSILE_HEIGHT     ; 2
    LDX #EV_REG_ENAM0       ; 2
    LDY #0                  ; 2
    JSR AddEvent            ; 6
.m0EventsDone:
    ; M1 ON / OFF (only while active)
    LDA m1_active           ; 3
    BEQ .m1EventsDone       ; 2/3
    LDA m1_y                ; 3
    LDX #EV_REG_ENAM1       ; 2
    LDY #MISSILE_ENABLE     ; 2
    JSR AddEvent            ; 6
    LDA m1_y                ; 3
    CLC                     ; 2
    ADC #MISSILE_HEIGHT     ; 2
    LDX #EV_REG_ENAM1       ; 2
    LDY #0                  ; 2
    JSR AddEvent            ; 6
.m1EventsDone:

    ; ---- Phase 2: sort the records by row, then emit the table ----
    JSR SortEvents          ; 6
    JMP EmitEvents          ; 3

; =============================================================================
; AddEvent
;
; Appends one event record (row, reg, val) to the events scratch buffer and
; records its byte offset in evOrder (the order array sorted by SortEvents).
;   A = row, X = register index, Y = value
; Clobbers A, X, Y and tempA.
; =============================================================================
AddEvent:
    STY tempA               ; 3   save value
    PHA                     ; 3   save row
    LDA evCount             ; 3
    ASL                     ; 2
    CLC                     ; 2
    ADC evCount             ; 3   A = evCount * 3 (byte offset of the new record)
    TAY                     ; 2   Y = record byte offset
    PLA                     ; 4   A = row
    STA events,Y            ; 4   store row
    TXA                     ; 2
    STA events+1,Y          ; 4   store register index
    LDA tempA               ; 3
    STA events+2,Y          ; 4   store value
    LDX evCount             ; 3   X = order index of the new record
    TYA                     ; 2   A = record byte offset
    STA evOrder,X           ; 4   evOrder[evCount] = offset
    INC evCount             ; 5
    RTS                     ; 6

; =============================================================================
; SortEvents
;
; Insertion-sorts evOrder[0..evCount) so that the rows of the referenced
; records are non-decreasing.  evOrder holds record byte offsets (0, 3, 6, ...),
; so shifting an order entry is a single-byte move (much cheaper than moving
; the 3-byte records themselves).
; =============================================================================
SortEvents:
    LDA evCount             ; 3
    CMP #2                  ; 2
    BCC .sortDone               ; 2/3  zero or one record: already sorted
    LDA #1                  ; 2
    STA recOff               ; 3   outer index i
.sortOuter:
    LDA recOff               ; 3
    CMP evCount             ; 3
    BCS .sortDone               ; 2/3
    LDX recOff               ; 3
    LDA evOrder,X           ; 4   key: record byte offset at order index i
    STA evOrderIdx             ; 3
    TAY                     ; 2
    LDA events,Y            ; 4   key row
    STA groupRow             ; 3
    LDX recOff               ; 3
    TXA                     ; 2
    TAY                     ; 2   Y = inner index j
.sortInner:
    TYA                     ; 2
    BEQ .sortPlace              ; 2/3  j == 0 -> insert at 0
    LDX evOrder-1,Y         ; 4   offset of the record at order index j-1
    LDA events,X            ; 4   row of j-1
    CMP groupRow             ; 3
    BCC .sortPlace              ; 2/3  row[j-1] < key -> insert at j
    LDA evOrder-1,Y         ; 4   shift evOrder[j-1] -> evOrder[j]
    STA evOrder,Y           ; 4
    DEY                     ; 2
    JMP .sortInner              ; 3
.sortPlace:
    LDA evOrderIdx             ; 3
    STA evOrder,Y           ; 4
    INC recOff               ; 5
    JMP .sortOuter              ; 3
.sortDone:
    RTS                     ; 6

; =============================================================================
; EmitEvents
;
; Walks evOrder (sorted by row) and writes the event table.  Two adjacent
; records on the same row are merged into a single entry (two writes).  If a
; pathological third record shares the row, its row is bumped to row+1 and its
; order entry is bubbled forward by BubbleOrder so it is emitted on the later
; line; this keeps every scanline inside the 76-cycle kernel budget.
;
; Deltas follow the kernel convention: delta(first) = row + 1 (prevRow starts
; at $FF = -1) and delta(next) = row - prevRow.  Records with a row >=
; KERNEL_SCANLINES are emitted harmlessly: their delta never reaches zero
; inside the 192-line kernel.  A terminator entry with delta =
; EV_TERMINATOR_DELTA ($FF) closes the table.
; =============================================================================
EmitEvents:
    LDA #$FF                ; 2
    STA prevRow             ; 3   sentinel -> first delta = row + 1
    LDA #0                  ; 2
    STA evOrderIdx          ; 3   order index
    STA evTblPtr            ; 3   evTbl byte offset

.recordLoop:
    LDA evOrderIdx          ; 3
    CMP evCount             ; 3
    BCC .processRecord      ; 2/3  records remain
    JMP .emitDone           ; 3

.processRecord:
    LDY evTblPtr            ; 3
    LDX evOrderIdx          ; 3
    LDA evOrder,X           ; 4   record byte offset
    TAX                     ; 2   X = record offset
    LDA events,X            ; 4   row
    STA groupRow            ; 3
    LDA events+1,X          ; 4   first write: register index
    STA evTbl+1,Y           ; 4
    LDA events+2,X          ; 4   first write: value
    STA evTbl+2,Y           ; 4
    LDA #0                  ; 2   default second write: dummy register
    STA evTbl+3,Y           ; 4
    STA evTbl+4,Y           ; 4

    ; ---- try to merge the next sorted record if it shares the row ----
    LDA evOrderIdx          ; 3
    CLC                     ; 2
    ADC #1                  ; 2
    STA recOff              ; 3   recOff = i+1 (emit continues here if no merge)
    TAX                     ; 2   X = i+1
    TXA                     ; 2
    CMP evCount             ; 3
    BCS .writeDelta         ; 2/3  no next record
    LDA evOrder,X           ; 4   A = next record offset
    STA nextOff             ; 3   save it
    TAY                     ; 2
    LDA events,Y            ; 4   next record's row
    CMP groupRow            ; 3
    BNE .writeDelta         ; 2/3  different row -> single write
    ; ---- merge the second record into the entry ----
    LDY evTblPtr            ; 3
    LDX nextOff             ; 3
    LDA events+1,X          ; 4
    STA evTbl+3,Y           ; 4
    LDA events+2,X          ; 4
    STA evTbl+4,Y           ; 4
    ; recOff = i+2 (skip past the merged pair)
    LDA recOff              ; 3
    CLC                     ; 2
    ADC #1                  ; 2
    STA recOff              ; 3
    ; ---- a pathological third record on the same row? ----
    TAX                     ; 2   X = i+2
    TXA                     ; 2
    CMP evCount             ; 3
    BCS .writeDelta         ; 2/3  no third record
    LDA evOrder,X           ; 4   A = third record offset
    TAY                     ; 2
    LDA events,Y            ; 4   third row
    CMP groupRow            ; 3
    BNE .writeDelta         ; 2/3  different row -> fine
    ; 3-way collision: bump the third record's row and bubble its order entry
    LDA events,Y            ; 4
    CLC                     ; 2
    ADC #1                  ; 2
    STA events,Y            ; 4   row++
    LDA recOff              ; 3
    STA bubbleIdx           ; 3   the nudged record's order index (i+2)
    JSR BubbleOrder         ; 6

.writeDelta:
    LDY evTblPtr            ; 3
    LDA groupRow            ; 3
    SEC                     ; 2
    SBC prevRow             ; 3
    STA evTbl,Y             ; 4   delta
    LDA groupRow            ; 3
    STA prevRow             ; 3
    LDA recOff              ; 3
    STA evOrderIdx          ; 3   advance the order index
    TYA                     ; 2   advance the table pointer
    CLC                     ; 2
    ADC #5                  ; 2
    STA evTblPtr            ; 3
    JMP .recordLoop         ; 3

.emitDone:
    ; ---- terminator entry: delta can never fire inside the kernel ----
    LDY evTblPtr            ; 3
    LDA #EV_TERMINATOR_DELTA ; 2
    STA evTbl,Y             ; 4
    LDA #0                  ; 2
    STA evTbl+1,Y           ; 4
    STA evTbl+2,Y           ; 4
    STA evTbl+3,Y           ; 4
    STA evTbl+4,Y           ; 4
    RTS                     ; 6

; =============================================================================
; BubbleOrder
;
; Bubbles the order entry at index bubbleIdx toward the end of evOrder while
; the row of the record it references (which was just bumped to a higher row)
; is larger than the row of the following entry.  Restores the sorted order
; after a 3-way-collision nudge.  The emit continues from recOff (unchanged),
; so the rearranged entries are emitted in their new row order.
; Clobbers A, X, Y, bubbleIdx, tempA.
; =============================================================================
BubbleOrder:
.bubLoop:
    LDA bubbleIdx           ; 3
    CLC                     ; 2
    ADC #1                  ; 2
    CMP evCount             ; 3
    BCS .bubDone               ; 2/3  reached the end
    TAX                     ; 2   X = bubbleIdx + 1
    ; row of the nudged record: events[evOrder[bubbleIdx]]
    LDY bubbleIdx           ; 3
    LDA evOrder,Y           ; 4
    TAY                     ; 2
    LDA events,Y            ; 4
    STA tempA            ; 3
    ; row of the following record: events[evOrder[X]]
    LDA evOrder,X           ; 4
    TAY                     ; 2
    LDA events,Y            ; 4
    CMP tempA            ; 3
    BCS .bubDone               ; 2/3  next >= nudged -> stop
    ; swap evOrder[bubbleIdx] and evOrder[X]
    LDY bubbleIdx           ; 3
    LDA evOrder,Y           ; 4
    PHA                     ; 3
    LDA evOrder,X           ; 4
    STA evOrder,Y           ; 4
    PLA                     ; 4
    STA evOrder,X           ; 4
    STX bubbleIdx           ; 3   nudged entry now at X
    JMP .bubLoop             ; 3
.bubDone:
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
ball_y      DS 1            ; ball first display row (BALL_Y_MIN..BALL_Y_MAX)
ball_dx     DS 1            ; horizontal step (+1 = right, $FF = left)
ball_dy     DS 1            ; vertical step (+1 = down, $FF = up)

; Missile state. m?_x is the leftmost visible pixel while active.
m0_x        DS 1            ; missile 0 horizontal position
m0_y        DS 1            ; missile 0 row (fixed while flying)
m0_active   DS 1            ; 1 = flying
m1_x        DS 1            ; missile 1 horizontal position
m1_y        DS 1            ; missile 1 row (fixed while flying)
m1_active   DS 1            ; 1 = flying

fire_prev   DS 1            ; packed fire-button state (bits FIRE_P0/FIRE_P1)
evCnt       DS 1            ; kernel: scanlines until the next event fires
evIdx       DS 1            ; kernel: byte offset of the current table entry
scanCnt     DS 1            ; kernel: line countdown (primed to KERNEL_SCANLINES)

evTbl       DS EV_TBL_SIZE  ; event table (55 bytes, see constants.inc)

; BuildEvents scratch: up to EV_MAX_EVENTS records of 3 bytes (row, reg, val).
events      DS EV_MAX_EVENTS * 3

evCount     DS 1            ; number of event records generated this frame

; Order array: evOrder[i] = byte offset of the i-th record when sorted by row.
; Sorting these single bytes is much cheaper than moving 3-byte records.
evOrder     DS EV_MAX_EVENTS

; BuildEvents working storage (each phase writes the shared temps before
; reading them, so the same byte is reused across phases).
groupRow    DS 1            ; SortEvents: key row  /  EmitEvents: entry row
prevRow     DS 1            ; EmitEvents: row of the previously written entry
evOrderIdx  DS 1            ; SortEvents: key offset  /  EmitEvents: order index
recOff      DS 1            ; SortEvents: outer index  /  EmitEvents: next order index
tempA       DS 1            ; UpdateMissiles fire state / AddEvent value / BubbleOrder row
evTblPtr    DS 1            ; EmitEvents: evTbl byte offset
nextOff     DS 1            ; EmitEvents: second record's byte offset during a merge
bubbleIdx   DS 1            ; EmitEvents/BubbleOrder: order index being bubbled

; =============================================================================
; 6502 vectors
; =============================================================================
    SEG
    ORG $FFFA
    .WORD Reset             ; NMI (unused)
    .WORD Reset             ; RESET
    .WORD Reset             ; IRQ (unused)
