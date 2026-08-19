; =============================================================================
; Wizard Duel - Atari 2600
; main.asm
;
; Round 3.1 - RAM optimization: the event kernel and builder were redesigned
; to cut RIOT RAM from 122 to 48 bytes (see the VARS segment and
; docs/en/memory-map.md).
;
;   * stable NTSC frame, 262 scanlines
;   * two TIA players visible simultaneously (P0 left, P1 right)
;   * players rendered as simple vertical paddles (Pong-style rectangles)
;   * vertical-only movement, driven by joystick 1 and joystick 2
;   * a TIA Ball object moving continuously and bouncing off the arena edges
;   * each player can fire one missile with the joystick fire button
;     (INPT4 for P0, INPT5 for P1); missiles fly horizontally and despawn
;     at the arena edges
;   * Round 4: TIA collision latches detect the cross-fire hits M0 -> P1 and
;     M1 -> P0.  ProcessCollisions (run at overscan init, after the kernel
;     that produced the overlaps) reads CXM0P/CXM1P, records the hit in the
;     one-byte hit_flags bitfield, deactivates the missile that scored it and
;     writes CXCLR so a hit is never counted twice.  No HP/damage is applied
;     yet.  The own-player bits (M0 x P0, M1 x P1) are ignored: a missile
;     never damages its own player.
;   * Round 5: hit_flags now drives real damage.  ProcessHitEffects (run at
;     overscan init, right after ProcessCollisions) removes one HP from the
;     player hit by each recorded cross-fire hit (no underflow below 0) and
;     locks a dead player's fire input so it can never spawn a missile.  A
;     dead player is no longer rendered (BuildEvents skips its events) but
;     keeps its position, and a missile that was already flying survives its
;     owner's death.  The overscan stays a fixed 10-line region: the WSYNC
;     countdown drops to OVERSCAN_LOOP_COUNT = 7 to absorb the added work.
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
; Round 3.1 change: entries are now VARIABLE-SIZE. A single write occupies 3
; bytes, a double write 5 bytes, and the table is terminated by a single $FF
; byte.  Because the common case is one write per scanline, the table shrank
; from a fixed 55 bytes to at most 31 bytes (10 singles + terminator), which
; allowed the builder scratch space to be removed entirely.
;
; Frame structure (NTSC):
;
;   VSYNC     3 scanlines   (lines 1..3,    explicit WSYNC)
;   VBLANK   64 scanlines   (lines 4..67,   TIM64T = VBLANK_TIMER_VALUE)
;   KERNEL  185 scanlines   (lines 68..252, explicit WSYNC loop)
;   OVERSCAN 10 scanlines   (lines 253..262, WSYNC countdown loop)
;   TOTAL   262 scanlines
;
; Round 6: VBLANK grew from 57 to 64 lines and the kernel shrank from 192 to
; 185 so the VBLANK TIM64T value could grow from 69 to 77.  Under real 6502
; branch timing (taken = 3 cycles, page crossing +1) the VBLANK work used to
; overrun the 69-timer expiry, making WaitVBlank exit at the (variable) work
; end instead of the timer, so frames slipped to 263/264/265 lines and the
; whole screen shook.  The 77 timer expires ~146 cycles past the worst work
; end; see constants.inc and docs/en/timing.md.
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

    ; Initial HP (Round 5): both players start at PLAYER_START_HP.
    LDA #PLAYER_START_HP
    STA p0_hp
    STA p1_hp

    ; fire_prev and fire_sync are cleared by the RAM zeroing above. The first
    ; UpdateMissiles call after power-on synchronizes fire_prev with the real
    ; button state instead of treating the boot-time INPT latch reading
    ; (which reads the fire lines as pressed) as a fresh rising edge.

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
    STA TIM64T              ; 4   VBLANK countdown (77 * 64 = 4928 cycles)
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
    LDY #0                  ; 2   Y = byte offset of the current entry
    LDA evTbl               ; 3   first delta
    STA evCnt               ; 3
    JMP KernelLoop          ; 3

; =============================================================================
; Visible kernel: 185 scanlines.
;
; Scanline budget: 76 cycles. The kernel is event-driven: each scanline just
; counts down evCnt and, when it reaches zero, applies the register writes of
; the current entry (evTbl indexed by Y) and reloads the next delta.  Entries
; are variable-size: a double entry (5 bytes) performs two writes, a single
; entry (3 bytes, marked by EV_SINGLE_FLAG = bit 7 of reg1) performs one.
; The three paths below are the only code executed during display.
;
; The kernel counts exactly KERNEL_SCANLINES lines with a RAM countdown
; (scanCnt, primed to 185 before the kernel).  The line counter deliberately
; lives in RAM rather than in X: the event code uses X (TAX) as the register
; index, so an X line counter would be clobbered on every event line and the
; frame would drift longer than 262 scanlines.  Y holds the table byte offset
; across the whole kernel (no STY/LDY per event line).
;
; Worst case (a scanline where a double-entry fires):
;   STA WSYNC            3   start of scanline
;   DEC scanCnt          5   kernel line countdown
;   BEQ .kernelEnd       2   (185 lines done)
;   DEC evCnt            5   count down to the next event
;   BNE KernelLoop       2   event line: not taken
;   LDA evTbl+1,Y        4   register index 1 (bit 7 = single flag)
;   BMI .singleWrite     2   double entry: not taken
;   TAX                  2   X = register index 1
;   LDA evTbl+2,Y        4   value 1
;   STA EV_WRITE_BASE,X  4   GRP0..ENABL
;   LDA evTbl+3,Y        4   register index 2
;   TAX                  2
;   LDA evTbl+4,Y        4   value 2
;   STA EV_WRITE_BASE,X  4
;   TYA                  2   advance Y past the 5-byte entry
;   CLC                  2
;   ADC #5               2
;   TAY                  2
;   LDA evTbl,Y          4   next delta
;   STA evCnt            3
;   JMP KernelLoop       3
;   Total               65   < 76, slack = 11
;
; Single-write event line: 54 cycles (BMI taken, one write, advance by 3).
; Non-event line: 3 + 5 + 2 + 5 + 3 (BNE taken) = 18 cycles.
;
; Write timing: on the double path the first register write lands during CPU
; cycle 30 and the second during cycle 44 of the scanline; the single-write
; path lands at cycle 33 (measured on the deterministic emulator).  A write
; before the beam passes the object's horizontal position applies to the
; current scanline; otherwise it applies one line later.  With the standard
; beam model (pixel p is reached at CPU cycle ~(p + 69) / 3) the gates are
; x >= 21 (first write), x >= 30 (single) and x >= 63 (second write).  The
; second slot is therefore ~42-49 pixels further right than the first, so an
; object whose X can fall below the second gate must never be written second.
; P0/P1 have fixed X (16/136) and the missiles have a bounded range, but the
; BALL's X spans the whole arena: InsertEvent therefore always gives ENABL
; the first write of a double (Round 8).  The leftmost ball positions still
; fall below even the first-write gate on the documented model; that residual
; is hardware-calibrated and reported in the Round 8 change log.
; See docs/en/timing.md.
;
; The kernel body is kept inside a single 256-byte page (ALIGN 256 before
; KernelLoop) so the backward branches have deterministic timing.
; =============================================================================
    ALIGN 256
