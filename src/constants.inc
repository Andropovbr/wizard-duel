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
;   VBLANK    37 lines  (TIM64T = 44, expires on the final VBLANK line)
;   KERNEL   192 lines  (explicit WSYNC loop)
;   OVERSCAN  30 lines  (TIM64T = 37, expires on the final line)
;   TOTAL    262 lines
; ---------------------------------------------------------------------------
FRAME_SCANLINES      = 262
VSYNC_SCANLINES      = 3
VBLANK_SCANLINES     = 37
KERNEL_SCANLINES     = 192
OVERSCAN_SCANLINES   = 30

VBLANK_TIMER_VALUE   = 43
OVERSCAN_TIMER_VALUE = 37

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
;   - ball_y: kernel scanline index at which the first ENABL = 1 write for
;     this ball occurs; because of the TIA graphics latch the ball is
;     physically displayed on scanlines ball_y + 1 .. ball_y + BALL_HEIGHT
;     (the same coordinate convention as the players).
;
; Horizontal positioning note: the TIA delays player graphics by 1 CLK more
; than the ball/missile output, so for the same PosObject input the ball
; appears 1 pixel to the LEFT of a player. PositionBall therefore passes
; ball_x + 1 to PosObject; the bounds below are expressed in the visible
; pixel coordinate (ball_x), so the ball stays fully inside the 160-pixel
; visible width.
; ---------------------------------------------------------------------------
BALL_WIDTH         = 4       ; ball size in pixels (CTRLPF D5:D4 = %10)
BALL_HEIGHT        = 4       ; ball size in scanlines (ENABL = 1 for 4 rows)
BALL_SIZE_CTRLPF   = %00100000   ; CTRLPF D5=1, D4=0 -> 4 color clocks
BALL_COLOR         = $0E     ; white (NTSC)
BALL_ENABLE        = $FF     ; ENABL bit 0 = ball output enabled. The kernel
                             ; computes this value branchlessly as
                             ; LDA #0 / SBC #0 -> $FF on a ball row, $00
                             ; otherwise (see main.asm); only bit 0 matters
                             ; to the TIA, but $FF avoids an extra AND.

BALL_X_MIN         = 0                     ; left edge of the visible area
BALL_X_MAX         = 160 - BALL_WIDTH      ; keep the 4-px ball fully visible
BALL_Y_MIN         = 0                     ; drawn on the first kernel line
BALL_Y_MAX         = KERNEL_SCANLINES - BALL_HEIGHT - 1
                                          ; last ball draw row on kernel line
                                          ; 187 -> displayed on lines 188..191.
                                          ; ENABL is cleared explicitly during
                                          ; overscan init, so the ball can
                                          ; never bleed into overscan

BALL_X_INIT        = 78      ; ~center of the 160-pixel arena
BALL_Y_INIT        = 95      ; ~center of the 192-line kernel

; Direction steps added to ball_x/ball_y every frame (constant speed).
DIR_LEFT  = $FF             ; -1
DIR_RIGHT = 1
DIR_UP    = $FF             ; -1
DIR_DOWN  = 1

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

; VBLANK values. Bit 1 blanks the display; bit 6 ($40) only controls the
; INPT latches used for paddles, which are not used yet.
VBLANK_BLANK = $02