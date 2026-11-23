#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdint.h>

uint8_t t_base(void), t_nop(void), t_rcall_ret(void), t_call_ret(void), t_icall_ret(void), t_eicall_ret(void);
uint8_t t_irq_latency(void), t_reti_gap(void), t_tifr_before(void), t_tifr_sbi(void), t_tifr_cbi(void);
uint8_t t_ctc0(uint8_t n), t_ctc1(uint8_t n), t_spi(void), t_temp(void);
uint8_t t_fmul(uint8_t a, uint8_t b), t_fmuls(uint8_t a, uint8_t b), t_fmulsu(uint8_t a, uint8_t b);
uint8_t t_pin_sbi(void), t_pin_cbi(void), t_sreg_mem(void), t_reg_mem(void);
void t_prio(void);
uint8_t t_sleep_idle(void), t_sleep_nose(void), t_t1mode(uint8_t a, uint8_t b, uint8_t top, uint8_t n), t_icr_normal(void);
uint8_t t_irq_lat_pc(void), t_presc(uint8_t k), t_eere(void), t_eepe(void), t_eeread_val(void);
uint8_t t_spi_done0(uint8_t spcr, uint8_t spsr, uint8_t n), t_spi_done1(uint8_t spcr, uint8_t spsr, uint8_t n), t_spi_done2(uint8_t spcr, uint8_t spsr, uint8_t n);
uint16_t t_uart_frame(uint8_t n), t_uart_udre(uint8_t n), t_uart_frame2(uint8_t d), t_uart_udre2(uint8_t d), t_uart_txc2(uint8_t d);
uint8_t t_presc_b(uint8_t k), t_presc_c(uint8_t k), t_presc_d(uint8_t k), t_presc_e(uint8_t k), t_gtccr(void), t_presc_f(uint8_t j), t_presc_h(uint8_t j), t_presc_i(uint8_t j);
extern uint8_t last_tifr, ocr_res[3], twi_status[2];
extern uint16_t twi_time[2];
void t_ocrbuf(uint8_t a, uint8_t b, uint8_t top), t_twi(uint8_t twbr);
uint8_t t_topbuf(uint8_t a, uint8_t b), t_ocrbuf0(uint8_t a, uint8_t b);
uint16_t t_adc_time(uint8_t d, uint8_t second), t_adc_free(void);
uint8_t t_pinlat(uint8_t k), t_oc1c(uint8_t a, uint8_t b, uint8_t top, uint8_t ocr, uint8_t j), t_oc0a(uint8_t a, uint8_t b, uint8_t ocr, uint8_t j);
uint8_t t_ocmod(uint8_t portb7, uint8_t j), t_foc(void), t_pinlat_out(uint8_t k, uint8_t st), t_pinlat_clr(uint8_t k), t_pinlat2(void);
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

static void line16(const char *name, uint16_t v) { puts_(name); put('='); hex(v >> 8); hex(v & 0xFF); put('\r'); put('\n'); }

static void mode(const char *name, uint8_t a, uint8_t b, uint8_t top) {
  char buf[12]; uint8_t i = 0;
  while (name[i]) { buf[i] = name[i]; i++; }
  buf[i + 1] = 0;
  buf[i] = 'a'; line(buf, t_t1mode(a, b, top, 100));
  buf[i] = 'b'; line(buf, t_t1mode(a, b, top, 137));
  buf[i] = 'f'; line(buf, last_tifr);
}

static uint8_t spi_done(uint8_t spcr, uint8_t spsr, uint16_t d) {
  uint8_t n = d / 3;
  switch (d % 3) {
    case 0: return t_spi_done0(spcr, spsr, n);
    case 1: return t_spi_done1(spcr, spsr, n);
    default: return t_spi_done2(spcr, spsr, n);
  }
}

