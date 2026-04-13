#include <avr/io.h>
#include <stdint.h>

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

static void timer0_init_for_blink(void) {
    TCCR0A = (1 << WGM01);
    TCCR0B = (1 << CS02) | (1 << CS00);
    OCR0A = 124;
    TIFR0 = (1 << OCF0A);
}

int main(void) {
    uint16_t ticks = 0;

    DDRB |= (1 << PB7);
    timer0_init_for_blink();

    for (;;) {
        if (TIFR0 & (1 << OCF0A)) {
            TIFR0 = (1 << OCF0A);
            ticks++;
            if ((ticks & 0x003F) == 0) {
                PORTB ^= (1 << PB7);
            }
        }
    }

    return 0;
}
