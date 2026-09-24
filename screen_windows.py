"""Computer control on Windows: reading the window in front through UI Automation, acting through winctl.py.

UI Automation is the accessibility layer Windows itself provides: every button, field, link and menu item of a window
with its name and on-screen position, for normal apps, Office, File Explorer, Settings and the browsers. No special
permission is needed. Screenshots (for the optional vision model) come from mss.
"""
import time

import computer_use
import winctl
from computer_use import Element, Observation

try:
    import uiautomation as auto
except Exception:   # not Windows, or the package is missing: available() says so
    auto = None

if winctl.IS_WIN:
    winctl.make_dpi_aware()   # before any window work, so read positions and clicked positions agree

INTERACTIVE = {
    "ButtonControl": "button", "EditControl": "text field", "HyperlinkControl": "link", "MenuItemControl": "menu item",
    "ListItemControl": "list item", "TabItemControl": "tab", "CheckBoxControl": "checkbox",
    "RadioButtonControl": "radio button", "ComboBoxControl": "combo box", "TreeItemControl": "tree item",
    "DataItemControl": "item", "SplitButtonControl": "split button", "SliderControl": "slider",
    "MenuBarControl": "menu bar", "SpinnerControl": "spinner", "DocumentControl": "document",
}
CONTEXT = {"TextControl": "text", "HeaderItemControl": "header", "ImageControl": "image"}
OWN_PROCESSES = {"jervis.exe", "electron.exe", "jervis-backend.exe"}   # never operate Jervis himself
MAX_VISITED = 2500
MAX_ELEMENTS = 400
TIME_BUDGET = 2.0   # seconds; a huge web page must not stall a step