KernelLoop:
    STA WSYNC               ; 3   start of scanline
    DEC scanCnt             ; 5   kernel line countdown (185 lines total)
    BEQ .kernelEnd          ; 2/3  185 lines drawn -> overscan
    DEC evCnt               ; 5   count down to the next event
    BNE KernelLoop          ; 2/3  not an event line -> loop back
    ; ---- event line: apply the current entry ----
    LDA evTbl+1,Y           ; 4   register index 1 (bit 7 = single flag)
    BMI .singleWrite        ; 2/3  single entry (flag set) -> one write
    ; ---- double entry (5 bytes): two register writes ----
    TAX                     ; 2   X = register index 1
    LDA evTbl+2,Y           ; 4   value 1
    STA EV_WRITE_BASE,X     ; 4   write GRP0..ENABL
    LDA evTbl+3,Y           ; 4   register index 2
    TAX                     ; 2
    LDA evTbl+4,Y           ; 4   value 2
    STA EV_WRITE_BASE,X     ; 4
    TYA                     ; 2   advance Y past the 5-byte entry
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2
    LDA evTbl,Y             ; 4   next delta
    STA evCnt               ; 3
    JMP KernelLoop          ; 3
.singleWrite:
    ; ---- single entry (3 bytes): one register write ----
    AND #$7F                ; 2   mask EV_SINGLE_FLAG off the index
    TAX                     ; 2   X = register index
    LDA evTbl+2,Y           ; 4   value
    STA EV_WRITE_BASE,X     ; 4
    TYA                     ; 2   advance Y past the 3-byte entry
    CLC                     ; 2
    ADC #3                  ; 2
    TAY                     ; 2
    LDA evTbl,Y             ; 4   next delta
    STA evCnt               ; 3
    JMP KernelLoop          ; 3

    ; ---- Overscan: 10 scanlines ------------------------------------------
    ; The overscan is a fixed WSYNC countdown, not a TIM64T wait.  A timer
    ; wait is only deterministic when the work before it is fixed: with the
    ; variable-cost collision pass the INTIM < 64 exit granularity made the
    ; overscan region land on different 76-cycle boundaries and the frame
    ; occasionally slipped to 263 scanlines.  Counting exactly
    ; OVERSCAN_LOOP_COUNT WSYNCs anchors the region: the collision pass
    ; (branchless, fixed cost) plus the Round 5 hit effects (branchy, but
    ; every path lands the first WSYNC on the same boundary - see
    ; ProcessHitEffects below) run before the loop, and the loop count was
    ; lowered to 7 so all that work still fits before the first boundary.
    ; The whole overscan stays exactly 760 cycles (10 lines) on every path.
.kernelEnd:
    LDA #VBLANK_BLANK       ; 2
    STA VBLANK              ; 3   blank output again
    LDA #0                  ; 2
    STA GRP0                ; 3   clear every object: the last kernel lines
    STA GRP1                ; 3   may have left a register enabled (e.g. the
    STA ENAM0               ; 3   ball OFF event at row 192 is dropped), and
    STA ENAM1               ; 3   the display must never bleed into overscan
    STA ENABL               ; 3
OverscanWait:
    ; Collision pass: reads the latches, updates hit_flags and m_active
    ; (fixed ~84 cycles, no branches - see ProcessCollisions below).
    JSR ProcessCollisions   ; 6 + ~84
    ; Round 5: consume hit_flags as HP damage and lock dead players' fire
    ; input.  Branchy, but its cost window keeps the first WSYNC on the same
    ; boundary (see ProcessHitEffects below).
    JSR ProcessHitEffects   ; 6 + 60..80

    ; Exactly OVERSCAN_LOOP_COUNT WSYNC writes.  From the kernel's last WSYNC
    ; (K) the epilogue (7 + 22) + JSR (6) + collision body (84 incl. RTS) +
    ; JSR (6) + hit-effects body (60..80 incl. RTS) + LDX (2) put the first
    ; write on cycle K+187..K+207, inside scanline 3 of the region; the
    ; alignment then snaps each iteration to a 76-cycle boundary, giving 7
    ; lines (K+228..K+684), and the JMP + VSYNC preamble that follow align the
    ; next frame's first VSYNC WSYNC to K+760.
    LDX #OVERSCAN_LOOP_COUNT ; 2