// First delay (in cycles after the SPDR write, plus one) at which SPIF reads as set.
static uint16_t spi_time(uint8_t spcr, uint8_t spsr) {
  uint16_t lo = 3, hi = 767;  // not set at lo, set at hi
  while (hi - lo > 1) {
    uint16_t mid = (lo + hi) / 2;
    if (spi_done(spcr, spsr, mid)) hi = mid; else lo = mid;
  }
  return hi;
}

static void named(const char *name, char suffix, uint8_t v) {
  char buf[12]; uint8_t i = 0;
  while (name[i]) { buf[i] = name[i]; i++; }
  buf[i] = suffix; buf[i + 1] = 0;
  line(buf, v);
}

static void ocrbuf(const char *name, uint8_t a, uint8_t b, uint8_t top) {
  t_ocrbuf(a, b, top);
  named(name, '1', ocr_res[0]);
  named(name, '2', ocr_res[1]);
  named(name, '3', ocr_res[2]);
}

// 48 samples of PB7, one per cycle after the timer start, as 12 hex digits (first sample = top bit).
static void wave_bits(const char *name, uint8_t bits[6]) {
  puts_(name); put('=');
  for (uint8_t i = 0; i < 6; i++) hex(bits[i]);
  put('\r'); put('\n');
}
static void oc1c(const char *name, uint8_t a, uint8_t b, uint8_t top, uint8_t ocr, uint8_t portb7) {
  uint8_t bits[6] = {0};
  for (uint8_t j = 0; j < 48; j++) if (t_oc1c(a, b, top, ocr, j | (portb7 ? 0x80 : 0))) bits[j >> 3] |= 0x80 >> (j & 7);
  wave_bits(name, bits);
}
static void oc0a(const char *name, uint8_t a, uint8_t b, uint8_t ocr) {
  uint8_t bits[6] = {0};
  for (uint8_t j = 0; j < 48; j++) if (t_oc0a(a, b, ocr, j)) bits[j >> 3] |= 0x80 >> (j & 7);
  wave_bits(name, bits);
}

