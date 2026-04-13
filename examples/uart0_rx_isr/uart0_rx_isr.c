#include <avr/interrupt.h>
#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

#ifndef BAUD
#define BAUD 9600UL
#endif

#define RX_BUF_SIZE 32

static volatile uint8_t rx_buf[RX_BUF_SIZE];
static volatile uint8_t rx_head;
static volatile uint8_t rx_tail;

static void uart0_init(void) {
    const uint16_t ubrr = (uint16_t)((F_CPU / (16UL * BAUD)) - 1UL);
    UBRR0H = (uint8_t)(ubrr >> 8);
    UBRR0L = (uint8_t)ubrr;
    UCSR0A = 0;
    UCSR0B = (1 << RXEN0) | (1 << TXEN0) | (1 << RXCIE0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

static void uart0_write_char(char c) {
    while (!(UCSR0A & (1 << UDRE0))) {
    }
    UDR0 = (uint8_t)c;
}

static void uart0_write_str(const char *s) {
    while (*s != '\0') {
        uart0_write_char(*s++);
    }
}

static void uart0_write_received(uint8_t value) {
    uart0_write_str("received {");
    if (value == '\r') {
        uart0_write_str("\\r");
    } else if (value == '\n') {
        uart0_write_str("\\n");
    } else if (value == '\\') {
        uart0_write_str("\\\\");
    } else if (value == '}') {
        uart0_write_str("\\}");
    } else if (value >= 0x20 && value <= 0x7E) {
        uart0_write_char((char)value);
    } else {
        static const char digits[] = "0123456789ABCDEF";
        uart0_write_str("\\x");
        uart0_write_char(digits[(value >> 4) & 0x0F]);
        uart0_write_char(digits[value & 0x0F]);
    }
    uart0_write_str("}\r\n");
}

ISR(USART0_RX_vect) {
    const uint8_t next_head = (uint8_t)((rx_head + 1U) % RX_BUF_SIZE);
    const uint8_t value = UDR0;

    if (next_head == rx_tail) {
        return;
    }

    rx_buf[rx_head] = value;
    rx_head = next_head;
}

int main(void) {
    uart0_init();
    sei();
    uart0_write_str("uart0 rx isr ready\r\n");

    for (;;) {
        if (rx_head != rx_tail) {
            const uint8_t value = rx_buf[rx_tail];
            rx_tail = (uint8_t)((rx_tail + 1U) % RX_BUF_SIZE);
            uart0_write_received(value);
        }
    }

    return 0;
}