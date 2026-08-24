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
;   * Round 6: the ball x player contact is now detected.  The same overscan
;     collision pass reads CXP0FB/CXP1FB (Ball x P0/P1, D6) and records the
;     contact in the one-byte ball_contact_flags bitfield, a separate byte
;     from hit_flags.  It is contact information ONLY: no damage, no state
;     change and no ball interaction yet - the ball still passes through the
;     players.  Dead players are not rendered, so they can never latch.
;   * Round 7: the minimal ball collision RESPONSE.  ApplyBallRebound (run at
;     overscan init, right after ProcessCollisions and before
;     ProcessHitEffects) consumes ball_contact_flags and steers the ball away
;     from the player it just touched: Ball x P0 -> ball_dx = DIR_RIGHT, Ball
;     x P1 -> ball_dx = DIR_LEFT, ball_dy untouched, no damage, no HP change,
;     no debounce/immunity.  The branchless table-driven body costs a fixed
;     27 cycles, but the extra 39 cycles (JSR + RTS) pushed the first overscan
;     WSYNC write out of the (K+228, K+304] window, so OVERSCAN_LOOP_COUNT
;     dropped from 6 to 5 and the region re-anchored on K+380 (see the
;     overscan comment below).
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
; Round 3.1 change: entries were made VARIABLE-SIZE. A single write occupied 3
; bytes, a double write 5 bytes, and the table was terminated by a single $FF
; byte.  Because the common case is one write per scanline, the table shrank
; from a fixed 55 bytes to at most 31 bytes (10 singles + terminator), which
; allowed the builder scratch space to be removed entirely.
;
; Round 9 (ball write-slot fix): the visible kernel was redesigned so every
; register write lands during HBLANK of the intended scanline.  The kernel
; pre-loaded the NEXT entry's writes into four pending registers (pendReg1/
; pendVal1/pendReg2/pendVal2) on the previous event line and a fixed
; "apply pending" block wrote them at scanline cycles 13/23 - before the beam
; reaches pixel 0 (~cycle 23).  Because the writes always landed early enough,
; an object's horizontal position could no longer decide whether its event
; applies one scanline late, so the ball's vertical span depends only on
; ball_y and BALL_HEIGHT (no more 1-scanline shift at low x).  The scanline
; countdown (scanCnt) is gone: the table ended with a 3-byte end-marker entry
; whose masked register equals EV_MARKER_INDEX, and the kernel jumped to
; .kernelEnd when it fired - exactly KERNEL_SCANLINES lines.  The event table
; grew to 33 bytes and the overscan countdown dropped to 6 (see the overscan
; section).
;
; Round 10 (table-direct kernel): the table is uniform 5-byte entries again
; ([delta, reg1, val1, reg2, val2]) and EV_SINGLE_FLAG is removed; a single
; event just leaves reg2 = 0 (its second pending write becomes a harmless
; AUDV1 write).  Deltas are gaps to the NEXT event and the first event's delta
; lives in a separate nullDelta byte.  The kernel is now a single fixed loop:
; every scanline starts with WSYNC + DEC evCnt + BNE; only the non-event
; branch applies the two pending writes, and only the event branch decodes the
; entry at Y into the pending registers.  All three paths are constant-cost and
; well under 76 cycles, so the kernel can never slip a scanline no matter how
; many events share a row - the Round 9 double-event 263-scanline slip is
; structurally impossible.  The marker fires on line 184 via its $FF delta
; byte.  The table grew to 55 bytes (see VARS and docs/en/memory-map.md).
;
; Round 11 (delta=1 fix): the two-phase Round 10 pipeline had a latent bug -
; the entry decoded on an event line applied on the NEXT non-event line, so
; two entries on consecutive rows (delta 1, e.g. P1 at y=50 and the ball at
; y=51) collided: the next event line re-decoded before the previous entry's
; writes ever applied, silently DROPPING the entry (an object could be
; invisible, or an OFF event could be dropped so an object stayed enabled to
; the bottom edge).  The kernel is redesigned to apply the last-decoded
; entry's two writes DIRECTLY from the table (LDX/LDA evTbl-4,Y) at the START
; of EVERY scanline, so there is no pending state to collide.  The decode is
; only "load delta, test the marker, advance Y".  Consecutive events now each
; apply on their own row.  The table carries a 5-byte DUMMY entry at offset 0
; (all zeros -> benign AUDV0 writes on the lines before the first event); real
; entries start at offset 5, and the kernel primes Y = 5 (or Y = 10 when the
; first entry fires on row 0).  The table grew to 60 bytes; the four pending
; registers are gone (see VARS and docs/en/memory-map.md).
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
    LDA #PLAYER_Y_INIT
    STA P0Y
    LDA #PLAYER_Y_INIT
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

    ; game_state defaults to STATE_MENU (0) from the RAM clearing above.
    ; game_mode defaults to MODE_DUEL (0).

    ; Initialize switch state to "released" (active-low: bit=1 means released)
    ; and reset_held to 0 (not being held).
    LDA #(SELECT_BIT|RESET_BIT)
    STA select_prev
    STA reset_prev
    LDA #0
    STA reset_held

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
    JSR HandleInput          ; SELECT/RESET input handling
    LDA game_state           ; 3
    BEQ .menuState           ; 2/3  STATE_MENU -> skip gameplay, setup visuals
    ; ---- Playing state: full gameplay update ----
    ; Round 13: pending_rally_reset triggers ResetRally at the start of
    ; this frame's VBLANK, before gameplay updates.  The flag was set in
    ; the previous frame's overscan (KO).
    LDA pending_rally_reset  ; 3
    BEQ .noPendingReset      ; 2/3  no rally reset pending
    JSR ResetRally           ; 6+54  restore rally state (clears the flag)
.noPendingReset:
    JSR UpdatePlayers       ; move both players vertically (see below)
    JSR UpdateBall          ; move the ball and bounce it off the arena edges
    ; Round 14: goal detected in SCORE mode → ResetRally immediately,
    ; before PositionPlayers/BuildEvents, so the visible frame already
    ; shows the fresh rally state (centered players, center ball, HP
    ; restored).  KO still uses the deferred path above (detected in
    ; overscan, flag set for next frame's VBLANK start).
    LDA pending_rally_reset ; 3
    BEQ .noGoalReset        ; 2/3  no goal this frame
    JSR ResetRally           ; 6+54  immediate rally reset (clears the flag)
    JMP .positionAndBuild   ; 3   skip missiles; state is fresh
.noGoalReset:
    JSR UpdateMissiles      ; fire, move and despawn both missiles
    JMP .positionAndBuild   ; 3
    ; ---- Menu state: set indicator colors, hide ball, show both paddles ---
.menuState:
    LDA game_mode            ; 3
    BEQ .menuDuel            ; 2/3  MODE_DUEL -> keep default PLAYER1_COLOR
    LDA #PLAYER2_COLOR       ; 2   MODE_SCORE -> blue indicator on P0
    JMP .menuColorSet        ; 3
.menuDuel:
    LDA #PLAYER1_COLOR       ; 2   MODE_DUEL -> red indicator on P0
.menuColorSet:
    STA COLUP0               ; 3   set P0 color to indicate the mode
    ; Hide the ball by matching its color to the background.
    ; Do NOT touch p0_hp or p1_hp: both paddles must remain visible.
    LDA #BACKGR_COLOR        ; 2
    STA COLUPF               ; 3   ball + missiles color = background -> invisible
    JMP .positionAndBuild    ; 3
.positionAndBuild:
    JSR PositionPlayers     ; fixed horizontal placement (RESP + HMP)
    JSR PositionBall        ; ball horizontal placement (RESBL + HMBL)
    JSR PositionMissiles    ; missile horizontal placement (RESM + HMM)
    JSR BuildEvents         ; rebuild the event table for the visible kernel

    ; Round 11 (delta=1 fix): there are no pending write registers any more -
    ; the kernel applies the last-decoded entry directly from the table on
    ; every line, so the last VBLANK line only has to set evCnt and Y.  No
    ; row-0 preload work is needed here.

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
    ; kernel.  There are no pending registers: the kernel applies the last
    ; decoded entry directly from the table, so the only priming left is evCnt
    ; and Y, and both paths fit comfortably within this single scanline.  CLC
    ; starts the carry-clear invariant used by the kernel's advance arithmetic
    ; (no CLC is needed on the kernel paths).
    STA WSYNC               ; 3   sync to the last VBLANK line
    STA HMOVE               ; 3   apply all HMP0..HMBL fine adjustments
    LDA #0                  ; 2
    STA VBLANK              ; 3   picture on from the next scanline
    STA GRP0                ; 3   clear objects for the first visible line
    STA GRP1                ; 3
    STA ENAM0               ; 3
    STA ENAM1               ; 3
    STA ENABL               ; 3
    CLC                     ; 2   carry-clear invariant for the kernel
    LDA nullDelta           ; 3   first delta (row_1, or 185 when empty)
    BEQ .primeRow0          ; 2/3 first entry fires on row 0
    STA evCnt               ; 3
    LDY #5                  ; 2   Y = first real entry offset (apply reads Y-5)
    JMP KernelLoop          ; 3
.primeRow0:
    ; First entry fires on row 0: prime evCnt with entry 0's OWN delta (the
    ; gap to the next entry) and set Y = 10 so the apply reads real entry 0
    ; (at table offset 5) from the first line.  The marker can never sit at
    ; row 0 (when the table is empty nullDelta is 185), and carry is still
    ; clear from the CLC above.
    LDA evTbl+5             ; 4   entry 0's delta (gap to the next entry)
    STA evCnt               ; 3
    LDY #10                 ; 2   Y = entry 1's offset (apply reads Y-5)
    JMP KernelLoop          ; 3

