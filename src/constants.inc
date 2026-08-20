; =============================================================================
; Wizard Duel - Atari 2600
; constants.inc
;
; Hardware register addresses and build-time constants.
;
; The Atari 2600 maps the TIA to $00-$3F (repeated in $40-$7F) and the
; RIOT (RAM + I/O + timer) to $0280-$02FF on the 6507.
; =============================================================================

; ---------------------------------------------------------------------------
; TIA - write registers
; ---------------------------------------------------------------------------
VSYNC   = $00
VBLANK  = $01
WSYNC   = $02
RSYNC   = $03
NUSIZ0  = $04
NUSIZ1  = $05
COLUP0  = $06
COLUP1  = $07
COLUPF  = $08
COLUBK  = $09
CTRLPF  = $0A
REFP0   = $0B
REFP1   = $0C
PF0     = $0D
PF1     = $0E
PF2     = $0F
RESP0   = $10
RESP1   = $11
RESM0   = $12
RESM1   = $13
RESBL   = $14
AUDC0   = $15
AUDC1   = $16
AUDF0   = $17
AUDF1   = $18
AUDV0   = $19
AUDV1   = $1A
GRP0    = $1B
GRP1    = $1C
ENAM0   = $1D
ENAM1   = $1E
ENABL   = $1F
HMP0    = $20
HMP1    = $21
HMM0    = $22
HMM1    = $23
HMBL    = $24
VDELP0  = $25
VDELP1  = $26
VDELBL  = $27
RESMP0  = $28
RESMP1  = $29
HMOVE   = $2A
HMCLR   = $2B
CXCLR   = $2C

; ---------------------------------------------------------------------------
; RIOT
; ---------------------------------------------------------------------------
; The I/O registers are $0280-$0283 (SWCHA, SWACNT, SWCHB, SWBCNT) and the
; interval timer lives in $0284-$0296 (INTIM read, TIM64T write). The 6507
; has no address bus above 13 bits, so these are the fixed hardware ports.
SWCHA   = $0280  ; joystick read (active low) / port A output
SWACNT  = $0281  ; port A data direction register (0 = input)
SWCHB   = $0282  ; console switches read (active low)
SWBCNT  = $0283  ; port B data direction register
INTIM   = $0284  ; interval timer (decrements while running)
TIM64T  = $0296  ; write timer value, countdown clock = 64 cycles

