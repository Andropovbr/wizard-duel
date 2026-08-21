; =============================================================================
; Orb Mini-Loop Prototype - R&D Spike
;
; Standalone test ROM proving that a dedicated orb mini-loop can render a
; diamond-shaped ball using per-row CTRLPF width changes and RESBL positioning.
;
; This is an ISOLATED prototype. It does NOT integrate with the production
; game. It does NOT modify the main kernel, event table, or game logic.
;
; Target shape (4 rows):
;   .XX.     row 0: CTRLPF narrow (2px)
;   XXXX     row 1: CTRLPF wide (4px)
;   XXXX     row 2: CTRLPF wide (4px)
;   .XX.     row 3: CTRLPF narrow (2px)
;
; Build: dasm tests/proto/orb_mini_loop_test.asm -f3 -otests/proto/orb_mini_loop_test.bin
; Run:   stella tests/proto/orb_mini_loop_test.bin
; =============================================================================

    processor 6502
    include "constants.inc"

; ---------------------------------------------------------------------------
; ORB constants
; ---------------------------------------------------------------------------
ORB_HEIGHT       = 4
ORB_ROWS         = ORB_HEIGHT

; CTRLPF values for each orb row (D5:D4 = ball width)
;   %00 = 1 color clock (narrowest)
;   %01 = 2 color clocks (narrow)
;   %10 = 4 color clocks (wide) -- current ball width
;   %11 = 8 color clocks (widest)
ORB_CTRLPF_NARROW = %00000000  ; D5=0, D4=0 -> 1 pixel (tip of diamond)
ORB_CTRLPF_WIDE   = %00100000  ; D5=1, D4=0 -> 4 pixels (body of diamond)

; Ball control bits
BALL_ENABLE_BIT  = %00000010  ; ENABL bit 1
BALL_DISABLE     = $00

; RESBL delay computation: delay_cycles = ball_x / 3
; For ball_x=78: delay = 26 NOPs
; Computed dynamically in VBLANK.
RESBL_BASE_CYCLE = 26          ; cycles after WSYNC before RESBL (without NOPs)

; Frame structure
FRAME_SCANLINES  = 262
VBLANK_LINES     = 64
KERNEL_LINES     = 185
OVERSCAN_LINES   = 10
VBLANK_TIMER     = 77

; Colors
BALL_COLOR       = $0E         ; white (NTSC)
PLAYER1_COLOR    = $46         ; red
PLAYER2_COLOR    = $84         ; blue
BACKGR_COLOR     = $00         ; black
MISSILE_COLOR    = $0E         ; white

; Player dimensions
PLAYER_HEIGHT    = 18
PADDLE_BITS      = %00111100

; Missile dimensions
MISSILE_HEIGHT   = 4
MISSILE_ENABLE   = %00000010

; ---------------------------------------------------------------------------
; RAM
; ---------------------------------------------------------------------------
    SEG.U VARS
    ORG $80

; Game state
ball_x          DS 1
ball_y          DS 1
ball_dx         DS 1
ball_dy         DS 1
P0Y             DS 1
P1Y             DS 1
m0_y            DS 1
m1_y            DS 1
m_active        DS 1

; Frame counter (for position sweep)
frame_lo        DS 1
frame_hi        DS 1

; Orb mini-loop state
orb_delay       DS 1           ; computed RESBL delay (NOP count)
orb_row_idx     DS 1           ; countdown: ORB_ROWS..0

; Event table (minimal: dummy + marker = 10 bytes)
evTbl           DS 10

; Builder scratch
tblLen          DS 1

; Kernel state
evCnt           DS 1
nullDelta       DS 1

; Temporary
temp1           DS 1

; ---------------------------------------------------------------------------
; Code
; ---------------------------------------------------------------------------
    SEG CODE
    ORG $F000

Reset:
    SEI
    CLD
    LDX #$FF
    TXS

    ; ---- clear TIA registers ----
    LDA #0
    LDX $80
.clearTia:
    STA 0,X
    INX
    BNE .clearTia

    ; ---- clear RAM ----
    LDX #$80