.overscanLoop:
    STA WSYNC               ; 3   one overscan line per iteration
    DEX                     ; 2
    BNE .overscanLoop       ; 2/3

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
;
; SWCHA is re-read for each direction (4 reads/frame).  The previous joystate
; scratch byte was removed to save RAM; the port reads are cheap and happen
; during VBLANK, where cycle count is not display-critical.
; =============================================================================
UpdatePlayers:
    ; Player 0 - up
    LDA SWCHA               ; 4   sample the joysticks
    AND #JOY1_UP            ; 2
    BNE .p0UpDone           ; 2/3
    LDA P0Y                 ; 3
    BEQ .p0UpDone           ; 2/3  already at the top of the arena
    DEC P0Y                 ; 5
.p0UpDone:

    ; Player 0 - down
    LDA SWCHA               ; 4
    AND #JOY1_DOWN          ; 2
    BNE .p0DownDone         ; 2/3
    LDA P0Y                 ; 3
    CMP #PLAYER_Y_MAX       ; 2
    BCS .p0DownDone         ; 2/3  already at the bottom of the arena
    INC P0Y                 ; 5
.p0DownDone:

    ; Player 1 - up
    LDA SWCHA               ; 4
    AND #JOY2_UP            ; 2
    BNE .p1UpDone           ; 2/3
    LDA P1Y                 ; 3
    BEQ .p1UpDone           ; 2/3
    DEC P1Y                 ; 5
.p1UpDone:

    ; Player 1 - down
    LDA SWCHA               ; 4
    AND #JOY2_DOWN          ; 2
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
; while pressed) and spawns a missile on the rising edge of the button
; (released -> pressed), and only while that player's missile is inactive.
; Holding the button does not produce a stream of missiles, and a rising edge
; while a missile is still flying neither spawns a second one nor resets the
; existing one.
;
;   M0 (left player): x = M0_X_INIT (18), moves right, despawns at x > 158
;   M1 (right player): x = M1_X_INIT (134), moves left, despawns at x < 2
;
; fire_prev stores the previous frame's button state (bit 0 = P0, bit 1 =
; P1, 1 = pressed) so a fire is detected on the rising edge only.  Both
; missiles share one packed "active" byte (m_active): bit 0 = M0, bit 1 =
; M1, which replaces the two separate m0_active/m1_active bytes of Round 3.
;
; Boot synchronisation: on real hardware (and in Stella) the TIA INPT latches
; read the fire lines as pressed for the first frames after RESET.  If the
; first UpdateMissiles treated that as a rising edge, every player would fire
; a missile at boot without touching the button.  Bit 7 of fire_prev
; (FIRE_SYNC) is cleared by Reset; on the first call UpdateMissiles only
; adopts the real button state into fire_prev (no spawn), so a genuine
; released->pressed transition is required to fire, and a button held at boot
; does not fire until it is released and pressed again.
; =============================================================================
UpdateMissiles:
    ; ---- sample both fire buttons into X (bits 1:0 = pressed mask) ----
    LDX #0                  ; 2
    LDA INPT4               ; 3   P0 fire button
    AND #$80                ; 2
    BNE .p0NotPressed       ; 2/3
    INX                     ; 2   bit 0
.p0NotPressed:
    LDA INPT5               ; 3   P1 fire button
    AND #$80                ; 2
    BNE .p1NotPressed       ; 2/3
    INX                     ; 2   bit 1
    INX                     ; 2
.p1NotPressed:

    ; ---- first frame after reset: adopt the real button state ----
    LDA fire_prev           ; 3
    BMI .edgeDetect         ; 2/3  bit 7 set -> already synchronised
    TXA                     ; 2
    ORA #FIRE_SYNC          ; 2   mark as synchronised
    STA fire_prev           ; 3   no spawn, just remember the real state
    JMP .movement           ; 3

.edgeDetect:
    ; ---- M0: spawn on rising edge while inactive ----
    TXA                     ; 2
    AND #FIRE_P0            ; 2
    BEQ .m0NoSpawn          ; 2/3  not pressed this frame
    LDA fire_prev           ; 3
    AND #FIRE_P0            ; 2
    BNE .m0NoSpawn          ; 2/3  was already pressed -> no new edge
    LDA m_active            ; 3
    AND #M0_BIT             ; 2
    BNE .m0NoSpawn          ; 2/3  still flying -> don't respawn
    LDA m_active            ; 3
    ORA #M0_BIT             ; 2
    STA m_active            ; 3
    LDA #M0_X_INIT          ; 2
    STA m0_x                ; 3
    LDA P0Y                 ; 3
    CLC                     ; 2
    ADC #MISSILE_SPAWN_OFFSET ; 2
    STA m0_y                ; 3
.m0NoSpawn:

    ; ---- M1: spawn on rising edge while inactive ----
    TXA                     ; 2
    AND #FIRE_P1            ; 2
    BEQ .m1NoSpawn          ; 2/3
    LDA fire_prev           ; 3
    AND #FIRE_P1            ; 2
    BNE .m1NoSpawn          ; 2/3
    LDA m_active            ; 3
    AND #M1_BIT             ; 2
    BNE .m1NoSpawn          ; 2/3  still flying -> don't respawn
    LDA m_active            ; 3
    ORA #M1_BIT             ; 2
    STA m_active            ; 3
    LDA #M1_X_INIT          ; 2
    STA m1_x                ; 3
    LDA P1Y                 ; 3
    CLC                     ; 2
    ADC #MISSILE_SPAWN_OFFSET ; 2
    STA m1_y                ; 3
.m1NoSpawn:

    ; ---- remember this frame's button state (keep the sync bit) ----
    TXA                     ; 2
    ORA #FIRE_SYNC          ; 2
    STA fire_prev           ; 3

.movement:
    ; ---- M0: move right, despawn past the right edge ----
    LDA m_active            ; 3
    AND #M0_BIT             ; 2
    BEQ .m0MoveDone         ; 2/3
    LDA m0_x                ; 3
    CLC                     ; 2
    ADC #MISSILE_SPEED      ; 2
    STA m0_x                ; 3
    CMP #M0_X_MAX + 1       ; 2   keep while x <= M0_X_MAX (fully visible)
    BCC .m0MoveDone         ; 2/3
    LDA m_active            ; 3
    AND #%11111110          ; 2   clear the M0 bit
    STA m_active            ; 3