; ---------------------------------------------------------------------------
; Frame structure (NTSC)
; ---------------------------------------------------------------------------
; One frame is exactly FRAME_SCANLINES lines. The three blank regions are
; produced with the RIOT interval timer (TIM64T); the values below were
; derived by counting CPU cycles so the timer expires on the intended
; scanline. See docs/en/timing.md for the full derivation.
;
;   VSYNC      3 lines  (3 explicit WSYNC writes)
;   VBLANK    64 lines  (TIM64T = 77, expires on the final VBLANK line)
;   KERNEL   185 lines  (explicit WSYNC loop)
;   OVERSCAN  10 lines  (WSYNC countdown loop, see below)
;   TOTAL    262 lines
;
; VBLANK is larger than in Round 2 because the event table for the visible
; kernel (players, ball and up to two missiles) is rebuilt every frame during
; VBLANK by BuildEvents.  OVERSCAN shrinks accordingly to keep the frame at
; 262 lines.
;
; Round 4: the overscan no longer uses a TIM64T wait.  The timer was only
; deterministic because the pre-timer work was fixed; with a variable-cost
; collision pass the INTIM < 64 exit granularity made the overscan region land
; on different 76-cycle boundaries, so the frame occasionally slipped to 263
; scanlines.  The overscan is now a fixed WSYNC countdown anchored to exactly
; 760 cycles (10 lines), and any variable-cost work that runs before the loop
; must land the first WSYNC on the same 76-cycle boundary on every path.
;
; Round 5: OVERSCAN_LOOP_COUNT drops from 8 to 7 so the region can absorb
; ProcessHitEffects (HP damage + dead-player fire lock) which runs after
; ProcessCollisions.  The fixed pre-loop work puts the first WSYNC write on
; cycle K+187..K+207 (K = last kernel WSYNC landing), which lands on K+228;
; the 7 countdown WSYNCs reach K+684 and the next frame's first VSYNC WSYNC
; lands on K+760.  See ProcessHitEffects in main.asm for the cost window.
;
; Round 6: the VBLANK TIM64T value grew from 69 to 77 and the kernel shrank
; from 192 to 185 lines to fix a whole-screen vertical shake when both
; missiles are active.  The old VBLANK timer was too small: with real 6502
; branch timing (taken = 3 cycles, page crossing +1) the VBLANK game logic
; (UpdatePlayers..BuildEvents) can end as late as ~4919 cycles into the
; frame, while a timer value of 69 expires at ~4553 cycles.  Whenever the
; work overran the expiry, the WaitVBlank INTIM spin exited at the *work end*
; (variable), so the final VBLANK WSYNC landed on different 76-cycle
; boundaries and frames slipped to 263/264/265 scanlines.  The value 77
; expires at ~4864 cycles ((77 - 1) * 64, when INTIM first reads 0), ~409
; cycles past the worst work measured under the emulator's realistic branch
; timing, so the spin always exits on the timer and every frame lands on the
; same boundary -> exactly 262 lines.  The kernel lost 7 lines to pay for
; the longer VBLANK.  See tools/benchmark.py (vblank_work/vblank_margin).
;
; Round 9: OVERSCAN_LOOP_COUNT drops from 7 to 6 and 8 cycles of NOP padding
; are inserted after ProcessHitEffects so the overscan stays anchored after
; the kernel redesign.  The kernel now ends on its own end-marker entry
; (KERNEL_SCANLINES lines, no scanCnt countdown), and the marker path reaches
; .kernelEnd at K+44 (K = last kernel WSYNC landing).  With the epilogue
; (22) + ProcessCollisions (90 incl. JSR) + ProcessHitEffects (6 + B, B in
; [62, 80]) + padding (8) + LDX (2), the first overscan WSYNC write lands on
; K+235..K+255, i.e. inside (K+228, K+304), so it snaps to K+304.  Six
; countdown WSYNCs then reach K+684 and the next frame's first VSYNC WSYNC
; lands on K+760, keeping the overscan exactly 10 lines.  See the overscan
; section of main.asm and docs/en/timing.md.
;
; Round 10 (table-direct kernel): the kernel is redesigned again so it ends on
; its own marker entry and every scanline is a fixed-cost path (see the kernel
; comment in main.asm).  The marker path now reaches .kernelEnd at K+50 instead
; of K+44, so the first overscan WSYNC write lands on K+241..K+261 - still
; inside (K+228, K+304) - and the six countdown WSYNCs keep the overscan on
; exactly 10 lines.  The overscan loop count and padding are unchanged.
; ---------------------------------------------------------------------------
FRAME_SCANLINES      = 262
VSYNC_SCANLINES      = 3
VBLANK_SCANLINES     = 64
KERNEL_SCANLINES     = 185
OVERSCAN_SCANLINES   = 10

VBLANK_TIMER_VALUE   = 77
OVERSCAN_LOOP_COUNT  = 6

; ---------------------------------------------------------------------------
; Player constants
; ---------------------------------------------------------------------------
; A player is PLAYER_HEIGHT scanlines tall and moves only on the vertical
; axis. PLAYERx_X is the fixed horizontal position (TIA pixel, 0..159).
;
; The vertical position PLAYERx_Y is the kernel scanline index at which the
; sprite's first row is drawn. The kernel renders each player as a solid
; rectangle: on every scanline X it computes the boolean
; "PLAYERx_Y <= X < PLAYERx_Y + PLAYER_HEIGHT" and writes either
; PADDLE_BITS (on the paddle rows) or $00 (elsewhere) to GRP0/GRP1. The
; whole sprite stays inside the visible region as long as Y stays within
; [MIN, MAX].
;
; PADDLE_BITS is the 8-bit row pattern, %00111100, a 4-pixel-wide vertical
; bar. Both players share it; the shape is provisional and intentionally
; neutral so the future mechanics can be developed without depending on
; character art. See the kernel comment in main.asm for the cycle cost of
; the branchless "draw or blank" computation.
; ---------------------------------------------------------------------------
PLAYER_HEIGHT      = 12
PLAYER_Y_MIN       = 0
PLAYER_Y_MAX       = KERNEL_SCANLINES - PLAYER_HEIGHT - 1
PADDLE_BITS        = %00111100

