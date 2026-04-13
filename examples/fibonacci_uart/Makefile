MCU      = atmega2560
F_CPU    = 16000000UL
BAUD     = 9600UL
CC       = avr-gcc
CFLAGS   = -mmcu=$(MCU) -DF_CPU=$(F_CPU) -DBAUD=$(BAUD) -Os -std=c99 -Wall -Wextra
OBJCOPY  = avr-objcopy


.PHONY: all sim clean

all: fibonacci_uart.elf fibonacci_uart.hex

sim: fibonacci_uart_sim.hex

fibonacci_uart.elf: fibonacci_uart.c
	$(CC) $(CFLAGS) -o $@ $<

fibonacci_uart.hex: fibonacci_uart.elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@

fibonacci_uart_sim.elf: fibonacci_uart.c
	$(CC) $(CFLAGS) -DFAST_SIM -o $@ $<

fibonacci_uart_sim.hex: fibonacci_uart_sim.elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@

clean:
	rm -f *.elf *.hex