.clearRam:
    STA 0,X
    INX
    BNE .clearRam

    ; ---- initialize game state ----
    LDA #78
    STA ball_x
    LDA #95
    STA ball_y
    LDA #1
    STA ball_dx
    LDA #1
    STA ball_dy

    LDA #48
    STA P0Y
    LDA #128
    STA P1Y
    LDA #88
    STA m0_y
    LDA #88
    STA m1_y
    LDA #0
    STA m_active

    LDA #0
    STA frame_lo
    STA frame_hi

    ; ---- initialize orb delay for starting position ----
    JSR ComputeOrbDelay

    ; ---- initialize minimal event table ----
    JSR InitEventTable

    ; ====================================================================
    ; Main loop (each iteration = one frame)
    ; ====================================================================
MainLoop:
StartOfFrame:
    ; ---- VSYNC ----
    LDA #2
    STA VSYNC
    STA WSYNC
    STA WSYNC
    STA WSYNC
    LDA #0
    STA VSYNC

    ; ---- VBLANK ----
    LDA #VBLANK_TIMER
    STA TIM64T

    ; ---- Ball movement (simple bounce) ----
    LDA ball_x
    CLC
    ADC ball_dx
    STA ball_x

    ; Check bounds [0, 156]
    LDA ball_dx
    BMI .checkLeft
.checkRight:
    LDA ball_x
    CMP #157
    BCC .moveY
    LDA #156
    STA ball_x
    LDA #$FF
    STA ball_dx
    JMP .moveY
.checkLeft:
    LDA ball_x
    CMP #0
    BCS .moveY
    LDA #0
    STA ball_x
    LDA #1
    STA ball_dx
.moveY:
    LDA ball_y
    CLC
    ADC ball_dy
    STA ball_y

    LDA ball_dy
    BMI .checkUp
.checkDown:
    LDA ball_y
    CMP #(KERNEL_LINES - ORB_HEIGHT + 1)
    BCC .moveDone
    LDA #(KERNEL_LINES - ORB_HEIGHT)
    STA ball_y
    LDA #$FF
    STA ball_dy
    JMP .moveDone
.checkUp:
    LDA ball_y
    CMP #0
    BCS .moveDone
    LDA #0
    STA ball_y
    LDA #1
    STA ball_dy
.moveDone:

    ; ---- Compute orb RESBL delay from ball_x ----
    JSR ComputeOrbDelay

    ; ---- Re-init event table (minimal: empty, just marker) ----
    JSR InitEventTable

    ; ---- Wait for VBLANK timer ----
.waitVblank:
    LDA INTIM
    BNE .waitVblank
    STA WSYNC

    ; ====================================================================
    ; Visible kernel
    ; ====================================================================
    ; Initialize kernel state
    LDA nullDelta
    STA evCnt
    LDY #5

KernelLoop:
    STA WSYNC

    ; ---- Apply the last-decoded entry's writes directly from the table ----
    LDX evTbl-4,Y           ; reg1
    LDA evTbl-3,Y           ; val1
    STA EV_WRITE_BASE,X     ; write 1
    LDX evTbl-2,Y           ; reg2 (0 = single: benign write)
    LDA evTbl-1,Y           ; val2
    STA EV_WRITE_BASE,X     ; write 2

    DEC evCnt
    BNE .applyOnly

    ; ---- Event line: load next delta and advance Y ----
    LDA evTbl,Y             ; this entry's delta
    STA evCnt
    CMP #$FF                ; marker?
    BEQ .kernelEnd

    TYA
    CLC
    ADC #5
    TAY
    JMP KernelLoop

.applyOnly:
    JMP KernelLoop

    ; ---- Kernel end ----
.kernelEnd:
    ; ---- Clear all TIA objects ----
    LDA #VBLANK_BLANK
    STA VBLANK
    LDA #0
    STA GRP0
    STA GRP1
    STA ENAM0
    STA ENAM1
    STA ENABL

    ; ---- Orb mini-loop (BALL_HEIGHT rows) ----
    ; Only runs if orb_row_idx > 0 (set by VBLANK when ball is visible)
    LDA orb_row_idx
    BEQ .orbDone