PLAYER1_X          = 16
PLAYER2_X          = 136
PLAYER1_Y_INIT     = 48
PLAYER2_Y_INIT     = 128

PLAYER1_COLOR      = $46     ; red (NTSC)
PLAYER2_COLOR      = $84     ; blue (NTSC)
BACKGR_COLOR       = $00     ; black

; ---------------------------------------------------------------------------
; Ball constants
; ---------------------------------------------------------------------------
; The ball is a TIA Ball object: BALL_WIDTH pixels wide (CTRLPF D5:D4 = %10)
; and BALL_HEIGHT scanlines tall. It is kept approximately square (4 x 4)
; because a 4-pixel-wide, 1-scanline-tall ball renders as a thin horizontal
; dash and, being only 1 scanline tall, has no vertical overlap between
; consecutive frames, which makes its 1 px/frame motion look stroboscopic.
; It moves at a constant 1 pixel per frame per axis and bounces off the four
; arena edges. It does NOT interact with the players this round (no
; collision, no collection, no power-up).
;
; ball_x / ball_y are the ball's visual position:
;   - ball_x: leftmost visible pixel of the ball (0..159)
;   - ball_y: first kernel scanline on which the ball is displayed; it is
;     displayed on the BALL_HEIGHT consecutive rows ball_y .. ball_y + 3.
;     In the event kernel an event written at the top of a scanline applies
;     on that scanline (verified on the target), so ball_y is the display row
;     directly (no TIA latch offset).
;
; Horizontal positioning note: the TIA delays player graphics by 1 CLK more
; than the ball/missile output, so for the same PosObject input the ball
; appears 1 pixel to the LEFT of a player. PositionBall therefore passes
; ball_x + 8 (or ball_x + 5 for the first 15-pixel region) to PosObject; the
; bounds below are expressed in the visible pixel coordinate (ball_x), so the
; ball stays fully inside the 160-pixel visible width.
; ---------------------------------------------------------------------------
BALL_WIDTH         = 4       ; ball size in pixels (CTRLPF D5:D4 = %10)
BALL_HEIGHT        = 4       ; ball size in scanlines (ENABL = 1 for 4 rows)
BALL_SIZE_CTRLPF   = %00100000   ; CTRLPF D5=1, D4=0 -> 4 color clocks
BALL_COLOR         = $0E     ; white (NTSC)
BALL_ENABLE        = %00000010   ; ENABL value on a ball row. The TIA only
                                 ; samples bit 1 of the ball enable register
                                 ; (verified against the Stella source:
                                 ; myEnam = value & 0x02), so the enable value
                                 ; is %00000010 rather than $FF.

BALL_X_MIN         = 0                     ; left edge of the visible area
BALL_X_MAX         = 160 - BALL_WIDTH      ; keep the 4-px ball fully visible
BALL_Y_MIN         = 0                     ; drawn on the first kernel line
BALL_Y_MAX         = KERNEL_SCANLINES - BALL_HEIGHT
                                           ; last first-draw row = 181; the
                                           ; ball occupies rows 181..184. The
                                           ; ball OFF event at row 185 is
                                           ; dropped by the event builder and
                                           ; ENABL is cleared explicitly during
                                           ; overscan init, so the ball can
                                           ; never bleed into overscan.

BALL_X_INIT        = 78      ; ~center of the 160-pixel arena
BALL_Y_INIT        = 95      ; ~center of the 185-line kernel

; Direction steps added to ball_x/ball_y every frame (constant speed).
DIR_LEFT  = $FF             ; -1
DIR_RIGHT = 1
DIR_UP    = $FF             ; -1
DIR_DOWN  = 1

