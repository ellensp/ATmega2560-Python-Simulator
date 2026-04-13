#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

#ifndef BAUD
#define BAUD 9600UL
#endif

#define UART_COUNT 4
#define MSG_BUF_SIZE 96

static void uart_init(uint8_t uart_index) {
    const uint16_t ubrr = (uint16_t)((F_CPU / (16UL * BAUD)) - 1UL);

    switch (uart_index) {
        case 0:
            UBRR0H = (uint8_t)(ubrr >> 8);
            UBRR0L = (uint8_t)ubrr;
            UCSR0A = 0;
            UCSR0B = (1 << RXEN0) | (1 << TXEN0);
            UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
            break;
        case 1:
            UBRR1H = (uint8_t)(ubrr >> 8);
            UBRR1L = (uint8_t)ubrr;
            UCSR1A = 0;
            UCSR1B = (1 << RXEN1) | (1 << TXEN1);
            UCSR1C = (1 << UCSZ11) | (1 << UCSZ10);
            break;
        case 2:
            UBRR2H = (uint8_t)(ubrr >> 8);
            UBRR2L = (uint8_t)ubrr;
            UCSR2A = 0;
            UCSR2B = (1 << RXEN2) | (1 << TXEN2);
            UCSR2C = (1 << UCSZ21) | (1 << UCSZ20);
            break;
        case 3:
            UBRR3H = (uint8_t)(ubrr >> 8);
            UBRR3L = (uint8_t)ubrr;
            UCSR3A = 0;
            UCSR3B = (1 << RXEN3) | (1 << TXEN3);
            UCSR3C = (1 << UCSZ31) | (1 << UCSZ30);
            break;
        default:
            break;
    }
}

static uint8_t uart_rx_ready(uint8_t uart_index) {
    switch (uart_index) {
        case 0:
            return (uint8_t)((UCSR0A & (1 << RXC0)) != 0);
        case 1:
            return (uint8_t)((UCSR1A & (1 << RXC1)) != 0);
        case 2:
            return (uint8_t)((UCSR2A & (1 << RXC2)) != 0);
        case 3:
            return (uint8_t)((UCSR3A & (1 << RXC3)) != 0);
        default:
            return 0;
    }
}

static uint8_t uart_read_byte(uint8_t uart_index) {
    switch (uart_index) {
        case 0:
            return UDR0;
        case 1:
            return UDR1;
        case 2:
            return UDR2;
        case 3:
            return UDR3;
        default:
            return 0;
    }
}

static void uart_write_byte(uint8_t uart_index, uint8_t value) {
    switch (uart_index) {
        case 0:
            while (!(UCSR0A & (1 << UDRE0))) {
            }
            UDR0 = value;
            break;
        case 1:
            while (!(UCSR1A & (1 << UDRE1))) {
            }
            UDR1 = value;
            break;
        case 2:
            while (!(UCSR2A & (1 << UDRE2))) {
            }
            UDR2 = value;
            break;
        case 3:
            while (!(UCSR3A & (1 << UDRE3))) {
            }
            UDR3 = value;
            break;
        default:
            break;
    }
}

static void uart_write_str(uint8_t uart_index, const char *s) {
    while (*s != '\0') {
        uart_write_byte(uart_index, (uint8_t)*s++);
    }
}

static void uart_write_u8(uint8_t uart_index, uint8_t value) {
    if (value >= 10U) {
        uart_write_byte(uart_index, (uint8_t)('0' + (value / 10U)));
    }
    uart_write_byte(uart_index, (uint8_t)('0' + (value % 10U)));
}

static void append_escaped_char(char *out, uint8_t *len, uint8_t ch) {
    if (ch == '\r') {
        if ((uint8_t)(*len + 2U) < MSG_BUF_SIZE) {
            out[(*len)++] = '\\';
            out[(*len)++] = 'r';
        }
        return;
    }
    if (ch == '\n') {
        if ((uint8_t)(*len + 2U) < MSG_BUF_SIZE) {
            out[(*len)++] = '\\';
            out[(*len)++] = 'n';
        }
        return;
    }
    if (ch == '\\' || ch == '"') {
        if ((uint8_t)(*len + 2U) < MSG_BUF_SIZE) {
            out[(*len)++] = '\\';
            out[(*len)++] = (char)ch;
        }
        return;
    }
    if ((uint8_t)(*len + 1U) < MSG_BUF_SIZE) {
        out[(*len)++] = (char)ch;
    }
}

static void broadcast_message(uint8_t source_uart, const char *message) {
    uint8_t dst;

    for (dst = 0; dst < UART_COUNT; dst++) {
        if (dst == source_uart) {
            continue;
        }

        uart_write_str(dst, "Uart ");
        uart_write_u8(dst, source_uart);
        uart_write_str(dst, " sent: \"");
        uart_write_str(dst, message);
        uart_write_str(dst, "\"\r\n");
    }
}

static void process_uart_input(uint8_t uart_index) {
    char msg[MSG_BUF_SIZE];
    uint8_t msg_len = 0;

    while (uart_rx_ready(uart_index)) {
        const uint8_t ch = uart_read_byte(uart_index);
        append_escaped_char(msg, &msg_len, ch);

        if (msg_len >= (MSG_BUF_SIZE - 3U)) {
            msg[msg_len] = '\0';
            broadcast_message(uart_index, msg);
            msg_len = 0;
        }
    }

    if (msg_len > 0U) {
        msg[msg_len] = '\0';
        broadcast_message(uart_index, msg);
    }
}

int main(void) {
    uint8_t i;

    for (i = 0; i < UART_COUNT; i++) {
        uart_init(i);
    }

    for (i = 0; i < UART_COUNT; i++) {
        uart_write_str(i, "uart ");
        uart_write_u8(i, i);
        uart_write_str(i, " ready\r\n");
    }

    for (;;) {
        for (i = 0; i < UART_COUNT; i++) {
            process_uart_input(i);
        }
    }

    return 0;
}
