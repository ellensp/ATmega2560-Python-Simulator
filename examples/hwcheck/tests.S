; Hardware/simulator comparison tests for the ATmega2560.
; Each function returns its result in r24. No pins are driven as outputs.
#include <avr/io.h>
#define IO(x) _SFR_IO_ADDR(x)

.section .bss
.global isr_val, mark_b, mark_c, ord_t0, ord_t1, ord_t2
isr_val: .byte 0
mark_b:  .byte 0
mark_c:  .byte 0
ord_t0:  .byte 0
ord_t1:  .byte 0
ord_t2:  .byte 0

.section .text

; Timer1: normal mode, clk/1, TCNT1 = 0
t1_start:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, 1
  sts TCCR1B, r18
  ret

.macro MEAS_BEGIN name
.global \name
\name:
  rcall t1_start
  lds r24, TCNT1L
.endm

.macro MEAS_END
  lds r25, TCNT1L
  sub r25, r24
  mov r24, r25
  ret
.endm

.macro NOPS n
  .rept \n
  nop
  .endr
.endm

just_ret:
  ret

MEAS_BEGIN t_base
MEAS_END

MEAS_BEGIN t_nop
  nop
MEAS_END

MEAS_BEGIN t_rcall_ret
  rcall just_ret
MEAS_END

MEAS_BEGIN t_call_ret
  call just_ret
MEAS_END

.global t_icall_ret
t_icall_ret:
  ldi r30, pm_lo8(just_ret)
  ldi r31, pm_hi8(just_ret)
  rcall t1_start
  lds r24, TCNT1L
  icall
MEAS_END

.global t_eicall_ret
t_eicall_ret:
  out IO(EIND), r1
  ldi r30, pm_lo8(just_ret)
  ldi r31, pm_hi8(just_ret)
  rcall t1_start
  lds r24, TCNT1L
  eicall
MEAS_END

; Interrupt latency: TCNT1L sampled in the ISR minus the compare value.
.global t_irq_latency
t_irq_latency:
  rcall t1_start
  ldi r18, 40
  sts OCR1BH, r1
  sts OCR1BL, r18
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ldi r18, (1<<OCIE1B)
  sts TIMSK1, r18
  sei
  NOPS 60
  cli
  sts TIMSK1, r1
  lds r24, isr_val
  subi r24, 40
  ret

.global TIMER1_COMPB_vect
TIMER1_COMPB_vect:
  push r24
  lds r24, TCNT1L
  sts isr_val, r24
  pop r24
  reti

; Two interrupts pending at once (Timer3 COMPB and COMPC). Returns the number of
; main-program instructions run between the first RETI and the second entry.
.global t_reti_gap
t_reti_gap:
  push r20
  ldi r20, 0
  sts TCCR3B, r1
  sts TCCR3A, r1
  sts TCNT3H, r1
  sts TCNT3L, r1
  ldi r18, 40
  sts OCR3BH, r1
  sts OCR3BL, r18
  sts OCR3CH, r1
  sts OCR3CL, r18
  ldi r18, 0x2F
  out IO(TIFR3), r18
  ldi r18, (1<<OCIE3B)|(1<<OCIE3C)
  sts TIMSK3, r18
  ldi r18, 1
  sts TCCR3B, r18
  sei
  .rept 80
  inc r20
  .endr
  cli
  sts TIMSK3, r1
  sts TCCR3B, r1
  lds r24, mark_c
  lds r25, mark_b
  sub r24, r25
  pop r20
  ret

.global TIMER3_COMPB_vect
TIMER3_COMPB_vect:
  sts mark_b, r20
  reti

.global TIMER3_COMPC_vect
TIMER3_COMPC_vect:
  sts mark_c, r20
  reti

; Timer0/1/2 compare A all pending, then SEI: order of service in ord_t0/1/2.
.global t_prio
t_prio:
  push r20
  ldi r20, 0
  cli
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TCCR2B, r1
  sts TCCR2A, r1
  out IO(TCNT0), r1
  sts TCNT1H, r1
  sts TCNT1L, r1
  sts TCNT2, r1
  ldi r18, 5
  out IO(OCR0A), r18
  sts OCR1AH, r1
  sts OCR1AL, r18
  sts OCR2A, r18
  ldi r18, 1
  out IO(TCCR0B), r18
  sts TCCR1B, r18
  sts TCCR2B, r18
  NOPS 40
  out IO(TCCR0B), r1
  sts TCCR1B, r1
  sts TCCR2B, r1
  ldi r18, 2
  sts TIMSK0, r18
  sts TIMSK1, r18
  sts TIMSK2, r18
  sei
  NOPS 12
  cli
  sts TIMSK0, r1
  sts TIMSK1, r1
  sts TIMSK2, r1
  ldi r18, 0x2F
  out IO(TIFR0), r18
  out IO(TIFR1), r18
  out IO(TIFR2), r18
  pop r20
  ret

.global TIMER0_COMPA_vect
TIMER0_COMPA_vect:
  inc r20
  sts ord_t0, r20
  reti
.global TIMER1_COMPA_vect
TIMER1_COMPA_vect:
  inc r20
  sts ord_t1, r20
  reti
.global TIMER2_COMPA_vect
TIMER2_COMPA_vect:
  inc r20
  sts ord_t2, r20
  reti

; Timer0 flags TOV0, OCF0A, OCF0B all set, timer stopped.
tifr0_all:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  ldi r18, 10
  out IO(OCR0A), r18
  ldi r18, 20
  out IO(OCR0B), r18
  out IO(TCNT0), r1
  ldi r18, 1
  out IO(TCCR0B), r18
  ldi r18, 200