; ---------------------------------------------------------------------------
; Missile constants
; ---------------------------------------------------------------------------
; Each player can fire one missile with the joystick fire button. A missile
; is MISSILE_HEIGHT scanlines tall and MISSILE_WIDTH pixels wide (set through
; the NUSIZ0/NUSIZ1 missile size bits), flies horizontally at constant
; MISSILE_SPEED pixels/frame and despawns at the arena edge.
;
; A missile spawns MISSILE_SPAWN_OFFSET rows below its player and keeps that
; vertical position while flying, so it contributes exactly two event-table
; events (ON at m?y, OFF at m?y + MISSILE_HEIGHT) like the ball.
;
; Horizontal positions use the same pixel coordinate as the ball (leftmost
; visible pixel), so a 2-pixel-wide missile stays fully inside the arena.
; ---------------------------------------------------------------------------
MISSILE_HEIGHT       = 4      ; scanlines tall
MISSILE_WIDTH        = 2      ; pixels wide (NUSIZ D5:D4 = %01)
MISSILE_NUSIZ        = %00010000
MISSILE_SPEED        = 2      ; pixels per frame
MISSILE_SPAWN_OFFSET = 4      ; spawn row = player row + 4 (paddle center)
MISSILE_ENABLE       = %00000010  ; ENAM0/ENAM1 value while visible (bit 1)

M0_X_INIT            = 18     ; left player's missile spawn x
M1_X_INIT            = 134    ; right player's missile spawn x
M0_X_MAX             = 158    ; M0 despawns when x > M0_X_MAX
M1_X_MIN             = 2      ; M1 despawns when x < M1_X_MIN

; Packed missile-active state (m_active): one bit per missile, so both missiles
; share a single RAM byte.  M0_BIT clears as "AND #%11111110", M1_BIT as
; "AND #%11111101".
M0_BIT = %00000001
M1_BIT = %00000010

; ---------------------------------------------------------------------------
; Event kernel constants
; ---------------------------------------------------------------------------
; The visible kernel is event-driven: instead of computing every object's
; enable every scanline, BuildEvents (run during VBLANK) writes a small table
; of uniform 5-byte "register write" entries.  Each entry is:
;
;   byte 0   delta          (scanlines until the NEXT event fires)
;   byte 1   reg1           (EV_WRITE_BASE offset, 1..5)
;   byte 2   val1
;   byte 3   reg2           (0 = single event: write 2 is a harmless AUDV1)
;   byte 4   val2
;
; A single event is stored with reg2 = 0: the kernel applies BOTH pending
; writes unconditionally, so write 2 becomes a benign write to AUDV1 ($1A + 0).
; The marker entry is [delta = EV_MARKER_VAL ($FF), 0, 0, 0, 0]; the kernel
; detects it by comparing the current entry's delta byte with EV_MARKER_VAL.
; Real deltas are 1..185, so $FF is an unambiguous sentinel.
;
; Register indices are offsets from EV_WRITE_BASE = AUDV1 ($1A); indices 1..5
; address GRP0..ENABL.
;
; Round 10 (table-direct kernel): the table is now uniform 5-byte entries and
; EV_SINGLE_FLAG is gone.  Deltas are gaps to the NEXT event (see
; ConvertDeltas); the first event's delta is stored separately in the nullDelta
; byte.
;
; Round 11 (delta=1 fix): the kernel applies the last-decoded entry's two
; writes DIRECTLY from the table on every scanline (LDX/LDA evTbl-4,Y ...), so
; no pending registers exist.  The decode is only "load delta, test the marker,
; advance Y".  Because the apply runs unconditionally at the START of every
; line, consecutive events (delta 1) can no longer collide: each entry's writes
; land on its own row.  The table carries a 5-byte DUMMY entry at offset 0
; (all zeros -> benign AUDV0 writes); real entries start at offset 5 and the
; kernel primes Y = 5 (so the pre-first-event lines read the dummy).  When the
; first entry fires on row 0 the priming primes Y = 10 instead (the apply then
; reads real entry 0 from line 0).  The end-marker entry fires on line 184
; (its delta byte is $FF), so the kernel always renders exactly
; KERNEL_SCANLINES lines and the overscan countdown stays anchored.
;
; Deltas: entry i applies on its DISPLAY row.  The entry is decoded on line
; row-1 (when evCnt hits 0) and, because the apply reads the last-decoded
; entry on every line, its writes land at the start of line row.  delta(first)
; = row_1 is stored in nullDelta; delta(i) = row_i - row_{i-1}; the last real
; entry's delta is KERNEL_SCANLINES - row_last (the gap to the marker on line
; 184).
;
; Row bound: an event with row >= KERNEL_SCANLINES is dropped by the builder
; (it could never be rendered and would push the marker past its line, breaking
; the 185-line frame).
;
; Size bound: EV_MAX_EVENTS = 10 events, each occupying exactly 5 bytes, plus
; the 5-byte dummy at offset 0 and the 5-byte marker -> EV_TBL_SIZE = 60 bytes.
; Merging two same-row singles into a double does not change the size (every
; entry is 5 bytes).  A row that already holds a double never accepts a third
; write: the builder bumps the extra event to row+1 (dropping it if that row
; would land past the last display line), keeping every scanline inside the
; kernel's cycle budget.
;
; Write-slot rule (Round 10, unchanged): on every line the kernel writes write
; 1 at scanline cycle ~15 (before the beam reaches pixel 0 at ~cycle 23) and
; write 2 at cycle ~27, which is only safe for objects with x >= 15.  The
; builder therefore guarantees, by insertion order and merge rules:
;   * the ball is always slot 1 on any row it shares (ball is inserted first),
;   * missile 1 is never slot 2 (its x can be as low as 2 < 15),
; so slot 2 is always one of P0 (x=16), P1 (x=136) or M0 (x >= 18).
; See the kernel comment in main.asm and docs/en/timing.md.
; ---------------------------------------------------------------------------
EV_REG_GRP0   = 1       ; GRP0  ($1B) - player 0 sprite
EV_REG_GRP1   = 2       ; GRP1  ($1C) - player 1 sprite
EV_REG_ENAM0  = 3       ; ENAM0 ($1D) - missile 0
EV_REG_ENAM1  = 4       ; ENAM1 ($1E) - missile 1
EV_REG_ENABL  = 5       ; ENABL ($1F) - ball
EV_WRITE_BASE = $1A     ; AUDV1; STA EV_WRITE_BASE,X writes the register above