.m0MoveDone:

    ; ---- M1: move left, despawn past the left edge ----
    LDA m_active            ; 3
    AND #M1_BIT             ; 2
    BEQ .m1MoveDone         ; 2/3
    LDA m1_x                ; 3
    SEC                     ; 2
    SBC #MISSILE_SPEED      ; 2
    STA m1_x                ; 3
    CMP #M1_X_MIN           ; 2   keep while x >= M1_X_MIN
    BCS .m1MoveDone         ; 2/3
    LDA m_active            ; 3
    AND #%11111101          ; 2   clear the M1 bit
    STA m_active            ; 3
.m1MoveDone:

    RTS                     ; 6

; =============================================================================
; ProcessCollisions
;
; Converts the TIA collision latches left by the current frame's visible
; kernel into gameplay hits.  Runs at overscan init, after the kernel that
; produced the overlaps: the deactivated missile is already inactive when the
; NEXT frame's UpdateMissiles checks m_active for a new rising-edge spawn.
;
; Collision lifecycle (documented decision, Round 4):
;
;     visible kernel renders  -> TIA latches accumulate
;     same frame's OVERSCAN   -> game reads the latches (no side effects)
;     game state updated      -> hit_flags set, scoring missile deactivated
;     same OVERSCAN           -> CXCLR clears every latch
;
; The latches are NOT cleared earlier: the whole overscan + VSYNC stretch is
; blanked (VBLANK bit set) and every object is cleared at overscan init, so
; no new collisions can be latched after the kernel ends.  Reading here and
; writing CXCLR immediately after can therefore never lose a hit, and the
; clear guarantees a hit rendered in frame N is never counted again in frame
; N+2.  The visible kernel is untouched: the hit is processed at the end of
; the frame whose render produced the overlap, so the missile that scored
; stays visible on the collision frame and disappears on the next - standard
; latch-based behavior.
;
; Only the cross-fire hits matter this round:
;
;     CXM0P D7 (M0 x P1)  -> HIT_P1, deactivate M0
;     CXM1P D7 (M1 x P0)  -> HIT_P0, deactivate M1
;
; The own-player bits (CXM0P D6 = M0 x P0, CXM1P D6 = M1 x P1) are ignored:
; a missile never damages its own player, even if the hardware reports the
; latch.  Reading a latch has no side effects, and CXCLR is written only at
; the end, so simultaneous hits (M0 -> P1 AND M1 -> P0 in the same frame)
; are both recorded and both missiles are deactivated independently.
;
; Placement note: ProcessCollisions deliberately runs at overscan init rather
; than in VBLANK.  The heaviest VBLANK path is already within a few cycles of
; the VBLANK timer window's alignment boundary, so adding the collision pass
; there made one frame per stress run slip to 263 scanlines.  An overscan
; TIM64T wait was also tried, but the emulator's INTIM < 64 exit granularity
; makes a timer wait nondeterministic whenever the pre-timer work varies, so
; the collision pass had to become BRANCHLESS (fixed ~84-cycle cost) and the
; overscan had to become a fixed WSYNC countdown (see the overscan section).
;
; This routine is branchless by construction: the latches are turned into
; 0/1 flags with the carry (ASL + ADC #0), hit_flags is the packed sum
; 2*hit0 + hit1, and the m_active update is a single lookup in newActiveTbl
; indexed by m_active + 4*hit0 + 8*hit1 (the high index bits select whether
; M0 and/or M1 cleared).  With no branches and a page-aligned table the cost
; is fixed on every path.
;
; Cycle budget (fixed path, no branches):
;   hit0/hit1 extraction       22
;   hit_flags = 2*hit0 + hit1  11
;   m_active table lookup      42
;   CXCLR + RTS                 9
;   Total                      84
;
; tempCount is a BuildEvents scratch (written before every use in VBLANK);
; reusing it here is safe because the collision pass runs after BuildEvents
; and nothing reads it between the two.
; =============================================================================
ProcessCollisions:
    ; ---- extract hit0 (CXM0P D7) and hit1 (CXM1P D7) as 0/1 flags ----
    LDA CXM0P               ; 3   read the M0/players collision latch
    ASL                     ; 2   carry = M0 x P1 (D7)
    LDA #0                  ; 2
    ADC #0                  ; 2   A = hit0 (0/1)
    TAY                     ; 2   Y = hit0
    LDA CXM1P               ; 3   read the M1/players collision latch
    ASL                     ; 2   carry = M1 x P0 (D7)
    LDA #0                  ; 2
    ADC #0                  ; 2   A = hit1 (0/1)
    TAX                     ; 2   X = hit1

    ; ---- hit_flags = 2*hit0 + hit1 (0, HIT_P1, HIT_P0 or both) ----
    TYA                     ; 2
    ASL                     ; 2   A = 2*hit0
    CPX #1                  ; 2   carry = hit1
    ADC #0                  ; 2   A = 2*hit0 + hit1
    STA hit_flags           ; 3

    ; ---- m_active = newActiveTbl[m_active + 4*hit0 + 8*hit1] ----
    TYA                     ; 2   A = hit0
    ASL                     ; 2
    ASL                     ; 2   A = 4*hit0
    STA tempCount           ; 3   scratch (see note above)
    TXA                     ; 2   A = hit1
    ASL                     ; 2
    ASL                     ; 2
    ASL                     ; 2   A = 8*hit1
    CLC                     ; 2
    ADC tempCount           ; 3   A = 4*hit0 + 8*hit1
    STA tempCount           ; 3
    LDA m_active            ; 3   A = current active mask (0..3)
    CLC                     ; 2
    ADC tempCount           ; 3   A = table index
    TAY                     ; 2   Y = index
    LDA newActiveTbl,Y      ; 4   clear the bit of every scoring missile
    STA m_active            ; 3   M0 disappears at the next render

    STA CXCLR               ; 3   clear every collision latch (strobe; the
                            ;     value written is ignored by the TIA)
    RTS                     ; 6

; newActiveTbl: index = m_active + 4*hit0 + 8*hit1.
;   m_active bits: bit0 = M0 flying, bit1 = M1 flying.
;   hit0 (index bit 2) clears bit0 (M0 scored), hit1 (index bit 3) clears
;   bit1 (M1 scored).  The table is page-aligned (16-byte boundary) so the
;   LDA newActiveTbl,Y lookup can never cross a 256-byte page and the routine
;   stays fixed-cost on the real 6502.
    ALIGN 16
newActiveTbl:
    DC.B 0, 1, 2, 3         ; no hits: keep m_active
    DC.B 0, 0, 2, 2         ; hit0: clear the M0 bit
    DC.B 0, 1, 0, 1         ; hit1: clear the M1 bit
    DC.B 0, 0, 0, 0         ; both hits: clear both

; =============================================================================
; ProcessHitEffects (Round 5)
;
; Consumes the hit_flags record written by ProcessCollisions (same overscan)
; as real HP damage and keeps dead players from firing:
;
;   * HIT_P0 -> decrement p0_hp, HIT_P1 -> decrement p1_hp, one HP per hit;
;   * a player already at 0 HP ignores further hits (never goes negative);
;   * hit_flags is READ but NOT cleared here: ProcessCollisions overwrites the
;     byte at the start of the NEXT frame's overscan, so each recorded hit is
;     consumed exactly once and Round 4's test contract (hit_flags observable
;     after the frame) is preserved;
;   * the dead-player fire lock: a player with 0 HP must never present a
;     rising fire edge to UpdateMissiles, so its FIRE_P0/FIRE_P1 bit in
;     fire_prev is forced to 1 ("pressed").  UpdateMissiles spawns only on a
;     released->pressed edge and OVERWRITES fire_prev during every VBLANK, so
;     the lock must be re-applied here every overscan.  It is computed
;     branchlessly with the ADC carry trick ("LDA hp; CLC; ADC #$FF" sets
;     carry = 1 iff the player is alive), building the dead mask
;     FIRE_P0 * (p0 dead) + FIRE_P1 * (p1 dead) and OR-ing it into fire_prev.
;
; Cost: unlike ProcessCollisions this routine is BRANCHY.  That is safe
; because the overscan is anchored by the fixed WSYNC countdown, not a timer:
; every path only has to land the first overscan WSYNC on the same 76-cycle
; boundary.  Per-path cost (emulator model, branch = 2 cycles):
;
;   P0 damage (not-hit / hit-dead / hit-alive)   7 / 12 / 17
;   P1 damage (not-hit / hit-dead / hit-alive)   7 / 12 / 17
;   fire lock (branchless)                      40
;   RTS                                          6
;
;   total B in [60, 80].  From the last kernel WSYNC landing (K) the fixed
;   part (DEC+Branch 7 + epilogue 22 + JSR ProcessCollisions 6 + collision
;   body 84 + JSR 6 + LDX 2) is 127, so the first overscan WSYNC write happens
;   at K + 127 + B in [K + 187, K + 207], which lands on K + 228 for EVERY
;   path.  With OVERSCAN_LOOP_COUNT = 7 the last overscan WSYNC lands on
;   K + 684 and the next frame's first VSYNC WSYNC lands on K + 760: the
;   overscan region is exactly 10 lines regardless of how many hits occurred.
;
;   On a real 6502 a taken branch costs +1 (and +1 more on a page crossing):
;   the damage costs become 8/13/17, total B in [62, 80], first write in
;   [K + 190, K + 208] - still strictly inside (K + 152, K + 228].  The ALIGN
;   256 below keeps the four BEQs inside one page so a page crossing can
;   never add a cycle.
; =============================================================================
    ALIGN 256
