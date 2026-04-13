import tkinter as tk
import re
import argparse
import time
import subprocess
import bisect
from types import SimpleNamespace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from sim import ATmega2560Emulator


class SimpleTooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_window: tk.Toplevel | None = None
        self.widget.bind("<Enter>", self._show, add="+")
        self.widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event: tk.Event) -> None:
        if self.tip_window is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip_window,
            text=self.text,
            justify=tk.LEFT,
            bg="#FFF8DC",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=3,
        )
        label.pack()

    def _hide(self, _event: tk.Event) -> None:
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class EmulatorGUI:
    REFRESH_SLIDER_MIN = 1
    REFRESH_SLIDER_MAX = 51
    REFRESH_SLIDER_REALTIME = 1
    DISASM_CONTEXT_ROWS = 120
    PROFILE_HEAT_LEVELS = 64
    PROFILE_FLASH_CONTEXT_ROWS = 2

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.emu = ATmega2560Emulator()
        self.loaded_path: str | None = None

        self.running = False
        self.run_after_id: str | None = None
        self.steps_remaining = 0
        self.run_continuous = False
        # Use separate pacing for finite runs vs continuous runs.
        # Finite runs optimize throughput; continuous mode optimizes live UI responsiveness.
        self.step_chunk = 5000
        self.step_chunk_continuous = 1500
        self.run_after_delay_ms = 0
        self.run_after_delay_ms_continuous = 0
        # Force a periodic tiny pause in continuous mode so Tk can repaint reliably.
        self.run_after_delay_ms_continuous_yield = 1
        self.run_yield_every_ticks_continuous = 4
        # UART text rendering is expensive, so refresh it periodically while running.
        self._run_tick_counter = 0
        self.uart_refresh_every_ticks = 1
        self._last_run_periodic_refresh_time = 0.0
        self.breakpoints: set[int] = set()
        self.disasm_labels: dict[int, str] = {}
        self.disasm_auto_labels: dict[int, str] = {}
        self._profile_line_meta: dict[int, tuple[str, int, int]] = {}
        self._profile_tip_window: tk.Toplevel | None = None
        self._profile_tip_label: tk.Label | None = None
        self._profile_return_space: str | None = None
        self._profile_return_addr: int | None = None
        self._pending_profile_focus_space: str | None = None
        self._pending_profile_focus_addr: int | None = None
        self._pending_flash_focus_pc: int | None = None
        self._pending_memory_focus_mode: str | None = None
        self._pending_memory_focus_addr: int | None = None
        self._profile_jump_highlight_space: str | None = None
        self._profile_jump_highlight_addr: int | None = None
        self._profile_jump_highlight_color: str | None = None
        self._disasm_cache_rows: dict[int, tuple[int, str, str]] = {}
        self._disasm_cache_pcs: list[int] = []
        self._disasm_cache_index_by_pc: dict[int, int] = {}
        self._disasm_decoded_until_pc = 0

        self._disasm_loaded_end_pc = 0
        self._disasm_loaded_start_pc = 0
        self._disasm_appending = False
        self._disasm_rebuilding_view = False
        self._disasm_scrollbar: ttk.Scrollbar | None = None
        self.left_mode_var = tk.StringVar(value="flash")
        self.profile_space_var = tk.StringVar(value="flash")
        self.profile_mode_var = tk.BooleanVar(value=False)
        self._last_non_profile_left_mode = "flash"
        self.flash_view_var = tk.StringVar(value="disasm")
        self._last_flash_view = "disasm"
        self._last_left_render_mode: str | None = None
        self.left_title_var = tk.StringVar(value="FLASH Viewer (Disassembly)")
        self.side_mode_var = tk.StringVar(value="registers")
        self.uart_selected_var = tk.IntVar(value=0)
        self.uart_frames: list[ttk.Frame] = []
        self.uart_text_widgets: list[tk.Text] = []
        self.uart_send_vars: list[tk.StringVar] = []
        self.uart_send_cr_vars: list[tk.BooleanVar] = []
        self.uart_send_lf_vars: list[tk.BooleanVar] = []
        self.uart_status_value_labels: list[dict[str, tk.Label]] = []
        self.adc_slider_vars: list[tk.IntVar] = []
        self.adc_slider_widgets: list[ttk.Scale] = []
        self.adc_value_labels: list[ttk.Label] = []
        self.adc_state_labels: list[ttk.Label] = []
        self.adc_pending_values: list[int] = [0] * 16
        self.uart_tx_cursors: list[int] = [0, 0, 0, 0]
        self._uart_scroll_canvas: tk.Canvas | None = None
        self.refresh_rate_scale_var = tk.DoubleVar(value=10.0)
        self.refresh_rate_label_var = tk.StringVar(value="GUI Update: 1.0s")

        self._build_ui()
        self.root.bind_all("<MouseWheel>", self._on_uart_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_uart_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_uart_mousewheel, add="+")
        self._refresh_idle_views(status_text="Load a .hex/.hx or .bin file to begin.")

    def _build_ui(self) -> None:
        self.root.title("ATmega2560 Simulator GUI")
        self.root.geometry("1300x800")

        top = ttk.Frame(self.root, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        self.load_btn = ttk.Button(top, text="Load .hex/.hx/.bin", command=self._on_load)
        self.load_btn.pack(side=tk.LEFT)

        self.path_var = tk.StringVar(value="No file loaded")
        self.path_lbl = ttk.Label(top, textvariable=self.path_var)
        self.path_lbl.pack(side=tk.LEFT, padx=(10, 18))
        self.path_tooltip = SimpleTooltip(self.path_lbl, "No file loaded")

        self.run_toggle_btn = ttk.Button(top, text="Run", command=self._on_run_toggle)
        self.run_toggle_btn.pack(side=tk.LEFT)

        self.step_btn = ttk.Button(top, text="Step", command=self._on_step)
        self.step_btn.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(top, text="Step count:").pack(side=tk.LEFT, padx=(10, 0))
        self.step_count_var = tk.StringVar(value="1")
        self.step_count_entry = ttk.Entry(top, textvariable=self.step_count_var, width=8)
        self.step_count_entry.pack(side=tk.LEFT, padx=(6, 6))

        self.restart_btn = ttk.Button(top, text="Restart", command=self._on_restart)
        self.restart_btn.pack(side=tk.LEFT, padx=(6, 18))

        self.profile_btn = ttk.Checkbutton(
            top,
            text="Profile",
            style="Toolbutton",
            variable=self.profile_mode_var,
            command=self._on_profile_toggle,
        )
        self.profile_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.refresh_rate_label = ttk.Label(
            top,
            textvariable=self.refresh_rate_label_var,
            width=20,
            anchor=tk.W,
        )
        self.refresh_rate_label.pack(side=tk.LEFT, padx=(0, 6))

        self.refresh_rate_scale = ttk.Scale(
            top,
            from_=self.REFRESH_SLIDER_MIN,
            to=self.REFRESH_SLIDER_MAX,
            orient=tk.HORIZONTAL,
            length=190,
            variable=self.refresh_rate_scale_var,
            command=self._on_refresh_rate_changed,
        )
        self.refresh_rate_scale.pack(side=tk.LEFT, padx=(0, 14))
        SimpleTooltip(
            self.refresh_rate_scale,
            "Left = slower GUI refresh interval (0.1s to 5.0s). Far right = Realtime (much slower run speed).",
        )
        self._on_refresh_rate_changed()

        status_row = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        status_row.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(status_row, text="Message:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="")
        status_lbl = ttk.Label(status_row, textvariable=self.status_var, anchor=tk.W)
        status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=3)
        main.add(right, weight=2)

        left_mode = ttk.Frame(left)
        left_mode.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(left_mode, text="Left:").pack(side=tk.LEFT)
        self.left_flash_btn = ttk.Radiobutton(
            left_mode,
            text="FLASH",
            variable=self.left_mode_var,
            value="flash",
            command=self._on_left_mode_changed,
        )
        self.left_flash_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.flash_disasm_btn = ttk.Radiobutton(
            left_mode,
            text="Disassembly",
            variable=self.flash_view_var,
            value="disasm",
            command=self._on_flash_view_changed,
        )
        self.flash_disasm_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.flash_raw_btn = ttk.Radiobutton(
            left_mode,
            text="Raw",
            variable=self.flash_view_var,
            value="raw",
            command=self._on_flash_view_changed,
        )
        self.flash_raw_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.left_ram_btn = ttk.Radiobutton(
            left_mode,
            text="RAM",
            variable=self.left_mode_var,
            value="ram",
            command=self._on_left_mode_changed,
        )
        self.left_ram_btn.pack(side=tk.LEFT, padx=(12, 0))
        self.left_eeprom_btn = ttk.Radiobutton(
            left_mode,
            text="EEPROM",
            variable=self.left_mode_var,
            value="eeprom",
            command=self._on_left_mode_changed,
        )
        self.left_eeprom_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(left, textvariable=self.left_title_var).pack(anchor=tk.W)
        self.disasm_text = tk.Text(left, wrap=tk.NONE, height=30, width=100)
        self.disasm_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.disasm_text.configure(state=tk.DISABLED)

        disasm_scroll_y = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self._on_disasm_scroll)
        disasm_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self._disasm_scrollbar = disasm_scroll_y
        self.disasm_text.configure(yscrollcommand=self._on_disasm_yview)

        self.disasm_text.bind("<MouseWheel>", self._on_disasm_view_event, add="+")
        self.disasm_text.bind("<Button-4>", self._on_disasm_view_event, add="+")
        self.disasm_text.bind("<Button-5>", self._on_disasm_view_event, add="+")
        self.disasm_text.bind("<KeyRelease>", self._on_disasm_view_event, add="+")
        self.disasm_text.bind("<Button-1>", self._on_disasm_click, add="+")
        self.disasm_text.bind("<Motion>", self._on_profile_motion, add="+")
        self.disasm_text.bind("<Leave>", self._on_profile_leave, add="+")

        right_mode = ttk.Frame(right)
        right_mode.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(right_mode, text="Right Pane:").pack(side=tk.LEFT)
        ttk.Radiobutton(
            right_mode,
            text="Registers + Flags",
            variable=self.side_mode_var,
            value="registers",
            command=self._on_side_mode_changed,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            right_mode,
            text="UART",
            variable=self.side_mode_var,
            value="uart",
            command=self._on_side_mode_changed,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            right_mode,
            text="ADC",
            variable=self.side_mode_var,
            value="adc",
            command=self._on_side_mode_changed,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.reg_panel = ttk.Frame(right)
        self.reg_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        ttk.Label(self.reg_panel, text="Registers + Flags").pack(anchor=tk.W)
        reg_body = ttk.Frame(self.reg_panel)
        reg_body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.reg_text = tk.Text(reg_body, wrap=tk.NONE, height=30, width=48)
        self.reg_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.reg_text.configure(state=tk.DISABLED)

        reg_scroll_y = ttk.Scrollbar(reg_body, orient=tk.VERTICAL, command=self.reg_text.yview)
        reg_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.reg_text.configure(yscrollcommand=reg_scroll_y.set)

        self.uart_panel = ttk.Frame(right)
        self._build_uart_panel()
        self.adc_panel = ttk.Frame(right)
        self._build_adc_panel()

        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        self.cycle_var = tk.StringVar(value="Cycles: 0 (since reset: 0)")
        self.cycle_lbl = ttk.Label(bottom, textvariable=self.cycle_var)
        self.cycle_lbl.pack(side=tk.LEFT)

        self.reset_var = tk.StringVar(value="Resets: 0 (watchdog: 0)")
        self.reset_lbl = ttk.Label(bottom, textvariable=self.reset_var)
        self.reset_lbl.pack(side=tk.LEFT, padx=(12, 0))

        self.reset_cycles_btn = ttk.Button(bottom, text="Reset Cycles", command=self._on_reset_cycles)
        self.reset_cycles_btn.pack(side=tk.LEFT, padx=(10, 0))

        self._on_left_mode_changed()

    def _build_uart_panel(self) -> None:
        self._uart_scroll_canvas = None

        selector_row = ttk.Frame(self.uart_panel)
        selector_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Label(selector_row, text="USART:").pack(side=tk.LEFT)
        for idx in range(4):
            ttk.Radiobutton(
                selector_row,
                text=str(idx),
                variable=self.uart_selected_var,
                value=idx,
                command=self._on_uart_channel_changed,
            ).pack(side=tk.LEFT, padx=(8, 0))

        content_host = ttk.Frame(self.uart_panel)
        content_host.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        for idx in range(4):
            frame = ttk.Labelframe(content_host, text=f"USART{idx}", padding=6)
            self.uart_frames.append(frame)

            bit_row = ttk.Frame(frame)
            bit_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
            bit_labels: dict[str, tk.Label] = {}
            for bit_name in ("TXEN", "RXEN", "RXC", "UDRE"):
                bit_value = tk.Label(
                    bit_row,
                    text=f"{bit_name}:0",
                    bg="#4B5563",
                    fg="#F9FAFB",
                    padx=6,
                    pady=2,
                    relief=tk.RIDGE,
                    bd=1,
                )
                bit_value.pack(side=tk.LEFT, padx=(0, 6))
                bit_labels[bit_name] = bit_value

            output_row = ttk.Frame(frame)
            output_row.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

            output = tk.Text(output_row, wrap=tk.WORD, height=6, width=48)
            output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            output.configure(state=tk.DISABLED)

            out_scroll = ttk.Scrollbar(output_row, orient=tk.VERTICAL, command=output.yview)
            out_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            output.configure(yscrollcommand=out_scroll.set)

            send_row = ttk.Frame(frame)
            send_row.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))

            ttk.Label(send_row, text="Send line:").pack(side=tk.TOP, anchor=tk.W)

            send_var = tk.StringVar(value="")
            send_entry = ttk.Entry(send_row, textvariable=send_var)
            send_entry.pack(side=tk.TOP, fill=tk.X, expand=True, pady=(2, 4))
            send_entry.bind("<Return>", lambda _e, i=idx: self._send_uart_line(i))

            suffix_row = ttk.Frame(send_row)
            suffix_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
            ttk.Label(suffix_row, text="Append:").pack(side=tk.LEFT)
            append_cr_var = tk.BooleanVar(value=False)
            append_lf_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(suffix_row, text="CR", variable=append_cr_var).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Checkbutton(suffix_row, text="LF", variable=append_lf_var).pack(side=tk.LEFT, padx=(6, 0))

            send_btn = ttk.Button(send_row, text="Send", command=lambda i=idx: self._send_uart_line(i))
            send_btn.pack(side=tk.TOP, anchor=tk.W)

            self.uart_text_widgets.append(output)
            self.uart_send_vars.append(send_var)
            self.uart_send_cr_vars.append(append_cr_var)
            self.uart_send_lf_vars.append(append_lf_var)
            self.uart_status_value_labels.append(bit_labels)

        self._show_selected_uart_panel()

    def _show_selected_uart_panel(self) -> None:
        selected = int(self.uart_selected_var.get())
        for idx, frame in enumerate(self.uart_frames):
            if idx == selected:
                if not frame.winfo_ismapped():
                    frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=4)
            else:
                frame.pack_forget()

    def _on_uart_channel_changed(self) -> None:
        self._show_selected_uart_panel()
        if self.side_mode_var.get() == "uart":
            self._update_uart_view()

    def _build_adc_panel(self) -> None:
        ttk.Label(self.adc_panel, text="ADC Inputs (0..1023)").pack(anchor=tk.W)
        body = ttk.Frame(self.adc_panel)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        for channel in range(16):
            row = ttk.Frame(body)
            row.pack(side=tk.TOP, fill=tk.X, pady=2)

            ttk.Label(row, text=f"ADC{channel:02d}", width=7).pack(side=tk.LEFT)

            value_var = tk.IntVar(value=0)
            slider = ttk.Scale(
                row,
                from_=0,
                to=1023,
                orient=tk.HORIZONTAL,
                variable=value_var,
                command=lambda _v, ch=channel: self._on_adc_slider_changed(ch),
            )
            slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 8))

            value_label = ttk.Label(row, text="0", width=5, anchor=tk.E)
            value_label.pack(side=tk.LEFT)

            state_label = ttk.Label(row, text="", width=16)
            state_label.pack(side=tk.LEFT, padx=(8, 0))

            self.adc_slider_vars.append(value_var)
            self.adc_slider_widgets.append(slider)
            self.adc_value_labels.append(value_label)
            self.adc_state_labels.append(state_label)

    def _event_in_uart_canvas(self, event: tk.Event) -> bool:
        if self.side_mode_var.get() != "uart":
            return False
        if self._uart_scroll_canvas is None:
            return False

        canvas = self._uart_scroll_canvas
        x0 = canvas.winfo_rootx()
        y0 = canvas.winfo_rooty()
        x1 = x0 + canvas.winfo_width()
        y1 = y0 + canvas.winfo_height()

        return x0 <= event.x_root < x1 and y0 <= event.y_root < y1

    def _on_uart_mousewheel(self, event: tk.Event) -> str | None:
        if not self._event_in_uart_canvas(event):
            return None
        if self._uart_scroll_canvas is None:
            return None

        steps = 0
        num = getattr(event, "num", None)
        if num == 4:
            steps = -3
        elif num == 5:
            steps = 3
        else:
            delta = int(getattr(event, "delta", 0))
            if delta != 0:
                steps = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)

        if steps != 0:
            self._uart_scroll_canvas.yview_scroll(steps, "units")
            return "break"
        return None

    def _set_uart_status_bit(self, index: int, bit_name: str, value: int) -> None:
        label = self.uart_status_value_labels[index][bit_name]
        label.configure(
            text=f"{bit_name}:{value}",
            bg="#1B7F3A" if value else "#4B5563",
            fg="#F9FAFB",
        )

    def _on_left_mode_changed(self) -> None:
        mode = self.left_mode_var.get()

        if mode in ("flash", "ram", "eeprom"):
            self._last_non_profile_left_mode = mode

        self.profile_mode_var.set(mode == "profile")

        if mode == "profile":
            self.flash_disasm_btn.pack_forget()
            self.flash_raw_btn.pack_forget()
            self.left_flash_btn.configure(
                variable=self.profile_space_var,
                value="flash",
                command=self._on_profile_space_changed,
            )
            self.left_ram_btn.configure(
                variable=self.profile_space_var,
                value="ram",
                command=self._on_profile_space_changed,
            )
            self.left_eeprom_btn.configure(
                variable=self.profile_space_var,
                value="eeprom",
                command=self._on_profile_space_changed,
            )
            if self.profile_space_var.get() not in ("flash", "ram", "eeprom"):
                self.profile_space_var.set("flash")
        else:
            self.left_flash_btn.configure(
                variable=self.left_mode_var,
                value="flash",
                command=self._on_left_mode_changed,
            )
            self.left_ram_btn.configure(
                variable=self.left_mode_var,
                value="ram",
                command=self._on_left_mode_changed,
            )
            self.left_eeprom_btn.configure(
                variable=self.left_mode_var,
                value="eeprom",
                command=self._on_left_mode_changed,
            )
            if not self.flash_disasm_btn.winfo_ismapped():
                self.flash_disasm_btn.pack(side=tk.LEFT, padx=(8, 0), before=self.left_ram_btn)
            if not self.flash_raw_btn.winfo_ismapped():
                self.flash_raw_btn.pack(side=tk.LEFT, padx=(8, 0), before=self.left_ram_btn)

        if mode == "flash":
            if self.flash_view_var.get() not in ("disasm", "raw"):
                self.flash_view_var.set(self._last_flash_view)
        else:
            current = self.flash_view_var.get()
            if current in ("disasm", "raw"):
                self._last_flash_view = current
            # Use a sentinel so neither FLASH sub-mode radio appears selected.
            self.flash_view_var.set("none")
        self._update_left_view()

    def _on_profile_space_changed(self) -> None:
        if self.left_mode_var.get() == "profile":
            self._update_left_view(preserve_disasm_scroll=True)

    def _on_flash_view_changed(self) -> None:
        current = self.flash_view_var.get()
        if current in ("disasm", "raw"):
            self._last_flash_view = current
        self.left_mode_var.set("flash")
        self._on_left_mode_changed()

    def _is_flash_disassembly_mode(self) -> bool:
        return self.left_mode_var.get() == "flash" and self.flash_view_var.get() == "disasm"

    @staticmethod
    def _memory_ascii(b: int) -> str:
        b &= 0xFF
        return chr(b) if 0x20 <= b <= 0x7E else "."

    def _format_memory_dump(self, data: bytes | bytearray, base_addr: int = 0) -> str:
        lines = ["ADDR   00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F  ASCII"]
        for offset in range(0, len(data), 16):
            chunk = data[offset : offset + 16]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            if len(chunk) < 16:
                hex_part += "   " * (16 - len(chunk))
            ascii_part = "".join(self._memory_ascii(b) for b in chunk)
            lines.append(f"{base_addr + offset:04X}:  {hex_part}  {ascii_part}")
        return "\n".join(lines) + "\n"

    def _flash_image_bytes(self) -> bytearray:
        image = bytearray()
        for word in self.emu.program:
            image.append(word & 0xFF)
            image.append((word >> 8) & 0xFF)
        return image

    def _update_memory_view(self, mode: str) -> None:
        preserve_scroll = self._last_left_render_mode == mode
        y_first = 0.0
        if preserve_scroll:
            y_first, _ = self.disasm_text.yview()

        focus_addr = None
        if self._pending_memory_focus_mode == mode:
            focus_addr = self._pending_memory_focus_addr

        if mode == "flash_raw":
            self.left_title_var.set("FLASH Viewer (Raw hex + ASCII)")
            image = self._flash_image_bytes()
            if image:
                text = self._format_memory_dump(image, 0x0000)
            else:
                text = "<no program loaded>\n"
        elif mode == "ram":
            self.left_title_var.set("RAM Viewer (0x0000..0x21FF) hex + ASCII")
            text = self._format_memory_dump(self.emu.data[: self.emu.DATA_SRAM_END + 1], 0x0000)
        else:
            self.left_title_var.set("EEPROM Viewer (0x0000..0x0FFF) hex + ASCII")
            text = self._format_memory_dump(self.emu.eeprom, 0x0000)

        self.disasm_text.configure(state=tk.NORMAL)
        self.disasm_text.delete("1.0", tk.END)
        self.disasm_text.insert(tk.END, text)
        self.disasm_text.configure(state=tk.DISABLED)
        if focus_addr is not None:
            focus_line = 2 + (focus_addr // 16)
            self._center_text_on_line(focus_line)
            self._pending_memory_focus_mode = None
            self._pending_memory_focus_addr = None
        elif preserve_scroll:
            self.disasm_text.yview_moveto(y_first)
        else:
            self.disasm_text.yview_moveto(0.0)

        if mode in ("ram", "eeprom") and self._profile_jump_highlight_space == mode and self._profile_jump_highlight_addr is not None:
            self._apply_persistent_highlight_to_line(2 + (self._profile_jump_highlight_addr // 16))
        else:
            self.disasm_text.tag_remove("jump_highlight", "1.0", tk.END)
        self._last_left_render_mode = mode

    @staticmethod
    def _lerp_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
        return (
            int(round(a[0] + (b[0] - a[0]) * t)),
            int(round(a[1] + (b[1] - a[1]) * t)),
            int(round(a[2] + (b[2] - a[2]) * t)),
        )

    def _profile_heat_color(self, level: int) -> str:
        level = max(0, min(self.PROFILE_HEAT_LEVELS, level))
        t = level / float(self.PROFILE_HEAT_LEVELS)
        c0 = (255, 255, 255)  # white
        c1 = (173, 216, 230)  # light blue
        c2 = (255, 165, 0)    # orange
        c3 = (255, 0, 0)      # red
        if t <= 1.0 / 3.0:
            rgb = self._lerp_rgb(c0, c1, t * 3.0)
        elif t <= 2.0 / 3.0:
            rgb = self._lerp_rgb(c1, c2, (t - 1.0 / 3.0) * 3.0)
        else:
            rgb = self._lerp_rgb(c2, c3, (t - 2.0 / 3.0) * 3.0)
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

    def _profile_heat_level(self, total: int, max_total: int) -> int:
        if total <= 0:
            return 0
        if max_total <= 0:
            return self.PROFILE_HEAT_LEVELS
        return min(self.PROFILE_HEAT_LEVELS, max(1, int(round((total / max_total) * self.PROFILE_HEAT_LEVELS))))

    def _profile_counts(self, space: str, addr: int) -> tuple[int, int]:
        if space == "ram":
            if 0 <= addr < len(self.emu.profile_ram_reads):
                return (self.emu.profile_ram_reads[addr], self.emu.profile_ram_writes[addr])
            return (0, 0)
        if space == "flash":
            if 0 <= addr < len(self.emu.profile_flash_reads):
                return (self.emu.profile_flash_reads[addr], self.emu.profile_flash_writes[addr])
            return (0, 0)
        if 0 <= addr < len(self.emu.profile_eeprom_reads):
            return (self.emu.profile_eeprom_reads[addr], self.emu.profile_eeprom_writes[addr])
        return (0, 0)

    def _profile_max_total(self, space: str) -> int:
        if space == "ram":
            return max((r + w for r, w in zip(self.emu.profile_ram_reads, self.emu.profile_ram_writes)), default=0)
        if space == "flash":
            return max((r + w for r, w in zip(self.emu.profile_flash_reads, self.emu.profile_flash_writes)), default=0)
        return max((r + w for r, w in zip(self.emu.profile_eeprom_reads, self.emu.profile_eeprom_writes)), default=0)

    def _profile_color_for_addr(self, space: str, addr: int) -> str:
        reads, writes = self._profile_counts(space, addr)
        total = reads + writes
        level = self._profile_heat_level(total, self._profile_max_total(space))
        return self._profile_heat_color(level)

    def _flash_profile_offsets(self, data_len: int) -> list[int]:
        if data_len <= 0:
            return []

        row_offsets: set[int] = set()
        for addr, (reads, writes) in enumerate(zip(self.emu.profile_flash_reads, self.emu.profile_flash_writes)):
            if reads or writes:
                row_offsets.add((addr // 16) * 16)

        pc_byte_addr = self.emu.pc * 2
        pc_row = (pc_byte_addr // 16) * 16
        for delta in range(-self.PROFILE_FLASH_CONTEXT_ROWS, self.PROFILE_FLASH_CONTEXT_ROWS + 1):
            offset = pc_row + (delta * 16)
            if 0 <= offset < data_len:
                row_offsets.add(offset)

        return sorted(row_offsets)

    def _insert_profile_region(
        self,
        title: str,
        data: bytes | bytearray,
        reads: list[int],
        writes: list[int],
        base_addr: int,
        space: str,
        max_total: int,
        row_offsets: list[int] | None = None,
    ) -> None:
        self.disasm_text.insert(tk.END, f"{title} Access Heatmap\n")
        self.disasm_text.insert(tk.END, "ADDR   " + " ".join(f"{i >> 4:X}" for i in range(16)) + "\n")
        self.disasm_text.insert(tk.END, "       " + " ".join(f"{i & 0xF:X}" for i in range(16)) + "\n")
        if row_offsets is None:
            row_offsets = list(range(0, len(data), 16))

        prev_offset = None
        for offset in row_offsets:
            if prev_offset is not None and offset > prev_offset + 16:
                self.disasm_text.insert(tk.END, "....\n")
            chunk = data[offset : offset + 16]
            line_no = int(self.disasm_text.index("end-1c").split(".")[0])
            line_addr = base_addr + offset
            self._profile_line_meta[line_no] = (space, line_addr, len(chunk))

            self.disasm_text.insert(tk.END, f"{line_addr:04X}:  ")
            for i, _ in enumerate(chunk):
                addr = line_addr + i
                total = (reads[addr] if addr < len(reads) else 0) + (writes[addr] if addr < len(writes) else 0)
                level = self._profile_heat_level(total, max_total)
                tag = f"profile_heat_{level}"
                self.disasm_text.insert(tk.END, " ", (tag,))
                if i < 15:
                    self.disasm_text.insert(tk.END, " ")
            if len(chunk) < 16:
                self.disasm_text.insert(tk.END, "  " * (16 - len(chunk)))
            self.disasm_text.insert(tk.END, "\n")
            prev_offset = offset
        self.disasm_text.insert(tk.END, "\n")

    def _update_profile_view(self) -> None:
        preserve_scroll = self._last_left_render_mode == "profile"
        y_first = 0.0
        if preserve_scroll:
            y_first, _ = self.disasm_text.yview()

        focus_space = self._pending_profile_focus_space
        focus_addr = self._pending_profile_focus_addr

        self.left_title_var.set("Access Profile (RAM/FLASH/EEPROM)")
        self._profile_line_meta = {}

        self.disasm_text.configure(state=tk.NORMAL)
        self.disasm_text.delete("1.0", tk.END)
        for level in range(self.PROFILE_HEAT_LEVELS + 1):
            color = self._profile_heat_color(level)
            self.disasm_text.tag_configure(f"profile_heat_{level}", background=color)

        selected = self.profile_space_var.get()
        if selected == "ram":
            max_total = max((r + w for r, w in zip(self.emu.profile_ram_reads, self.emu.profile_ram_writes)), default=0)
            self._insert_profile_region(
                "RAM",
                self.emu.data[: self.emu.DATA_SRAM_END + 1],
                self.emu.profile_ram_reads,
                self.emu.profile_ram_writes,
                0x0000,
                "ram",
                max_total,
            )
        elif selected == "eeprom":
            max_total = max(
                (r + w for r, w in zip(self.emu.profile_eeprom_reads, self.emu.profile_eeprom_writes)),
                default=0,
            )
            self._insert_profile_region(
                "EEPROM",
                self.emu.eeprom,
                self.emu.profile_eeprom_reads,
                self.emu.profile_eeprom_writes,
                0x0000,
                "eeprom",
                max_total,
            )
        else:
            flash_image = self._flash_image_bytes()
            max_total = max(
                (r + w for r, w in zip(self.emu.profile_flash_reads, self.emu.profile_flash_writes)),
                default=0,
            )
            self._insert_profile_region(
                "FLASH",
                flash_image,
                self.emu.profile_flash_reads,
                self.emu.profile_flash_writes,
                0x0000,
                "flash",
                max_total,
                row_offsets=self._flash_profile_offsets(len(flash_image)),
            )

        self.disasm_text.configure(state=tk.DISABLED)
        if focus_space == selected and focus_addr is not None:
            for line_no, meta in self._profile_line_meta.items():
                space, base_addr, count = meta
                if space == focus_space and base_addr <= focus_addr < (base_addr + count):
                    self._center_text_on_line(line_no)
                    break
            self._pending_profile_focus_space = None
            self._pending_profile_focus_addr = None
        elif preserve_scroll:
            self.disasm_text.yview_moveto(y_first)
        else:
            self.disasm_text.yview_moveto(0.0)
        self._last_left_render_mode = "profile"

    def _update_left_view(self, preserve_disasm_scroll: bool = False) -> None:
        mode = self.left_mode_var.get()
        if mode == "profile":
            self._update_profile_view()
            return
        if mode == "flash":
            if self.flash_view_var.get() == "disasm":
                self.left_title_var.set("FLASH Viewer (Disassembly)")
                self._update_disassembly_view(preserve_disasm_scroll=preserve_disasm_scroll)
            else:
                self._update_memory_view("flash_raw")
            return
        self._update_memory_view(mode)

    def _on_profile_toggle(self) -> None:
        try:
            if self.profile_mode_var.get():
                self._clear_persistent_jump_highlight()
                if self.left_mode_var.get() in ("flash", "ram", "eeprom"):
                    self._last_non_profile_left_mode = self.left_mode_var.get()
                if self._profile_return_space in ("flash", "ram", "eeprom"):
                    self.profile_space_var.set(self._profile_return_space)
                    self._pending_profile_focus_space = self._profile_return_space
                    self._pending_profile_focus_addr = self._profile_return_addr
                self.left_mode_var.set("profile")
                self._on_left_mode_changed()
                self._set_status("Showing access profile heatmap (white->blue->orange->red, scaled by max activity).")
            else:
                target = self._last_non_profile_left_mode
                if target not in ("flash", "ram", "eeprom"):
                    target = "flash"
                self.left_mode_var.set(target)
                self._on_left_mode_changed()
                self._set_status("Profile view closed.")
        except Exception as exc:
            self._set_status(f"Profile view failed: {exc}")

    def _hide_profile_tooltip(self) -> None:
        if self._profile_tip_window is not None:
            self._profile_tip_window.destroy()
            self._profile_tip_window = None
            self._profile_tip_label = None

    def _on_profile_leave(self, _event: tk.Event) -> None:
        self._hide_profile_tooltip()

    def _profile_addr_at_index(self, index: str) -> tuple[str, int] | None:
        line_str, col_str = index.split(".")
        line = int(line_str)
        col = int(col_str)
        meta = self._profile_line_meta.get(line)
        if meta is None:
            return None

        space, base_addr, count = meta
        byte_start_col = 7
        cell_stride = 2
        rel = col - byte_start_col
        if rel < 0:
            return None

        byte_index = rel // cell_stride
        in_cell = (rel % cell_stride) == 0
        if byte_index < 0 or byte_index >= count or not in_cell:
            return None
        return (space, base_addr + byte_index)

    def _open_profile_address(self, space: str, addr: int) -> None:
        self._profile_return_space = space
        self._profile_return_addr = addr
        self._profile_jump_highlight_space = space
        self._profile_jump_highlight_addr = addr
        self._profile_jump_highlight_color = self._profile_color_for_addr(space, addr)
        self.profile_mode_var.set(False)

        if space == "flash":
            self.left_mode_var.set("flash")
            self.flash_view_var.set("disasm")
            self._pending_flash_focus_pc = addr // 2
            self._set_status(f"Opened FLASH disassembly at 0x{addr:04X}.")
        else:
            self.left_mode_var.set(space)
            self._pending_memory_focus_mode = space
            self._pending_memory_focus_addr = addr
            self._set_status(f"Opened {space.upper()} view at 0x{addr:04X}.")

        self._on_left_mode_changed()

    def _on_profile_motion(self, event: tk.Event) -> None:
        if self.left_mode_var.get() != "profile":
            self._hide_profile_tooltip()
            return

        index = self.disasm_text.index(f"@{event.x},{event.y}")
        hit = self._profile_addr_at_index(index)
        if hit is None:
            self._hide_profile_tooltip()
            return

        space, addr = hit
        reads, writes = self._profile_counts(space, addr)
        total = reads + writes
        tip_text = f"{space.upper()} 0x{addr:04X} | total={total}  reads={reads}  writes={writes}"

        x = self.disasm_text.winfo_rootx() + event.x + 16
        y = self.disasm_text.winfo_rooty() + event.y + 12
        if self._profile_tip_window is None:
            self._profile_tip_window = tk.Toplevel(self.disasm_text)
            self._profile_tip_window.wm_overrideredirect(True)
            self._profile_tip_label = tk.Label(
                self._profile_tip_window,
                text=tip_text,
                justify=tk.LEFT,
                bg="#FFF8DC",
                relief=tk.SOLID,
                borderwidth=1,
                padx=6,
                pady=3,
            )
            self._profile_tip_label.pack()
        else:
            assert self._profile_tip_label is not None
            self._profile_tip_label.configure(text=tip_text)
        self._profile_tip_window.wm_geometry(f"+{x}+{y}")

    def _on_side_mode_changed(self) -> None:
        mode = self.side_mode_var.get()
        if mode == "uart":
            self.reg_panel.pack_forget()
            self.adc_panel.pack_forget()
            self.uart_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self._show_selected_uart_panel()
            self._update_uart_view()
            return

        if mode == "adc":
            self.reg_panel.pack_forget()
            self.uart_panel.pack_forget()
            self.adc_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self._update_adc_view()
            return

        self.uart_panel.pack_forget()
        self.adc_panel.pack_forget()
        self.reg_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._update_register_view()

    @staticmethod
    def _adc_channel_pin(channel: int) -> tuple[str, int]:
        if 0 <= channel <= 7:
            return ("F", channel)
        if 8 <= channel <= 15:
            return ("K", channel - 8)
        raise ValueError("ADC channel out of range")

    def _is_adc_channel_input_mode(self, channel: int) -> tuple[bool, str]:
        adcsra = self.emu.data[self.emu.DATA_ADCSRA]
        if ((adcsra >> self.emu.ADC_ADEN_BIT) & 1) == 0:
            return (False, "ADC disabled")

        port_name, bit = self._adc_channel_pin(channel)
        _, ddr_addr, _ = self.emu.GPIO_PORTS[port_name]
        ddr_value = self.emu.data[ddr_addr]
        if ((ddr_value >> bit) & 1) == 1:
            return (False, "Pin output")

        return (True, "Input")

    def _sync_adc_pending_values_from_emulator(self) -> None:
        self.adc_pending_values = [int(value & 0x3FF) for value in self.emu._adc_channel_values[:16]]

    def set_adc_input_value(self, channel: int, value: int) -> None:
        if not 0 <= channel < 16:
            raise ValueError(f"ADC channel out of range: {channel}")
        value = max(0, min(1023, int(value)))
        self.adc_pending_values[channel] = value
        if channel < len(self.adc_slider_vars):
            self.adc_slider_vars[channel].set(value)
            self.adc_value_labels[channel].configure(text=str(value))
        # CLI/UI injected ADC values should always seed the emulated channel source,
        # even when ADC is currently disabled or the pin is temporarily configured as output.
        self.emu.set_adc_channel_value(channel, value)

    def _on_adc_slider_changed(self, channel: int) -> None:
        value = int(round(self.adc_slider_vars[channel].get()))
        value = max(0, min(1023, value))
        self.adc_pending_values[channel] = value
        self.adc_slider_vars[channel].set(value)
        self.adc_value_labels[channel].configure(text=str(value))
        self.emu.set_adc_channel_value(channel, value)

    def _update_adc_view(self) -> None:
        for channel in range(16):
            value = self.adc_pending_values[channel]
            if int(round(self.adc_slider_vars[channel].get())) != value:
                self.adc_slider_vars[channel].set(value)
            self.adc_value_labels[channel].configure(text=str(value))

            # Keep emulated ADC source values synchronized with GUI values regardless
            # of transient ADEN/DDRx state so startup --adc arguments always take effect.
            if int(self.emu._adc_channel_values[channel] & 0x3FF) != value:
                self.emu.set_adc_channel_value(channel, value)

            enabled, state_text = self._is_adc_channel_input_mode(channel)
            if enabled:
                self.adc_state_labels[channel].configure(text=state_text, foreground="#1B7F3A")
            else:
                self.adc_state_labels[channel].configure(text=state_text, foreground="#6B7280")

    def _append_uart_output(self, index: int, text: str) -> None:
        widget = self.uart_text_widgets[index]
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, text)
        if float(widget.index("end-1c").split(".")[0]) > 1200:
            widget.delete("1.0", "200.0")
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    @staticmethod
    def _format_uart_bytes(data: list[int]) -> str:
        out: list[str] = []
        for b in data:
            b &= 0xFF
            if b == 0x0D:
                continue
            if b == 0x0A:
                out.append("\n")
            elif b == 0x09 or 0x20 <= b <= 0x7E:
                out.append(chr(b))
            else:
                out.append(f"\\x{b:02X}")
        return "".join(out)

    def _update_uart_view(self) -> None:
        for idx in range(4):
            uart = self.emu.get_uart(idx)
            ucsra = self.emu.data[uart.DATA_UCSRA]
            ucsrb = self.emu.data[uart.DATA_UCSRB]
            txen = (ucsrb >> uart.TXEN_BIT) & 1
            rxen = (ucsrb >> uart.RXEN_BIT) & 1
            rxc = (ucsra >> uart.RXC_BIT) & 1
            udre = (ucsra >> uart.UDRE_BIT) & 1
            self._set_uart_status_bit(idx, "TXEN", txen)
            self._set_uart_status_bit(idx, "RXEN", rxen)
            self._set_uart_status_bit(idx, "RXC", rxc)
            self._set_uart_status_bit(idx, "UDRE", udre)

            start = self.uart_tx_cursors[idx]
            end = len(uart.tx_log)
            if end <= start:
                continue

            chunk = uart.tx_log[start:end]
            self.uart_tx_cursors[idx] = end
            text = self._format_uart_bytes(chunk)
            if text:
                self._append_uart_output(idx, text)

    def _reset_uart_views(self) -> None:
        self.uart_tx_cursors = [0, 0, 0, 0]
        for idx in range(4):
            widget = self.uart_text_widgets[idx]
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.configure(state=tk.DISABLED)
            self.uart_send_vars[idx].set("")
            self._set_uart_status_bit(idx, "TXEN", 0)
            self._set_uart_status_bit(idx, "RXEN", 0)
            self._set_uart_status_bit(idx, "RXC", 0)
            self._set_uart_status_bit(idx, "UDRE", 0)

    def _send_uart_line(self, index: int) -> None:
        line = self.uart_send_vars[index].get()
        suffix = ""
        if self.uart_send_cr_vars[index].get():
            suffix += "\r"
        if self.uart_send_lf_vars[index].get():
            suffix += "\n"
        payload = (line + suffix).encode("ascii", errors="replace")
        for b in payload:
            self.emu.inject_uart_rx_byte(index, b)
        self._append_uart_output(index, f"\n>> {line}\n")
        self.uart_send_vars[index].set("")
        self._set_status(f"Injected line into USART{index} RX.")

    def _has_program(self) -> bool:
        return len(self.emu.program) > 0

    def _clear_disasm_cache(self) -> None:
        self._disasm_cache_rows = {}
        self._disasm_cache_pcs = []
        self._disasm_cache_index_by_pc = {}
        self._disasm_decoded_until_pc = 0
        self._disasm_loaded_start_pc = 0
        self._disasm_loaded_end_pc = 0

    @staticmethod
    def _extract_target_pc_from_disasm_text(text: str) -> int | None:
        match = re.search(r"0x([0-9A-Fa-f]{5})$", text)
        if not match:
            return None
        prefix = text[: match.start()].rstrip()
        if not prefix.startswith(("BR", "RJMP", "RCALL", "JMP", "CALL")):
            return None
        try:
            return int(match.group(1), 16)
        except ValueError:
            return None

    def _label_for_pc(self, pc: int) -> str | None:
        return self.disasm_labels.get(pc) or self.disasm_auto_labels.get(pc)

    def _append_next_disasm_cache_row(self) -> bool:
        pc = self._disasm_decoded_until_pc
        if pc < 0 or pc >= len(self.emu.program):
            return False

        words, text = self.emu._disassemble_one(pc)
        words = max(1, words)
        chunk = self.emu.program[pc : min(pc + words, len(self.emu.program))]
        byte_parts: list[str] = []
        for word in chunk:
            byte_parts.append(f"{word & 0xFF:02X}")
            byte_parts.append(f"{(word >> 8) & 0xFF:02X}")
        bytes_hex = " ".join(byte_parts)

        target_pc = self._extract_target_pc_from_disasm_text(text)
        if target_pc is not None and self._label_for_pc(target_pc) is None:
            self.disasm_auto_labels[target_pc] = f"loc_{target_pc:05X}"

        idx = len(self._disasm_cache_pcs)
        self._disasm_cache_pcs.append(pc)
        self._disasm_cache_index_by_pc[pc] = idx
        self._disasm_cache_rows[pc] = (words, bytes_hex, text)
        self._disasm_decoded_until_pc = min(len(self.emu.program), pc + words)
        return True

    def _ensure_disasm_pc_cached(self, pc_word: int) -> None:
        if not self._has_program():
            return
        target = max(0, min(pc_word, len(self.emu.program) - 1))
        while self._disasm_decoded_until_pc <= target:
            if not self._append_next_disasm_cache_row():
                break

    def _build_cached_disasm_rows(self, pcs: list[int]) -> list:
        rows = []
        for pc in pcs:
            words, bytes_hex, text = self._disasm_cache_rows[pc]
            rows.append(
                SimpleNamespace(
                    pc=pc,
                    words=words,
                    bytes_hex=bytes_hex,
                    text=text,
                    is_pc=(pc == self.emu.pc),
                )
            )
        return rows

    def _get_cached_disassembly_window(self, center_pc: int, before: int, after: int) -> list:
        if not self._has_program():
            return []

        center_pc = max(0, min(center_pc, len(self.emu.program) - 1))
        self._ensure_disasm_pc_cached(center_pc)
        if not self._disasm_cache_pcs:
            return []

        center_idx = self._disasm_cache_index_by_pc.get(center_pc)
        if center_idx is None:
            center_idx = max(0, bisect.bisect_right(self._disasm_cache_pcs, center_pc) - 1)

        target_end_idx = center_idx + max(after, 0)
        while len(self._disasm_cache_pcs) <= target_end_idx:
            if not self._append_next_disasm_cache_row():
                break

        start_idx = max(0, center_idx - max(before, 0))
        end_idx = min(len(self._disasm_cache_pcs), target_end_idx + 1)
        return self._build_cached_disasm_rows(self._disasm_cache_pcs[start_idx:end_idx])

    def _get_cached_disassembly_rows_from(self, start_pc: int, count: int) -> list:
        if not self._has_program() or count <= 0:
            return []

        start_pc = max(0, min(start_pc, len(self.emu.program) - 1))
        self._ensure_disasm_pc_cached(start_pc)
        if not self._disasm_cache_pcs:
            return []

        start_idx = bisect.bisect_left(self._disasm_cache_pcs, start_pc)
        target_end_idx = start_idx + count
        while len(self._disasm_cache_pcs) < target_end_idx:
            if not self._append_next_disasm_cache_row():
                break

        end_idx = min(len(self._disasm_cache_pcs), target_end_idx)
        return self._build_cached_disasm_rows(self._disasm_cache_pcs[start_idx:end_idx])

    def _get_cached_disassembly_range(self, start_pc: int, end_pc: int) -> list:
        if not self._has_program() or end_pc <= start_pc:
            return []

        start_pc = max(0, min(start_pc, len(self.emu.program) - 1))
        end_pc = max(start_pc, min(end_pc, len(self.emu.program)))
        self._ensure_disasm_pc_cached(max(0, end_pc - 1))
        if not self._disasm_cache_pcs:
            return []

        start_idx = bisect.bisect_left(self._disasm_cache_pcs, start_pc)
        end_idx = bisect.bisect_left(self._disasm_cache_pcs, end_pc)
        return self._build_cached_disasm_rows(self._disasm_cache_pcs[start_idx:end_idx])

    @staticmethod
    def _find_matching_elf_path(program_path: str) -> Path | None:
        p = Path(program_path)
        if p.suffix.lower() not in (".hex", ".hx"):
            return None
        candidate = p.with_suffix(".elf")
        return candidate if candidate.is_file() else None

    def _load_disasm_labels_from_elf(self, elf_path: Path) -> tuple[dict[int, str], str]:
        cmd = ["avr-nm", "-n", "--defined-only", str(elf_path)]
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError:
            return {}, "avr-nm not found; disassembly labels disabled."
        except subprocess.CalledProcessError as exc:
            return {}, f"Failed to read ELF symbols: {exc}"

        labels_by_pc: dict[int, list[tuple[int, str]]] = {}
        for line in proc.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            addr_hex, sym_type, name = parts[0], parts[1], parts[2]
            if sym_type not in ("t", "T", "w", "W"):
                continue
            try:
                byte_addr = int(addr_hex, 16)
            except ValueError:
                continue
            pc_word = byte_addr // 2
            # Prefer strong text symbols over weak aliases at the same address.
            rank = 0 if sym_type in ("t", "T") else 1
            labels_by_pc.setdefault(pc_word, []).append((rank, name))

        merged: dict[int, str] = {}
        for pc_word, ranked_names in labels_by_pc.items():
            ranked_unique = sorted(set(ranked_names), key=lambda item: (item[0], len(item[1]), item[1]))
            merged[pc_word] = ranked_unique[0][1]

        return merged, f"Loaded {len(merged)} disassembly label address(es) from {elf_path.name}."

    def _format_disasm_rows(
        self,
        rows: list,
        focus_pc: int | None = None,
        highlight_pc: int | None = None,
    ) -> tuple[str, int | None, int | None]:
        rendered: list[str] = []
        pc_line_no: int | None = None
        highlight_line_no: int | None = None
        for row in rows:
            label = self._label_for_pc(row.pc)
            if label:
                rendered.append(f"{label}:")
            rendered.append(self._format_disasm_row(row))
            if focus_pc is not None and row.pc == focus_pc:
                pc_line_no = len(rendered)
            elif focus_pc is None and row.is_pc:
                pc_line_no = len(rendered)
            if highlight_pc is not None and row.pc == highlight_pc:
                highlight_line_no = len(rendered)
        return "\n".join(rendered) + "\n", pc_line_no, highlight_line_no

    def _center_text_on_line(self, line_no: int) -> None:
        self.disasm_text.update_idletasks()
        if line_no <= 0:
            return

        line_index = f"{line_no}.0"
        self.disasm_text.see(line_index)
        self.disasm_text.update_idletasks()

        line_info = self.disasm_text.dlineinfo(line_index)
        if line_info is None:
            return

        line_y = line_info[1]
        line_height = max(1, line_info[3])
        target_y = max(0, (self.disasm_text.winfo_height() // 2) - (line_height // 2))
        delta_pixels = line_y - target_y
        if delta_pixels == 0:
            return

        delta_lines = int(round(delta_pixels / line_height))
        if delta_lines != 0:
            self.disasm_text.yview_scroll(delta_lines, "units")

    def _center_disasm_on_line(self, line_no: int) -> None:
        self._center_text_on_line(line_no)

    def _apply_persistent_highlight_to_line(self, line_no: int) -> None:
        if line_no <= 0:
            return
        color = self._profile_jump_highlight_color or "#FFF2A8"
        self.disasm_text.tag_configure("jump_highlight", background=color)
        self.disasm_text.tag_remove("jump_highlight", "1.0", tk.END)
        self.disasm_text.tag_add("jump_highlight", f"{line_no}.0", f"{line_no}.end")

    def _clear_persistent_jump_highlight(self) -> None:
        self._profile_jump_highlight_space = None
        self._profile_jump_highlight_addr = None
        self._profile_jump_highlight_color = None
        self.disasm_text.tag_remove("jump_highlight", "1.0", tk.END)

    def _sync_run_toggle_button(self) -> None:
        self.run_toggle_btn.configure(text="Stop" if self.running else "Run")

    def _refresh_slider_value(self) -> int:
        return int(round(self.refresh_rate_scale_var.get()))

    def _is_realtime_refresh(self) -> bool:
        return self._refresh_slider_value() <= self.REFRESH_SLIDER_REALTIME

    def _get_periodic_refresh_interval_seconds(self) -> float:
        slider_value = self._refresh_slider_value()
        if slider_value <= self.REFRESH_SLIDER_REALTIME:
            return 0.0
        return max(0.1, (slider_value - 1) / 10.0)

    def _on_refresh_rate_changed(self, _value: str | None = None) -> None:
        slider_value = self._refresh_slider_value()
        self.refresh_rate_scale_var.set(float(slider_value))
        if slider_value <= self.REFRESH_SLIDER_REALTIME:
            self.refresh_rate_label_var.set("GUI Update: Realtime")
        else:
            self.refresh_rate_label_var.set(f"GUI Update: {(slider_value - 1) / 10.0:.1f}s")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _cancel_pending_run(self) -> None:
        if self.run_after_id is not None:
            self.root.after_cancel(self.run_after_id)
            self.run_after_id = None

    def _on_load(self) -> None:
        path = filedialog.askopenfilename(
            title="Load AVR Program",
            filetypes=[
                ("AVR images", "*.hex *.hx *.bin"),
                ("Hex", "*.hex *.hx"),
                ("Binary", "*.bin"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        self._load_program_path(path)

    def _load_program_path(self, path: str, show_error_dialog: bool = True) -> bool:
        self._on_stop()
        self.disasm_labels = {}
        self.disasm_auto_labels = {}
        self._clear_disasm_cache()
        try:
            self.emu.load_program_file(path)
            self.emu.reset()
        except Exception as exc:
            if show_error_dialog:
                messagebox.showerror("Load failed", str(exc))
            else:
                self._refresh_idle_views(status_text=f"Load failed: {exc}")
            return False

        self.loaded_path = path
        self.breakpoints.clear()
        self._reset_uart_views()
        self._sync_adc_pending_values_from_emulator()
        self.path_var.set(Path(path).name)
        self.path_tooltip.text = path

        status_text = "Program loaded and reset."
        elf_path = self._find_matching_elf_path(path)
        if elf_path is not None:
            labels, label_status = self._load_disasm_labels_from_elf(elf_path)
            self.disasm_labels = labels
            status_text = f"{status_text} {label_status}"

        self._refresh_idle_views(status_text=status_text)
        return True

    def _on_step(self) -> None:
        if self.running:
            return
        if not self._has_program():
            self._set_status("No program loaded.")
            return
        if self.emu.halted:
            self._refresh_idle_views(status_text=self.emu.halt_reason or "CPU halted.")
            return

        try:
            n = int(self.step_count_var.get().strip())
        except ValueError:
            self._set_status("Step count must be an integer.")
            return
        if n <= 0:
            self._set_status("Step count must be > 0.")
            return

        result = None
        try:
            for _ in range(n):
                if self.emu.halted:
                    break
                result = self.emu.step()
                if self.emu.pc in self.breakpoints:
                    break
        except NotImplementedError as exc:
            self._refresh_idle_views(status_text=str(exc))
            return

        if self.emu.halted:
            self._refresh_idle_views(status_text=self.emu.halt_reason or "CPU halted.")
            return
        if self.emu.pc in self.breakpoints:
            self._refresh_idle_views(status_text=f"Breakpoint at PC=0x{self.emu.pc:05X}")
            return
        if result is None:
            self._refresh_idle_views(status_text="No step executed.")
            return
        if n == 1:
            self._refresh_idle_views(status_text=f"Stepped: {result.description}")
        else:
            self._refresh_idle_views(status_text=f"Stepped {n} instruction(s).")

    def _on_run_toggle(self) -> None:
        if self.running:
            self._on_stop()
            return
        self._on_run_n(-1)

    def _on_run_n(self, n_override: int | None = None) -> None:
        if not self._has_program():
            self._set_status("No program loaded.")
            return
        if self.running:
            return

        if n_override is None:
            self._set_status("Use Run for continuous execution.")
            return
        n = n_override

        if n == -1:
            self.run_continuous = True
            self.steps_remaining = -1
            run_label = "continuously"
        elif n > 0:
            self.run_continuous = False
            self.steps_remaining = n
            run_label = f"{n} step(s)"
        else:
            self._set_status("Run count must be > 0, or -1 for continuous run.")
            return

        if self.emu.pc in self.breakpoints:
            self._refresh_idle_views(status_text=f"Breakpoint at PC=0x{self.emu.pc:05X}")
            return

        self.running = True
        self._run_tick_counter = 0
        self._last_run_periodic_refresh_time = time.monotonic()
        self._sync_run_toggle_button()
        self._set_status(f"Running {run_label}...")
        self._run_tick()

    def _run_tick(self) -> None:
        if not self.running:
            return

        self._run_tick_counter += 1

        executed = 0
        stop_reason = "Paused."
        tick_step_chunk = self.step_chunk_continuous if self.run_continuous else self.step_chunk
        tick_after_delay_ms = (
            self.run_after_delay_ms_continuous if self.run_continuous else self.run_after_delay_ms
        )
        if self.run_continuous and (self._run_tick_counter % self.run_yield_every_ticks_continuous == 0):
            tick_after_delay_ms = self.run_after_delay_ms_continuous_yield
        try:
            while executed < tick_step_chunk and self.running:
                if self.emu.halted:
                    stop_reason = self.emu.halt_reason or "CPU halted."
                    self.running = False
                    break
                if self.emu.pc in self.breakpoints:
                    stop_reason = f"Breakpoint at PC=0x{self.emu.pc:05X}"
                    self.running = False
                    break
                if (not self.run_continuous) and self.steps_remaining <= 0:
                    stop_reason = "Run complete."
                    self.running = False
                    break

                self.emu.step()
                executed += 1
                if not self.run_continuous:
                    self.steps_remaining -= 1

            self._update_summary_labels()

            if self._is_realtime_refresh():
                # Full view refresh every tick is useful for live inspection,
                # but significantly slows execution.
                self._refresh_idle_views()
            else:
                now = time.monotonic()
                interval_s = self._get_periodic_refresh_interval_seconds()
                if (now - self._last_run_periodic_refresh_time) >= interval_s:
                    self._last_run_periodic_refresh_time = now
                    self._refresh_idle_views()

        except NotImplementedError as exc:
            stop_reason = str(exc)
            self.running = False
        except Exception as exc:
            import traceback
            stop_reason = f"Exception: {type(exc).__name__}: {exc}"
            print(f"ERROR in _run_tick: {stop_reason}")
            traceback.print_exc()
            self.running = False

        if not self.running:
            self._cancel_pending_run()
            self._sync_run_toggle_button()
            self._refresh_idle_views(status_text=stop_reason)
            return

        # Keep UI responsive; continuous mode intentionally yields a little more often.
        self.run_after_id = self.root.after(tick_after_delay_ms, self._run_tick)

    def _on_stop(self) -> None:
        if self.running:
            self.running = False
            self._cancel_pending_run()
        self.run_continuous = False
        self._sync_run_toggle_button()
        self._refresh_idle_views(status_text="Stopped.")

    def _on_restart(self) -> None:
        self._on_stop()
        if self._has_program():
            self.emu.reset()
            self._reset_uart_views()
            self._sync_adc_pending_values_from_emulator()
            self._refresh_idle_views(status_text="CPU reset.")
        else:
            self._refresh_idle_views(status_text="No program loaded.")

    def _on_reset_cycles(self) -> None:
        self.emu.cycles = 0
        self.emu.total_cycles = 0
        self._update_summary_labels()
        self._set_status("Cycles reset to 0.")

    def _update_summary_labels(self) -> None:
        self.cycle_var.set(f"Cycles: {self.emu.total_cycles:,} (since reset: {self.emu.cycles:,})")
        self.reset_var.set(
            f"Resets: {self.emu.reset_count:,} (watchdog: {self.emu.watchdog_reset_count:,})"
        )

    def _refresh_idle_views(self, status_text: str = "", preserve_disasm_scroll: bool = False) -> None:
        self._update_left_view(preserve_disasm_scroll=preserve_disasm_scroll)
        if self.side_mode_var.get() == "uart":
            self._update_uart_view()
        elif self.side_mode_var.get() == "adc":
            self._update_adc_view()
        else:
            self._update_register_view()
        self._update_summary_labels()
        if status_text:
            self._set_status(status_text)

    def _format_disasm_row(self, row) -> str:
        bp = "*" if row.pc in self.breakpoints else " "
        marker = "->" if row.is_pc else "  "
        rendered_text = self._rewrite_disasm_target_to_label(row.text)
        return f"{bp}{marker} {row.pc:05X}: {row.bytes_hex:<11}  {rendered_text}"

    def _rewrite_disasm_target_to_label(self, text: str) -> str:
        target_pc = self._extract_target_pc_from_disasm_text(text)
        if target_pc is None:
            return text

        match = re.search(r"0x([0-9A-Fa-f]{5})$", text)
        if not match:
            return text
        prefix = text[: match.start()].rstrip()

        label = self._label_for_pc(target_pc)
        if not label:
            return text
        return f"{prefix} {label} ; {match.group(0)}"

    @staticmethod
    def _extract_pc_from_line(line_text: str) -> int | None:
        match = re.search(r"\b([0-9A-Fa-f]{5}):", line_text)
        if not match:
            return None
        try:
            return int(match.group(1), 16)
        except ValueError:
            return None

    def _on_disasm_click(self, event: tk.Event) -> None:
        if self.left_mode_var.get() == "profile":
            if self.running:
                return
            hit = self._profile_addr_at_index(self.disasm_text.index(f"@{event.x},{event.y}"))
            if hit is None:
                return
            self._open_profile_address(*hit)
            return
        if not self._is_flash_disassembly_mode():
            return
        if self.running:
            return

        line_index = self.disasm_text.index(f"@{event.x},{event.y}")
        line_start = f"{line_index} linestart"
        line_end = f"{line_index} lineend"
        line_text = self.disasm_text.get(line_start, line_end)

        pc = self._extract_pc_from_line(line_text)
        if pc is None:
            return

        if pc in self.breakpoints:
            self.breakpoints.remove(pc)
            status = f"Breakpoint removed: 0x{pc:05X}"
        else:
            self.breakpoints.add(pc)
            status = f"Breakpoint added: 0x{pc:05X}"

        self._refresh_idle_views(status_text=status, preserve_disasm_scroll=True)

    def _on_disasm_scroll(self, *args: str) -> None:
        self.disasm_text.yview(*args)
        if not self._is_flash_disassembly_mode():
            return
        self._maybe_extend_disassembly()

    def _on_disasm_yview(self, first: str, last: str) -> None:
        if self._disasm_scrollbar is not None:
            self._disasm_scrollbar.set(first, last)
        if not self._is_flash_disassembly_mode():
            return
        self._maybe_extend_disassembly(float(first), float(last))

    def _on_disasm_view_event(self, _event: tk.Event) -> None:
        if not self._is_flash_disassembly_mode():
            return
        # Run after the default scroll/key handler so yview values are current.
        self.root.after_idle(self._maybe_extend_disassembly)

    def _maybe_extend_disassembly(self, y_first: float | None = None, y_last: float | None = None) -> None:
        if not self._is_flash_disassembly_mode():
            return
        if self._disasm_rebuilding_view:
            return
        if self._disasm_appending or not self._has_program():
            return
        if self.running:
            return

        if y_first is None or y_last is None:
            y_first, y_last = self.disasm_text.yview()

        if y_first <= 0.03 and self._disasm_loaded_start_pc > 0:
            self._prepend_disassembly_chunk(max_rows=140)
            return

        if y_last < 0.97:
            return

        self._append_disassembly_chunk(max_rows=140)

    def _prepend_disassembly_chunk(self, max_rows: int = 140) -> None:
        if not self._is_flash_disassembly_mode():
            return
        if self._disasm_loaded_start_pc <= 0:
            return

        start_pc = max(0, self._disasm_loaded_start_pc - max_rows)
        rows = self._get_cached_disassembly_window(
            center_pc=self._disasm_loaded_start_pc,
            before=self._disasm_loaded_start_pc - start_pc,
            after=0,
        )
        rows = [row for row in rows if row.pc < self._disasm_loaded_start_pc]
        if not rows:
            self._disasm_loaded_start_pc = 0
            return

        self._disasm_appending = True
        try:
            top_line_before = int(float(self.disasm_text.index("@0,0").split(".")[0]))
            text, _, _ = self._format_disasm_rows(rows)
            inserted_lines = text.count("\n")

            self.disasm_text.configure(state=tk.NORMAL)
            self.disasm_text.insert("1.0", text)
            self.disasm_text.configure(state=tk.DISABLED)
            self._disasm_loaded_start_pc = rows[0].pc

            total_lines = int(float(self.disasm_text.index("end-1c").split(".")[0]))
            new_top_line = min(max(1, top_line_before + inserted_lines), max(total_lines, 1))
            y_first = (new_top_line - 1) / max(total_lines - 1, 1)
            self.disasm_text.yview_moveto(max(0.0, min(1.0, y_first)))
        finally:
            self._disasm_appending = False

    def _append_disassembly_chunk(self, max_rows: int = 140) -> None:
        if not self._is_flash_disassembly_mode():
            return
        if self._disasm_loaded_end_pc >= len(self.emu.program):
            return

        self._disasm_appending = True
        try:
            rows = self._get_cached_disassembly_rows_from(self._disasm_loaded_end_pc, max_rows)
            if not rows:
                self._disasm_loaded_end_pc = len(self.emu.program)
                return

            text, _, _ = self._format_disasm_rows(rows)
            if self._disasm_loaded_start_pc == self._disasm_loaded_end_pc:
                self._disasm_loaded_start_pc = rows[0].pc
            self._disasm_loaded_end_pc = rows[-1].pc + rows[-1].words

            self.disasm_text.configure(state=tk.NORMAL)
            self.disasm_text.insert(tk.END, text)
            self.disasm_text.configure(state=tk.DISABLED)
        finally:
            self._disasm_appending = False

    def _update_disassembly_view(self, preserve_disasm_scroll: bool = False) -> None:
        if not self._is_flash_disassembly_mode():
            return

        focus_pc = self._pending_flash_focus_pc
        highlight_pc = None
        if self._profile_jump_highlight_space == "flash" and self._profile_jump_highlight_addr is not None:
            highlight_pc = self._profile_jump_highlight_addr // 2

        # While not preserving manual scroll, render a symmetric window around the
        # current PC so the label-aware centering logic can keep it visually centered.
        preserve_scroll = preserve_disasm_scroll or (self.running and self._is_realtime_refresh())
        y_first = 0.0
        if preserve_scroll:
            y_first, _ = self.disasm_text.yview()

        if not self._has_program():
            text = "<no program loaded>\n"
            self._disasm_loaded_end_pc = 0
            self._disasm_loaded_start_pc = 0
            pc_line_no = None
            highlight_line_no = None
        else:
            if preserve_disasm_scroll and self._disasm_loaded_end_pc > self._disasm_loaded_start_pc:
                rows = self._get_cached_disassembly_range(
                    self._disasm_loaded_start_pc,
                    self._disasm_loaded_end_pc,
                )
                if not rows:
                    rows = self._get_cached_disassembly_window(
                        center_pc=self.emu.pc,
                        before=self.DISASM_CONTEXT_ROWS,
                        after=self.DISASM_CONTEXT_ROWS,
                    )
            else:
                rows = self._get_cached_disassembly_window(
                    center_pc=focus_pc if focus_pc is not None else self.emu.pc,
                    before=self.DISASM_CONTEXT_ROWS,
                    after=self.DISASM_CONTEXT_ROWS,
                )
            text, pc_line_no, highlight_line_no = self._format_disasm_rows(
                rows,
                focus_pc=focus_pc,
                highlight_pc=highlight_pc,
            )
            if rows:
                self._disasm_loaded_start_pc = rows[0].pc
                self._disasm_loaded_end_pc = rows[-1].pc + rows[-1].words
            else:
                self._disasm_loaded_start_pc = 0
                self._disasm_loaded_end_pc = 0
                highlight_line_no = None

        self.disasm_text.configure(state=tk.NORMAL)
        self._disasm_rebuilding_view = True
        try:
            self.disasm_text.delete("1.0", tk.END)
            self.disasm_text.insert(tk.END, text)
            self.disasm_text.configure(state=tk.DISABLED)

            # Preserve manual scroll while running; otherwise center on current PC
            # before re-enabling lazy top/bottom extension callbacks.
            if preserve_scroll:
                self.disasm_text.yview_moveto(y_first)
            elif self._has_program():
                if pc_line_no is not None:
                    self._center_disasm_on_line(pc_line_no)
                else:
                    self.disasm_text.yview_moveto(0.0)

            if highlight_line_no is not None:
                self._apply_persistent_highlight_to_line(highlight_line_no)
            else:
                self.disasm_text.tag_remove("jump_highlight", "1.0", tk.END)
        finally:
            self._disasm_rebuilding_view = False
        self._pending_flash_focus_pc = None
        self._last_left_render_mode = "flash_disasm"

    def _update_register_view(self) -> None:
        snap = self.emu.snapshot_state()
        regs = snap["regs"]
        flags = snap["flags"]

        def bits8(value: int) -> str:
            return format(value & 0xFF, "08b")

        def io_level(ddr: int, port: int, pin: int) -> int:
            # Effective pin level: output bits follow PORT, input bits follow PIN.
            return ((port & ddr) | (pin & (~ddr & 0xFF))) & 0xFF

        lines = []
        lines.append(f"PC: 0x{snap['pc']:05X}")
        lines.append(f"SP: 0x{snap['sp']:04X}")
        lines.append(f"SREG: 0b{snap['sreg']:08b}")
        lines.append(f"HALTED: {snap['halted']}")
        lines.append("")
        lines.append("FLAGS: " + " ".join(f"{name}={flags[name]}" for name in ["I", "T", "H", "S", "V", "N", "Z", "C"]))
        lines.append("")
        lines.append("CORE I/O:")
        lines.append(
            "  ".join(
                [
                    f"EIND=0x{self.emu.data[self.emu.DATA_EIND]:02X}",
                    f"RAMPZ=0x{self.emu.data[self.emu.DATA_RAMPZ]:02X}",
                    f"SREG=0x{snap['sreg'] & 0xFF:02X}",
                ]
            )
        )
        lines.append("")

        for row in range(0, 32, 4):
            chunk = "  ".join(f"r{idx:02d}=0x{regs[idx]:02X}" for idx in range(row, row + 4))
            lines.append(chunk)

        lines.append("")
        lines.append("PORTS:")
        for name, (pin_addr, ddr_addr, port_addr) in self.emu.GPIO_PORTS.items():
            pin = self.emu.data[pin_addr]
            ddr = self.emu.data[ddr_addr]
            port = self.emu.data[port_addr]
            lvl = io_level(ddr, port, pin)
            lines.append(
                f"P{name} PIN={bits8(pin)} DDR={bits8(ddr)} PORT={bits8(port)} LVL={bits8(lvl)}"
            )

        self.reg_text.configure(state=tk.NORMAL)
        self.reg_text.delete("1.0", tk.END)
        self.reg_text.insert(tk.END, "\n".join(lines) + "\n")
        self.reg_text.configure(state=tk.DISABLED)


def main() -> None:
    parser = argparse.ArgumentParser(description="ATmega2560 Simulator GUI")
    parser.add_argument(
        "image",
        nargs="?",
        help="Optional program image to load at startup (.hex/.hx/.bin)",
    )
    parser.add_argument(
        "--load",
        dest="load_path",
        help="Program image path to load at startup (.hex/.hx/.bin)",
    )
    parser.add_argument(
        "--adc",
        dest="adc_values",
        action="append",
        default=[],
        metavar="CHANNEL=VALUE[,CHANNEL=VALUE...]",
        help="Set GUI ADC slider startup value, e.g. --adc 0=512 or --adc 0=512,ADC15=1023 (repeatable)",
    )
    args = parser.parse_args()

    root = tk.Tk()
    app = EmulatorGUI(root)

    adc_pairs: list[tuple[int, int]] = []
    for spec in args.adc_values:
        for item in spec.split(","):
            text = item.strip()
            if not text:
                continue
            if "=" not in text:
                parser.error(f"Invalid --adc value '{text}'. Use CHANNEL=VALUE.")
            channel_text, value_text = text.split("=", 1)
            channel_text = channel_text.strip().lower()
            if channel_text.startswith("adc"):
                channel_text = channel_text[3:]
            try:
                channel = int(channel_text, 10)
            except ValueError:
                parser.error(f"Invalid ADC channel in '{text}'. Use 0..15 or ADC0..ADC15.")
            try:
                value = int(value_text.strip(), 10)
            except ValueError:
                parser.error(f"Invalid ADC value in '{text}'. Use 0..1023.")
            if not 0 <= channel <= 15:
                parser.error(f"ADC channel out of range in '{text}'. Use 0..15.")
            if not 0 <= value <= 1023:
                parser.error(f"ADC value out of range in '{text}'. Use 0..1023.")
            adc_pairs.append((channel, value))

    startup_path = args.load_path if args.load_path else args.image

    def _startup() -> None:
        if startup_path and not app._load_program_path(startup_path, show_error_dialog=True):
            return
        for channel, value in adc_pairs:
            app.set_adc_input_value(channel, value)
        if adc_pairs:
            app._refresh_idle_views(
                status_text=f"Applied {len(adc_pairs)} ADC startup value(s).",
                preserve_disasm_scroll=True,
            )

    if startup_path:
        # Schedule startup actions after widgets are fully created.
        root.after(0, _startup)
    elif adc_pairs:
        root.after(0, _startup)

    root.mainloop()


if __name__ == "__main__":
    main()
