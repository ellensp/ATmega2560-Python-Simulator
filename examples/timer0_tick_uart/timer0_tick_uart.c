#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

#ifndef BAUD
#define BAUD 9600UL
#endif

static void uart0_init(void) {
    const uint16_t ubrr = (uint16_t)((F_CPU / (16UL * BAUD)) - 1UL);
    UBRR0H = (uint8_t)(ubrr >> 8);
    UBRR0L = (uint8_t)ubrr;
    UCSR0A = 0;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

static void uart0_write_char(char c) {
    while (!(UCSR0A & (1 << UDRE0))) {
    }
    UDR0 = (uint8_t)c;
}

static void uart0_write_str(const char *s) {
    while (*s) {
        uart0_write_char(*s++);
    }
}

static void timer0_init(void) {
    TCCR0A = (1 << WGM01);
    TCCR0B = (1 << CS02) | (1 << CS00);
    OCR0A = 124;
    TIFR0 = (1 << OCF0A);
}

int main(void) {
    uint16_t ticks = 0;

    uart0_init();
    timer0_init();

    for (;;) {
        if (TIFR0 & (1 << OCF0A)) {
            TIFR0 = (1 << OCF0A);
            ticks++;
            uart0_write_str("tick\r\n");
            if ((ticks & 0x000F) == 0) {
                uart0_write_str("16 ticks\r\n");
            }
        }
    }

    return 0;
}