ProcessHitEffects:
    ; ---- P0 damage: HIT_P0 set and P0 alive -> lose one HP ----
    LDA hit_flags           ; 3
    AND #HIT_P0             ; 2
    BEQ .p0After            ; 2/3  not hit
    LDA p0_hp               ; 3
    BEQ .p0After            ; 2/3  already dead: ignore further hits
    DEC p0_hp               ; 5
.p0After:
    ; ---- P1 damage: HIT_P1 set and P1 alive -> lose one HP ----
    LDA hit_flags           ; 3
    AND #HIT_P1             ; 2
    BEQ .p1After            ; 2/3  not hit
    LDA p1_hp               ; 3
    BEQ .p1After            ; 2/3  already dead: ignore further hits
    DEC p1_hp               ; 5
.p1After:
    ; ---- dead-player fire lock (branchless) ----
    LDA p0_hp               ; 3
    CLC                     ; 2
    ADC #$FF                ; 2   carry = 1 iff p0 alive
    LDA #0                  ; 2
    ADC #0                  ; 2   A = alive0 (0/1)
    EOR #1                  ; 2   A = dead0 (0/1)
    STA tempCount           ; 3   dead mask bit 0
    LDA p1_hp               ; 3
    CLC                     ; 2
    ADC #$FF                ; 2   carry = 1 iff p1 alive
    LDA #0                  ; 2
    ADC #0                  ; 2   A = alive1 (0/1)
    EOR #1                  ; 2   A = dead1 (0/1)
    ASL                     ; 2   A = dead1 * 2 (mask bit 1)
    ORA tempCount           ; 3   full dead mask
    ORA fire_prev           ; 3   force the locked bits
    STA fire_prev           ; 3
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
    LDA m_active            ; 3
    AND #M0_BIT             ; 2
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
    LDA m_active            ; 3
    AND #M1_BIT             ; 2
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
; Every object contributes an ON event (turn the register on) and an OFF
; event (turn it off) at its display rows:
;
;     P0   ON (P0Y, GRP0, PADDLE_BITS)          OFF (P0Y+12, GRP0, 0)
;     P1   ON (P1Y, GRP1, PADDLE_BITS)          OFF (P1Y+12, GRP1, 0)
;     Ball ON (ball_y, ENABL, BALL_ENABLE)      OFF (ball_y+4, ENABL, 0)
;     M0   ON (m0_y, ENAM0, MISSILE_ENABLE)     OFF (m0_y+4, ENAM0, 0)
;     M1   ON (m1_y, ENAM1, MISSILE_ENABLE)     OFF (m1_y+4, ENAM1, 0)
;
;   Inactive missiles contribute nothing, and (Round 5) a player with 0 HP
;   contributes nothing either: BuildEvents skips the P0/P1 events of a dead
;   player so it is simply not drawn.  InsertEvent inserts every event
;   directly into evTbl in row order, merging same-row singles into doubles
;   and bumping surplus same-row events to row+1, so no scanline ever needs
;   more than two writes.  When a ball event merges into a double it is
;   always written FIRST (see InsertEvent: the ball's X spans the whole
;   arena, so it must never take the late second write).  The table holds
;   ABSOLUTE rows while it is built; ConvertDeltas turns them into the
;   deltas the kernel counts down.  Because the table is variable-size and
;   never exceeds EV_TBL_SIZE bytes (10 singles + terminator = 31), no
;   separate record/order scratch buffer is needed.
;
; The builder runs in VBLANK (up to ~56*64 cycles available), so its own
; cycle count is not display-critical.
; =============================================================================
BuildEvents:
    ; ---- reset the table to just its terminator ----
    LDA #EV_TERMINATOR_DELTA ; 2
    STA evTbl               ; 3
    LDA #1                  ; 2
    STA tblLen              ; 3   table length in bytes
    ; ---- P0 ON / OFF (only while alive: a dead player is not rendered) ----
    LDA p0_hp               ; 3
    BEQ .p0EventsDone       ; 2/3  dead -> no events
    LDA P0Y                 ; 3
    LDX #EV_REG_GRP0        ; 2
    LDY #PADDLE_BITS        ; 2
    JSR InsertEvent         ; 6
    LDA P0Y                 ; 3
    CLC                     ; 2
    ADC #PLAYER_HEIGHT      ; 2
    LDX #EV_REG_GRP0        ; 2
    LDY #0                  ; 2
    JSR InsertEvent         ; 6
