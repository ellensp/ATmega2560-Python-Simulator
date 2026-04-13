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

static void uart0_write_hex8(uint8_t value) {
    const char *digits = "0123456789ABCDEF";
    uart0_write_char(digits[(value >> 4) & 0x0F]);
    uart0_write_char(digits[value & 0x0F]);
}

static void eeprom_write_byte(uint16_t addr, uint8_t value) {
    while (EECR & (1 << EEPE)) {
    }

    EEAR = addr;
    EEDR = value;
    EECR |= (1 << EEMPE);
    EECR |= (1 << EEPE);
}

static uint8_t eeprom_read_byte(uint16_t addr) {
    while (EECR & (1 << EEPE)) {
    }

    EEAR = addr;
    EECR |= (1 << EERE);
    return EEDR;
}

static void delay_short(void) {
    for (volatile uint32_t i = 0; i < (F_CPU / 40UL); i++) {
        __asm__ __volatile__("nop");
    }
}

int main(void) {
    uint8_t value = 0;

    uart0_init();

    for (;;) {
        eeprom_write_byte(0x0010, value);
        value = eeprom_read_byte(0x0010);

        uart0_write_str("eeprom=" );
        uart0_write_hex8(value);
        uart0_write_str("\r\n");

        value++;
        delay_short();
    }

    return 0;
}
