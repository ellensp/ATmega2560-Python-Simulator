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

static uint8_t is_prime(uint16_t n) {
    uint16_t d;

    if (n < 2) {
        return 0;
    }

    for (d = 2; (uint32_t)d * (uint32_t)d <= n; d++) {
        if ((n % d) == 0) {
            return 0;
        }
    }

    return 1;
}

static void delay_short(void) {
    for (volatile uint32_t i = 0; i < (F_CPU / 80UL); i++) {
        __asm__ __volatile__("nop");
    }
}

int main(void) {
    uint16_t candidate = 2;

    uart0_init();
    uart0_write_str("Primes:\r\n");

    for (;;) {
        if (is_prime(candidate)) {
            uart0_write_u16(candidate);
            uart0_write_str("\r\n");
            delay_short();
        }

        candidate++;
        if (candidate == 0) {
            candidate = 2;
            uart0_write_str("(restart)\r\n");
        }
    }

    return 0;
}
