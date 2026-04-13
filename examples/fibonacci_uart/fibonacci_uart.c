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

static void uart0_write_u16(uint16_t value) {
    char buf[6];
    uint8_t i = 0;

    if (value == 0) {
        uart0_write_char('0');
        return;
    }

    while (value > 0 && i < sizeof(buf)) {
        buf[i++] = (char)('0' + (value % 10U));
        value /= 10U;
    }

    while (i > 0) {
        uart0_write_char(buf[--i]);
    }
}

static void delay_short(void) {
#ifdef FAST_SIM
    /* Minimal delay for simulator use — avoids running millions of NOP cycles. */
    __asm__ __volatile__("nop");
#else
    for (volatile uint32_t i = 0; i < (F_CPU / 40UL); i++) {
        __asm__ __volatile__("nop");
    }
#endif
}

int main(void) {
    uint16_t a = 0;
    uint16_t b = 1;

    uart0_init();
    uart0_write_str("Fibonacci:\r\n");

    for (;;) {
        uart0_write_u16(a);
        uart0_write_str("\r\n");

        {
            const uint16_t next = (uint16_t)(a + b);
            a = b;
            b = next;
            if (b < a) {
                a = 0;
                b = 1;
                uart0_write_str("(restart)\r\n");
            }
        }

        delay_short();
    }

    return 0;
}
