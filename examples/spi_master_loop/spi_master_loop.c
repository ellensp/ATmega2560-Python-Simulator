#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

static void delay_short(void) {
    for (volatile uint32_t i = 0; i < (F_CPU / 120UL); i++) {
        __asm__ __volatile__("nop");
    }
}

static void spi_init_master(void) {
    DDRB |= (1 << PB0) | (1 << PB1) | (1 << PB2);
    SPCR = (1 << SPE) | (1 << MSTR) | (1 << SPR0);
    SPSR = 0;
}

static uint8_t spi_transfer(uint8_t out) {
    SPDR = out;
    while (!(SPSR & (1 << SPIF))) {
    }
    return SPDR;
}

int main(void) {
    uint8_t tx = 0;

    DDRA = 0xFF;
    spi_init_master();

    for (;;) {
        const uint8_t rx = spi_transfer(tx);
        PORTA = rx;
        tx++;
        delay_short();
    }

    return 0;
}