.p0EventsDone:
    ; ---- P1 ON / OFF (only while alive: a dead player is not rendered) ----
    LDA p1_hp               ; 3
    BEQ .p1EventsDone       ; 2/3  dead -> no events
    LDA P1Y                 ; 3
    LDX #EV_REG_GRP1        ; 2
    LDY #PADDLE_BITS        ; 2
    JSR InsertEvent         ; 6
    LDA P1Y                 ; 3
    CLC                     ; 2
    ADC #PLAYER_HEIGHT      ; 2
    LDX #EV_REG_GRP1        ; 2
    LDY #0                  ; 2
    JSR InsertEvent         ; 6
.p1EventsDone:
    ; ---- Ball ON / OFF ----
    LDA ball_y              ; 3
    LDX #EV_REG_ENABL       ; 2
    LDY #BALL_ENABLE        ; 2
    JSR InsertEvent         ; 6
    LDA ball_y              ; 3
    CLC                     ; 2
    ADC #BALL_HEIGHT        ; 2
    LDX #EV_REG_ENABL       ; 2
    LDY #0                  ; 2
    JSR InsertEvent         ; 6
    ; ---- M0 ON / OFF (only while active) ----
    LDA m_active            ; 3
    AND #M0_BIT             ; 2
    BEQ .m0EventsDone       ; 2/3
    LDA m0_y                ; 3
    LDX #EV_REG_ENAM0       ; 2
    LDY #MISSILE_ENABLE     ; 2
    JSR InsertEvent         ; 6
    LDA m0_y                ; 3
    CLC                     ; 2
    ADC #MISSILE_HEIGHT     ; 2
    LDX #EV_REG_ENAM0       ; 2
    LDY #0                  ; 2
    JSR InsertEvent         ; 6
.m0EventsDone:
    ; ---- M1 ON / OFF (only while active) ----
    LDA m_active            ; 3
    AND #M1_BIT             ; 2
    BEQ .m1EventsDone       ; 2/3
    LDA m1_y                ; 3
    LDX #EV_REG_ENAM1       ; 2
    LDY #MISSILE_ENABLE     ; 2
    JSR InsertEvent         ; 6
    LDA m1_y                ; 3
    CLC                     ; 2
    ADC #MISSILE_HEIGHT     ; 2
    LDX #EV_REG_ENAM1       ; 2
    LDY #0                  ; 2
    JSR InsertEvent         ; 6
.m1EventsDone:

    ; ---- convert absolute rows to kernel deltas ----
    JMP ConvertDeltas       ; 3

; =============================================================================
; InsertEvent
;
; Inserts one event (row, reg, val) into evTbl, which holds ABSOLUTE rows
; while the builder runs.  Entries are variable-size and kept sorted by row:
;
;   single entry:  [row, reg | EV_SINGLE_FLAG, val]      (3 bytes)
;   double entry:  [row, reg1, val1, reg2, val2]         (5 bytes)
;
; The scan walks the table from the first byte:
;   * the terminator (row $FF) is reached, or the current entry's row is
;     larger: insert a new single entry before it (shift-by-3);
;   * the current entry shares the row AND is a single: merge the new event
;     into it as its second write (shift-by-2), converting it to a double;
;     if the new event is the ball (ENABL), it is swapped into the FIRST
;     write instead, because the ball's X is variable and the second write
;     (cycle 44) may land after the beam passed ball_x;
;   * the current entry shares the row but is already a double: bump the new
;     event's row to row+1 and continue the scan (a table entry never holds
;     three writes, which would break the 76-cycle kernel budget).
;
; Because merging a same-row event replaces two separate singles with one
; double (6 -> 5 bytes), the table can never exceed EV_TBL_SIZE bytes.
;
; A = row, X = register index, Y = value.
; Uses evRow, tempCount, tblLen and the stack (row/reg/val are held on the
; stack while the table is scanned and shifted).
; =============================================================================
InsertEvent:
    STA evRow               ; 3   save the event row
    PHA                     ; 3   save the row on the stack
    TXA                     ; 2
    PHA                     ; 3   save reg on the stack
    TYA                     ; 2
    PHA                     ; 3   save val on the stack
    LDY #0                  ; 2   scan from the first table byte
