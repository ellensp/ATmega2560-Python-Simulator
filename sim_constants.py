"""ATmega2560 emulator — class-level constants mixin.

All hardware register addresses, bit positions, vector addresses, and
peripheral layout constants live here so the other mixin modules stay
focused on behaviour rather than magic numbers.
"""


class _EmulatorConstants:
    # ATmega2560 flash geometry (byte-addressed flash: 256 KiB => 131072 words).
    FLASH_SIZE_BYTES = 256 * 1024
    FLASH_SIZE_WORDS = FLASH_SIZE_BYTES // 2
    PC_WORD_MASK = FLASH_SIZE_WORDS - 1

    # SREG bit positions
    FLAG_C = 0
    FLAG_Z = 1
    FLAG_N = 2
    FLAG_V = 3
    FLAG_S = 4
    FLAG_H = 5
    FLAG_T = 6
    FLAG_I = 7

    # Word-addressed interrupt vector targets for ATmega2560.
    # This device uses 4-byte vector table entries in flash, so vector slot N
    # starts at word address (2 * N), where N is __vector_N.
    VECTOR_INT0 = 0x0002
    VECTOR_INT1 = 0x0004
    VECTOR_INT2 = 0x0006
    VECTOR_INT3 = 0x0008
    VECTOR_INT4 = 0x000A
    VECTOR_INT5 = 0x000C
    VECTOR_INT6 = 0x000E
    VECTOR_INT7 = 0x0010
    VECTOR_PCINT0 = 0x0012
    VECTOR_PCINT1 = 0x0014
    VECTOR_PCINT2 = 0x0016
    VECTOR_WDT = 0x0018
    VECTOR_TIMER2_COMPA = 0x001A
    VECTOR_TIMER2_COMPB = 0x001C
    VECTOR_TIMER2_OVF = 0x001E
    VECTOR_TIMER1_CAPT = 0x0020
    VECTOR_TIMER1_COMPA = 0x0022
    VECTOR_TIMER1_COMPB = 0x0024
    VECTOR_TIMER1_COMPC = 0x0026
    VECTOR_TIMER1_OVF = 0x0028
    VECTOR_TIMER0_COMPA = 0x002A
    VECTOR_TIMER0_COMPB = 0x002C
    VECTOR_TIMER0_OVF = 0x002E
    VECTOR_SPI_STC = 0x0030
    VECTOR_USART0_RX = 0x0032
    VECTOR_USART0_UDRE = 0x0034
    VECTOR_USART0_TX = 0x0036
    VECTOR_ANALOG_COMP = 0x0038
    VECTOR_ADC = 0x003A
    VECTOR_EEPROM_READY = 0x003C
    VECTOR_TIMER3_CAPT = 0x003E
    VECTOR_TIMER3_COMPA = 0x0040
    VECTOR_TIMER3_COMPB = 0x0042
    VECTOR_TIMER3_COMPC = 0x0044
    VECTOR_TIMER3_OVF = 0x0046
    VECTOR_USART1_RX = 0x0048
    VECTOR_USART1_UDRE = 0x004A
    VECTOR_USART1_TX = 0x004C
    VECTOR_TWI = 0x004E
    VECTOR_TIMER4_CAPT = 0x0052
    VECTOR_TIMER4_COMPA = 0x0054
    VECTOR_TIMER4_COMPB = 0x0056
    VECTOR_TIMER4_COMPC = 0x0058
    VECTOR_TIMER4_OVF = 0x005A
    VECTOR_TIMER5_CAPT = 0x005C
    VECTOR_TIMER5_COMPA = 0x005E
    VECTOR_TIMER5_COMPB = 0x0060
    VECTOR_TIMER5_COMPC = 0x0062
    VECTOR_TIMER5_OVF = 0x0064
    VECTOR_USART2_RX = 0x0066
    VECTOR_USART2_UDRE = 0x0068
    VECTOR_USART2_TX = 0x006A
    VECTOR_USART3_RX = 0x006C
    VECTOR_USART3_UDRE = 0x006E
    VECTOR_USART3_TX = 0x0070

    # I/O-space addresses (0x00–0x3F, accessed via IN/OUT).
    IO_EIFR = 0x1C
    IO_EIMSK = 0x1D
    IO_PCIFR = 0x1B
    IO_NAME_OVERRIDES = {
        0x3F: "SREG",
        0x3E: "SPH",
        0x3D: "SPL",
        0x3C: "EIND",
        0x3B: "RAMPZ",
    }

    # Extended I/O / data-space register addresses.
    DATA_EICRA = 0x0069
    DATA_EICRB = 0x006A
    DATA_PCICR = 0x0068
    DATA_PCMSK0 = 0x006B
    DATA_PCMSK1 = 0x006C
    DATA_PCMSK2 = 0x006D
    DATA_ACSR = 0x0050
    DATA_SPCR = 0x004C
    DATA_SPSR = 0x004D
    DATA_SPDR = 0x004E
    DATA_ADCL = 0x0078
    DATA_ADCH = 0x0079
    DATA_ADCSRA = 0x007A
    DATA_ADCSRB = 0x007B
    DATA_ADMUX = 0x007C
    DATA_TWBR = 0x00B8
    DATA_TWSR = 0x00B9
    DATA_TWAR = 0x00BA
    DATA_TWDR = 0x00BB
    DATA_TWCR = 0x00BC
    DATA_TWAMR = 0x00BD
    DATA_RAMPZ = 0x005B
    DATA_EIND = 0x005C
    DATA_SPL = 0x005D
    DATA_SPH = 0x005E
    DATA_GTCCR = 0x0043
    DATA_SMCR = 0x0053
    # Cycles from a wake-up interrupt becoming pending in idle sleep to the start
    # of its entry (1 when awake). Measured on a real ATmega2560.
    SLEEP_WAKE_CYCLES = 7
    DATA_SREG = 0x005F
    DATA_EECR = 0x003F
    DATA_EEDR = 0x0040
    DATA_EEARL = 0x0041
    DATA_EEARH = 0x0042

    # EEPROM
    EEPROM_SIZE = 4096
    EEPROM_ADDR_MASK = EEPROM_SIZE - 1
    EECR_EERE_BIT = 0
    EECR_EEPE_BIT = 1
    EECR_EEMPE_BIT = 2
    EECR_EERIE_BIT = 3
    EECR_EEPM0_BIT = 4
    EECR_EEPM1_BIT = 5
    # Self-timed programming: 3.3 ms for erase + write, 1.8 ms for erase only or
    # write only, at 16 MHz.
    EEPROM_WRITE_CYCLES = 52800
    EEPROM_HALF_WRITE_CYCLES = 28800
    # The CPU is halted for 4 cycles after EERE and 2 after EEPE (measured).
    EEPROM_READ_HALT_CYCLES = 4
    EEPROM_WRITE_HALT_CYCLES = 2
    EEPROM_EEMPE_WINDOW_CYCLES = 4

    # ADC
    ADC_ADPS_MASK = 0x07
    ADC_ADIE_BIT = 3
    ADC_ADIF_BIT = 4
    ADC_ADATE_BIT = 5
    ADC_ADSC_BIT = 6
    ADC_ADEN_BIT = 7
    ADC_ADLAR_BIT = 5
    ADC_BASE_CONVERSION_CYCLES = 13

    # Analog comparator (ACSR)
    ACSR_ACIS0_BIT = 0
    ACSR_ACIS1_BIT = 1
    ACSR_ACIC_BIT = 2
    ACSR_ACIE_BIT = 3
    ACSR_ACI_BIT = 4
    ACSR_ACO_BIT = 5
    ACSR_ACBG_BIT = 6
    ACSR_ACD_BIT = 7
    ANALOG_COMPARATOR_BANDGAP_LEVEL = 256

    # SPI (SPCR / SPSR)
    SPCR_SPR0_BIT = 0
    SPCR_SPR1_BIT = 1
    SPCR_CPHA_BIT = 2
    SPCR_CPOL_BIT = 3
    SPCR_MSTR_BIT = 4
    SPCR_DORD_BIT = 5
    SPCR_SPE_BIT = 6
    SPCR_SPIE_BIT = 7
    SPSR_SPI2X_BIT = 0
    SPSR_WCOL_BIT = 6
    SPSR_SPIF_BIT = 7

    # TWI (TWCR)
    TWCR_TWIE_BIT = 0
    TWCR_TWEN_BIT = 2
    TWCR_TWWC_BIT = 3
    TWCR_TWSTO_BIT = 4
    TWCR_TWSTA_BIT = 5
    TWCR_TWEA_BIT = 6
    TWCR_TWINT_BIT = 7
    TWI_STATUS_START = 0x08
    TWI_STATUS_REP_START = 0x10
    TWI_STATUS_MT_SLA_ACK = 0x18
    TWI_STATUS_MT_DATA_ACK = 0x28
    TWI_STATUS_MR_SLA_ACK = 0x40
    TWI_STATUS_MR_DATA_ACK = 0x50
    TWI_STATUS_MR_DATA_NACK = 0x58

    # GPIO port layout: port-letter → (PIN addr, DDR addr, PORT addr)
    GPIO_PORTS = {
        "A": (0x20, 0x21, 0x22),
        "B": (0x23, 0x24, 0x25),
        "C": (0x26, 0x27, 0x28),
        "D": (0x29, 0x2A, 0x2B),
        "E": (0x2C, 0x2D, 0x2E),
        "F": (0x2F, 0x30, 0x31),
        "G": (0x32, 0x33, 0x34),
        "H": (0x100, 0x101, 0x102),
        "J": (0x103, 0x104, 0x105),
        "K": (0x106, 0x107, 0x108),
        "L": (0x109, 0x10A, 0x10B),
    }
    GPIO_PIN_ADDRS = {
        pin_addr: (ddr_addr, port_addr)
        for pin_addr, ddr_addr, port_addr in GPIO_PORTS.values()
    }
    # PIN addresses feeding the three PCINT groups: PCINT0-7 = PB0-7,
    # PCINT8 = PE0 and PCINT9-15 = PJ0-6, PCINT16-23 = PK0-7.
    PCINT_GROUP_PIN_ADDRS = (0x23, 0x2C, 0x103, 0x106)
    # INT0-3 are PD0-3, INT4-7 are PE4-7: registers whose writes can change them.
    EXTINT_RELEVANT_DATA_ADDRS = {0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x0069, 0x006A}
    # Data-space addresses that can change which pins contribute to PCINT groups.
    PCINT_RELEVANT_DATA_ADDRS = {
        DATA_PCMSK0,
        DATA_PCMSK1,
        DATA_PCMSK2,
        DATA_PCICR,
        0x23,
        0x24,
        0x25,
        0x2C,
        0x2D,
        0x2E,
        0x103,
        0x104,
        0x105,
        0x106,
        0x107,
        0x108,
    }
    # GPIO pins driven by alternate peripheral functions.
    UART_TX_PINS = {
        0: ("E", 1),
        1: ("D", 3),
        2: ("H", 1),
        3: ("J", 1),
    }
    SPI_PIN_SCK = ("B", 1)
    SPI_PIN_MOSI = ("B", 2)
    TWI_PIN_SCL = ("D", 0)
    TWI_PIN_SDA = ("D", 1)

    # Internal SRAM address range.
    DATA_SRAM_START = 0x0200
    DATA_SRAM_END = 0x21FF