EV_MAX_EVENTS     = 10    ; 2 players + ball + 2 missiles, 2 events each
EV_TBL_SIZE       = EV_MAX_EVENTS * 5 + 10  ; dummy + 10 entries + marker = 60
EV_MARKER_ROW     = $FF   ; builder sentinel: the marker's "row" during build
EV_MARKER_VAL     = $FF   ; kernel sentinel: the marker's delta byte (CMP #$FF)

; BuildEvents active/phase masks.  During the build nullDelta doubles as the
; active-object mask (bit set = the object still has an event to emit) and
; evCnt doubles as the ON-pending mask (bit set = its ON event is still due).
; Both are dead at that point in the frame: ConvertDeltas rewrites nullDelta
; right after the build, and the kernel primes evCnt after BuildEvents returns.
; The ball is scanned FIRST in the selection (bit 4) so it wins row ties and
; keeps slot 1 on any row it shares (see the write-slot rule above).
OBJ_BALL_BIT  = %00010000   ; bit 4: ball (always active)
OBJ_M1_BIT    = %00000001   ; bit 0: missile 1
OBJ_M0_BIT    = %00000010   ; bit 1: missile 0
OBJ_P0_BIT    = %00000100   ; bit 2: player 0 (only while alive)
OBJ_P1_BIT    = %00001000   ; bit 3: player 1 (only while alive)

; ---------------------------------------------------------------------------
; Joystick masks (SWCHA is active low: a bit is 0 when the direction is
; pushed).
;   Port 0 (left player / P0): D7 right, D6 left, D5 down, D4 up
;   Port 1 (right player / P1): D3 right, D2 left, D1 down, D0 up
; ---------------------------------------------------------------------------
JOY1_UP   = %00010000
JOY1_DOWN = %00100000
JOY2_UP   = %00000001
JOY2_DOWN = %00000010

; Fire buttons are read through the TIA INPT latches. For joysticks (VBLANK
; bit 6 clear), bit 7 of INPT4/INPT5 is 0 while the button is pressed.
; The TIA maps INPT0-3 at $38-$3B (paddle/keypad inputs) and INPT4/INPT5 at
; $3C/$3D (the fire-button latches).  $04/$05 are NUSIZ0/NUSIZ1, write-only
; registers: reading them would return the register address on the data bus
; (open bus) instead of the fire-button state.
INPT4 = $3C              ; P0 fire button (bit 7, active low)
INPT5 = $3D              ; P1 fire button (bit 7, active low)

