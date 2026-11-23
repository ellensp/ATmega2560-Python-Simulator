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