.scan:
    LDA evTbl,Y             ; 4   row of the current entry ($FF = terminator)
    CMP #EV_TERMINATOR_DELTA ; 2
    BEQ .insertSingle       ; 2/3  end of the table -> insert a single entry
    CMP evRow               ; 3
    BCC .advance            ; 2/3  current row < new row -> keep scanning
    BEQ .sameRow            ; 2/3  current row == new row
    JMP .insertSingle       ; 3   current row > new row -> insert before it
.advance:
    LDA evTbl+1,Y           ; 4   reg1 of the current entry (flag in bit 7)
    AND #EV_SINGLE_FLAG     ; 2
    BNE .advanceSingle      ; 2/3  single entry -> advance by 3
    TYA                     ; 2   double entry -> advance by 5
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2
    JMP .scan               ; 3
.advanceSingle:
    TYA                     ; 2
    CLC                     ; 2
    ADC #3                  ; 2
    TAY                     ; 2
    JMP .scan               ; 3
.sameRow:
    LDA evTbl+1,Y           ; 4   reg1 of the same-row entry
    AND #EV_SINGLE_FLAG     ; 2
    BNE .mergeSingle        ; 2/3  single entry -> merge into a double
    INC evRow               ; 5   double entry: bump the new event to row+1
    JMP .advance            ; 3   and keep scanning
.mergeSingle:
    ; convert the 3-byte single at Y into a 5-byte double:
    TYA                     ; 2
    CLC                     ; 2
    ADC #2                  ; 2   make room for reg2/val2 at oldY+2
    TAY                     ; 2
    JSR ShiftBy2            ; 6   (Y is preserved)
    PLA                     ; 4   val
    STA evTbl+2,Y           ; 4   val2   (Y+2 = oldY+4)
    PLA                     ; 4   reg
    STA evTbl+1,Y           ; 4   reg2   (Y+1 = oldY+3)
    CMP #EV_REG_ENABL       ; 2   did the ball event merge as the second write?
    BNE .noBallSwap         ; 2/3
    ; Round 8 (ball write-slot fix): the ball's X spans the whole arena, so a
    ; second-write (cycle 44) can land after the beam passed ball_x and push
    ; the ball's ON/OFF to the next scanline (a 1-scanline vertical shift).
    ; Give ENABL the first write (cycle 30, the earliest slot) by swapping it
    ; into reg1.  reg1 cannot already be ENABL here: ball_y != ball_y + 4 and
    ; a merge happens only into a single entry, never into an existing double.
    ; The co-object then takes the second write; players (P0 x=16) are the
    ; only objects whose fixed X falls below the second-write gate, so those
    ; rare shared rows shift that player edge instead of the ball.  The
    ; definitive fix (writes early enough for every X) requires an earlier
    ; kernel write slot and is documented as a known limitation.
    LDA evTbl-1,Y           ; 4   existing reg1 (flag in bit 7)
    AND #$7F                ; 2   clear the single flag -> becomes clean reg2
    STA evTbl+1,Y           ; 4
    LDA #EV_REG_ENABL       ; 2   reg1 = ball (flag already clear)
    STA evTbl-1,Y           ; 4
    LDA evTbl,Y             ; 4   existing val1 -> becomes val2
    LDX evTbl+2,Y           ; 4   new val2 (ball value) -> becomes val1
    STA evTbl+2,Y           ; 4   (STA zp,Y is used instead of STX zp,Y,
    TXA                     ; 2    which has no emulator coverage)
    STA evTbl,Y             ; 4
.noBallSwap:
    LDA evTbl-1,Y           ; 4   reg1   (Y-1 = oldY+1, flag in bit 7)
    AND #$7F                ; 2   clear the single flag -> now a double
    STA evTbl-1,Y           ; 4
    LDA tblLen              ; 3
    CLC                     ; 2
    ADC #2                  ; 2
    STA tblLen              ; 3
    PLA                     ; 4   discard the saved row
    RTS                     ; 6
.insertSingle:
    JSR ShiftBy3            ; 6   make room for the 3-byte entry (Y preserved)
    PLA                     ; 4   val
    STA evTbl+2,Y           ; 4
    PLA                     ; 4   reg
    ORA #EV_SINGLE_FLAG     ; 2
    STA evTbl+1,Y           ; 4
    PLA                     ; 4   discard the original stacked row
    LDA evRow               ; 3   use the effective row (may have been bumped)
    STA evTbl,Y             ; 4
    LDA tblLen              ; 3
    CLC                     ; 2
    ADC #3                  ; 2
    STA tblLen              ; 3
    RTS                     ; 6

; =============================================================================
; ShiftBy2 / ShiftBy3
;
; Shift every byte at index >= Y up by 2 (ShiftBy2) or 3 (ShiftBy3) so
; InsertEvent can extend a same-row single into a double (2 bytes) or insert
; a new single entry (3 bytes) at Y.  Runs from the top of the table down so
; no byte is overwritten before it is read.  Preserves Y; clobbers A, X and
; tempCount.
;
; Bounds: a shift-by-3 happens only when inserting a new single, which can
; push the table to at most 31 bytes, so tblLen is <= 28 before it and the
; largest write index is 30 (evTbl+3,X with X = tblLen-1 <= 27).  A
; shift-by-2 (a merge) never needs more than index 30 either.  All accesses
; stay inside the 31-byte table.
;
; The loop terminates when X == tempCount (after copying the insertion point's
; byte).  DEX wraps 0 -> $FF, so the loop must test X before it can wrap:
; CPX + BNE stops at X == tempCount instead of comparing X >= tempCount.
; =============================================================================
ShiftBy2:                    ; Y = first index to move
    STY tempCount            ; 3   remember the insertion point
    LDX tblLen               ; 3   X = table length in bytes