1: dec r18
  brne 1b
  out IO(TCCR0B), r1
  ret

.global t_tifr_before
t_tifr_before:
  rcall tifr0_all
  in r24, IO(TIFR0)
  ldi r18, 7
  out IO(TIFR0), r18
  ret

.global t_tifr_sbi
t_tifr_sbi:
  rcall tifr0_all
  sbi IO(TIFR0), OCF0A
  in r24, IO(TIFR0)
  ldi r18, 7
  out IO(TIFR0), r18
  ret

.global t_tifr_cbi
t_tifr_cbi:
  rcall tifr0_all
  cbi IO(TIFR0), OCF0A
  in r24, IO(TIFR0)
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; Timer0 CTC, OCR0A = 9: TCNT0 after 3*n+1 cycles (n in r24).
.global t_ctc0
t_ctc0:
  out IO(TCCR0B), r1
  ldi r18, (1<<WGM01)
  out IO(TCCR0A), r18
  ldi r18, 9
  out IO(OCR0A), r18
  out IO(TCNT0), r1
  ldi r18, 1
  out IO(TCCR0B), r18
1: dec r24
  brne 1b
  out IO(TCCR0B), r1
  in r24, IO(TCNT0)
  out IO(TCCR0A), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; Timer1 CTC (mode 4), OCR1A = 99: TCNT1L after the same delay.
.global t_ctc1
t_ctc1:
  sts TCCR1B, r1
  sts TCCR1A, r1
  ldi r18, 99
  sts OCR1AH, r1
  sts OCR1AL, r18
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, (1<<WGM12)|1
  sts TCCR1B, r18
1: dec r24
  brne 1b
  sts TCCR1B, r1
  lds r24, TCNT1L
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ret

; SPI master, f/4: polls of SPSR (5 cycles each) until SPIF.
.global t_spi
t_spi:
  sbi IO(PORTB), 0
  NOPS 200            ; let the SS pull-up rise, or SPE clears MSTR
  ldi r18, (1<<SPE)|(1<<MSTR)
  out IO(SPCR), r18
  out IO(SPSR), r1
  in r18, IO(SPSR)
  in r18, IO(SPDR)
  ldi r24, 0
  ldi r18, 0xA5
  out IO(SPDR), r18
1: inc r24
  breq 2f
  in r18, IO(SPSR)
  sbrs r18, SPIF
  rjmp 1b
2: in r18, IO(SPDR)
  out IO(SPCR), r1
  cbi IO(PORTB), 0
  ret

; 16-bit TEMP register: TCNT1 = 0, write TCNT1H = 0x12 only, read L then H.
.global t_temp
t_temp:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, 0x12
  sts TCNT1H, r18
  lds r18, TCNT1L
  lds r24, TCNT1H
  sts TCNT1H, r1
  sts TCNT1L, r1
  ret

; SREG C,Z after FMUL / FMULS / FMULSU of r24 * r22.
.macro FM name, op
.global \name
\name:
  push r16
  push r17
  mov r16, r24
  mov r17, r22
  clc
  \op r16, r17
  in r24, IO(SREG)
  andi r24, 3
  clr r1
  pop r17
  pop r16
  ret
.endm
FM t_fmul, fmul
FM t_fmuls, fmuls
FM t_fmulsu, fmulsu

; SBI / CBI on PINA (DDRA = 0, so only the pull-ups change).
.global t_pin_sbi
t_pin_sbi:
  ldi r18, 0x06
  out IO(PORTA), r18
  sbi IO(PINA), 0
  in r24, IO(PORTA)
  out IO(PORTA), r1
  ret

.global t_pin_cbi
t_pin_cbi:
  ldi r18, 0x07
  out IO(PORTA), r18
  cbi IO(PINA), 1
  in r24, IO(PORTA)
  out IO(PORTA), r1
  ret

; SREG and the register file read through data-space addresses.
.global t_sreg_mem
t_sreg_mem:
  sec
  lds r24, 0x005F
  andi r24, 1
  clc
  ret

.global t_reg_mem
t_reg_mem:
  ldi r19, 0x5A
  lds r24, 0x0013
  ret

; ---- second batch ----

; TCNT1L read by the instruction right after the one that starts Timer1.
.global t_start_read1
t_start_read1:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, 1
  sts TCCR1B, r18
  lds r24, TCNT1L
  sts TCCR1B, r1
  ret

.global t_start_read0
t_start_read0:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r18, 1
  out IO(TCCR0B), r18
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; Timer1 running clk/1 with OCF1B already set, interrupts off.
irq_pending:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, 5
  sts OCR1BH, r1
  sts OCR1BL, r18
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ldi r18, 1
  sts TCCR1B, r18
  NOPS 20
  ret

; Flag pending and unmasked, then SEI: ISR sample minus a sample taken just before SEI.
.global t_irq_sei
t_irq_sei:
  rcall irq_pending
  ldi r18, (1<<OCIE1B)
  sts TIMSK1, r18
  lds r25, TCNT1L
  sei
  NOPS 20
  cli
  sts TIMSK1, r1
  lds r24, isr_val
  sub r24, r25
  ret

; Flag pending, I set, then unmask with STS TIMSK1.
.global t_irq_mask
t_irq_mask:
  rcall irq_pending
  ldi r18, (1<<OCIE1B)
  sei
  nop
  lds r25, TCNT1L
  sts TIMSK1, r18
  NOPS 20
  cli
  sts TIMSK1, r1
  lds r24, isr_val
  sub r24, r25
  ret