; =============================================================================
; Visible kernel: 185 scanlines.
;
; Scanline budget: 76 cycles.  The kernel is event-driven and has NO pending
; registers: every scanline starts by applying the LAST-DECODED entry's two
; writes directly from the table (the apply reads the entry through Y-5, since
; Y always points one entry past it), then counts down to the next event.
; This is the Round 11 delta=1 fix: because the apply runs unconditionally at
; the START of every line - event line or not - consecutive events (delta 1)
; can never collide the way the Round 10 two-phase pipeline did (see the
; header comment).  Each entry's writes land on its own display row.
;
; The apply is idempotent: events model persistent state transitions (an
; object is enabled from its ON row until its OFF row), so re-applying the
; last-decoded entry's writes on the lines between events is harmless - and it
; is exactly what guarantees the writes land at the START of their scanline
; every time.
;
; The kernel ends when the end-marker entry fires: evCnt hits 0 on line 184,
; the decode reads the marker's delta byte ($FF = EV_MARKER_VAL), CMP #$FF
; matches and the BEQ jumps to .kernelEnd.  Exactly KERNEL_SCANLINES lines.
;
; Cycle budgets (realistic branch timing, page-aligned body):
;   non-event line : WSYNC + apply + DEC + BNE + JMP              38 cycles
;   event line     : WSYNC + apply + DEC + BNE + decode + JMP     54 cycles
;   end-marker line: WSYNC + apply + DEC + BNE + decode + BEQ .end 46 cycles
;
; All three paths are well under 76, so no line can ever slip - the frame is
; always 262 scanlines no matter how events are arranged.  (Round 9's event
; lines could reach 74/76 and a two-write double event line together with the
; apply block could exceed the budget, occasionally producing 263 lines; see
; docs/en/timing-analysis.md.)
;
;   STA WSYNC             3    start of scanline
;   LDX evTbl-4,Y         4    reg1 of the last-decoded entry
;   LDA evTbl-3,Y         4    val1
;   STA EV_WRITE_BASE,X   4    write 1, before the beam reaches pixel 0
;   LDX evTbl-2,Y         4    reg2 (0 = single event: benign AUDV0/AUDV1)
;   LDA evTbl-1,Y         4    val2
;   STA EV_WRITE_BASE,X   4    write 2
;   DEC evCnt             5    count down to the next event
;   BNE .applyOnly        3    non-event line: loop
;   LDA evTbl,Y           4    this entry's delta (gap to the next event)
;   STA evCnt             3
;   CMP #EV_MARKER_VAL    2    marker sentinel ($FF)?
;   BEQ .kernelEnd        2/3  marker fired -> kernel done
;   TYA                   2    advance to the next entry
;   ADC #5                2    carry is 0 (delta < $FF cleared it)
;   TAY                   2
;   JMP KernelLoop        3
;   Total (non-event)    38; event 54 (the DEC/BNE/decode/JMP add 16 more);
;   end-marker 46 (the BEQ ends the line, no TYA/ADC/TAY/JMP).
;
; Write timing: write 1 completes at CPU cycle 15 and write 2 at cycle 27 of
; the scanline (4 cycles earlier than Round 10's pending-apply at 18/28 on the
; same emulator cycle convention).  The beam reaches pixel p at cycle
; ~(p + 69)/3, so pixel 0 is reached at ~23.  Write 1 always lands before
; pixel 0; write 2 only lands before an object whose x >= 15.  The builder
; enforces the slot rule: ENAM1 must never be slot 2 (M1 x varies); ENABL
; may be slot 2 only when ball_x >= 15.  When Ball and a player share a row,
; they are reordered within the slot pair (no bump) based on ball_x:
;   ball_x >= 15: player slot 1, ball slot 2
;   ball_x <  15: ball slot 1, player slot 2
; See the event kernel constants in constants.inc.
;
; Dummy entry: the table's first 5 bytes are all zeros (reg1 = reg2 = 0), so
; on the lines before the first event fires the apply writes both values to
; AUDV0 ($1A + 0) - a benign write while the display is on.  Y is primed to 5
; (real entry 0 starts at offset 5), so the apply reads evTbl[1..4] (the dummy)
; until the first decode advances Y to 10.
;
; Carry invariant: CLC runs once in the priming.  On the kernel paths carry is
; clear at the ADC #5: the event decode's CMP #EV_MARKER_VAL clears carry for
; every real delta (< $FF), and the marker's CMP sets carry only on the BEQ
; .kernelEnd path (which skips the ADC).  No CLC in the kernel.
;
; The kernel body is kept inside a single 256-byte page (ALIGN 256 before
; KernelLoop) so the backward branches have deterministic timing.
; =============================================================================
    ALIGN 256
KernelLoop:
    STA WSYNC               ; 3   start of scanline
    ; ---- apply the last-decoded entry's writes directly from the table ----
    LDX evTbl-4,Y           ; 4   reg1 (Y-5 is the last-decoded entry)
    LDA evTbl-3,Y           ; 4   val1
    STA EV_WRITE_BASE,X     ; 4   write 1, before the beam reaches pixel 0
    LDX evTbl-2,Y           ; 4   reg2 (0 = single event: benign write)
    LDA evTbl-1,Y           ; 4   val2
    STA EV_WRITE_BASE,X     ; 4   write 2 (only safe for objects with x >= 15;
                            ;    the builder enforces the slot rule)
    DEC evCnt               ; 5   count down to the next event
    BNE .applyOnly          ; 2/3  not an event line -> loop
    ; ---- event line: load the next delta and advance Y ----
    LDA evTbl,Y             ; 4   this entry's delta (gap to the next event)
    STA evCnt               ; 3
    CMP #EV_MARKER_VAL      ; 2   marker sentinel ($FF)?
    BEQ .kernelEnd          ; 2/3  marker fired -> kernel done
    TYA                     ; 2   advance to the next entry
    ADC #5                  ; 2   carry is 0 (delta < $FF cleared it)
    TAY                     ; 2
.applyOnly:
    JMP KernelLoop          ; 3

    ; ---- Overscan: 10 scanlines ------------------------------------------
    ; The overscan is a fixed WSYNC countdown, not a TIM64T wait.  A timer
    ; wait is only deterministic when the work before it is fixed: with the
    ; variable-cost collision pass the INTIM < 64 exit granularity made the
    ; overscan region land on different 76-cycle boundaries and the frame
    ; occasionally slipped to 263 scanlines.  Counting exactly
    ; OVERSCAN_LOOP_COUNT WSYNCs anchors the region: the collision pass
    ; (branchless, fixed cost) plus the Round 7 ball rebound (branchless,
    ; fixed cost) plus the Round 5 hit effects (branchy, but every path lands
    ; the first WSYNC on the same boundary - see ProcessHitEffects below) run
    ; before the loop.  Round 7 pushed the first WSYNC landing out of the
    ; (K+228, K+304] slot, so the loop count dropped from 6 (Round 9/10/11) to
    ; 5 and the region re-anchored on K+380.  The whole overscan stays exactly
    ; 760 cycles (10 lines) on every path.
.kernelEnd:
    LDA #VBLANK_BLANK       ; 2
    STA VBLANK              ; 3   blank output again
    LDA #0                  ; 2
    STA GRP0                ; 3   clear every object: the last kernel lines
    STA GRP1                ; 3   may have left a register enabled (e.g. the
    STA ENAM0               ; 3   ball OFF event at row 185 is dropped), and
    STA ENAM1               ; 3   the display must never bleed into overscan
    STA ENABL               ; 3
OverscanWait:
    ; Collision pass: reads the latches, updates hit_flags, m_active and
    ; ball_contact_flags (fixed 117 cycles, no branches - see
    ; ProcessCollisions below).
    JSR ProcessCollisions   ; 6 + 117
    ; Round 7: consume ball_contact_flags as the minimal ball rebound -
    ; Ball x P0 steers the ball right, Ball x P1 steers it left, ball_dy is
    ; never touched, no damage/HP change.  Branchless, fixed 27 cycles (see
    ; ApplyBallRebound below).
    JSR ApplyBallRebound    ; 6 + 27
    ; Round 5: consume hit_flags as HP damage and lock dead players' fire
    ; input.  Branchy, but its cost window keeps the first WSYNC on the same
    ; boundary (see ProcessHitEffects below).
    JSR ProcessHitEffects   ; 6 + 60..80
    ; Round 9/10/11: 8 cycles of padding.  The kernel now ends on the
    ; end-marker entry: the marker path reaches .kernelEnd at K+46 (K = last
    ; kernel WSYNC landing; Round 9 was K+44, Round 10 K+50 - the Round 11
    ; table-direct apply is 4 cycles shorter).  From K+46 the epilogue (22) +
    ; JSR (6) + collision body (117 incl. RTS; Round 6 added 33 for the ball
    ; contact pass) + JSR (6) + rebound body (27 incl. RTS; Round 7) + JSR (6)
    ; + hit-effects body (62..80 incl. RTS) + NOPs (8) + LDX (2) put the first
    ; countdown WSYNC write on K+306..K+326, inside (K+304, K+380), so the
    ; alignment snaps it to K+380.  Without the padding the write could land
    ; on K+304 or earlier, splitting the region over fewer lines.  Round 7
    ; pushed the write out of the Round 9/10/11 window (K+269..K+287, snapped
    ; to K+304), so OVERSCAN_LOOP_COUNT dropped from 6 to 5: five iterations
    ; then reach K+684, and the JMP + VSYNC preamble that follow align the
    ; next frame's first VSYNC WSYNC to K+760.  The overscan stays exactly
    ; 10 lines (K+76..K+760) on every path.  The NOPs replace the cycles that
    ; used to come from the scanCnt epilogue (DEC/BEQ) + one extra WSYNC.
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    LDX #OVERSCAN_LOOP_COUNT ; 2
.overscanLoop:
    STA WSYNC               ; 3   one overscan line per iteration
    DEX                     ; 2
    BNE .overscanLoop       ; 2/3

    JMP StartOfFrame        ; 3   next frame

