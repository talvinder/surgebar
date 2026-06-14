"""Custom NSPopover surge panel — the polished, self-drawn UI.

A native macOS menu (NSMenu) can only render text. To get the iStat-Menus /
CleanShot look — a live CPU graph, colored per-process bars, action buttons — the
app draws its own view in AppKit. This module does that with one custom NSView
inside an NSPopover.

Why NSPopover (not a raw borderless window): it hands us positioning, the arrow,
click-outside dismissal, and dark-mode material for free, so there's far less to
get wrong. The view draws on a clear background so the popover's vibrant material
shows through, and uses semantic NSColors (labelColor, systemRed, …) so light and
dark mode are automatic.

PyObjC note: only the genuine Objective-C entry points (init…, isFlipped,
drawRect_, mouseDown_, statusClicked_) are left as selectors. Every Python-only
helper is marked @objc.python_method so PyObjC doesn't try to turn names like
`_draw_button` into selectors with mismatched argument counts.

Everything here is wrapped defensively by the caller: if popover setup throws, the
app falls back to the plain menu. The fancy UI can never break the tool.
"""

from __future__ import annotations

import AppKit
import objc
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

PANEL_WIDTH = 340.0
PAD = 16.0
ROW_H = 34.0
BAR_H = 5.0


def _heat_color(cpu):
    if cpu >= 85:
        return AppKit.NSColor.systemRedColor()
    if cpu >= 60:
        return AppKit.NSColor.systemOrangeColor()
    return AppKit.NSColor.systemGreenColor()


def _font(size, bold):
    if bold:
        return AppKit.NSFont.systemFontOfSize_weight_(size, AppKit.NSFontWeightMedium)
    return AppKit.NSFont.systemFontOfSize_(size)


def _text(s, size, color, bold=False):
    attrs = {AppKit.NSFontAttributeName: _font(size, bold), AppKit.NSForegroundColorAttributeName: color}
    return AppKit.NSAttributedString.alloc().initWithString_attributes_(s, attrs)


def _draw_text_clipped(s, size, color, x, y, w, h, bold=False):
    """Draw single-line text that truncates with an ellipsis inside [x, w] — never overflows."""
    para = AppKit.NSMutableParagraphStyle.alloc().init()
    para.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    attrs = {
        AppKit.NSFontAttributeName: _font(size, bold),
        AppKit.NSForegroundColorAttributeName: color,
        AppKit.NSParagraphStyleAttributeName: para,
    }
    AppKit.NSAttributedString.alloc().initWithString_attributes_(s, attrs).drawInRect_(
        NSMakeRect(x, y, w, h)
    )