int main(void) {
  cli();
  UCSR0A = _BV(U2X0);
  UBRR0 = 16;               // 115200 at 16 MHz
  UCSR0B = _BV(TXEN0);
  UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);

  puts_("HWCHECK 11\r\n");
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
  line("sleep_idle", t_sleep_idle());
  line("sleep_nose", t_sleep_nose() - base);
  mode("m4", 0x00, 0x08, 99);   // CTC, TOP = OCR1A
  mode("m12", 0x00, 0x18, 99);  // CTC, TOP = ICR1
  mode("m14", 0x02, 0x18, 99);  // fast PWM, TOP = ICR1
  mode("m15", 0x03, 0x18, 99);  // fast PWM, TOP = OCR1A
  mode("m8", 0x00, 0x10, 50);   // phase and frequency correct, TOP = ICR1
  mode("m10", 0x02, 0x10, 50);  // phase correct, TOP = ICR1
  mode("m11", 0x03, 0x10, 50);  // phase correct, TOP = OCR1A
  mode("m1", 0x01, 0x00, 50);   // phase correct, 8-bit
  mode("m5", 0x01, 0x08, 50);   // fast PWM, 8-bit
  line("icr_normal", t_icr_normal());
  line("irq_lat_pc", t_irq_lat_pc());
  for (uint8_t k = 0; k <= 8; k++) { char n[8] = "presc_0"; n[6] = '0' + k; line(n, t_presc(k)); }
  for (uint8_t k = 0; k <= 8; k++) { char n[9] = "prescb_0"; n[7] = '0' + k; line(n, t_presc_b(k)); }
  for (uint8_t k = 0; k <= 8; k++) { char n[9] = "prescd_0"; n[7] = '0' + k; line(n, t_presc_d(k)); }
  for (uint8_t k = 0; k <= 8; k++) { char n[9] = "presce_0"; n[7] = '0' + k; line(n, t_presc_e(k)); }
  line("gtccr", t_gtccr());
  // One hex digit per delay 0..39.
  puts_("pf="); for (uint8_t j = 0; j < 40; j++) put("0123456789ABCDEF"[t_presc_f(j) & 15]); puts_("\r\n");
  puts_("ph="); for (uint8_t j = 0; j < 40; j++) put("0123456789ABCDEF"[t_presc_h(j) & 15]); puts_("\r\n");
  puts_("pi="); for (uint8_t j = 0; j < 40; j++) put("0123456789ABCDEF"[t_presc_i(j) & 15]); puts_("\r\n");
  line16("spi_f4", spi_time(0x50, 0));
  line16("spi_f16", spi_time(0x51, 0));
  line16("spi_f64", spi_time(0x52, 0));
  line16("spi_f2", spi_time(0x50, 1));
  line16("spi_f8", spi_time(0x51, 1));
  while (!(UCSR0A & _BV(UDRE0))) {}
  line("txc", t_txc());
  ocrbuf("ob0_", 0x00, 0x00, 200);   // normal
  ocrbuf("ob4_", 0x00, 0x08, 200);   // CTC
  ocrbuf("ob5_", 0x01, 0x08, 200);   // fast PWM, 8-bit
  ocrbuf("ob14_", 0x02, 0x18, 200);  // fast PWM, TOP = ICR1
  ocrbuf("ob1_", 0x01, 0x00, 100);   // phase correct, 8-bit
  ocrbuf("ob10_", 0x02, 0x10, 100);  // phase correct, TOP = ICR1
  ocrbuf("ob8_", 0x00, 0x10, 100);   // phase and frequency correct, TOP = ICR1
  line("tb4", t_topbuf(0x00, 0x08));   // CTC, TOP = OCR1A
  line("tb15", t_topbuf(0x03, 0x18));  // fast PWM, TOP = OCR1A
  line("tb11", t_topbuf(0x03, 0x10));  // phase correct, TOP = OCR1A
  line("tb9", t_topbuf(0x01, 0x10));   // phase and frequency correct, TOP = OCR1A
  line("ob0n", t_ocrbuf0(0x00, 0x00));  // Timer0 normal
  line("ob0f", t_ocrbuf0(0x03, 0x00));  // Timer0 fast PWM
  line("ob0p", t_ocrbuf0(0x01, 0x00));  // Timer0 phase correct
  puts_("adc1="); for (uint8_t d = 0; d < 20; d++) { uint16_t v = t_adc_time(d, 0); hex(v >> 8); hex(v & 0xFF); put(' '); } puts_("\r\n");
  puts_("adc2="); for (uint8_t d = 0; d < 20; d++) { uint16_t v = t_adc_time(d, 1); hex(v >> 8); hex(v & 0xFF); put(' '); } puts_("\r\n");
  line16("adc_free", t_adc_free());
  t_twi(72);
  line16("twi72_start", twi_time[0]); line("twi72_start_st", twi_status[0]);
  line16("twi72_addr", twi_time[1]); line("twi72_addr_st", twi_status[1]);
  t_twi(12);
  line16("twi12_start", twi_time[0]); line16("twi12_addr", twi_time[1]);
  { uint8_t bits[6] = {0}; for (uint8_t j = 0; j < 8; j++) if (t_pinlat(j)) bits[0] |= 0x80 >> j; line("pinlat", bits[0]); }
  { uint8_t b = 0; for (uint8_t j = 0; j < 8; j++) if (t_pinlat_out(j, 0)) b |= 0x80 >> j; line("pinlat_out", b); }
  { uint8_t b = 0; for (uint8_t j = 0; j < 8; j++) if (t_pinlat_out(j, 1)) b |= 0x80 >> j; line("pinlat_st", b); }
  { uint8_t b = 0; for (uint8_t j = 0; j < 8; j++) if (t_pinlat_clr(j)) b |= 0x80 >> j; line("pinlat_clr", b); }
  line("pinlat2", t_pinlat2());
  oc1c("oc_n_t", 0x04, 0x00, 20, 6, 0);     // normal, toggle
  oc1c("oc_c_t", 0x04, 0x18, 20, 6, 0);     // CTC (TOP = ICR1), toggle
  oc1c("oc_c_c", 0x08, 0x18, 20, 6, 1);     // CTC, clear (PORTB7 = 1 has no effect while connected)
  oc1c("oc_c_s", 0x0C, 0x18, 20, 6, 0);     // CTC, set
  oc1c("oc_f_n", 0x0A, 0x18, 20, 6, 0);     // fast PWM, non-inverting
  oc1c("oc_f_i", 0x0E, 0x18, 20, 6, 0);     // fast PWM, inverting
  oc1c("oc_f_t", 0x06, 0x18, 20, 6, 1);     // fast PWM, COM1C = 1: disconnected (PORTB7 = 1 shows)
  oc1c("oc_f_n0", 0x0A, 0x18, 20, 0, 0);    // OCR1C = BOTTOM
  oc1c("oc_f_nT", 0x0A, 0x18, 20, 20, 0);   // OCR1C = TOP
  oc1c("oc_f_i0", 0x0E, 0x18, 20, 0, 0);
  oc1c("oc_f_iT", 0x0E, 0x18, 20, 20, 0);
  oc1c("oc_p_n", 0x0A, 0x10, 20, 6, 0);     // phase correct, non-inverting
  oc1c("oc_p_i", 0x0E, 0x10, 20, 6, 0);
  oc1c("oc_p_n0", 0x0A, 0x10, 20, 0, 0);
  oc1c("oc_p_nT", 0x0A, 0x10, 20, 20, 0);
  oc1c("oc_q_n", 0x08, 0x10, 20, 6, 0);     // phase and frequency correct, non-inverting
  oc1c("oc_p_nT2", 0x0A, 0x10, 20, 20, 0);  // leaves the output high
  oc1c("oc_p_n2", 0x0A, 0x10, 20, 6, 0);    // phase correct again, starting high
  oc1c("oc_q_nT", 0x08, 0x10, 20, 20, 0);
  oc1c("oc_q_n3", 0x08, 0x10, 20, 3, 0);
  oc1c("oc_q_nT2", 0x08, 0x10, 20, 20, 0);
  oc1c("oc_q_n10", 0x08, 0x10, 20, 10, 0);
  oc1c("oc_q_i", 0x0C, 0x10, 20, 6, 0);     // phase and frequency correct, inverting
  oc1c("oc_q_n0", 0x08, 0x10, 20, 0, 0);
  oc0a("oc0_n_t", 0x40, 0x00, 6);           // Timer0 normal, toggle
  oc0a("oc0_c_t", 0x42, 0x00, 5);           // Timer0 CTC, toggle
  oc0a("oc0_f_t", 0x43, 0x08, 5);           // Timer0 fast PWM with TOP = OCR0A, toggle
  oc0a("oc0_p_t", 0x41, 0x08, 5);           // Timer0 phase correct with TOP = OCR0A, toggle
  { uint8_t bits[6] = {0}; for (uint8_t j = 0; j < 48; j++) if (t_ocmod(0, j)) bits[j >> 3] |= 0x80 >> (j & 7); wave_bits("oc_mod0", bits); }
  { uint8_t bits[6] = {0}; for (uint8_t j = 0; j < 48; j++) if (t_ocmod(1, j)) bits[j >> 3] |= 0x80 >> (j & 7); wave_bits("oc_mod1", bits); }
  line("foc", t_foc()); line("foc_tccr1c", ocr_res[0]);
  line16("uart_udre_10", t_uart_udre(10));
  line16("uart_udre_23", t_uart_udre(23));
  // The EEPROM write is timed by an RC oscillator, so it comes last: nothing
  // after it has to be cycle-exact.
  line("eere", t_eere() - base);
  line("eepe", t_eepe() - base);
  line("eeread_val", t_eeread_val());
  puts_("DONE\r\n");
  for (;;) {}
}
