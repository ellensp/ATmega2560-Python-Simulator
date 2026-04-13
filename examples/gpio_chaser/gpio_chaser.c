#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

static void delay_short(void) {
    for (volatile uint32_t i = 0; i < (F_CPU / 30UL); i++) {
        __asm__ __volatile__("nop");
    }
}

int main(void) {
    uint8_t bit = 0;

    DDRA = 0xFF;

    for (;;) {
        PORTA = (uint8_t)(1U << bit);
        bit = (uint8_t)((bit + 1U) & 0x07U);
        delay_short();
    }

    return 0;
}