.shift2Loop:
    DEX                     ; 2   next byte down
    LDA evTbl,X              ; 4   copy the byte...
    STA evTbl+2,X            ; 4   ...two positions up
    CPX tempCount            ; 3   stop after the insertion point
    BNE .shift2Loop           ; 2/3
    RTS                     ; 6

ShiftBy3:                    ; Y = first index to move
    STY tempCount            ; 3
    LDX tblLen               ; 3
.shift3Loop:
    DEX                     ; 2
    LDA evTbl,X              ; 4
    STA evTbl+3,X            ; 4   ...three positions up
    CPX tempCount            ; 3
    BNE .shift3Loop           ; 2/3
    RTS                     ; 6

; =============================================================================
; ConvertDeltas
;
; Walks the finished table and replaces every absolute row with the delta the
; kernel counts down: delta(first) = row + 1 (prevRow starts at $FF = -1) and
; delta(next) = row - prevRow.  Events with a row >= KERNEL_SCANLINES are
; emitted harmlessly: their delta never reaches zero inside the 185-line
; kernel.  The terminator keeps delta = EV_TERMINATOR_DELTA ($FF), which can
; never fire.  Clobbers A, X, Y, evRow and tempCount.
; =============================================================================
ConvertDeltas:
    LDY #0                  ; 2   scan from the first byte
    LDA #$FF                ; 2
    STA tempCount           ; 3   prevRow sentinel
.deltaLoop:
    LDA evTbl,Y             ; 4   absolute row of the current entry
    CMP #EV_TERMINATOR_DELTA ; 2
    BEQ .deltaDone          ; 2/3  terminator: its $FF is already a delta
    STA evRow               ; 3   remember the absolute row
    SEC                     ; 2
    SBC tempCount           ; 3   delta = row - prevRow
    STA evTbl,Y             ; 4   store the delta
    LDA evRow               ; 3   restore the absolute row
    STA tempCount           ; 3   prevRow = row
    LDA evTbl+1,Y           ; 4   reg1 of the current entry (flag in bit 7)
    AND #EV_SINGLE_FLAG     ; 2
    BNE .deltaSingle        ; 2/3
    TYA                     ; 2   double entry -> advance by 5
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2
    JMP .deltaLoop          ; 3
.deltaSingle:
    TYA                     ; 2   single entry -> advance by 3
    CLC                     ; 2
    ADC #3                  ; 2
    TAY                     ; 2
    JMP .deltaLoop          ; 3
.deltaDone:
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
;
; Round 3.1 layout - 48 bytes (was 122).  The event table is now variable-size
; (EV_TBL_SIZE = 31 bytes max) and the builder inserts events directly into
; it, so the events/evOrder scratch buffers, evCount, evIdx, joystate, the two
; separate missile-active bytes and fire_sync are all gone.  m_active packs
; both missiles into one byte and fire_prev carries the boot-sync flag in its
; bit 7.  Builder temps are three shared bytes; InsertEvent holds its payload
; on the CPU stack while the table is scanned/shifted.
;
; Round 4 adds one byte: hit_flags (HIT_P0/HIT_P1), the observable result of
; the missile-on-player collision detection -> 49 bytes total.
;
; Round 5 adds two bytes: p0_hp/p1_hp (PLAYER_START_HP each), the hit points
; consumed by ProcessHitEffects -> 51 bytes total.
; =============================================================================
    SEG.U VARS
    ORG $80
P0Y         DS 1            ; player 0 vertical position (0..PLAYER_Y_MAX)
P1Y         DS 1            ; player 1 vertical position (0..PLAYER_Y_MAX)
p0_hp       DS 1            ; player 0 hit points (0..PLAYER_START_HP)
p1_hp       DS 1            ; player 1 hit points (0..PLAYER_START_HP)
ball_x      DS 1            ; ball visible left pixel (BALL_X_MIN..BALL_X_MAX)
ball_y      DS 1            ; ball first display row (BALL_Y_MIN..BALL_Y_MAX)
ball_dx     DS 1            ; horizontal step (+1 = right, $FF = left)
ball_dy     DS 1            ; vertical step (+1 = down, $FF = up)

; Missile state. m?_x is the leftmost visible pixel while active; m_active is
; the packed active mask (bit 0 = M0, bit 1 = M1).
m0_x        DS 1            ; missile 0 horizontal position
m0_y        DS 1            ; missile 0 row (fixed while flying)
m1_x        DS 1            ; missile 1 horizontal position
m1_y        DS 1            ; missile 1 row (fixed while flying)
m_active    DS 1            ; M0_BIT = M0 flying, M1_BIT = M1 flying
hit_flags   DS 1            ; HIT_P0/HIT_P1, set by ProcessCollisions (Round 4)

fire_prev   DS 1            ; packed fire state (FIRE_P0/FIRE_P1 + FIRE_SYNC)
evCnt       DS 1            ; kernel: scanlines until the next event fires
scanCnt     DS 1            ; kernel: line countdown (primed to KERNEL_SCANLINES)

evTbl       DS EV_TBL_SIZE  ; event table (<= 31 bytes, see constants.inc)

; BuildEvents shared temps (written before use, so the same bytes are reused
; across the insert and convert phases).
evRow       DS 1            ; InsertEvent: event row  /  ConvertDeltas: row
tempCount   DS 1            ; InsertEvent: shift point / ConvertDeltas: prevRow
tblLen      DS 1            ; table length in bytes

; =============================================================================
; 6502 vectors
; =============================================================================
    SEG
    ORG $FFFA
    .WORD Reset             ; NMI (unused)
    .WORD Reset             ; RESET
    .WORD Reset             ; IRQ (unused)
