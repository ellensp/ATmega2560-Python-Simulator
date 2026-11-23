#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdint.h>

uint8_t t_base(void), t_nop(void), t_rcall_ret(void), t_call_ret(void), t_icall_ret(void), t_eicall_ret(void);
uint8_t t_irq_latency(void), t_reti_gap(void), t_tifr_before(void), t_tifr_sbi(void), t_tifr_cbi(void);
uint8_t t_ctc0(uint8_t n), t_ctc1(uint8_t n), t_spi(void), t_temp(void);
uint8_t t_fmul(uint8_t a, uint8_t b), t_fmuls(uint8_t a, uint8_t b), t_fmulsu(uint8_t a, uint8_t b);
uint8_t t_pin_sbi(void), t_pin_cbi(void), t_sreg_mem(void), t_reg_mem(void);
void t_prio(void);
uint8_t t_irq_lat2(uint8_t ocr), t_irq_lat3(uint8_t ocr);
uint8_t t_start_read1(void), t_start_read0(void), t_irq_sei(void), t_irq_mask(void), t_adif(void), t_spif(void), t_txc(void);
extern uint8_t ord_t0, ord_t1, ord_t2;

static void put(char c) {
  while (!(UCSR0A & _BV(UDRE0))) {}
  UDR0 = c;
}
static void puts_(const char *s) { while (*s) put(*s++); }
static void hex(uint8_t v) {
  const char *d = "0123456789ABCDEF";
  put(d[v >> 4]); put(d[v & 15]);
}
static void line(const char *name, uint8_t v) { puts_(name); put('='); hex(v); put('\r'); put('\n'); }

int main(void) {
  cli();
  UCSR0A = _BV(U2X0);
  UBRR0 = 16;               // 115200 at 16 MHz
  UCSR0B = _BV(TXEN0);
  UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);

  puts_("HWCHECK 2\r\n");
  uint8_t base = t_base();
  line("base", base);
  line("nop", t_nop() - base);
  line("rcall_ret", t_rcall_ret() - base);
  line("call_ret", t_call_ret() - base);
  line("icall_ret", t_icall_ret() - base);
  line("eicall_ret", t_eicall_ret() - base);
  line("irq_latency", t_irq_latency());
  line("reti_gap", t_reti_gap());
  t_prio();
  line("prio_t0", ord_t0);
  line("prio_t1", ord_t1);
  line("prio_t2", ord_t2);
  line("tifr_before", t_tifr_before());
  line("tifr_sbi", t_tifr_sbi());
  line("tifr_cbi", t_tifr_cbi());
  line("ctc0_100", t_ctc0(100));
  line("ctc0_137", t_ctc0(137));
  line("ctc1_100", t_ctc1(100));
  line("ctc1_137", t_ctc1(137));
  line("spi_polls", t_spi());
  line("temp", t_temp());
  line("fmul_80_80", t_fmul(0x80, 0x80));
  line("fmul_ff_ff", t_fmul(0xFF, 0xFF));
  line("fmul_40_02", t_fmul(0x40, 0x02));
  line("fmuls_80_80", t_fmuls(0x80, 0x80));
  line("fmuls_c0_40", t_fmuls(0xC0, 0x40));
  line("fmulsu_80_ff", t_fmulsu(0x80, 0xFF));
  line("fmulsu_40_80", t_fmulsu(0x40, 0x80));
  line("pin_sbi", t_pin_sbi());
  line("pin_cbi", t_pin_cbi());
  line("sreg_mem", t_sreg_mem());
  line("reg_mem", t_reg_mem());
  line("ucsr0a_u2x", UCSR0A & _BV(U2X0));
  line("start_read1", t_start_read1());
  line("start_read0", t_start_read0());
  line("irq_sei", t_irq_sei());
  line("irq_mask", t_irq_mask());
  line("adif", t_adif());
  line("spif", t_spif());
  line("irq_lat2_40", t_irq_lat2(40));
  line("irq_lat2_41", t_irq_lat2(41));
  line("irq_lat3_60", t_irq_lat3(60));
  line("irq_lat3_61", t_irq_lat3(61));
  line("irq_lat3_62", t_irq_lat3(62));
  while (!(UCSR0A & _BV(UDRE0))) {}
  line("txc", t_txc());
  puts_("DONE\r\n");
  for (;;) {}
}