; =============================================================================
; HandleInput (Round 12, v3)
;
; Reads SWCHB once per frame into swchb_cur.  SELECT and RESET bits are
; active-low (0 = pressed).
;
; SWCHB bit layout (Atari 2600 spec):
;   bit 0 = RESET, bit 1 = SELECT
;
; SELECT: rising-edge detection (released -> pressed) toggles game_mode.
; Only active in STATE_MENU; ignored during gameplay.
;
; RESET semantics (falling-edge, classic Atari 2600):
;   While RESET is held in the menu: game stays frozen, no gameplay.
;   On RESET release (pressed -> released): InitGame runs, game starts.
;   During gameplay: RESET returns to STATE_MENU.
; =============================================================================
HandleInput:
    LDA SWCHB                ; 4   read console switches ONCE
    STA swchb_cur            ; 3   snapshot for this frame
    LDA game_state           ; 3
    BNE .playingInput        ; 2/3
    ; ---- Menu state ----
    ; SELECT: rising edge -> toggle mode
    LDA swchb_cur            ; 3
    AND #SELECT_BIT          ; 2
    BNE .selectNotPressed    ; 2/3
    LDA select_prev          ; 3
    AND #SELECT_BIT          ; 2
    BEQ .selectUpdate        ; 2/3  no edge (was already pressed)
    LDA game_mode            ; 3
    EOR #1                   ; 2   toggle 0 <-> 1
    STA game_mode            ; 3
.selectUpdate:
    LDA swchb_cur            ; 3
    AND #SELECT_BIT          ; 2
    STA select_prev          ; 3
    JMP .resetMenu           ; 3
.selectNotPressed:
    LDA swchb_cur            ; 3
    AND #SELECT_BIT          ; 2
    STA select_prev          ; 3
    ; RESET in menu: while held -> stay frozen; on release -> start game
.resetMenu:
    LDA swchb_cur            ; 3
    AND #RESET_BIT           ; 2
    BEQ .resetIsPressed      ; 2/3  RESET pressed (bit = 0)
    ; RESET released this frame
    LDA reset_held           ; 3
    BEQ .resetMenuDone       ; 2/3  was not held -> nothing to do
    ; Falling edge: was held, now released -> start the game
    JSR InitGame             ; 6
    JMP .resetMenuDone       ; 3
.resetIsPressed:
    LDA #1                   ; 2
    STA reset_held           ; 3   mark that RESET is being held
.resetMenuDone:
    RTS                      ; 6

.playingInput:
    ; ---- Playing state: SELECT or RESET returns to menu ----
    LDA swchb_cur            ; 3   read ONCE, reuse for both checks
    ; SELECT rising edge -> return to menu
    PHA                      ; 3   save for RESET check
    AND #SELECT_BIT          ; 2
    BNE .selectNotPressedP   ; 2/3
    LDA select_prev          ; 3
    AND #SELECT_BIT          ; 2
    BEQ .selectUpdateP       ; 2/3  no edge
    LDA #STATE_MENU
    STA game_state
    ; Clean up RESET state so stale flags don't trigger InitGame next frame
    LDA #0
    STA reset_held
    LDA swchb_cur
    AND #RESET_BIT
    STA reset_prev
.selectUpdateP:
    LDA swchb_cur            ; 3
    AND #SELECT_BIT          ; 2
    STA select_prev          ; 3
    PLA                      ; 4   restore SWCHB snapshot
    RTS                      ; 6   SELECT already handled, done
.selectNotPressedP:
    LDA swchb_cur            ; 3
    AND #SELECT_BIT          ; 2
    STA select_prev          ; 3
    PLA                      ; 4   discard saved SWCHB
    ; RESET rising edge -> return to menu
.resetCheckP:
    LDA swchb_cur            ; 3
    AND #RESET_BIT           ; 2
    BNE .resetNotPressedP    ; 2/3
    LDA reset_prev           ; 3
    AND #RESET_BIT           ; 2
    BEQ .resetDoneP          ; 2/3  no edge
    LDA #STATE_MENU
    STA game_state
    ; Clean up RESET state: sync reset_prev so next frame in menu
    ; correctly sees RESET held (no false falling edge)
    LDA #0
    STA reset_held
    LDA swchb_cur
    AND #RESET_BIT
    STA reset_prev
    JMP .resetDoneP          ; 3
.resetNotPressedP:
    LDA swchb_cur            ; 3
    AND #RESET_BIT           ; 2
    STA reset_prev           ; 3
.resetDoneP:
    RTS                      ; 6

; =============================================================================
; InitGame (Round 12)
;
; Transitions from STATE_MENU to STATE_PLAYING.  Reinitializes all gameplay
; state (players, ball, missiles, HP) exactly like the power-on Reset, so
; the game always starts clean regardless of what happened in the menu.
; The selected game_mode is preserved.
;
; Called once when RESET is pressed on the menu screen.  The hardware RESET
; (power cycle) clears RAM and starts in STATE_MENU via the Reset vector;
; this routine handles the software transition to gameplay.
; =============================================================================
; =============================================================================
; ResetRally (Round 13)
;
; Restores rally state for a new rally: HP, positions, ball, missiles,
; and transient flags.  Does NOT touch scores — those are managed by the
; caller (InitGame for game start, goal/KO handlers during gameplay).
;
; Called from: InitGame (game start), StartOfFrame (pending_rally_reset)
; =============================================================================
ResetRally:
    LDA #PLAYER_START_HP
    STA p0_hp
    STA p1_hp
    LDA #PLAYER_Y_INIT
    STA P0Y
    STA P1Y
    LDA #BALL_X_INIT
    STA ball_x
    LDA #BALL_Y_INIT
    STA ball_y
    ; Determine ball_dx from pending_rally_reset encoding:
    ;   RALLY_RESET_KO (1) or RALLY_RESET_P1_GOAL (3) → DIR_RIGHT
    ;   RALLY_RESET_P0_GOAL (2) → DIR_LEFT
    LDX pending_rally_reset
    CPX #RALLY_RESET_P0_GOAL
    BEQ .rallyP0Goal
    ; Default: DIR_RIGHT (covers KO and P1 goal)
    LDA #DIR_RIGHT
    JMP .rallySetDx
.rallyP0Goal:
    LDA #DIR_LEFT
.rallySetDx:
    STA ball_dx
    LDA #DIR_DOWN
    STA ball_dy
    LDA #0
    STA m_active
    STA hit_flags
    STA ball_contact_flags
    STA fire_prev
    STA pending_rally_reset
    RTS

; =============================================================================
; InitGame (Round 12, updated Round 13)
;
; Transitions from STATE_MENU to STATE_PLAYING.  Reinitializes all gameplay
; state (players, ball, missiles, HP) exactly like the power-on Reset, so
; the game always starts clean regardless of what happened in the menu.
; The selected game_mode is preserved.  Scores are reset to 0-0.
;
; Called once when RESET is pressed on the menu screen.  The hardware RESET
; (power cycle) clears RAM and starts in STATE_MENU via the Reset vector;
; this routine handles the software transition to gameplay.
; =============================================================================
InitGame:
    ; Restore all colors to gameplay defaults (menu may have changed
    ; COLUP0 for the mode indicator and COLUPF to hide the ball).
    LDA #PLAYER1_COLOR
    STA COLUP0
    LDA #PLAYER2_COLOR
    STA COLUP1
    LDA #BALL_COLOR
    STA COLUPF               ; ball + missiles share this color

    ; Reset scores (game start only; not touched during rally resets)
    LDA #0
    STA score_p0
    STA score_p1

    ; Reset rally state (HP, positions, ball, missiles, flags)
    JSR ResetRally

    ; Transition to playing state
    LDA #STATE_PLAYING
    STA game_state
    RTS

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
    ; ---- Game mode check: SCORE mode uses goal detection instead of bounce ---
    LDA game_mode            ; 3
    BNE .scoreHorizontal     ; 2/3  SCORE mode → goal check instead of bounce
    ; ---- DUEL mode: original horizontal bounce (unchanged) ----
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
    JMP .verticalBounce     ; 3

.scoreHorizontal:
    ; ---- SCORE mode: check for goal instead of horizontal bounce ----
    ; Goal: ball exits the arena past the opponent's side.
    ;   ball_dx positive (moving right) + ball_x == BALL_X_MAX -> P0 scores
    ;   ball_dx negative (moving left)  + ball_x == BALL_X_MIN -> P1 scores
    ; On goal: increment score, set pending_rally_reset, kill missiles,
    ; skip movement.  ResetRally executes in the same VBLANK (before
    ; PositionPlayers/BuildEvents) so no transitional frame is rendered.
    LDA ball_dx             ; 3
    BMI .scoreCheckLeft     ; 2/3  moving left ($FF)
    ; Moving right: check right edge
    LDA ball_x              ; 3
    CMP #BALL_X_MAX         ; 2   at the right edge?
    BNE .verticalBounce     ; 2/3  not at edge → no goal, continue normally
    ; Goal! Ball exited right → P0 scores
    INC score_p0            ; 5
    LDA #RALLY_RESET_P0_GOAL ; 2  P0 scored → DIR_LEFT toward P0
    STA pending_rally_reset ; 3
    LDA #0                  ; 2
    STA m_active            ; 3   kill existing missiles → no TIA latches
    JMP .done               ; 3   skip movement (rally ends this frame)