; ADIF after the ADC interrupt has run.
.global t_adif
t_adif:
  ldi r18, (1<<REFS0)
  sts ADMUX, r18
  ldi r18, (1<<ADEN)|(1<<ADSC)|(1<<ADIE)|4
  sts ADCSRA, r18
  sei
  ldi r18, 250
1: dec r18
  brne 1b
  cli
  lds r24, ADCSRA
  andi r24, (1<<ADIF)
  ldi r18, (1<<ADIF)
  sts ADCSRA, r18
  ret
.global ADC_vect
ADC_vect:
  push r24
  lds r24, isr16
  sts isr16b, r24
  lds r24, isr16+1
  sts isr16b+1, r24
  lds r24, TCNT1L
  sts isr16, r24
  lds r24, TCNT1H
  sts isr16+1, r24
  pop r24
  reti

; SPIF after the SPI interrupt has run.
.global t_spif
t_spif:
  sbi IO(PORTB), 0
  NOPS 200
  ldi r18, (1<<SPE)|(1<<MSTR)|(1<<SPIE)
  out IO(SPCR), r18
  out IO(SPSR), r1
  in r18, IO(SPSR)
  in r18, IO(SPDR)
  sei
  ldi r18, 0xA5
  out IO(SPDR), r18
  NOPS 80
  cli
  in r24, IO(SPSR)
  andi r24, (1<<SPIF)
  in r18, IO(SPDR)
  out IO(SPCR), r1
  cbi IO(PORTB), 0
  ret
.global SPI_STC_vect
SPI_STC_vect:
  reti

; TXC0 after the USART0 TX-complete interrupt has run (sends one newline).
.global t_txc
t_txc:
  lds r18, UCSR0B
  ori r18, (1<<TXCIE0)
  sts UCSR0B, r18
  ldi r18, 0x0A
  sts UDR0, r18
  sei
  ldi r19, 12
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  cli
  lds r24, UCSR0A
  andi r24, (1<<TXC0)
  lds r18, UCSR0B
  andi r18, ~(1<<TXCIE0)
  sts UCSR0B, r18
  ret
.global USART0_TX_vect
USART0_TX_vect:
  push r24
  lds r24, TCNT1L
  sts isr16, r24
  lds r24, TCNT1H
  sts isr16+1, r24
  pop r24
  reti

; Interrupt latency with a sled of 2-cycle instructions; compare value in r24.
.global t_irq_lat2
t_irq_lat2:
  mov r19, r24
  rcall t1_start
  sts OCR1BH, r1
  sts OCR1BL, r19
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ldi r18, (1<<OCIE1B)
  sts TIMSK1, r18
  sei
  .rept 40
  rjmp .+0
  .endr
  cli
  sts TIMSK1, r1
  lds r24, isr_val
  sub r24, r19
  ret

; Same with a sled of 3-cycle instructions (jmp to the next address).
.global t_irq_lat3
t_irq_lat3:
  mov r19, r24
  rcall t1_start
  sts OCR1BH, r1
  sts OCR1BL, r19
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ldi r18, (1<<OCIE1B)
  sts TIMSK1, r18
  sei
  .rept 30
  jmp 1f
1:
  .endr
  cli
  sts TIMSK1, r1
  lds r24, isr_val
  sub r24, r19
  ret

; ---- third batch ----
.section .bss
.global last_tifr, isr16
last_tifr: .byte 0
isr16:     .byte 0, 0
.section .text

; Idle sleep woken by Timer1 compare B: ISR sample minus the compare value.
.global t_sleep_idle
t_sleep_idle:
  call t1_start
  ldi r18, 40
  sts OCR1BH, r1
  sts OCR1BL, r18
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ldi r18, (1<<OCIE1B)
  sts TIMSK1, r18
  ldi r18, (1<<SE)
  out IO(SMCR), r18
  sei
  sleep
  NOPS 8
  cli
  out IO(SMCR), r1
  sts TIMSK1, r1
  lds r24, isr_val
  subi r24, 40
  ret

; SLEEP with SE clear: cycles.
MEAS_BEGIN t_sleep_nose
  sleep
MEAS_END

; Timer1 in a given mode: r24 = TCCR1A, r22 = TCCR1B mode bits, r20 = TOP (ICR1 and OCR1A),
; r18 = delay loops. OCR1B = 20. Returns TCNT1L after the delay; TIFR1 goes to last_tifr.
.global t_t1mode
t_t1mode:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  sts OCR1AH, r1
  sts OCR1AL, r20
  ldi r19, 20
  sts OCR1BH, r1
  sts OCR1BL, r19
  sts TCCR1A, r24
  sts TCCR1B, r22
  sts ICR1H, r1
  sts ICR1L, r20
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r19, 0x2F
  out IO(TIFR1), r19
  ori r22, 1
  sts TCCR1B, r22
1: dec r18
  brne 1b
  sts TCCR1B, r1
  lds r24, TCNT1L
  lds r25, TCNT1H
  in r19, IO(TIFR1)
  sts last_tifr, r19
  sts TCCR1A, r1
  ldi r19, 0x2F
  out IO(TIFR1), r19
  ret

; ICR1L read back after a write in normal mode (0x55 written).
.global t_icr_normal
t_icr_normal:
  sts TCCR1B, r1
  sts TCCR1A, r1
  ldi r18, 0x55
  sts ICR1H, r1
  sts ICR1L, r18
  lds r24, ICR1L
  lds r25, ICR1H
  ret

