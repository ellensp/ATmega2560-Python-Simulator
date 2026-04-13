/*
 * adc_poll.c — ATmega2560 ADC feature demonstration
 *
 * Exercises all 16 ADC channels and the three main ADC operating modes:
 *
 *   Section 1: Polled right-adjusted reads (10-bit result in ADC register)
 *              Channels 0-7  use ADMUX[MUX2:0] with ADCSRB.MUX5 = 0.
 *              Channels 8-15 use ADMUX[MUX2:0] with ADCSRB.MUX5 = 1.
 *
 *   Section 2: Polled left-adjusted reads (ADLAR=1, 8 MSBs in ADCH)
 *              Reports ADCH only; useful for 8-bit resolution applications.
 *
 *   Section 3: ISR-driven conversions (ADIE + ADC_vect)
 *              Enables the ADC interrupt, starts a conversion, and busy-waits
 *              on a volatile flag set inside the ISR.
 *
 * Output format (9600 8N1, UART0):
 *   === poll ch0-15 ===
 *   adc[00]=<value>          (right-adjusted, 0-1023)
 *   ...
 *   === left-adj ch0-15 ===
 *   adcL[00]=<ADCH>          (8 MSBs of result, 0-255)
 *   ...
 *   === isr ch0-15 ===
 *   adcI[00]=<value>         (right-adjusted, 0-1023)
 *   ...
 *   done
 */

#include <avr/interrupt.h>
#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

/* MUX5 is bit 3 of ADCSRB on ATmega2560.  Define locally so the file
 * compiles even if the header version differs. */
#ifndef MUX5
#define MUX5 3
#endif

/* ---- UART ---------------------------------------------------------------- */

static void uart0_init(void) {
    const uint16_t ubrr = (uint16_t)((F_CPU / (16UL * 9600UL)) - 1UL);
    UBRR0H = (uint8_t)(ubrr >> 8);
    UBRR0L = (uint8_t)(ubrr & 0xFFU);
    UCSR0A = 0;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

static void uart0_putc(char c) {
    while (!(UCSR0A & (1 << UDRE0))) {}
    UDR0 = (uint8_t)c;
}

static void uart0_puts(const char *s) {
    while (*s) uart0_putc(*s++);
}

static void uart0_puti(uint16_t v) {
    char buf[6];
    uint8_t i = 0;
    if (!v) { uart0_putc('0'); return; }
    while (v && i < (uint8_t)sizeof(buf)) {
        buf[i++] = (char)('0' + v % 10U);
        v /= 10U;
    }
    while (i) uart0_putc(buf[--i]);
}

/* Print a two-digit zero-padded decimal (0-15). */
static void uart0_put2d(uint8_t v) {
    uart0_putc((char)('0' + v / 10U));
    uart0_putc((char)('0' + v % 10U));
}

/* ---- ADC ----------------------------------------------------------------- */

static void adc_init(void) {
    /* AVcc reference, right-adjust, prescaler /128, ADC enabled. */
    ADCSRB = 0;
    ADMUX  = (1 << REFS0);
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);
}

/*
 * Select channel 0-15.  Channels 8-15 require MUX5=1 in ADCSRB.
 * Preserves REFS1:0 and ADLAR in ADMUX; clears MUX4:0.
 */
static void adc_select(uint8_t ch) {
    if (ch > 7) {
        ADCSRB |=  (uint8_t)(1 << MUX5);
    } else {
        ADCSRB &= (uint8_t)~(1 << MUX5);
    }
    ADMUX = (uint8_t)((ADMUX & 0xE0U) | (ch & 0x07U));
}

/* Section 1: polled right-adjusted 10-bit read. */
static uint16_t adc_read(uint8_t ch) {
    ADMUX &= (uint8_t)~(1 << ADLAR);
    adc_select(ch);
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC)) {}
    return ADC;
}

/* Section 2: polled left-adjusted read; returns ADCH (8 MSBs). */
static uint8_t adc_read_left(uint8_t ch) {
    ADMUX |= (uint8_t)(1 << ADLAR);
    adc_select(ch);
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC)) {}
    const uint8_t hi = ADCH;
    ADMUX &= (uint8_t)~(1 << ADLAR);   /* restore right-adjust */
    return hi;
}

/* ---- Section 3: ISR-driven conversion ------------------------------------ */

static volatile uint16_t _isr_result;
static volatile uint8_t  _isr_done;

ISR(ADC_vect) {
    _isr_result = ADC;
    _isr_done   = 1;
    ADCSRA &= (uint8_t)~(1 << ADIE);   /* one-shot: disable until next request */
}

/* Starts a conversion with ADIE enabled, busy-waits for the ISR to fire. */
static uint16_t adc_read_isr(uint8_t ch) {
    ADMUX &= (uint8_t)~(1 << ADLAR);
    adc_select(ch);
    _isr_done = 0;
    ADCSRA |= (1 << ADIE) | (1 << ADSC);
    while (!_isr_done) {}
    return _isr_result;
}

/* ---- main ---------------------------------------------------------------- */

int main(void) {
    uint8_t ch;

    uart0_init();
    adc_init();
    sei();

    /* ---- 1. Polled right-adjusted reads, all 16 channels ---- */
    uart0_puts("=== poll ch0-15 ===\r\n");
    for (ch = 0; ch < 16U; ch++) {
        uart0_puts("adc[");
        uart0_put2d(ch);
        uart0_puts("]=");
        uart0_puti(adc_read(ch));
        uart0_puts("\r\n");
    }

    /* ---- 2. Left-adjusted reads, all 16 channels ---- */
    uart0_puts("=== left-adj ch0-15 ===\r\n");
    for (ch = 0; ch < 16U; ch++) {
        uart0_puts("adcL[");
        uart0_put2d(ch);
        uart0_puts("]=");
        uart0_puti(adc_read_left(ch));
        uart0_puts("\r\n");
    }

    /* ---- 3. ISR-driven reads, all 16 channels ---- */
    uart0_puts("=== isr ch0-15 ===\r\n");
    for (ch = 0; ch < 16U; ch++) {
        uart0_puts("adcI[");
        uart0_put2d(ch);
        uart0_puts("]=");
        uart0_puti(adc_read_isr(ch));
        uart0_puts("\r\n");
    }

    uart0_puts("done\r\n");
    for (;;) {}
}