class WindowsScreen(computer_use.Environment):
    name = "Windows"

    def available(self):
        if not winctl.IS_WIN:
            return False, "This is the Windows version of computer control."
        if auto is None:
            return False, "Computer control needs the UI Automation package, which is missing from this install."
        return True, ""

    # ---------- looking ----------
    def _target_window(self):
        """The window the user is working in: the one in front, or the one right behind Jervis's own window."""
        front = winctl.foreground_window()
        if front and winctl.window_process_name(front) not in OWN_PROCESSES:
            return front
        for hwnd, _title in winctl.list_windows():
            if winctl.window_process_name(hwnd) not in OWN_PROCESSES:
                return hwnd
        return front

    def observe(self) -> Observation:
        hwnd = self._target_window()
        self._target = hwnd
        observation = Observation()
        observation.cursor = winctl.cursor_position()
        observation.screenshot, observation.screen_size = self._screenshot()
        observation.other_windows = [title for h, title in winctl.list_windows()
                                     if h != hwnd and winctl.window_process_name(h) not in OWN_PROCESSES][:15]
        if not hwnd:
            observation.note = "No window is in front."
            return observation
        window = auto.ControlFromHandle(hwnd)
        if window is None:
            observation.note = "The window in front can't be read."
            return observation
        observation.window = window.Name or ""
        observation.app = (winctl.window_process_name(hwnd) or "").removesuffix(".exe")
        observation.elements = self._collect(window)
        return observation

    def _collect(self, window) -> list:
        elements, visited, started = [], 0, time.time()
        try:
            for control, _depth in auto.WalkControl(window, includeTop=False, maxDepth=30):
                visited += 1
                if visited > MAX_VISITED or len(elements) >= MAX_ELEMENTS or time.time() - started > TIME_BUDGET:
                    break
                kind = INTERACTIVE.get(control.ControlTypeName) or CONTEXT.get(control.ControlTypeName)
                if not kind:
                    continue
                try:
                    if control.IsOffscreen:
                        continue
                    rect = control.BoundingRectangle
                    if rect.width() <= 1 or rect.height() <= 1:
                        continue
                    name = (control.Name or "").strip()
                    value = ""
                    password = bool(getattr(control.Element, "CurrentIsPassword", False))
                    if kind in ("text field", "combo box", "document") and not password:
                        pattern = control.GetPattern(auto.PatternId.ValuePattern)
                        if pattern is not None:
                            value = (pattern.Value or "")[:200]
                    if control.ControlTypeName in CONTEXT and not name:
                        continue
                    elements.append(Element(
                        id=len(elements) + 1, role=kind, name=name[:120], value=value,
                        rect=(rect.left, rect.top, rect.width(), rect.height()), enabled=bool(control.IsEnabled),
                        focused=bool(control.HasKeyboardFocus), password=password, handle=control))
                except Exception:
                    continue   # an element that vanished mid-read is simply skipped
        except Exception as e:
            print(f"Reading the window stopped early: {e}", flush=True)
        return elements

    def _screenshot(self):
        try:
            import mss
            from PIL import Image
            with mss.mss() as grab:
                monitor = grab.monitors[1]
                shot = grab.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb), (monitor["width"], monitor["height"])
        except Exception:
            return None, (0, 0)

    def cursor(self):
        return winctl.cursor_position()

    # ---------- acting ----------
    def _bring_forward(self) -> None:
        """Keys and clicks go to the window in front: if that is Jervis's own, put the one being worked in first."""
        target = getattr(self, "_target", None)
        front = winctl.foreground_window()
        if target and front != target and winctl.window_process_name(front) in OWN_PROCESSES:
            winctl.focus(target)
            time.sleep(0.15)

    def focus_moved(self) -> bool:
        target = getattr(self, "_target", None)
        front = winctl.foreground_window()
        if not target or not front or front == target or winctl.window_process_name(front) in OWN_PROCESSES:
            return False
        return winctl.window_process_name(front) != winctl.window_process_name(target)   # a dialog of the same app is fine

    def focus_element(self, element: Element) -> str:
        self._bring_forward()
        control = element.handle
        if control is not None:
            try:
                control.SetFocus()
                time.sleep(0.15)
                if control.HasKeyboardFocus:
                    return ""
            except Exception:
                pass
        self.click(element.center)   # some fields only take the cursor from a real click
        time.sleep(0.3)
        try:
            focused = auto.GetFocusedControl()   # a combo box's text part is a child of the combo box
            if control is None or control.HasKeyboardFocus or (
                    focused is not None and auto.ControlsAreSame(focused.GetParentControl(), control)):
                return ""
        except Exception:
            return ""   # can't tell: the click is the best there is
        return (f"I couldn't put the cursor in [{element.id}] {element.label()}, so nothing was typed. Try clicking "
                "it first, or pick another element.")

    def press_element(self, element: Element) -> str:
        control = element.handle
        if control is not None:
            try:
                if element.role in ("text field", "combo box", "document"):
                    control.SetFocus()
                    return ""
                pattern = control.GetPattern(auto.PatternId.InvokePattern)
                if pattern is not None:
                    pattern.Invoke()
                    return ""
                for pattern_id, call in ((auto.PatternId.TogglePattern, "Toggle"),
                                         (auto.PatternId.SelectionItemPattern, "Select"),
                                         (auto.PatternId.ExpandCollapsePattern, "Expand")):
                    pattern = control.GetPattern(pattern_id)
                    if pattern is not None:
                        getattr(pattern, call)()
                        return ""
            except Exception:
                pass   # fall back to a real click
        return self.click(element.center)

    def click(self, point, button="left", double=False) -> str:
        self._bring_forward()
        winctl.click(point[0], point[1], button=button, double=double)
        return ""

    def type_text(self, text: str) -> str:
        self._bring_forward()
        winctl.type_text(text)
        return ""

    def press_keys(self, keys: list) -> str:
        names = []
        for key in keys:
            key = {"cmd": "ctrl", "meta": "win", "return": "enter", "option": "alt"}.get(key, key)
            if key not in winctl.VK:
                return f"Unknown key “{key}”."
            names.append(key)
        self._bring_forward()
        winctl.press(*names)
        return ""

    def scroll(self, amount: int, point=None) -> str:
        if point is not None:
            winctl.scroll(amount, point[0], point[1])
        else:
            winctl.scroll(amount)
        return ""

    def switch_window(self, title: str) -> str:
        wanted = title.lower()
        for hwnd, window_title in winctl.list_windows():
            if wanted in window_title.lower() and winctl.window_process_name(hwnd) not in OWN_PROCESSES:
                return "" if winctl.focus(hwnd) else f"Windows didn't let me bring “{window_title}” to the front."
        return f"No open window called “{title}”."