; Interrupt latency of compare B in 8-bit phase-correct PWM (mode 1), counting up.
.global t_irq_lat_pc
t_irq_lat_pc:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  ldi r18, 40
  sts OCR1BH, r1
  sts OCR1BL, r18
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, (1<<WGM10)
  sts TCCR1A, r18
  ldi r18, 0x2F
  out IO(TIFR1), r18
  ldi r18, (1<<OCIE1B)
  sts TIMSK1, r18
  ldi r18, 1
  sts TCCR1B, r18
  sei
  NOPS 60
  cli
  sts TIMSK1, r1
  sts TCCR1B, r1
  sts TCCR1A, r1
  lds r24, isr_val
  subi r24, 40
  ret

; Prescaler reset (GTCCR.PSRSYNC), r24 = 0..8 cycles later start Timer0 at clk/8,
; read TCNT0 after 20 more cycles.
.global t_presc
t_presc:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(presc_sled_end)
  ldi r31, pm_hi8(presc_sled_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<PSRSYNC)
  ldi r19, 2
  out IO(GTCCR), r18
  ijmp
  NOPS 8
presc_sled_end:
  out IO(TCCR0B), r19
  NOPS 20
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; EEPROM read strobe: cycles of SBI EECR,EERE.
.global t_eere
t_eere:
  ldi r18, 0x0F
  out IO(EEARH), r18
  ldi r18, 0xFF
  out IO(EEARL), r18
  call t1_start
  lds r24, TCNT1L
  sbi IO(EECR), EERE
MEAS_END

; EEPROM write of 0xA5 to the last cell: cycles of SBI EEMPE + SBI EEPE.
.global t_eepe
t_eepe:
  ldi r18, 0x0F
  out IO(EEARH), r18
  ldi r18, 0xFF
  out IO(EEARL), r18
  ldi r18, 0xA5
  out IO(EEDR), r18
  out IO(EECR), r1
  call t1_start
  lds r24, TCNT1L
  sbi IO(EECR), EEMPE
  sbi IO(EECR), EEPE
  lds r25, TCNT1L
  sub r25, r24
  mov r24, r25
1: sbic IO(EECR), EEPE
  rjmp 1b
  ret

; EEDR after reading the cell back.
.global t_eeread_val
t_eeread_val:
  sbi IO(EECR), EERE
  in r24, IO(EEDR)
  ret

; SPIF sampled 3*n + k - 1 cycles after the SPDR write. r24 = SPCR, r22 = SPSR, r20 = n.
.macro SPI_DONE name, k
.global \name
\name:
  sbi IO(PORTB), 0
  NOPS 200
  out IO(SPCR), r24
  out IO(SPSR), r22
  in r19, IO(SPSR)
  in r19, IO(SPDR)
  ldi r19, 0xA5
  out IO(SPDR), r19
1: dec r20
  brne 1b
  NOPS \k
  in r24, IO(SPSR)
  andi r24, 0x80
2: in r19, IO(SPSR)
  sbrs r19, SPIF
  rjmp 2b
  in r19, IO(SPDR)
  out IO(SPCR), r1
  out IO(SPSR), r1
  cbi IO(PORTB), 0
  ret
.endm
SPI_DONE t_spi_done0, 0
SPI_DONE t_spi_done1, 1
SPI_DONE t_spi_done2, 2

; USART0: cycles from the UDR0 write to the TX-complete interrupt (sends a newline).
; r24 = delay loops before the write.
.global t_uart_frame
t_uart_frame:
  push r20
  mov r20, r24
  ldi r19, 16
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  lds r18, UCSR0A
  ori r18, (1<<TXC0)
  sts UCSR0A, r18
  call t1_start
  lds r18, UCSR0B
  ori r18, (1<<TXCIE0)
  sts UCSR0B, r18
3: dec r20
  brne 3b
  ldi r18, 0x0A
  sei
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts UDR0, r18
  ldi r19, 16
5: ldi r18, 250
4: dec r18
  brne 4b
  dec r19
  brne 5b
  cli
  lds r18, UCSR0B
  andi r18, ~(1<<TXCIE0)
  sts UCSR0B, r18
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  pop r20
  ret

; Like t_presc, but TCNT0 is read after 11 cycles (one clk/8 tick, or two if the
; prescaler phase is not tied to the timer start).
.global t_presc_b
t_presc_b:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(presc_b_end)
  ldi r31, pm_hi8(presc_b_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<PSRSYNC)
  ldi r19, 2
  out IO(GTCCR), r18
  ijmp
  NOPS 8