class SurgePanelView(AppKit.NSView):
    """Draws the whole panel and hit-tests its action buttons."""

    def initWithDelegate_(self, delegate):
        self = objc.super(SurgePanelView, self).init()
        if self is None:
            return None
        self._delegate = delegate
        self._snapshot = None
        self._cpu_values = []
        self._actions = []
        self._diagnosing = False
        self._hit_regions = []  # list of (rect, kind, payload)
        return self

    def isFlipped(self):
        return True  # top-left origin makes the layout math read top-down

    @objc.python_method
    def set_data(self, snapshot, cpu_values, actions, diagnosing=False):
        self._snapshot, self._cpu_values = snapshot, cpu_values
        self._actions = list(actions or [])
        self._diagnosing = diagnosing
        self.setNeedsDisplay_(True)

    @objc.python_method
    def content_height(self):
        """Total height from the SAME data drawRect uses — so frame and content can't drift."""
        if self._snapshot is None:
            return 220.0
        y = PAD + 24 + 46  # top pad + header + CPU/sparkline
        if self._actions:
            y += 16 + (min(len(self._actions), 3) * 32 + 8) + 12
        elif self._diagnosing:
            y += 16 + 36 + 12
        rows = min(len(getattr(self._snapshot, "rows", ())), 5)
        y += 18 + rows * ROW_H + 4  # TOP PROCESSES header + rows + gap
        y += 26 + 16                # footer buttons + bottom pad
        return float(y)

    def drawRect_(self, _rect):
        self._hit_regions = []
        snap = self._snapshot
        if snap is None:
            return
        y = PAD

        dot = AppKit.NSColor.systemGreenColor()
        headline = "All clear"
        if snap.surging:
            dot, headline = AppKit.NSColor.systemRedColor(), "CPU surge"
        elif snap.cpu_percent >= 60:
            dot, headline = AppKit.NSColor.systemOrangeColor(), "Running warm"

        self._fill_circle(PAD, y + 4, 9, dot)
        _text(headline, 13, dot, bold=True).drawAtPoint_(NSMakePoint(PAD + 16, y))
        load_attr = _text(f"load {snap.load1:.1f} · {self._cores()} cores", 11,
                          AppKit.NSColor.tertiaryLabelColor())
        load_w = load_attr.size().width
        load_attr.drawAtPoint_(NSMakePoint(PANEL_WIDTH - PAD - load_w, y + 1))
        y += 24

        num = _text(f"{snap.cpu_percent:.0f}", 32, AppKit.NSColor.labelColor(), bold=True)
        num.drawAtPoint_(NSMakePoint(PAD, y))
        num_w = num.size().width
        _text("%", 16, AppKit.NSColor.secondaryLabelColor()).drawAtPoint_(
            NSMakePoint(PAD + num_w + 2, y + 12)
        )
        spark_x = PAD + num_w + 34
        self._draw_sparkline(spark_x, y + 6, PANEL_WIDTH - PAD - spark_x, 30, dot)
        y += 46

        if self._actions:
            y = self._draw_recommendations(y)
        elif self._diagnosing:
            y = self._draw_thinking(y)

        _text("TOP PROCESSES", 10, AppKit.NSColor.tertiaryLabelColor(), bold=True).drawAtPoint_(
            NSMakePoint(PAD, y)
        )
        y += 18
        for row in list(getattr(snap, "rows", ()))[:5]:
            self._draw_process_row(y, row)
            y += ROW_H
        y += 4

        gap = 8.0
        avail = PANEL_WIDTH - 2 * PAD - gap
        diag_w = avail * 0.62
        self._draw_button(PAD, y, diag_w, 26, "Diagnose now", "diagnose", None,
                          AppKit.NSColor.controlAccentColor(), filled=False)
        self._draw_button(PAD + diag_w + gap, y, avail - diag_w, 26, "Settings", "settings", None,
                          AppKit.NSColor.secondaryLabelColor(), filled=False)

    @objc.python_method
    def _draw_thinking(self, y):
        accent = AppKit.NSColor.controlAccentColor()
        _text("RECOMMENDED", 10, accent, bold=True).drawAtPoint_(NSMakePoint(PAD, y))
        y += 16
        band_h = 36.0
        accent.colorWithAlphaComponent_(0.08).set()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(PAD, y, PANEL_WIDTH - 2 * PAD, band_h), 8, 8
        ).fill()
        self._fill_circle(PAD + 10, y + 13, 9, accent.colorWithAlphaComponent_(0.6))
        _text("Analyzing top processes with AI…", 12, AppKit.NSColor.secondaryLabelColor()).drawAtPoint_(
            NSMakePoint(PAD + 28, y + 9)
        )
        return y + band_h + 12

    @objc.python_method
    def _draw_recommendations(self, y):
        actions = self._actions[:3]
        accent = AppKit.NSColor.controlAccentColor()
        _text("RECOMMENDED", 10, accent, bold=True).drawAtPoint_(NSMakePoint(PAD, y))
        y += 16
        band_h = len(actions) * 32 + 8
        accent.colorWithAlphaComponent_(0.10).set()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(PAD, y, PANEL_WIDTH - 2 * PAD, band_h), 8, 8
        ).fill()
        verbs = {"throttle": "Throttle", "quit": "Quit", "kill": "Kill"}
        label_x = PAD + 10
        yy = y + 6
        for i, action in enumerate(actions):
            kind = action.get("kind")
            label = action.get("label") or action.get("rationale") or "?"
            if kind in verbs:
                btn_w = 70.0
                btn_x = PANEL_WIDTH - PAD - 10 - btn_w
                self._draw_button(btn_x, yy + 3, btn_w, 22, verbs[kind], "recommend", i,
                                  accent, filled=(i == 0))
                label_w = btn_x - label_x - 8
                color = AppKit.NSColor.labelColor()
                text = label
            else:  # info: no button, full-width label, whole row is the hit target
                label_w = PANEL_WIDTH - PAD - 10 - label_x
                self._hit_regions.append((NSMakeRect(label_x, yy, label_w, 28), "recommend", i))
                color = AppKit.NSColor.secondaryLabelColor()
                text = "ⓘ  " + label
            _draw_text_clipped(text, 12, color, label_x, yy + 5, label_w, 18)
            yy += 32
        return y + band_h + 12

    @objc.python_method
    def _draw_process_row(self, y, row):
        _text((row.label or row.name)[:34], 12, AppKit.NSColor.labelColor(), bold=True).drawAtPoint_(
            NSMakePoint(PAD, y)
        )
        cpu = row.cpu_percent
        cpu_attr = _text(f"{cpu:.0f}%", 12, _heat_color(cpu), bold=True)
        cpu_w = cpu_attr.size().width
        cpu_attr.drawAtPoint_(NSMakePoint(PANEL_WIDTH - PAD - cpu_w - 16, y))
        x_rect = NSMakeRect(PANEL_WIDTH - PAD - 13, y, 14, 15)
        _text("✕", 11, AppKit.NSColor.tertiaryLabelColor()).drawAtPoint_(
            NSMakePoint(PANEL_WIDTH - PAD - 11, y)
        )
        self._hit_regions.append((x_rect, "kill", row.pid))
        bar_y = y + 20
        track = NSMakeRect(PAD, bar_y, PANEL_WIDTH - 2 * PAD, BAR_H)
        AppKit.NSColor.quaternaryLabelColor().set()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(track, 2.5, 2.5).fill()
        frac = max(0.0, min(1.0, cpu / 100.0))
        if frac > 0.02:
            fill = NSMakeRect(PAD, bar_y, (PANEL_WIDTH - 2 * PAD) * frac, BAR_H)
            _heat_color(cpu).set()
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(fill, 2.5, 2.5).fill()

    @objc.python_method
    def _fill_circle(self, x, y, d, color):
        color.set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, d, d)).fill()

    @objc.python_method
    def _draw_sparkline(self, x, y, w, h, color):
        vals = self._cpu_values[-30:]
        if len(vals) < 2 or w < 10:
            return
        n = len(vals)
        path = AppKit.NSBezierPath.bezierPath()
        path.setLineWidth_(2.0)
        path.setLineJoinStyle_(AppKit.NSLineJoinStyleRound)
        for i, v in enumerate(vals):
            px = x + w * (i / (n - 1))
            py = y + h - (max(0.0, min(100.0, v)) / 100.0) * h
            if i == 0:
                path.moveToPoint_(NSMakePoint(px, py))
            else:
                path.lineToPoint_(NSMakePoint(px, py))
        color.colorWithAlphaComponent_(0.9).set()
        path.stroke()

    @objc.python_method
    def _draw_button(self, x, y, w, h, title, kind, payload, tint, filled):
        rect = NSMakeRect(x, y, w, h)
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 6, 6)
        if filled:
            tint.set()
            path.fill()
            txt_color = AppKit.NSColor.whiteColor()
        else:
            tint.colorWithAlphaComponent_(0.5).set()
            path.setLineWidth_(1.0)
            path.stroke()
            txt_color = tint
        attr = _text(title, 12, txt_color, bold=True)
        sz = attr.size()
        attr.drawAtPoint_(NSMakePoint(x + (w - sz.width) / 2, y + (h - sz.height) / 2))
        self._hit_regions.append((rect, kind, payload))

    @objc.python_method
    def _cores(self):
        from .signals import CORE_COUNT
        return CORE_COUNT

    def mouseDown_(self, event):
        pt = self.convertPoint_fromView_(event.locationInWindow(), None)
        for rect, kind, payload in self._hit_regions:
            if AppKit.NSPointInRect(pt, rect):
                if self._delegate is not None:
                    self._delegate.panel_action(kind, payload)
                return


