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
;   VBLANK    57 lines  (TIM64T = 69, expires on the final VBLANK line)
;   KERNEL   192 lines  (explicit WSYNC loop)
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
; ---------------------------------------------------------------------------
FRAME_SCANLINES      = 262
VSYNC_SCANLINES      = 3
VBLANK_SCANLINES     = 57
KERNEL_SCANLINES     = 192
OVERSCAN_SCANLINES   = 10

VBLANK_TIMER_VALUE   = 69
OVERSCAN_LOOP_COUNT  = 7

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
                                           ; last first-draw row = 188; the
                                           ; ball occupies rows 188..191. The
                                           ; ball OFF event at row 192 is
                                           ; dropped by the event builder and
                                           ; ENABL is cleared explicitly during
                                           ; overscan init, so the ball can
                                           ; never bleed into overscan.

BALL_X_INIT        = 78      ; ~center of the 160-pixel arena
BALL_Y_INIT        = 95      ; ~center of the 192-line kernel

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
; of variable-size "register write" entries.  Each entry is either:
;
;   single entry (3 bytes):   byte 0  delta
;                             byte 1  reg1 | EV_SINGLE_FLAG
;                             byte 2  val1
;   double entry (5 bytes):   byte 0  delta
;                             byte 1  reg1
;                             byte 2  val1
;                             byte 3  reg2
;                             byte 4  val2
;
; EV_SINGLE_FLAG (bit 7 of reg1) marks a single entry.  The kernel loads reg1
; and tests bit 7 with BMI: flag set -> one write, flag clear -> two writes.
; Entries are stored in ascending row order; a terminator entry (delta =
; EV_TERMINATOR_DELTA, a single byte) closes the table.
;
; Register indices are offsets from EV_WRITE_BASE = AUDV1 ($1A); indices 1..5
; address GRP0..ENABL.  A single entry performs exactly one write (no dummy),
; which is what makes the variable-size entries worth their code.
;
; Deltas: the first entry fires on line (delta - 1) and every following entry
; fires `delta` lines after the previous one, so the builder computes
; delta(first) = row + 1 and delta(next) = row - prevRow.  The kernel counts
; exactly KERNEL_SCANLINES lines with a RAM countdown, so the table only holds
; real events followed by a terminator whose delta can never fire
; (EV_TERMINATOR_DELTA = $FF > any possible remaining line count).
;
; Size bound: 10 events, each contributing at most one single entry (3 bytes)
; when on a distinct row -> 30 bytes + 1 terminator = 31.  Merging two
; same-row singles into a double saves one byte, so the table can never exceed
; EV_TBL_SIZE bytes.  A row that already holds a double never accepts a third
; write: the builder bumps the extra event to row+1 instead, keeping every
; scanline inside the kernel's cycle budget.
; ---------------------------------------------------------------------------
EV_REG_GRP0   = 1       ; GRP0  ($1B) - player 0 sprite
EV_REG_GRP1   = 2       ; GRP1  ($1C) - player 1 sprite
EV_REG_ENAM0  = 3       ; ENAM0 ($1D) - missile 0
EV_REG_ENAM1  = 4       ; ENAM1 ($1E) - missile 1
EV_REG_ENABL  = 5       ; ENABL ($1F) - ball
EV_WRITE_BASE = $1A     ; AUDV1; STA EV_WRITE_BASE,X writes the register above
EV_SINGLE_FLAG = $80    ; bit 7 of reg1 marks a 3-byte single entry

EV_MAX_EVENTS     = 10      ; 2 players + ball + 2 missiles, 2 events each
EV_TBL_SIZE       = EV_MAX_EVENTS * 3 + 1   ; 10 singles + terminator = 31
EV_TERMINATOR_DELTA = $FF   ; never fires inside a 192-line kernel

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
; TIA collision registers (Round 4)
; ---------------------------------------------------------------------------
; The TIA latches a bit whenever two objects render an overlapping pixel
; (same scanline, overlapping horizontal extent).  Once set, a latch persists
; until CXCLR is written; reading a latch has NO side effects.  The register
; READ addresses share bytes with write registers ($00 is also VSYNC, $01
; also VBLANK): reads and writes on the same byte access different internal
; registers, so "LDA CXM0P" and "STA VSYNC" never interfere.
;
;   CXM0P  ($00, read): D7 = M0 x P1,  D6 = M0 x P0
;   CXM1P  ($01, read): D7 = M1 x P0,  D6 = M1 x P1
;   CXCLR  ($2C, write): clear every collision latch (strobe, value ignored)
;
; Only the cross-fire hits are gameplay this round.  The own-player bits
; (M0 x P0, M1 x P1) are deliberately ignored by the collision logic so a
; missile can never damage its own player.
CXM0P      = $00
CXM1P      = $01
M0_HIT_P1  = %10000000   ; CXM0P D7: M0 overlapped P1 (the M0 -> P1 hit)
M0_HIT_P0  = %01000000   ; CXM0P D6: M0 overlapped P0 (own player, ignored)
M1_HIT_P0  = %10000000   ; CXM1P D7: M1 overlapped P0 (the M1 -> P0 hit)
M1_HIT_P1  = %01000000   ; CXM1P D6: M1 overlapped P1 (own player, ignored)

; hit_flags bitfield (Round 4): a compact, testable record of which player
; was hit by the missile-on-player collisions just processed.  One bit per
; player; ProcessCollisions sets it and ProcessHitEffects (Round 5) consumes
; it as HP damage in the same overscan.
HIT_P0     = %00000001   ; player 0 was hit by M1
HIT_P1     = %00000010   ; player 1 was hit by M0

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