; Packed fire-button edge state (fire_prev): bit 0 = P0 pressed last frame,
; bit 1 = P1 pressed last frame, bit 7 (FIRE_SYNC) = the first-frame boot
; synchronisation already happened.
FIRE_P0 = %00000001
FIRE_P1 = %00000010
FIRE_SYNC = %10000000

; ---------------------------------------------------------------------------
; TIA collision registers (Round 4, ball contact added in Round 6)
; ---------------------------------------------------------------------------
; The TIA latches a bit whenever two objects render an overlapping pixel
; (same scanline, overlapping horizontal extent).  Once set, a latch persists
; until CXCLR is written; reading a latch has NO side effects.  The register
; READ addresses share bytes with write registers ($00 is also VSYNC, $01
; also VBLANK, $02 also WSYNC, $03 also RSYNC): reads and writes on the same
; byte access different internal registers, so "LDA CXM0P" and "STA VSYNC"
; never interfere.
;
;   CXM0P   ($00, read): D7 = M0 x P1,  D6 = M0 x P0
;   CXM1P   ($01, read): D7 = M1 x P0,  D6 = M1 x P1
;   CXP0FB  ($02, read): D7 = P0 x PF,  D6 = P0 x BL  (ball contact)
;   CXP1FB  ($03, read): D7 = P1 x PF,  D6 = P1 x BL  (ball contact)
;   CXCLR   ($2C, write): clear every collision latch (strobe, value ignored)
;
; Only the cross-fire missile hits are gameplay (Round 4).  The own-player
; missile bits (M0 x P0, M1 x P1) are deliberately ignored so a missile can
; never damage its own player.  The player x ball bits (Round 6) are recorded
; in ball_contact_flags as pure contact information (no gameplay effect yet).
; The player x playfield bits are ignored: the playfield is never displayed.
CXM0P      = $00
CXM1P      = $01
CXP0FB     = $02
CXP1FB     = $03
M0_HIT_P1  = %10000000   ; CXM0P D7: M0 overlapped P1 (the M0 -> P1 hit)
M0_HIT_P0  = %01000000   ; CXM0P D6: M0 overlapped P0 (own player, ignored)
M1_HIT_P0  = %10000000   ; CXM1P D7: M1 overlapped P0 (the M1 -> P0 hit)
M1_HIT_P1  = %01000000   ; CXM1P D6: M1 overlapped P1 (own player, ignored)
BALL_HIT_P0 = %01000000  ; CXP0FB D6: the ball overlapped P0
BALL_HIT_P1 = %01000000  ; CXP1FB D6: the ball overlapped P1

; hit_flags bitfield (Round 4): a compact, testable record of which player
; was hit by the missile-on-player collisions just processed.  One bit per
; player; ProcessCollisions sets it and ProcessHitEffects (Round 5) consumes
; it as HP damage in the same overscan.
HIT_P0     = %00000001   ; player 0 was hit by M1
HIT_P1     = %00000010   ; player 1 was hit by M0

; ball_contact_flags bitfield (Round 6): which player the ball touched during
; the frame just rendered.  A deliberate SEPARATE byte from hit_flags: ball
; contact is contact information only (no damage), while hit_flags is the
; missile damage record consumed by ProcessHitEffects.  ProcessCollisions
; overwrites it every overscan, so it always reflects the most recent frame.
; A dead player is not rendered and therefore can never set a TIA latch: the
; rendering gate (BuildEvents skipping its GRP events) is what keeps a dead
; player contact-free, not an HP check here.
CONTACT_P0 = %00000001   ; the ball overlapped player 0
CONTACT_P1 = %00000010   ; the ball overlapped player 1

; ---------------------------------------------------------------------------
; Player HP (Round 5)
; ---------------------------------------------------------------------------
; Each player starts a round with PLAYER_START_HP hit points.  A valid
; cross-fire hit removes one HP (see ProcessHitEffects in main.asm); at 0 HP
; the player is dead and, while still occupying the arena, is no longer
; rendered and can no longer fire.  The value is deliberately not baked into
; the gameplay logic: damage and death only compare against zero, so any
; starting value works.
PLAYER_START_HP      = 3

; VBLANK values. Bit 1 blanks the display; bit 6 ($40) only controls the
; INPT latches used for paddles, which are not used yet.
VBLANK_BLANK = $02