.scoreCheckLeft:
    LDA ball_x              ; 3
    CMP #BALL_X_MIN         ; 2   at the left edge?
    BNE .verticalBounce     ; 2/3  not at edge → no goal
    ; Goal! Ball exited left → P1 scores
    INC score_p1            ; 5
    LDA #RALLY_RESET_P1_GOAL ; 2  P1 scored → DIR_RIGHT toward P1
    STA pending_rally_reset ; 3
    LDA #0                  ; 2
    STA m_active            ; 3   kill existing missiles
    JMP .done               ; 3   skip movement

.verticalBounce:
    ; ---- Vertical bounce (both modes, unchanged) ----
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
.done:
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
; The missile pass only reacts to the cross-fire hits:
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
; Round 6 adds the ball contact pass:
;
;     CXP0FB D6 (Ball x P0)  -> CONTACT_P0 in ball_contact_flags
;     CXP1FB D6 (Ball x P1)  -> CONTACT_P1 in ball_contact_flags
;
; This is contact information only: no damage, no state change, no ball
; rebound.  ball_contact_flags is a separate byte from hit_flags so the
; missile damage record stays unambiguous.  A dead player is not rendered
; (BuildEvents skips its GRP events), so the TIA never latches a ball x dead
; player overlap: the rendering gate keeps dead players contact-free, no HP
; check is needed here.  The player x playfield bits (D7) are ignored: the
; playfield is never displayed in this game.  The ball block is read BEFORE
; the CXCLR strobe at the end, so a contact rendered in frame N is recorded
; once and never again.
;
; Placement note: ProcessCollisions deliberately runs at overscan init rather
; than in VBLANK.  The heaviest VBLANK path is already within a few cycles of
; the VBLANK timer window's alignment boundary, so adding the collision pass
; there made one frame per stress run slip to 263 scanlines.  An overscan
; TIM64T wait was also tried, but the emulator's INTIM < 64 exit granularity
; makes a timer wait nondeterministic whenever the pre-timer work varies, so
; the collision pass had to become BRANCHLESS (fixed 117-cycle cost) and the
; overscan had to become a fixed WSYNC countdown (see the overscan section).
;
; This routine is branchless by construction: the latches are turned into
; 0/1 flags with the carry (ASL + ADC #0), hit_flags is the packed sum
; 2*hit0 + hit1, and the m_active update is a single lookup in newActiveTbl
; indexed by m_active + 4*hit0 + 8*hit1 (the high index bits select whether
; M0 and/or M1 cleared).  The ball block turns each D6 latch into a 0/1 flag
; with a double ASL (the second ASL moves D6 into the carry) and packs
; CONTACT_P0 | 2*CONTACT_P1 the same way.  With no branches and a
; page-aligned table the cost is fixed on every path.
;
; Cycle budget (fixed path, no branches):
;   hit0/hit1 extraction       22
;   hit_flags = 2*hit0 + hit1  11
;   m_active table lookup      42
;   ball contact flags         33
;   CXCLR + RTS                 9
;   Total                     117
;
; Overscan anchoring: the fixed pre-loop cost before the first countdown
; WSYNC grows by the same 33 cycles on every path, so all paths still land
; that WSYNC on the same 76-cycle boundary (K+304) and the overscan stays
; exactly 10 lines (see the overscan section for the recomputed window).
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

    ; ---- ball_contact_flags = CONTACT_P0 | CONTACT_P1 ----
    ; CXP0FB/CXP1FB D6 (the ball x player bits) become 0/1 flags via the
    ; double-ASL carry trick, then pack to bits 0/1.  Branchless, read before
    ; CXCLR below, so contacts are recorded once per frame.
    LDA CXP0FB              ; 3   read the Ball/P0 collision latch
    ASL                     ; 2
    ASL                     ; 2   carry = Ball x P0 (D6)
    LDA #0                  ; 2
    ADC #0                  ; 2   A = contact0 (0/1)
    STA ball_contact_flags  ; 3   CONTACT_P0 bit set iff the ball touched P0

    LDA CXP1FB              ; 3   read the Ball/P1 collision latch
    ASL                     ; 2
    ASL                     ; 2   carry = Ball x P1 (D6)
    LDA #0                  ; 2
    ADC #0                  ; 2   A = contact1 (0/1)
    ASL                     ; 2   A = 2*contact1 (CONTACT_P1 bit)
    ORA ball_contact_flags  ; 3   merge both contact bits
    STA ball_contact_flags  ; 3

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
; ApplyBallRebound (Round 7)
;
; Consumes the ball_contact_flags record written by ProcessCollisions (same
; overscan) and steers the ball away from the player it just touched:
;
;   * CONTACT_P0 (Ball x P0) -> ball_dx = DIR_RIGHT  (steer right)
;   * CONTACT_P1 (Ball x P1) -> ball_dx = DIR_LEFT   (steer left)
;   * no contact            -> ball_dx unchanged
;   * both contacts         -> P1 wins (DIR_LEFT); physically unreachable with
;     the current arena geometry, but defined and tested for determinism
;
; ball_dy is NEVER touched: the ball keeps its vertical step.  No damage, no
; HP change, no ball removal, no power-up: this is the minimal collision
; response.  There is no debounce/immunity yet - the ball is re-steered on
; EVERY overlapping frame.  A contact lasting K frames re-steers the ball K
; times, but all K re-steers push it in the SAME direction, so the repeated
; contact is self-limiting: as soon as the ball moves off the paddle the
; contact clears.  The reverse-bounce pattern (ball hitting the paddle from
; the wrong side on consecutive frames) is NOT corrected here by design; it is
; observed and handled at the game-rule level, not in this routine.
;
; The routine is branchless and fixed-cost (27 cycles + 6 JSR + 6 RTS = 39):
; the contact bits become table indices, not branches, so the overscan stays
; anchored exactly like ProcessCollisions.
;
; reboundTbl is indexed by (old_dx_slot * 4 + contact_flags), where
; old_dx_slot = 0 for DIR_RIGHT and 1 for DIR_LEFT (bit 7 of ball_dx, pulled
; into the index by the ASL carry trick):
;
;   old dx  | flags | new dx
;   ------- | ----- | -------
;   right   |  none | right
;   right   | P0    | right
;   right   | P1    | left
;   right   | both  | left
;   left    |  none | left
;   left    | P0    | right
;   left    | P1    | left
;   left    | both  | left
;
; The table is 16-byte aligned so the indexed LDA can never cross a page and
; the 4-cycle cost is guaranteed.
; =============================================================================
ApplyBallRebound:
    LDA ball_dx             ; 3   current step (+1 right, $FF left)
    ASL                     ; 2   carry = bit 7 (0 = right, 1 = left)
    LDA #0                  ; 2
    ADC #0                  ; 2   A = old_dx_slot (0 or 1)
    ASL                     ; 2   *2
    ASL                     ; 2   *4
    CLC                     ; 2
    ADC ball_contact_flags  ; 3   A = old_dx_slot*4 + contact_flags
    TAY                     ; 2   Y = index
    LDA reboundTbl,Y        ; 4   new ball_dx
    STA ball_dx             ; 3
    RTS                     ; 6

    ALIGN 16
reboundTbl:
    DC.B DIR_RIGHT, DIR_RIGHT, DIR_LEFT, DIR_LEFT   ; old dx right (slot 0)
    DC.B DIR_LEFT,  DIR_RIGHT, DIR_LEFT, DIR_LEFT   ; old dx left  (slot 1)

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
;   total B in [60, 80].  The overscan work between the last kernel WSYNC
;   landing and the first overscan WSYNC write is fixed except for B, so the
;   write always lands inside the same 76-cycle window and the countdown
;   snaps it to K+380 (measured for no-collision, both-hit, both-ball, all
;   and dead-player paths).  With OVERSCAN_LOOP_COUNT = 5 the last overscan
;   WSYNC lands on K+684 and the next frame's first VSYNC WSYNC lands on
;   K+760: the overscan region is exactly 10 lines regardless of how many
;   hits occurred.
;
;   On a real 6502 a taken branch costs +1 (and +1 more on a page crossing):
;   the damage costs become 8/13/17, total B in [62, 80].  The write window
;   still keeps the landing on K+380 - the margins are at least 20 cycles on
;   either side of the 76-cycle (K+304, K+380] slot.  The ALIGN 256 below
;   keeps the four BEQs inside one page so a page crossing can never add a
;   cycle.
; =============================================================================
    ALIGN 256
ProcessHitEffects:
    ; ---- SCORE mode: check if a goal already ended the rally ----
    ; When pending_rally_reset is set (goal scored in UpdateBall), skip
    ; damage processing.  The rally will be reset in the next frame's
    ; VBLANK.  Pad the skip path to maintain overscan WSYNC alignment.
    LDA game_mode           ; 3
    BEQ .processDamage      ; 2/3  DUEL → always process damage
    LDA pending_rally_reset ; 3
    BEQ .processDamage      ; 2/3  no goal → process damage normally
    ; Goal already scored this rally: skip damage, pad for timing, fireLock.
    ; The pad (8 NOPs = 16 cycles) ensures the first overscan WSYNC write
    ; lands inside the (K+304, K+380) alignment window.
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    NOP                     ; 2
    JMP .fireLock           ; 3

.processDamage:
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
    ; ---- SCORE mode: KO detection (P0-first priority, max 1 point/rally) ----
    ; Only in SCORE mode.  P0 is checked first; if P0 is KO'd, P1 scores
    ; and P1 is NOT checked (P0-first priority ensures exactly 1 point).
    LDA game_mode           ; 3
    BEQ .fireLock           ; 2/3  DUEL → no KO scoring
    ; Check P0 KO (HP == 0 after damage)
    LDA p0_hp               ; 3
    BNE .p0AliveKo          ; 2/3  alive → skip P0 KO
    ; P0 KO'd → P1 scores
    INC score_p1            ; 5
    LDA #RALLY_RESET_KO     ; 2
    STA pending_rally_reset ; 3
    JMP .fireLock           ; 3   P0 KO processed; P1 NOT checked (priority)
.p0AliveKo:
    ; Check P1 KO (only if P0 is alive)
    LDA p1_hp               ; 3
    BNE .fireLock           ; 2/3  alive → no KO
    ; P1 KO'd → P0 scores
    INC score_p0            ; 5
    LDA #RALLY_RESET_KO     ; 2
    STA pending_rally_reset ; 3
.fireLock:
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
;     P0   ON (P0Y, GRP0, PADDLE_BITS)          OFF (P0Y+18, GRP0, 0)
;     P1   ON (P1Y, GRP1, PADDLE_BITS)          OFF (P1Y+18, GRP1, 0)
;     Ball ON (ball_y, ENABL, BALL_ENABLE)      OFF (ball_y+4, ENABL, 0)
;     M0   ON (m0_y, ENAM0, MISSILE_ENABLE)     OFF (m0_y+4, ENAM0, 0)
;     M1   ON (m1_y, ENAM1, MISSILE_ENABLE)     OFF (m1_y+4, ENAM1, 0)
;
;   Inactive missiles contribute nothing, and (Round 5) a player with 0 HP
;   contributes nothing either: BuildEvents skips the P0/P1 events of a dead
;   player so it is simply not drawn.  InsertEvent inserts every event
;   directly into evTbl in row order, merging same-row singles into doubles
;   and bumping surplus same-row events to row+1, so no scanline ever needs
;   more than two writes.  An event whose row would fall past the last display
;   line (row >= KERNEL_SCANLINES, e.g. the ball OFF at ball_y+4 when the ball
;   sits on the floor) is dropped: the kernel would never reach it and the
;   end-marker must stay on line 184.  The table holds ABSOLUTE rows while it
;   is built; ConvertDeltas turns them into the deltas the kernel counts
;   down, ending with the marker entry.
;
; Insertion order (Round 10, write-slot rule): Ball, M1, M0, P0, P1, so the
; ball always becomes slot 1 on any row it shares and M1 is inserted before
; M0 (and before P0/P1).  InsertEvent refuses to merge a new event as slot 2
; when its register is ENABL or ENAM1, so slot 2 can only ever be P0, P1 or
; M0 - the only objects whose x is guaranteed >= 15 (the deadline for the
; second pending write).  See the event kernel constants in constants.inc.
;
; The table is always exactly 5-byte entries (EV_TBL_SIZE = 60 bytes max:
; a 5-byte dummy at offset 0, 10 real entries from offset 5 and the marker),
; so tblLen counts ENTRIES, not bytes, and no separate record/order scratch
; buffer is needed.
;
; The builder runs in VBLANK (up to ~56*64 cycles available), so its own
; cycle count is not display-critical.
; =============================================================================
BuildEvents:
    ; ---- reset the table to empty: the dummy at offset 0, the marker at 5 ----
    ; The dummy's delta byte is the builder sentinel EV_MARKER_ROW ($FF) so the
    ; AppendEvent back-scan stops AT the dummy and inserts before entry 0.  Its
    ; reg1/reg2 are 0, so the kernel's apply writes the benign AUDV0 register
    ; on every line before the first event fires.
    LDA #EV_MARKER_ROW       ; 2   dummy delta (back-scan sentinel)
    STA evTbl               ; 3
    LDA #0                  ; 2
    STA evTbl+1             ; 3   dummy reg1 (0 -> AUDV0)
    STA evTbl+2             ; 3   dummy val1
    STA evTbl+3             ; 3   dummy reg2 (0 -> AUDV0)
    STA evTbl+4             ; 3   dummy val2
    LDA #EV_MARKER_ROW       ; 2   builder sentinel row ($FF) for the marker
    STA evTbl+5             ; 3   marker row byte; the kernel reads it as $FF
    LDA #0                  ; 2
    STA evTbl+6             ; 3   marker reg1
    STA evTbl+7             ; 3   marker val1
    STA evTbl+8             ; 3   marker reg2
    STA evTbl+9             ; 3   marker val2
    STA tblLen              ; 3   no real entries yet
    ; ---- every object emitted in strictly ascending event order (selection) ----
    ; A FIXED insertion order can land every insert mid-table, each one shifting
    ; up to the whole suffix (a shift is ~16 cycles per byte).  Under collision
    ; stress the old fixed-order builder reached ~4900 cycles and the worst
    ; VBLANK work (~5770) blew past the T=77 timer expiry (4864), drifting
    ; frames to 274+ scanlines.  This builder emits ONE event per round - the
    ; smallest remaining ON or OFF row - so the table is written in nearly
    ; sorted order: AppendEvent (below) appends at the end in the common case
    ; (no shift) and only occasionally shifts a small suffix.
    ;
    ; Selection scan order: P0 → P1 → Ball → M0 → M1.  Players are scanned
    ; before the ball so that when they share a row, the player wins slot 1
    ; and the ball is bumped to row+1.  The ball is 3 pixels tall; a
    ; 1-scanline shift is invisible.  Paddles are 18 pixels tall; a
    ; 1-scanline shift is clearly visible.  The AppendEvent slot rule still
    ; prevents ENABL/ENAM1 from occupying slot 2.
    LDA #OBJ_BALL_BIT         ; 2   the ball is always rendered
    STA nullDelta             ; 3   activeMask
    LDA m_active              ; 3
    AND #M1_BIT               ; 2
    BEQ .m1Inactive           ; 2/3
    LDA nullDelta             ; 3
    ORA #OBJ_M1_BIT           ; 2
    STA nullDelta             ; 3
.m1Inactive:
    LDA m_active              ; 3
    AND #M0_BIT               ; 2
    BEQ .m0Inactive           ; 2/3
    LDA nullDelta             ; 3
    ORA #OBJ_M0_BIT           ; 2
    STA nullDelta             ; 3
.m0Inactive:
    LDA p0_hp                 ; 3   dead player -> no events
    BEQ .p0Inactive           ; 2/3
    LDA nullDelta             ; 3
    ORA #OBJ_P0_BIT           ; 2
    STA nullDelta             ; 3
.p0Inactive:
    LDA p1_hp                 ; 3
    BEQ .maskDone             ; 2/3
    LDA nullDelta             ; 3
    ORA #OBJ_P1_BIT           ; 2
    STA nullDelta             ; 3
.maskDone:
    LDA nullDelta             ; 3
    STA evCnt                 ; 3   onMask: every object starts with ON due

.selectionLoop:
    LDA nullDelta             ; 3   any active object left?
    BNE .doSelection          ; 2/3
    JMP .buildDone            ; 3   (loop exit is >127 bytes away: use JMP)
.doSelection:
    LDA #$FF                  ; 2
    STA evRow                 ; 3   running minimum row = $FF
    ; ---- P0 (bit 2): scanned before Ball so players win row ties ----
    LDA nullDelta             ; 3
    AND #OBJ_P0_BIT           ; 2
    BEQ .scanP1               ; 2/3
    LDA evCnt                 ; 3
    AND #OBJ_P0_BIT           ; 2
    BNE .p0OnCand             ; 2/3
    LDA P0Y                   ; 3   OFF candidate
    CLC                       ; 2
    ADC #PLAYER_HEIGHT        ; 2
    JMP .p0Cand               ; 3
.p0OnCand:
    LDA P0Y                   ; 3   ON candidate
.p0Cand:
    CMP evRow                 ; 3
    BCS .scanP1               ; 2/3
    STA evRow                 ; 3
    LDX #2                    ; 2   candidate: P0
.scanP1:
    LDA nullDelta             ; 3
    AND #OBJ_P1_BIT           ; 2
    BEQ .scanBall             ; 2/3
    LDA evCnt                 ; 3
    AND #OBJ_P1_BIT           ; 2
    BNE .p1OnCand             ; 2/3
    LDA P1Y                   ; 3   OFF candidate
    CLC                       ; 2
    ADC #PLAYER_HEIGHT        ; 2
    JMP .p1Cand               ; 3
.p1OnCand:
    LDA P1Y                   ; 3   ON candidate
.p1Cand:
    CMP evRow                 ; 3
    BCS .scanBall             ; 2/3
    STA evRow                 ; 3
    LDX #3                    ; 2   candidate: P1
.scanBall:
    ; ---- Ball (bit 4): scanned AFTER players so players win row ties ----
    ; When Ball and a player share a row, they are reordered within the slot
    ; pair based on ball_x (no bump).  See AppendEvent .sameRow.
    LDA nullDelta             ; 3
    AND #OBJ_BALL_BIT         ; 2
    BEQ .scanM0               ; 2/3
    LDA evCnt                 ; 3   ON still pending?
    AND #OBJ_BALL_BIT         ; 2
    BNE .ballOnCand           ; 2/3
    LDA ball_y                ; 3   OFF candidate
    CLC                       ; 2
    ADC #BALL_HEIGHT          ; 2
    JMP .ballCand             ; 3
.ballOnCand:
    LDA ball_y                ; 3   ON candidate
.ballCand:
    CMP evRow                 ; 3
    BCS .scanM0               ; 2/3
    STA evRow                 ; 3
    LDX #4                    ; 2   candidate: Ball
.scanM0:
    LDA nullDelta             ; 3
    AND #OBJ_M0_BIT           ; 2
    BEQ .scanM1               ; 2/3
    LDA evCnt                 ; 3
    AND #OBJ_M0_BIT           ; 2
    BNE .m0OnCand             ; 2/3
    LDA m0_y                  ; 3   OFF candidate
    CLC                       ; 2
    ADC #MISSILE_HEIGHT       ; 2
    JMP .m0Cand               ; 3
.m0OnCand:
    LDA m0_y                  ; 3   ON candidate
.m0Cand:
    CMP evRow                 ; 3
    BCS .scanM1               ; 2/3
    STA evRow                 ; 3
    LDX #1                    ; 2   candidate: M0
.scanM1:
    LDA nullDelta             ; 3
    AND #OBJ_M1_BIT           ; 2
    BEQ .emitObj              ; 2/3
    LDA evCnt                 ; 3
    AND #OBJ_M1_BIT           ; 2
    BNE .m1OnCand             ; 2/3
    LDA m1_y                  ; 3   OFF candidate
    CLC                       ; 2
    ADC #MISSILE_HEIGHT       ; 2
    JMP .m1Cand               ; 3
.m1OnCand:
    LDA m1_y                  ; 3   ON candidate
.m1Cand:
    CMP evRow                 ; 3
    BCS .emitObj              ; 2/3
    STA evRow                 ; 3
    LDX #0                    ; 2   candidate: M1
.emitObj:
    CPX #4                    ; 2   dispatch on the smallest event
    BEQ .emitBall             ; 2/3
    CPX #0                    ; 2
    BEQ .emitM1               ; 2/3
    CPX #1                    ; 2
    BEQ .emitM0               ; 2/3
    CPX #2                    ; 2
    BEQ .tP0                  ; 2/3  (trampoline: .emitP0 is >127 bytes away)
    JMP .emitP1               ; 3
.tP0:
    JMP .emitP0               ; 3
.emitBall:
    LDA evCnt                 ; 3   ON still pending?
    AND #OBJ_BALL_BIT         ; 2
    BNE .emitBallOn           ; 2/3
    LDA ball_y                ; 3   Ball OFF
    CLC                       ; 2
    ADC #BALL_HEIGHT          ; 2
    LDX #EV_REG_ENABL         ; 2
    LDY #0                    ; 2
    JSR AppendEvent           ; 6
    LDA nullDelta             ; 3   Ball done: clear the active bit
    EOR #OBJ_BALL_BIT         ; 2
    STA nullDelta             ; 3
    JMP .selectionLoop        ; 3
.emitBallOn:
    LDA ball_y                ; 3   Ball ON
    LDX #EV_REG_ENABL         ; 2
    LDY #BALL_ENABLE          ; 2
    JSR AppendEvent           ; 6
    LDA evCnt                 ; 3   ON emitted: clear the on-pending bit
    EOR #OBJ_BALL_BIT         ; 2
    STA evCnt                 ; 3
    JMP .selectionLoop        ; 3
.emitM1:
    LDA evCnt                 ; 3
    AND #OBJ_M1_BIT           ; 2
    BNE .emitM1On             ; 2/3
    LDA m1_y                  ; 3   M1 OFF
    CLC                       ; 2
    ADC #MISSILE_HEIGHT       ; 2
    LDX #EV_REG_ENAM1         ; 2
    LDY #0                    ; 2
    JSR AppendEvent           ; 6
    LDA nullDelta             ; 3   M1 done
    EOR #OBJ_M1_BIT           ; 2
    STA nullDelta             ; 3
    JMP .selectionLoop        ; 3
.emitM1On:
    LDA m1_y                  ; 3   M1 ON
    LDX #EV_REG_ENAM1         ; 2
    LDY #MISSILE_ENABLE       ; 2
    JSR AppendEvent           ; 6
    LDA evCnt                 ; 3   ON emitted
    EOR #OBJ_M1_BIT           ; 2
    STA evCnt                 ; 3
    JMP .selectionLoop        ; 3
.emitM0:
    LDA evCnt                 ; 3
    AND #OBJ_M0_BIT           ; 2
    BNE .emitM0On             ; 2/3
    LDA m0_y                  ; 3   M0 OFF
    CLC                       ; 2
    ADC #MISSILE_HEIGHT       ; 2
    LDX #EV_REG_ENAM0         ; 2
    LDY #0                    ; 2
    JSR AppendEvent           ; 6
    LDA nullDelta             ; 3   M0 done
    EOR #OBJ_M0_BIT           ; 2
    STA nullDelta             ; 3
    JMP .selectionLoop        ; 3
.emitM0On:
    LDA m0_y                  ; 3   M0 ON
    LDX #EV_REG_ENAM0         ; 2
    LDY #MISSILE_ENABLE       ; 2
    JSR AppendEvent           ; 6
    LDA evCnt                 ; 3   ON emitted
    EOR #OBJ_M0_BIT           ; 2
    STA evCnt                 ; 3
    JMP .selectionLoop        ; 3
.emitP0:
    LDA evCnt                 ; 3
    AND #OBJ_P0_BIT           ; 2
    BNE .emitP0On             ; 2/3
    LDA P0Y                   ; 3   P0 OFF
    CLC                       ; 2
    ADC #PLAYER_HEIGHT        ; 2
    LDX #EV_REG_GRP0          ; 2
    LDY #0                    ; 2
    JSR AppendEvent           ; 6
    LDA nullDelta             ; 3   P0 done
    EOR #OBJ_P0_BIT           ; 2
    STA nullDelta             ; 3
    JMP .selectionLoop        ; 3
.emitP0On:
    LDA P0Y                   ; 3   P0 ON
    LDX #EV_REG_GRP0          ; 2
    LDY #PADDLE_BITS          ; 2
    JSR AppendEvent           ; 6
    LDA evCnt                 ; 3   ON emitted
    EOR #OBJ_P0_BIT           ; 2
    STA evCnt                 ; 3
    JMP .selectionLoop        ; 3
.emitP1:
    LDA evCnt                 ; 3
    AND #OBJ_P1_BIT           ; 2
    BNE .emitP1On             ; 2/3
    LDA P1Y                   ; 3   P1 OFF
    CLC                       ; 2
    ADC #PLAYER_HEIGHT        ; 2
    LDX #EV_REG_GRP1          ; 2
    LDY #0                    ; 2
    JSR AppendEvent           ; 6
    LDA nullDelta             ; 3   P1 done
    EOR #OBJ_P1_BIT           ; 2
    STA nullDelta             ; 3
    JMP .selectionLoop        ; 3
.emitP1On:
    LDA P1Y                   ; 3   P1 ON
    LDX #EV_REG_GRP1          ; 2
    LDY #PADDLE_BITS          ; 2
    JSR AppendEvent           ; 6
    LDA evCnt                 ; 3   ON emitted
    EOR #OBJ_P1_BIT           ; 2
    STA evCnt                 ; 3
    JMP .selectionLoop        ; 3
.buildDone:

    ; ---- convert absolute rows to kernel deltas ----
    JMP ConvertDeltas       ; 3

; =============================================================================
; AppendEvent
;
; Adds one event (row, reg, val) to evTbl, which holds ABSOLUTE rows while the
; builder runs.  Every entry is the uniform 5-byte format:
;
;   [row, reg1, val1, reg2, val2]     (reg2 = 0 marks a single event)
;
; Real entries live from table offset 5 (the dummy occupies bytes 0..4; its
; delta byte is the EV_MARKER_ROW sentinel so the back-scan below stops before
; entry 0 and inserts at offset 5).
;
; BuildEvents emits the events in ascending row order, so the new row is >=
; every row already in the table.  AppendEvent therefore scans BACKWARD from
; the last entry (a short walk - ties/bumps keep the insertion point near the
; end) and:
;   * entry row < new row: write the new entry at the marker position (no
;     shift in the common case), fresh marker 5 bytes on;
;   * entry row == new row: merge the new event as its slot 2 - UNLESS the
;     event is already a double, the new event is ENAM1 (M1 x can be < 15),
;     or the new event is ENABL and ball_x < 15 (the beam reaches pixel 15
;     at cycle ~28, but slot 2 writes at cycle 27).  When the existing entry
;     has ENABL in slot 1 and the new event is a player, the two are swapped:
;     player -> slot 2 (always safe, player x=16), ball -> slot 1 (always
;     safe).  When the new event is ENABL and ball_x < 15 and the existing
;     entry is a player, they are also swapped: player -> slot 2, ball -> slot
;     1.  Otherwise the event's row is bumped to row+1.
;   * entry row > new row: step one entry back.
;
; A table entry never holds three writes (that would break the 76-cycle kernel
; budget), so a double never merges a third event: the extra event is bumped
; to row+1 instead.  If a bumped row falls past the last display line, the
; event is dropped.  Every event with a row >= KERNEL_SCANLINES is dropped
; immediately (before anything is pushed to the stack): such an event could
; never be rendered and would push the end-marker past line 184, breaking the
; 185-line frame.  The same drop applies when tblLen already holds
; EV_MAX_EVENTS.
;
; A = row, X = register index, Y = value.
; Uses evRow, tempCount (via ShiftBy5 and the *5 math), tblLen and the stack
; (the value AND the register index are held on the stack while the table is
; scanned and shifted, so the register index survives the scan; row stays in
; evRow).  The stack order is [value, reg] with reg on top.
; =============================================================================
.dropEntry:
    RTS                     ; 6   drop an event whose row is off the display
AppendEvent:
    STA evRow               ; 3   save the event row
    CMP #KERNEL_SCANLINES   ; 2   row past the last display line?
    BCS .dropEntry          ; 2/3  -> dropped (backward, short)
    TYA                     ; 2   save the value on the stack
    PHA                     ; 3
    TXA                     ; 2   save the register index on the stack too:
    PHA                     ; 3   the *5 math below would clobber X otherwise
    LDA tblLen              ; 3
    CMP #EV_MAX_EVENTS      ; 2   table full?
    BCC .haveRoom           ; 2/3  room -> continue
    PLA                     ; 4   discard the register index
    PLA                     ; 4   discard the saved value
    RTS                     ; 6
.haveRoom:
    LDA tblLen              ; 3
    BEQ .firstEntry         ; 2/3  empty table -> first entry at offset 5
    ; Y = offset of the last real entry = 5 * (tblLen - 1) + 5, without X
    SEC                     ; 2
    SBC #1                  ; 2   tblLen - 1
    STA tempCount           ; 3
    ASL                     ; 2
    ASL                     ; 2   4 * (tblLen - 1)
    CLC                     ; 2
    ADC tempCount           ; 3   5 * (tblLen - 1)
    CLC                     ; 2
    ADC #5                  ; 2   + dummy offset
    TAY                     ; 2
.scanBack:
    LDA evTbl,Y             ; 4   current entry's row
    CMP evRow               ; 3
    BCC .appendAfter        ; 2/3  entry row < new row -> append after it
    BEQ .sameRow            ; 2/3  entry row == new row -> merge or bump
    ; entry row > new row: step one entry back
    TYA                     ; 2
    SEC                     ; 2
    SBC #5                  ; 2
    TAY                     ; 2
    BCS .scanBack           ; 2/3  still inside the real entries
    JMP .insertAtZero       ; 3   walked past entry 0 -> insert at offset 5
.appendAfter:
    TYA                     ; 2
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2   Y = marker position (append)
    JMP .writeEntry         ; 3
.firstEntry:
    LDY #5                  ; 2   first real entry at offset 5 (after the dummy)
.writeEntry:
    ; ---- write the new entry at Y, fresh marker at Y+5 ----
    PLA                     ; 4   register index
    STA evTbl+1,Y           ; 4   reg1
    PLA                     ; 4   value
    STA evTbl+2,Y           ; 4   val1
    LDA #0                  ; 2
    STA evTbl+3,Y           ; 4   reg2 = 0 -> single event
    STA evTbl+4,Y           ; 4   val2
    LDA evRow               ; 3
    STA evTbl,Y             ; 4   row
    LDA #EV_MARKER_ROW      ; 2
    STA evTbl+5,Y           ; 4   fresh marker 5 bytes on
    LDA #0                  ; 2
    STA evTbl+6,Y           ; 4   marker reg1
    STA evTbl+7,Y           ; 4   marker val1
    STA evTbl+8,Y           ; 4   marker reg2
    STA evTbl+9,Y           ; 4   marker val2
    INC tblLen              ; 5
    RTS                     ; 6
.sameRow:
    LDA evTbl+3,Y           ; 4   reg2 of the same-row entry
    BNE .bumpRow            ; 2/3  already a double -> bump the new event
    ; ---- slot-2 register safety check ----
    ; Slot 2 writes at cycle 27; the beam reaches pixel p at ~(p+69)/3, so
    ; pixel 15 at cycle ~28.  An object with x >= 15 is safe in slot 2.
    ; Players are always at x=16 (safe).  ENABL depends on ball_x.
    ; ENAM1 can be at any x (M1 x varies) so it is never slot 2.
    CPX #EV_REG_ENAM1       ; 2   M1 must never be slot 2 (x can be < 15)
    BEQ .bumpRow            ; 2/3
    CPX #EV_REG_ENABL       ; 2   is the NEW event the ball?
    BEQ .ballNewSameRow     ; 2/3  -> check ball_x for slot-2 safety
    ; ---- new event is NOT the ball; check if the EXISTING entry is ENABL ----
    LDA evTbl+1,Y           ; 4   reg1 of the existing entry
    CMP #EV_REG_ENABL       ; 2
    BNE .normalMerge        ; 2/3  neither is ENABL -> safe to merge as slot 2
    ; ---- existing entry has ENABL in slot 1, new event is a player ----
    ; Swap: player -> slot 1, ball -> slot 2.  Player x=16 is always safe
    ; for slot 2.  Ball goes to slot 1 (always safe).
    LDA ball_x              ; 3
    CMP #15                 ; 2   ball_x >= 15 -> ball safe in slot 2
    BCS .swapEnabl          ; 2/3  -> swap (ball to slot 2, player to slot 1)
    ; ball_x < 15: ball cannot go to slot 2, but player CAN go to slot 2.
    ; Swap: player -> slot 1, ball -> slot 2 would put ball in slot 2 (unsafe).
    ; Instead: player -> slot 1 (overwrite, no change), ball -> slot 2 is
    ; unsafe.  But player x=16 IS safe for slot 2, so we can just put the
    ; player in slot 1 and the ball in slot 2... wait, ball_x < 15 means
    ; ball CANNOT be slot 2.  So: put player in slot 1, ball in slot 1?
    ; No - the existing entry already has ENABL in slot 1.
    ; Correct: put the PLAYER in slot 1 (overwrite ENABL), put ball in slot 2.
    ; But ball_x < 15 means slot 2 write arrives too late for the ball.
    ; The ball is 3 pixels wide; the write at cycle 27 reaches the beam at
    ; pixel ~12 (cycle 27 -> ~(12+69)/3 = 27).  For ball_x < 15 the beam
    ; has already passed the ball's left edge.  We must put the ball in slot 1.
    ; Player x=16 IS safe for slot 2.  So: ball -> slot 1, player -> slot 2.
    ; This means: overwrite slot 1 with player (wrong!), put ball in slot 2.
    ; Actually we need: slot 1 = ENABL (ball), slot 2 = GRP (player).
    ; The existing entry has ENABL in slot 1 already.  We just need to add
    ; the player as slot 2.  Player x=16 is safe for slot 2.  Done!
    JMP .normalMerge        ; 3   merge player into slot 2 (safe: player x=16)
.ballNewSameRow:
    LDA ball_x              ; 3
    CMP #15                 ; 2   ball_x >= 15 -> safe to merge as slot 2
    BCS .normalMerge        ; 2/3  -> merge ball into slot 2
    ; ball_x < 15: ball cannot be slot 2.  Check if existing entry has a
    ; player: swap ball to slot 1, player to slot 2 (player x=16 always safe).
    LDA evTbl+1,Y           ; 4   reg1 of the existing entry
    CMP #EV_REG_ENABL       ; 2
    BEQ .bumpRow            ; 2/3  both ENABL: impossible (ball is single), bump
    ; Existing entry is a player.  Swap: player -> slot 2, ball -> slot 1.
    ; Player x=16 is always safe for slot 2.
.swapEnabl:
    PLA                     ; 4   register index (ENABL)
    STA tempSwap            ; 3   save ball's register temporarily
    PLA                     ; 4   value (BALL_ENABLE)
    ; Read the existing player entry from the table
    PHA                     ; 4   push ball's value (will go to slot 1)
    LDA evTbl+2,Y           ; 4   player's value
    PHA                     ; 4   push player's value (will go to slot 2)
    LDA evTbl+1,Y           ; 4   player's register
    PHA                     ; 4   push player's register (will go to slot 2)
    ; Write ball to slot 1 (overwrite the player's register)
    LDA tempSwap            ; 3   ball's register (ENABL)
    STA evTbl+1,Y           ; 4   slot 1 reg = ENABL
    PLA                     ; 4   player's register
    STA evTbl+3,Y           ; 4   slot 2 reg = player's register
    PLA                     ; 4   player's value
    STA evTbl+4,Y           ; 4   slot 2 val = player's value
    PLA                     ; 4   ball's value
    STA evTbl+2,Y           ; 4   slot 1 val = BALL_ENABLE
    LDA evRow               ; 3   restore row (clobbered by tempSwap load)
    STA evTbl,Y             ; 4   row (unchanged, but restore for correctness)
    RTS                     ; 6
.normalMerge:
    ; ---- merge the new event into the same-row single as its slot 2 ----
    PLA                     ; 4   register index
    STA evTbl+3,Y           ; 4   reg2
    PLA                     ; 4   value
    STA evTbl+4,Y           ; 4   val2
    RTS                     ; 6
.bumpRow:
    INC evRow               ; 5   double entry or forbidden slot 2: bump row+1
    LDA evRow               ; 3   bumped row past the last display line?
    CMP #KERNEL_SCANLINES   ; 2
    BCS .dropStacked        ; 2/3  -> drop (pop the value and return)
    TYA                     ; 2   look at the next entry (or the marker)
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2
    LDA evTbl,Y             ; 4   its row ($FF if it is the marker)
    CMP #EV_MARKER_ROW      ; 2
    BEQ .bumpToWrite        ; 2/3  next is the marker -> append the bumped event
    CMP evRow               ; 3
    BEQ .sameRow            ; 2/3  bumped row == next row -> merge/bump again
    ; next row > bumped row -> insert the bumped event before it (at Y)
    ; fall through into insertMid
.bumpToWrite:
    JMP .writeEntry         ; 3
.insertMid:
    ; ---- shift the suffix from Y up by 5, then write the entry at Y ----
    JSR ShiftBy5            ; 6   Y preserved; shifts the marker + suffix
    PLA                     ; 4   register index
    STA evTbl+1,Y           ; 4   reg1
    PLA                     ; 4   value
    STA evTbl+2,Y           ; 4   val1
    LDA #0                  ; 2
    STA evTbl+3,Y           ; 4   reg2 = 0 -> single event
    STA evTbl+4,Y           ; 4   val2
    LDA evRow               ; 3   effective row (may have been bumped)
    STA evTbl,Y             ; 4   row
    INC tblLen              ; 5
    RTS                     ; 6
.insertAtZero:
    LDY #5                  ; 2   insert before the first real entry
    JMP .insertMid          ; 3
.dropStacked:
    PLA                     ; 4   discard the register index
    PLA                     ; 4   discard the saved value
    RTS                     ; 6

; =============================================================================
; ShiftBy5
;
; Shift every byte at index >= Y up by 5 so AppendEvent can insert a new
; 5-byte entry at Y.  Runs from the top of the table down so no byte is
; overwritten before it is read.  Preserves Y; clobbers A, X and tempCount.
;
; Bounds: a shift happens only when inserting a new entry, and the table is
; full-checked before the scan, so tblLen is at most EV_MAX_EVENTS - 1 = 9
; before the shift: the marker sits at 5*9 + 5 = 50 and its last byte at 54,
; so X starts at 5*9 + 10 = 55, DEX makes it 54 (the current top), and the
; largest write index is 54 + 5 = 59 - inside the 60-byte table (dummy +
; entries + marker).
;
; The loop terminates when X == tempCount (after copying the insertion point's
; byte).  DEX wraps 0 -> $FF, so the loop must test X before it can wrap:
; CPX + BNE stops at X == tempCount instead of comparing X >= tempCount.
; =============================================================================
ShiftBy5:                    ; Y = first index to move
    STY tempCount            ; 3   remember the insertion point
    LDA tblLen               ; 3   number of real entries
    ASL                     ; 2
    ASL                     ; 2   4 * tblLen
    CLC                     ; 2
    ADC tblLen              ; 3   5 * tblLen = offset of the marker
    CLC                     ; 2
    ADC #10                 ; 2   one past the top byte (X = top + 1, dummy
                            ;     offset included)
    TAX                     ; 2
.shift5Loop:
    DEX                     ; 2   next byte down
    LDA evTbl,X             ; 4   copy the byte...
    STA evTbl+5,X           ; 4   ...five positions up
    CPX tempCount           ; 3   stop after the insertion point
    BNE .shift5Loop         ; 2/3
    RTS                     ; 6

; =============================================================================
; ConvertDeltas
;
; Walks the finished table and replaces every absolute row with the delta the
; kernel counts down: the gap to the NEXT entry.  The first real entry's row
; (at table offset 5, after the dummy) is stored in nullDelta (the kernel
; primes evCnt with it); entry i's delta is row_i - row_{i-1}; the last real
; entry's delta is KERNEL_SCANLINES - row_last (the gap to the marker, which
; fires on line 184 and ends the kernel).  When the table is empty nullDelta =
; KERNEL_SCANLINES and the kernel counts all 185 lines straight to the marker
; at offset 5.  The marker's delta byte stays EV_MARKER_VAL ($FF), which the
; kernel tests with CMP #$FF.
;
; Every event row is < KERNEL_SCANLINES (InsertEvent drops the rest), so the
; last entry's delta is always >= 1 and the kernel renders exactly 185 lines.
; Clobbers A, X, Y, evRow, tempCount and nullDelta.
; =============================================================================
ConvertDeltas:
    LDY #5                  ; 2   first real entry at offset 5 (after the dummy)
    LDX tblLen              ; 3   number of real entries
    BEQ .noEvents           ; 2/3
    LDA evTbl,Y             ; 4   first real row
    STA nullDelta           ; 3   prime delta = row_1