OrbLoop:
    STA WSYNC

    ; ---- Set ball width for this row (CTRLPF) ----
    LDX orb_row_idx
    LDA orb_width_tbl,X
    STA CTRLPF              ; write at cycle ~13

    ; ---- Enable/disable ball (ENABL) ----
    LDA orb_enabl_tbl,X
    STA ENABL               ; write at cycle ~20

    ; ---- NOP padding for RESBL timing ----
    ; RESBL must fire after the beam reaches ball_x
    ; For ball_x=78: beam reaches ~cycle 49, RESBL fires ~cycle 52
    ; For ball_x=0: beam reaches ~cycle 23, RESBL fires ~cycle 52
    ; The delay is computed in VBLANK (orb_delay = ball_x / 3)
    LDX orb_delay
.nopLoop:
    NOP                     ; 2 cycles each
    DEX
    BNE .nopLoop

    ; ---- Reposition ball (RESBL) ----
    STA RESBL               ; reset ball position counter

    ; ---- Count down ----
    DEC orb_row_idx
    BNE OrbLoop

.orbDone:
    ; ---- Restore CTRLPF default ----
    LDA #BALL_SIZE_CTRLPF
    STA CTRLPF

    ; ====================================================================
    ; Overscan (10 scanlines)
    ; ====================================================================
    LDX #OVERSCAN_LINES
.overscanLoop:
    STA WSYNC
    DEX
    BNE .overscanLoop

    JMP MainLoop

; =============================================================================
; ComputeOrbDelay
;
; Computes orb_delay = ball_x / 3 (integer division).
; This determines how many NOP cycles to insert before RESBL in the orb
; mini-loop, aligning the ball position with the beam.
;
; For ball_x=0: delay=0, RESBL fires at cycle 26, ball at x=0
; For ball_x=78: delay=26, RESBL fires at cycle 52, ball at x=78
; For ball_x=156: delay=52, RESBL fires at cycle 78, ball at x=156
; =============================================================================
ComputeOrbDelay:
    LDA ball_x
    LDX #0
.divLoop:
    CMP #3
    BCC .divDone
    SBC #3
    INX
    JMP .divLoop
.divDone:
    STX orb_delay
    RTS

; =============================================================================
; InitEventTable
;
; Initialize the event table to empty (just dummy + marker).
; The kernel will render KERNEL_LINES lines with no events (all benign writes).
; =============================================================================
InitEventTable:
    ; Dummy entry (offset 0): delta=$FF (back-scan sentinel), regs=0
    LDA #$FF
    STA evTbl
    LDA #0
    STA evTbl+1
    STA evTbl+2
    STA evTbl+3
    STA evTbl+4

    ; Marker entry (offset 5): delta=$FF, regs=0
    LDA #$FF
    STA evTbl+5
    LDA #0
    STA evTbl+6
    STA evTbl+7
    STA evTbl+8
    STA evTbl+9

    ; Kernel state
    LDA #0
    STA tblLen

    ; nullDelta = KERNEL_LINES (count straight to marker)
    LDA #KERNEL_LINES
    STA nullDelta

    RTS

; =============================================================================
; Data tables
; =============================================================================

; Orb width values for each row (index 1..4)
; Row 1 (top):    narrow (1px)
; Row 2 (middle): wide (4px)
; Row 3 (middle): wide (4px)
; Row 4 (bottom): narrow (1px)
orb_width_tbl:
    DC.B 0                         ; index 0 (unused)
    DC.B ORB_CTRLPF_NARROW         ; row 1: 1px
    DC.B ORB_CTRLPF_WIDE           ; row 2: 4px
    DC.B ORB_CTRLPF_WIDE           ; row 3: 4px
    DC.B ORB_CTRLPF_NARROW         ; row 4: 1px

; Orb enable values for each row (index 1..4)
orb_enabl_tbl:
    DC.B 0                         ; index 0 (unused)
    DC.B BALL_ENABLE_BIT           ; row 1: on
    DC.B BALL_ENABLE_BIT           ; row 2: on
    DC.B BALL_ENABLE_BIT           ; row 3: on
    DC.B BALL_ENABLE_BIT           ; row 4: on

; Player graphics (simple rectangle)
player_bits:
    DC.B PADDLE_BITS

; Missile graphics
missile_bits:
    DC.B MISSILE_ENABLE

; ---------------------------------------------------------------------------
; Vectors
; ---------------------------------------------------------------------------
    ORG $FFFC
    DC.W Reset
    DC.W Reset
