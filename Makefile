MCU := atmega2560
F_CPU := 16000000UL

CC := avr-gcc
OBJCOPY := avr-objcopy
SIZE := avr-size

PYTHON := $(if $(wildcard .venv-pypy310/bin/python),.venv-pypy310/bin/python,pypy3)

CFLAGS := -mmcu=$(MCU) -DF_CPU=$(F_CPU) -Os -Wall -Wextra -std=c11
LDFLAGS := -mmcu=$(MCU)

EXAMPLES_DIR := examples
EXAMPLE_SRCS := $(wildcard $(EXAMPLES_DIR)/*/*.c)
EXAMPLE_ELFS := $(EXAMPLE_SRCS:.c=.elf)
EXAMPLE_HEXS := $(EXAMPLE_SRCS:.c=.hex)

BLINK_TARGET := $(EXAMPLES_DIR)/blink/blink
BLINK_HEX := $(BLINK_TARGET).hex

HELLO_TARGET := $(EXAMPLES_DIR)/hello_world/hello_world
HELLO_HEX := $(HELLO_TARGET).hex

FIB_HEX := $(EXAMPLES_DIR)/fibonacci_uart/fibonacci_uart.hex
PRIMES_HEX := $(EXAMPLES_DIR)/primes_uart/primes_uart.hex
COUNTER_HEX := $(EXAMPLES_DIR)/counter_uart/counter_uart.hex
GPIO_HEX := $(EXAMPLES_DIR)/gpio_chaser/gpio_chaser.hex
TIMER_TICK_HEX := $(EXAMPLES_DIR)/timer0_tick_uart/timer0_tick_uart.hex
ADC_HEX := $(EXAMPLES_DIR)/adc_poll/adc_poll.hex
SPI_HEX := $(EXAMPLES_DIR)/spi_master_loop/spi_master_loop.hex
EEPROM_HEX := $(EXAMPLES_DIR)/eeprom_rw/eeprom_rw.hex
UART_RELAY_HEX := $(EXAMPLES_DIR)/uart_relay/uart_relay.hex
UART0_RX_ISR_HEX := $(EXAMPLES_DIR)/uart0_rx_isr/uart0_rx_isr.hex


.PHONY: all examples clean size sim sim-fast sim-visual \
	hello fibonacci primes counter gpio-chaser timer0-tick adc spi eeprom uart-relay uart0-rx-isr help

all: examples

examples: $(EXAMPLE_ELFS) $(EXAMPLE_HEXS)

%.elf: %.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

%.hex: %.elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@

size: $(BLINK_TARGET).elf
	$(SIZE) $<

hello: $(HELLO_HEX)
fibonacci: $(FIB_HEX)
primes: $(PRIMES_HEX)
counter: $(COUNTER_HEX)
gpio-chaser: $(GPIO_HEX)
timer0-tick: $(TIMER_TICK_HEX)
adc: $(ADC_HEX)
spi: $(SPI_HEX)
eeprom: $(EEPROM_HEX)
uart-relay: $(UART_RELAY_HEX)
uart0-rx-isr: $(UART0_RX_ISR_HEX)

sim: $(BLINK_HEX)
	$(PYTHON) run_hex.py $(BLINK_HEX) --steps 2000 -v

sim-fast: $(BLINK_HEX)
	$(PYTHON) run_hex.py $(BLINK_HEX) --steps 200000

sim-visual: $(BLINK_HEX)
	$(PYTHON) run_hex.py $(BLINK_HEX) --steps 2000 --visual --visual-every 20 --visual-clear

clean:
	rm -f $(EXAMPLE_ELFS) $(EXAMPLE_HEXS) $(EXAMPLES_DIR)/blink/blink_sim.elf $(EXAMPLES_DIR)/blink/blink_sim.hex

help:
	@echo "Targets:"
	@echo "  make        Build all example ELF and HEX files"
	@echo "  make examples Build all example ELF and HEX files"
	@echo "  make hello/fibonacci/primes/counter/gpio-chaser/timer0-tick/adc/spi/eeprom/uart-relay/uart0-rx-isr"
	@echo "              Build one example HEX by name (and its ELF dependency)"
	@echo "  make size   Show blink ELF size"
	@echo "  make sim    Run in Python simulator (verbose)"
	@echo "  make sim-fast   Run simulator without per-step trace"
	@echo "  make sim-visual Run simulator with visual I/O/LED frames"
	@echo "  make clean  Remove build outputs"