.deltaLoop:
    LDA evTbl,Y             ; 4   absolute row of the current entry
    STA evRow               ; 3   remember it
    LDA evTbl+5,Y           ; 4   next entry's row
    CMP #EV_MARKER_ROW      ; 2   next entry is the end-marker?
    BNE .notLast            ; 2/3  no -> use its row as the next boundary
    LDA #KERNEL_SCANLINES   ; 2   yes -> gap to the marker on line 184
.notLast:
    SEC                     ; 2
    SBC evRow               ; 3   delta = next - current
    STA evTbl,Y             ; 4   store the delta
    TYA                     ; 2   advance to the next entry
    CLC                     ; 2
    ADC #5                  ; 2
    TAY                     ; 2
    DEX                     ; 2
    BNE .deltaLoop          ; 2/3
    RTS                     ; 6
.noEvents:
    LDA #KERNEL_SCANLINES   ; 2
    STA nullDelta           ; 3   185: count straight to the marker
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
; Round 3.1 layout - 48 bytes (was 122).  The event table is variable-size
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
;
; Round 10: the event table becomes uniform 5-byte entries again
; (EV_TBL_SIZE = 55 bytes) and a nullDelta byte stores the first event's
; delta, so the table can live at its own fixed offset.  RAM total: 79 bytes
; used / 49 free ($80-$CE).  The +28-byte growth buys the constant-cost
; table-direct kernel that makes the 263-scanline slip impossible (see the
; kernel comment and docs/en/memory-map.md).
;
; Round 11 (delta=1 fix): the kernel now applies every entry directly from
; the table, so the four pending registers (pendReg1..pendVal2) are gone.  The
; table grows to EV_TBL_SIZE = 60 bytes (a 5-byte dummy at offset 0, so the
; pre-first-event apply writes only AUDV0).  Net RAM: 80 bytes used / 48 free
; ($80-$CF).  The +1 byte is justified by the correctness fix: with the old
; two-phase pipeline, two events on consecutive rows silently dropped the
; first entry's writes (objects invisible or left enabled to the bottom edge).
;
; Round 6 (ball contact): adds ball_contact_flags (CONTACT_P0/CONTACT_P1),
; the observable record of ball x player contact -> 81 bytes used / 47 free
; ($80-$D0).  The +1 byte over Round 11 is deliberate and documented: the flag
; is a distinct byte by design (contact information must never mix with the
; hit_flags damage record), it must survive the whole frame (it cannot share
; a VBLANK builder scratch or the fire/missile bit-packs, which are all
; rewritten every VBLANK), and the alternative packings were rejected in the
; Round 6 change log.  The project RAM budget was raised to 81 accordingly.
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
ball_contact_flags DS 1     ; CONTACT_P0/CONTACT_P1, set by ProcessCollisions
                            ; (Round 6, ball x player contact record)