class PopoverController(AppKit.NSObject):
    """Owns the NSPopover and routes status-item clicks + panel button actions."""

    def initWithApp_(self, app):
        self = objc.super(PopoverController, self).init()
        if self is None:
            return None
        self._app = app
        self._view = SurgePanelView.alloc().initWithDelegate_(self)
        self._view.setFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 360))
        vc = AppKit.NSViewController.alloc().init()
        vc.setView_(self._view)
        self._popover = AppKit.NSPopover.alloc().init()
        self._popover.setContentViewController_(vc)
        self._popover.setContentSize_(NSMakeSize(PANEL_WIDTH, 360))
        self._popover.setBehavior_(AppKit.NSPopoverBehaviorTransient)
        self._popover.setAnimates_(False)  # instant resize when content grows — no jarring mid-show animation
        self._status_menu = None
        self._button = None
        return self

    @objc.python_method
    def wire_status_item(self, status_item):
        button = status_item.button()
        if button is None:
            return False
        menu = status_item.menu()
        button.setTarget_(self)
        button.setAction_("statusClicked:")
        button.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)
        self._status_menu = menu
        self._button = button
        status_item.setMenu_(None)  # detach last, so a failure above leaves the menu intact
        return True

    def statusClicked_(self, _sender):
        event = AppKit.NSApp().currentEvent()
        right = event is not None and (
            event.type() == AppKit.NSEventTypeRightMouseUp
            or bool(event.modifierFlags() & AppKit.NSEventModifierFlagControl)
        )
        if right and self._status_menu is not None:
            self._status_menu.popUpMenuPositioningItem_atLocation_inView_(
                None, NSMakePoint(0, -4), self._button
            )
            return
        self.toggle()

    @objc.python_method
    def toggle(self):
        if self._popover.isShown():
            self._popover.close()
            return
        self.refresh()
        self._popover.showRelativeToRect_ofView_preferredEdge_(
            self._button.bounds(), self._button, AppKit.NSRectEdgeMinY
        )

    @objc.python_method
    def refresh(self):
        # Load the view with data FIRST, then size the window from that exact same
        # data via the view's own height. Frame and drawn content can never drift.
        self._view.set_data(
            self._app.monitor_snapshot(), self._app.monitor_cpu_values(),
            self._app.actions(), self._app.diagnosing(),
        )
        height = self._view.content_height()
        self._popover.setContentSize_(NSMakeSize(PANEL_WIDTH, height))
        self._view.setFrame_(NSMakeRect(0, 0, PANEL_WIDTH, height))

    @objc.python_method
    def refresh_if_visible(self):
        if self._popover.isShown():
            self.refresh()

    @objc.python_method
    def show_settings_menu(self):
        if self._popover.isShown():
            self._popover.close()
        if self._status_menu is not None and self._button is not None:
            self._status_menu.popUpMenuPositioningItem_atLocation_inView_(
                None, NSMakePoint(0, -4), self._button
            )

    @objc.python_method
    def panel_action(self, kind, payload):
        self._app.panel_action(kind, payload)