presc_b_end:
  out IO(TCCR0B), r19
  NOPS 11
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; The same without touching GTCCR: prescaler left free-running.
.global t_presc_c
t_presc_c:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(presc_c_end)
  ldi r31, pm_hi8(presc_c_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 2
  ijmp
  NOPS 8
presc_c_end:
  out IO(TCCR0B), r19
  NOPS 11
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; USART0 idle: cycles from the UDR0 write to the data-register-empty interrupt.
.global t_uart_udre
t_uart_udre:
  push r20
  mov r20, r24
  ldi r19, 16
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  call t1_start
3: dec r20
  brne 3b
  ldi r18, 0x0A
  lds r19, UCSR0B
  ori r19, (1<<UDRIE0)
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts UDR0, r18
  sts UCSR0B, r19
  sei
  NOPS 40
  cli
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  pop r20
  ret

.global USART0_UDRE_vect
USART0_UDRE_vect:
  push r24
  lds r24, TCNT1L
  sts isr16, r24
  lds r24, TCNT1H
  sts isr16+1, r24
  in r24, IO(SREG)
  push r24
  lds r24, UCSR0B
  andi r24, ~(1<<UDRIE0)
  sts UCSR0B, r24
  pop r24
  out IO(SREG), r24
  pop r24
  reti

; Like t_presc_b with 40 more cycles between the prescaler reset and the timer start.
.global t_presc_d
t_presc_d:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(presc_d_end)
  ldi r31, pm_hi8(presc_d_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<PSRSYNC)
  ldi r19, 2
  out IO(GTCCR), r18
  NOPS 40
  ijmp
  NOPS 8
presc_d_end:
  out IO(TCCR0B), r19
  NOPS 11
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; GTCCR read back right after writing PSRSYNC.
.global t_gtccr
t_gtccr:
  ldi r18, (1<<PSRSYNC)
  out IO(GTCCR), r18
  in r24, IO(GTCCR)
  ret

; Timer0 at clk/8 already running (prescaler free-running, all other timers stopped):
; stop it r24 cycles after a tick was seen, restart at once, read TCNT0 11 cycles later.
.global t_presc_e
t_presc_e:
  sts TCCR1B, r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(presc_e_end)
  ldi r31, pm_hi8(presc_e_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 2
  out IO(TCCR0B), r19
  in r18, IO(TCNT0)
1: in r25, IO(TCNT0)
  cp r25, r18
  breq 1b
  ijmp
  NOPS 8
presc_e_end:
  out IO(TCCR0B), r1
  out IO(TCNT0), r1
  out IO(TCCR0B), r19
  NOPS 11
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; Like t_uart_frame, with exactly r24 (0..47) extra cycles before the UDR0 write
; and a fixed length otherwise.
.global t_uart_frame2
t_uart_frame2:
  ldi r30, pm_lo8(uf2_sled_end)
  ldi r31, pm_hi8(uf2_sled_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 16
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  lds r18, UCSR0A
  ori r18, (1<<TXC0)
  sts UCSR0A, r18
  call t1_start
  lds r18, UCSR0B
  ori r18, (1<<TXCIE0)
  sts UCSR0B, r18
  ldi r18, 0x0A
  sei
  ijmp
  NOPS 48
uf2_sled_end:
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts UDR0, r18
  ldi r19, 16
5: ldi r18, 250
4: dec r18
  brne 4b
  dec r19
  brne 5b
  cli
  lds r18, UCSR0B
  andi r18, ~(1<<TXCIE0)
  sts UCSR0B, r18
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  ret

; Two bytes written back to back: cycles from the first UDR0 write to the
; data-register-empty interrupt (when the second byte moves to the shift register).
; r24 = 0..47 extra cycles before the first write.
.global t_uart_udre2
t_uart_udre2:
  ldi r30, pm_lo8(uq_sled_end)
  ldi r31, pm_hi8(uq_sled_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 16
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  call t1_start
  ldi r18, 0x0A
  lds r19, UCSR0B
  ori r19, (1<<UDRIE0)
  ijmp
  NOPS 48
uq_sled_end:
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts UDR0, r18
  sts UDR0, r18
  sts UCSR0B, r19
  sei
  ldi r19, 16
5: ldi r18, 250
4: dec r18
  brne 4b
  dec r19
  brne 5b
  cli
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  ret

; Prescaler reset, Timer0 started at clk/8, TCNT0 read r24 (0..47) cycles later.
.global t_presc_f
t_presc_f:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(pf_end)
  ldi r31, pm_hi8(pf_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<PSRSYNC)
  ldi r19, 2
  out IO(GTCCR), r18
  out IO(TCCR0B), r19
  ijmp
  NOPS 48
pf_end:
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; The same, then 20 cycles later stop, clear TCNT0 and restart; TCNT0 read r24 cycles
; after the restart.
.global t_presc_h
t_presc_h:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  ldi r30, pm_lo8(ph_end)
  ldi r31, pm_hi8(ph_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<PSRSYNC)
  ldi r19, 2
  out IO(GTCCR), r18
  out IO(TCCR0B), r19
  NOPS 20
  out IO(TCCR0B), r1
  out IO(TCNT0), r1
  out IO(TCCR0B), r19
  ijmp
  NOPS 48
ph_end:
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; Prescaler reset with all timers stopped, r24 (0..47) cycles later start Timer0 at
; clk/8 and read TCNT0 12 cycles after that.
.global t_presc_i
t_presc_i:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TCNT0), r1
  sts TCCR1B, r1
  ldi r30, pm_lo8(pi_end)
  ldi r31, pm_hi8(pi_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<PSRSYNC)
  ldi r19, 2
  out IO(GTCCR), r18
  ijmp
  NOPS 48
pi_end:
  out IO(TCCR0B), r19
  NOPS 12
  in r24, IO(TCNT0)
  out IO(TCCR0B), r1
  ldi r18, 7
  out IO(TIFR0), r18
  ret

; Two bytes written back to back: cycles from the first UDR0 write to the
; TX-complete interrupt after the second frame. r24 = 0..47 extra cycles.
.global t_uart_txc2
t_uart_txc2:
  ldi r30, pm_lo8(ut_sled_end)
  ldi r31, pm_hi8(ut_sled_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 16
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  lds r18, UCSR0A
  ori r18, (1<<TXC0)
  sts UCSR0A, r18
  call t1_start
  lds r18, UCSR0B
  ori r18, (1<<TXCIE0)
  sts UCSR0B, r18
  ldi r18, 0x0A
  sei
  ijmp
  NOPS 48
ut_sled_end:
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts UDR0, r18
  sts UDR0, r18
  ldi r19, 16
5: ldi r18, 250
4: dec r18
  brne 4b
  dec r19
  brne 5b
  cli
  lds r18, UCSR0B
  andi r18, ~(1<<TXCIE0)
  sts UCSR0B, r18
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  ret

; r22 bytes sent with a polling loop (wait for UDRE, write UDR0), starting idle with
; r24 (0..47) extra cycles of delay: cycles from just before the first write to the
; end of the last one.
.global t_uart_putn
t_uart_putn:
  ldi r30, pm_lo8(up_sled_end)
  ldi r31, pm_hi8(up_sled_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 16
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  call t1_start
  ldi r18, 0x0A
  ijmp
  NOPS 48
up_sled_end:
  lds r24, TCNT1L
  lds r25, TCNT1H
3: lds r19, UCSR0A
  sbrs r19, UDRE0
  rjmp 3b
  sts UDR0, r18
  dec r22
  brne 3b
  lds r18, TCNT1L
  lds r19, TCNT1H
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  ret

; ---- fourth batch ----
.section .bss
.global ocr_res, isr16b, twi_time, twi_status
ocr_res:    .byte 0, 0, 0
isr16b:     .byte 0, 0
twi_time:   .byte 0, 0, 0, 0
twi_status: .byte 0, 0
.section .text

; OCR1B written while Timer1 runs in the given mode: r24 = TCCR1A, r22 = TCCR1B mode
; bits, r20 = TOP (ICR1 and OCR1A). OCR1B is 80 before the start and 20 is written
; about 6 clocks after it. TIFR1 is sampled about 46, 140 and 250 clocks after the
; start (flags cleared at about 92) into ocr_res.
.global t_ocrbuf
t_ocrbuf:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  sts OCR1AH, r1
  sts OCR1AL, r20
  ldi r19, 80
  sts OCR1BH, r1
  sts OCR1BL, r19
  sts TCCR1A, r24
  sts TCCR1B, r22
  sts ICR1H, r1
  sts ICR1L, r20
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r19, 0x2F
  out IO(TIFR1), r19
  ldi r18, 20
  ori r22, 1
  sts TCCR1B, r22
  sts OCR1BH, r1
  sts OCR1BL, r18
  NOPS 40
  in r18, IO(TIFR1)
  sts ocr_res, r18
  NOPS 44
  out IO(TIFR1), r19
  NOPS 48
  in r18, IO(TIFR1)
  sts ocr_res+1, r18
  NOPS 100
  in r18, IO(TIFR1)
  sts ocr_res+2, r18
  sts TCCR1B, r1
  sts TCCR1A, r1
  out IO(TIFR1), r19
  ret

; OCR1A as TOP rewritten while running: r24 = TCCR1A, r22 = TCCR1B mode bits.
; OCR1A is 99 at the start and 49 is written about 6 clocks later; returns TCNT1L
; after 100 delay loops.
.global t_topbuf
t_topbuf:
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  ldi r19, 99
  sts OCR1AH, r1
  sts OCR1AL, r19
  sts TCCR1A, r24
  sts TCCR1B, r22
  sts TCNT1H, r1
  sts TCNT1L, r1
  ldi r18, 49
  ori r22, 1
  sts TCCR1B, r22
  sts OCR1AH, r1
  sts OCR1AL, r18
  ldi r18, 100
1: dec r18
  brne 1b
  sts TCCR1B, r1
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts TCCR1A, r1
  ldi r19, 0x2F
  out IO(TIFR1), r19
  ret

; Timer0 in mode r24 (TCCR0A) / r22 (TCCR0B mode bits): OCR0B is 80 before the start
; and 20 is written 2 clocks after it; returns TIFR0 about 44 clocks after the start.
.global t_ocrbuf0
t_ocrbuf0:
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  ldi r19, 200
  out IO(OCR0A), r19
  ldi r19, 80
  out IO(OCR0B), r19
  out IO(TCCR0A), r24
  out IO(TCCR0B), r22
  out IO(TCNT0), r1
  ldi r19, 7
  out IO(TIFR0), r19
  ldi r18, 20
  ori r22, 1
  out IO(TCCR0B), r22
  out IO(OCR0B), r18
  NOPS 42
  in r24, IO(TIFR0)
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(TIFR0), r19
  ret

; ADC at clk/16: cycles from the write that starts a conversion to its interrupt.
; r24 = 0..47 extra cycles between enabling the ADC and starting; r22 = 0 for the
; first conversion after enabling, 1 to measure a second one.
.global t_adc_time
t_adc_time:
  ldi r30, pm_lo8(adc_sled_end)
  ldi r31, pm_hi8(adc_sled_end)
  sub r30, r24
  sbc r31, r1
  ldi r18, (1<<REFS0)
  sts ADMUX, r18
  sts ADCSRB, r1
  sts ADCSRA, r1
  call t1_start
  ldi r18, (1<<ADEN)|4
  sts ADCSRA, r18
  tst r22
  breq 2f
  ldi r18, (1<<ADEN)|(1<<ADSC)|4
  sts ADCSRA, r18
1: lds r18, ADCSRA
  sbrc r18, ADSC
  rjmp 1b
  ldi r18, (1<<ADEN)|(1<<ADIF)|4
  sts ADCSRA, r18
2: ldi r18, (1<<ADEN)|(1<<ADSC)|(1<<ADIE)|4
  sei
  ijmp
  NOPS 48
adc_sled_end:
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts ADCSRA, r18
  ldi r18, 250
3: dec r18
  brne 3b
  cli
  sts ADCSRA, r1
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  movw r24, r18
  ret

; Free-running ADC at clk/16: cycles between two consecutive conversion interrupts.
.global t_adc_free
t_adc_free:
  ldi r18, (1<<REFS0)
  sts ADMUX, r18
  sts ADCSRB, r1
  sts ADCSRA, r1
  call t1_start
  ldi r18, (1<<ADEN)|(1<<ADSC)|(1<<ADATE)|(1<<ADIE)|4
  sts ADCSRA, r18
  sei
  ldi r19, 2
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  cli
  sts ADCSRA, r1
  lds r24, isr16
  lds r25, isr16+1
  lds r18, isr16b
  lds r19, isr16b+1
  sub r24, r18
  sbc r25, r19
  ret

; TWI master with nothing on the bus but the pull-ups: START, then SLA+W for 0x28.
; r24 = TWBR. Cycles of each go to twi_time, TWSR after each to twi_status.
.global t_twi
t_twi:
  sts TWSR, r1
  sts TWBR, r24
  call t1_start
  ldi r18, (1<<TWINT)|(1<<TWSTA)|(1<<TWEN)|(1<<TWIE)
  sei
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts TWCR, r18
  ldi r19, 4
2: ldi r18, 250
1: dec r18
  brne 1b
  dec r19
  brne 2b
  cli
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  sts twi_time, r18
  sts twi_time+1, r19
  lds r18, TWSR
  sts twi_status, r18
  ldi r18, 0x50
  sts TWDR, r18
  call t1_start
  ldi r18, (1<<TWINT)|(1<<TWEN)|(1<<TWIE)
  sei
  lds r24, TCNT1L
  lds r25, TCNT1H
  sts TWCR, r18
  ldi r19, 20
4: ldi r18, 250
3: dec r18
  brne 3b
  dec r19
  brne 4b
  cli
  lds r18, isr16
  lds r19, isr16+1
  sub r18, r24
  sbc r19, r25
  sts twi_time+2, r18
  sts twi_time+3, r19
  lds r18, TWSR
  sts twi_status+1, r18
  ldi r18, (1<<TWINT)|(1<<TWSTO)|(1<<TWEN)
  sts TWCR, r18
  NOPS 40
  sts TWCR, r1
  ret

.global TWI_vect
TWI_vect:
  push r24
  lds r24, TCNT1L
  sts isr16, r24
  lds r24, TCNT1H
  sts isr16+1, r24
  ldi r24, (1<<TWEN)
  sts TWCR, r24
  pop r24
  reti

; ---- fifth batch: compare outputs on PB7 (OC0A / OC1C, the board's LED pin) ----

; PINB7 read r24 (0..47) cycles after PORTB7 is set (PB7 driven as an output).
.global t_pinlat
t_pinlat:
  ldi r30, pm_lo8(pl_end)
  ldi r31, pm_hi8(pl_end)
  sub r30, r24
  sbc r31, r1
  cbi IO(PORTB), 7
  sbi IO(DDRB), 7
  NOPS 4
  sbi IO(PORTB), 7
  ijmp
  NOPS 48
pl_end:
  in r24, IO(PINB)
  cbi IO(PORTB), 7
  cbi IO(DDRB), 7
  andi r24, 0x80
  ret

; OC1C on PB7. r24 = TCCR1A (COM1C and WGM bits), r22 = TCCR1B mode bits, r20 = TOP
; (ICR1), r18 = OCR1C, r16 = cycles (0..47) from the start to the PINB read.
; PORTB7 is 0 unless bit 7 of r16 is set.
.global t_oc1c
t_oc1c:
  mov r19, r16
  andi r19, 0x7F
  ldi r30, pm_lo8(oc1_end)
  ldi r31, pm_hi8(oc1_end)
  sub r30, r19
  sbc r31, r1
  sts TCCR1B, r1
  sts TCCR1A, r1
  sts TIMSK1, r1
  sts OCR1CH, r1
  sts OCR1CL, r18
  cbi IO(PORTB), 7
  sbrc r16, 7
  sbi IO(PORTB), 7
  sbi IO(DDRB), 7
  sts TCCR1A, r24
  sts TCCR1B, r22
  sts ICR1H, r1
  sts ICR1L, r20
  sts TCNT1H, r1
  sts TCNT1L, r1
  ori r22, 1
  sts TCCR1B, r22
  ijmp
  NOPS 48
oc1_end:
  in r24, IO(PINB)
  sts TCCR1B, r1
  sts TCCR1A, r1
  cbi IO(PORTB), 7
  cbi IO(DDRB), 7
  ldi r19, 0x2F
  out IO(TIFR1), r19
  andi r24, 0x80
  ret

; OC0A on PB7. r24 = TCCR0A, r22 = TCCR0B mode bits, r20 = OCR0A, r18 = cycles to the read.
.global t_oc0a
t_oc0a:
  ldi r30, pm_lo8(oc0_end)
  ldi r31, pm_hi8(oc0_end)
  sub r30, r18
  sbc r31, r1
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  out IO(OCR0A), r20
  cbi IO(PORTB), 7
  sbi IO(DDRB), 7
  out IO(TCCR0A), r24
  out IO(TCCR0B), r22
  out IO(TCNT0), r1
  ori r22, 1
  out IO(TCCR0B), r22
  ijmp
  NOPS 48
oc0_end:
  in r24, IO(PINB)
  out IO(TCCR0B), r1
  out IO(TCCR0A), r1
  cbi IO(DDRB), 7
  ldi r19, 7
  out IO(TIFR0), r19
  andi r24, 0x80
  ret

; OC0A (CTC toggle, OCR0A = 5) and OC1C (CTC toggle, ICR1 = 20, OCR1C = 6) both on
; PB7. r24 = PORTB7 level (selects how the two are combined), r22 = cycles to the read.
.global t_ocmod
t_ocmod:
  ldi r30, pm_lo8(ocm_end)
  ldi r31, pm_hi8(ocm_end)
  sub r30, r22
  sbc r31, r1
  out IO(TCCR0B), r1
  sts TCCR1B, r1
  ldi r19, 5
  out IO(OCR0A), r19
  ldi r19, 6
  sts OCR1CH, r1
  sts OCR1CL, r19
  cbi IO(PORTB), 7
  sbrc r24, 0
  sbi IO(PORTB), 7
  sbi IO(DDRB), 7
  ldi r19, 0x42
  out IO(TCCR0A), r19
  ldi r19, 0x04
  sts TCCR1A, r19
  ldi r19, 0x18
  sts TCCR1B, r19
  ldi r19, 20
  sts ICR1H, r1
  sts ICR1L, r19
  sts TCNT1H, r1
  sts TCNT1L, r1
  out IO(TCNT0), r1
  ldi r18, 1
  ldi r19, 0x19
  out IO(TCCR0B), r18
  sts TCCR1B, r19
  ijmp
  NOPS 48
ocm_end:
  in r24, IO(PINB)
  out IO(TCCR0B), r1
  sts TCCR1B, r1
  out IO(TCCR0A), r1
  sts TCCR1A, r1
  cbi IO(PORTB), 7
  cbi IO(DDRB), 7
  ldi r19, 7
  out IO(TIFR0), r19
  ldi r19, 0x2F
  out IO(TIFR1), r19
  andi r24, 0x80
  ret

; Force output compare: OC1C in normal mode, toggle. Returns PINB7 before, after one
; FOC1C strobe and after a second one in bits 0, 1, 2; TIFR1 afterwards in bits 4-7.
.global t_foc
t_foc:
  sts TCCR1B, r1
  ldi r19, 0x04
  sts TCCR1A, r19
  cbi IO(PORTB), 7
  sbi IO(DDRB), 7
  ldi r19, 0x2F
  out IO(TIFR1), r19
  ldi r24, 0
  NOPS 3
  sbic IO(PINB), 7
  ori r24, 1
  ldi r19, 0x20
  sts TCCR1C, r19
  NOPS 3
  sbic IO(PINB), 7
  ori r24, 2
  sts TCCR1C, r19
  NOPS 3
  sbic IO(PINB), 7
  ori r24, 4
  in r19, IO(TIFR1)
  swap r19
  andi r19, 0xF0
  or r24, r19
  lds r19, TCCR1C
  sts ocr_res, r19
  sts TCCR1A, r1
  cbi IO(DDRB), 7
  ret

; Like t_pinlat, but PORTB7 is set with OUT (and r22 selects ST through a pointer).
.global t_pinlat_out
t_pinlat_out:
  ldi r30, pm_lo8(plo_end)
  ldi r31, pm_hi8(plo_end)
  sub r30, r24
  sbc r31, r1
  ldi r19, 0x80
  ldi r26, 0x25
  ldi r27, 0x00
  cbi IO(PORTB), 7
  sbi IO(DDRB), 7
  NOPS 4
  sbrc r22, 0
  rjmp 1f
  out IO(PORTB), r19
  ijmp
1: st X, r19
  ijmp
  NOPS 48
plo_end:
  in r24, IO(PINB)
  out IO(PORTB), r1
  cbi IO(DDRB), 7
  andi r24, 0x80
  ret

; PORTB7 cleared with CBI / OUT / ST after being high: same read sweep.
.global t_pinlat_clr
t_pinlat_clr:
  ldi r30, pm_lo8(plc_end)
  ldi r31, pm_hi8(plc_end)
  sub r30, r24
  sbc r31, r1
  sbi IO(PORTB), 7
  sbi IO(DDRB), 7
  NOPS 4
  cbi IO(PORTB), 7
  ijmp
  NOPS 48
plc_end:
  in r24, IO(PINB)
  cbi IO(DDRB), 7
  andi r24, 0x80
  ret

; PINB7 read straight after PORTB7 is set, with no instruction in between and with
; one NOP: bit 0 OUT+IN, bit 1 OUT+NOP+IN, bit 2 SBI+IN, bit 3 SBI+NOP+IN,
; bit 4 ST+IN, bit 5 ST+NOP+IN.
.global t_pinlat2
t_pinlat2:
  ldi r24, 0
  ldi r19, 0x80
  ldi r26, 0x25
  ldi r27, 0x00
  sbi IO(DDRB), 7
  out IO(PORTB), r1
  NOPS 4
  out IO(PORTB), r19
  in r18, IO(PINB)
  sbrc r18, 7
  ori r24, 1
  out IO(PORTB), r1
  NOPS 4
  out IO(PORTB), r19
  nop
  in r18, IO(PINB)
  sbrc r18, 7
  ori r24, 2
  out IO(PORTB), r1
  NOPS 4
  sbi IO(PORTB), 7
  in r18, IO(PINB)
  sbrc r18, 7
  ori r24, 4
  out IO(PORTB), r1
  NOPS 4
  sbi IO(PORTB), 7
  nop
  in r18, IO(PINB)
  sbrc r18, 7
  ori r24, 8
  out IO(PORTB), r1
  NOPS 4
  st X, r19
  in r18, IO(PINB)
  sbrc r18, 7
  ori r24, 16
  out IO(PORTB), r1
  NOPS 4
  st X, r19
  nop
  in r18, IO(PINB)
  sbrc r18, 7
  ori r24, 32
  out IO(PORTB), r1
  cbi IO(DDRB), 7
  ret