fire_prev   DS 1            ; packed fire state (FIRE_P0/FIRE_P1 + FIRE_SYNC)
evCnt       DS 1            ; kernel: scanlines until the next event fires

; Game state and mode (Round 12).  game_state is STATE_MENU (0) on power-on
; (RAM cleared to 0) and STATE_PLAYING (1) during gameplay.  game_mode
; records DUEL (0) or SCORE (1) and persists through menu/play transitions.
; select_prev/reset_prev hold the previous frame's switch bits for edge
; detection (released -> pressed).
game_state  DS 1            ; STATE_MENU or STATE_PLAYING
game_mode   DS 1            ; MODE_DUEL or MODE_SCORE
select_prev DS 1            ; previous SELECT switch bit for edge detection
reset_prev  DS 1            ; previous RESET switch bit for edge detection
swchb_cur   DS 1            ; current frame SWCHB snapshot (HandleInput)
reset_held  DS 1            ; nonzero while RESET is held in menu

; SCORE mode state (Round 13).  score_p0/score_p1 track the score for each
; player; both start at 0 when a SCORE game begins.  pending_rally_reset is
; set when a rally ends (goal or KO) and triggers ResetRally at the start of
; the NEXT frame's VBLANK.  This defers the rally reset out of the overscan
; (where timing is critical) and out of UpdateBall (where it would interfere
; with missile state).  The flag is cleared by ResetRally.
score_p0     DS 1            ; SCORE mode: Player 0 score (0..255)
score_p1     DS 1            ; SCORE mode: Player 1 score (0..255)
pending_rally_reset DS 1     ; SCORE mode: set on goal/KO, cleared by ResetRally

; Event table: 5-byte dummy at offset 0 (all-zero regs so the kernel's
; pre-first-event apply writes only AUDV0), then up to EV_MAX_EVENTS real
; 5-byte entries, then the 5-byte marker.  Deltas are gaps to the NEXT event
; (ConvertDeltas); reg2 = 0 marks a single event.
evTbl       DS EV_TBL_SIZE  ; dummy + entries + end-marker (60 bytes, constants.inc)

; BuildEvents shared temps (written before use, so the same bytes are reused
; across the insert and convert phases).
evRow       DS 1            ; InsertEvent: event row  /  ConvertDeltas: row
tempCount   DS 1            ; InsertEvent: shift point / ConvertDeltas: prevRow
tempSwap    DS 1            ; AppendEvent: ball value during slot swap
tblLen      DS 1            ; number of real entries in the table

nullDelta   DS 1            ; first event's delta (row_1, or 185 when empty)

; =============================================================================
; 6502 vectors
; =============================================================================
    SEG
    ORG $FFFA
    .WORD Reset             ; NMI (unused)
    .WORD Reset             ; RESET
    .WORD Reset             ; IRQ (unused)
