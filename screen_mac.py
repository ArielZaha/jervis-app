"""Computer control on macOS: reading the window in front through the Accessibility API, acting through Quartz.

Needs the Accessibility permission (System Settings > Privacy & Security > Accessibility) for Jervis, which macOS asks
for the first time. Screenshots additionally need Screen Recording; without it Jervis works from the accessibility
information alone.
"""
import os
import time

import computer_use
from computer_use import Element, Observation

try:
    import AppKit
    import ApplicationServices as AX
    import Quartz
except ImportError:   # not macOS, or pyobjc missing: available() says so
    AppKit = AX = Quartz = None

INTERACTIVE = {
    "AXButton": "button", "AXTextField": "text field", "AXTextArea": "text area", "AXSearchField": "search field",
    "AXLink": "link", "AXMenuItem": "menu item", "AXMenuButton": "menu button", "AXPopUpButton": "pop-up button",
    "AXCheckBox": "checkbox", "AXRadioButton": "radio button", "AXComboBox": "combo box", "AXSlider": "slider",
    "AXDisclosureTriangle": "disclosure", "AXTab": "tab", "AXCell": "cell", "AXRow": "row",
    "AXMenuBarItem": "menu", "AXIncrementor": "stepper", "AXColorWell": "color", "AXDockItem": "dock item",
}
CONTEXT = {"AXStaticText": "text", "AXHeading": "heading", "AXImage": "image"}
SUBROLE_NAMES = {"AXCloseButton": "Close window", "AXMinimizeButton": "Minimize window",
                 "AXZoomButton": "Zoom window", "AXFullScreenButton": "Full screen"}
OWN_APPS = {"jervis", "electron"}   # Jervis's own window is never the thing to operate

KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36,
    "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "tab": 48, "space": 49, "`": 50, "backspace": 51, "escape": 53, "delete": 117, "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121, "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
    "f11": 103, "f12": 111,
}
MODIFIERS = {}
if Quartz is not None:
    MODIFIERS = {"cmd": Quartz.kCGEventFlagMaskCommand, "shift": Quartz.kCGEventFlagMaskShift,
                 "alt": Quartz.kCGEventFlagMaskAlternate, "ctrl": Quartz.kCGEventFlagMaskControl,
                 "fn": Quartz.kCGEventFlagMaskSecondaryFn}
MAX_VISITED = 3000
MAX_ELEMENTS = 400


def _attr(element, name):
    err, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return value if err == 0 else None


def _point(value):
    if value is None:
        return None
    ok, point = AX.AXValueGetValue(value, AX.kAXValueCGPointType, None)
    return (point.x, point.y) if ok else None


def _size(value):
    if value is None:
        return None
    ok, size = AX.AXValueGetValue(value, AX.kAXValueCGSizeType, None)
    return (size.width, size.height) if ok else None


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return str(value)
    except Exception:
        return ""


class MacScreen(computer_use.Environment):
    name = "macOS"
    select_all = ["cmd", "a"]

    def __init__(self):
        self._warmed = set()   # apps whose web content accessibility was already switched on

    def available(self):
        if AX is None:
            return False, "Computer control needs macOS's accessibility support, which isn't available here."
        options = {AX.kAXTrustedCheckOptionPrompt: True}   # macOS shows its own "allow" prompt the first time
        if not AX.AXIsProcessTrustedWithOptions(options):
            return False, ("Jervis needs permission to use this Mac: open System Settings, Privacy & Security, "
                           "Accessibility, turn on Jervis, then ask me again.")
        return True, ""

    # ---------- looking ----------
    def _target_app(self):
        """The app the user is working in: the front app, or the one behind Jervis's own window."""
        workspace = AppKit.NSWorkspace.sharedWorkspace()
        front = workspace.frontmostApplication()
        if front and (front.localizedName() or "").lower() not in OWN_APPS:
            return front
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
        for info in windows or []:
            owner = (info.get("kCGWindowOwnerName") or "").lower()
            if info.get("kCGWindowLayer", 0) == 0 and owner and owner not in OWN_APPS:
                app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(info.get("kCGWindowOwnerPID"))
                if app is not None:
                    return app
        return front

    def observe(self) -> Observation:
        app = self._target_app()
        self._target = app
        observation = Observation(app=(app.localizedName() if app else "") or "")
        observation.cursor = self.cursor()
        bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        observation.screen_size = (int(bounds.size.width), int(bounds.size.height))
        observation.other_windows = self._window_titles(exclude_pid=app.processIdentifier() if app else None)
        observation.screenshot = self._screenshot()
        if app is None:
            observation.note = "No app is in front."
            return observation
        app_element = AX.AXUIElementCreateApplication(app.processIdentifier())
        # Chrome, Electron apps: expose web content to accessibility (they only do it when asked).
        AX.AXUIElementSetAttributeValue(app_element, "AXManualAccessibility", True)
        window = _attr(app_element, "AXFocusedWindow") or next(iter(_attr(app_element, "AXWindows") or []), None)
        if window is None:
            observation.note = f"{observation.app} has no open window."
            return observation
        observation.window = _text(_attr(window, "AXTitle"))
        observation.elements = self._collect(window)
        if app.processIdentifier() not in self._warmed:
            self._warmed.add(app.processIdentifier())
            if len(observation.elements) < 30:   # just switched on: Chrome/Electron need a moment to build it
                time.sleep(1.5)
                observation.elements = self._collect(window)
        menu_bar = _attr(app_element, "AXMenuBar")   # the app's menus are part of what can be used
        if menu_bar is not None:
            observation.elements += self._collect(menu_bar, start_id=len(observation.elements) + 1, max_depth=1)
        return observation

    def _collect(self, root, start_id: int = 1, max_depth: int = 40) -> list:
        elements, queue, visited = [], [(root, 0)], 0
        screen = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        while queue and visited < MAX_VISITED and len(elements) < MAX_ELEMENTS:
            node, depth = queue.pop(0)
            visited += 1
            role = _text(_attr(node, "AXRole"))
            subrole = _text(_attr(node, "AXSubrole"))
            if role in INTERACTIVE or role in CONTEXT:
                position, size = _point(_attr(node, "AXPosition")), _size(_attr(node, "AXSize"))
                if position and size and size[0] > 1 and size[1] > 1 and \
                        position[0] + size[0] > 0 and position[1] + size[1] > 0 and \
                        position[0] < screen.size.width and position[1] < screen.size.height:
                    name = " ".join(filter(None, (_text(_attr(node, "AXTitle")), _text(_attr(node, "AXDescription")))))
                    name = name or SUBROLE_NAMES.get(subrole, "") or _text(_attr(node, "AXHelp"))
                    placeholder = _text(_attr(node, "AXPlaceholderValue"))
                    value = _attr(node, "AXValue")
                    value = "" if isinstance(value, bool) else _text(value)
                    password = subrole == "AXSecureTextField"
                    kind = "search field" if subrole == "AXSearchField" else INTERACTIVE.get(role) or CONTEXT[role]
                    if role in CONTEXT and not (name or value):
                        pass   # an unlabeled picture or empty text tells the AI nothing
                    else:
                        elements.append(Element(
                            id=start_id + len(elements), role=kind, name=(name or placeholder)[:120],
                            value="" if password else value[:200], rect=(position[0], position[1], size[0], size[1]),
                            enabled=_attr(node, "AXEnabled") is not False, focused=bool(_attr(node, "AXFocused")),
                            password=password, handle=node))
            if depth < max_depth:
                for child in _attr(node, "AXChildren") or []:
                    queue.append((child, depth + 1))
        return elements

    def _window_titles(self, exclude_pid=None) -> list:
        titles = []
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
        for info in windows or []:
            if info.get("kCGWindowLayer", 0) != 0 or info.get("kCGWindowOwnerPID") == exclude_pid:
                continue
            owner = info.get("kCGWindowOwnerName") or ""
            if owner.lower() in OWN_APPS:
                continue
            title = info.get("kCGWindowName") or ""
            label = f"{owner}: {title}" if title else owner
            if label and label not in titles:
                titles.append(label)
        return titles[:15]

    def _screenshot(self):
        if not Quartz.CGPreflightScreenCaptureAccess():
            return None   # no Screen Recording permission: work from accessibility only
        try:
            import mss
            from PIL import Image
            with mss.mss() as grab:
                shot = grab.grab(grab.monitors[1])
                return Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception:
            return None

    def cursor(self):
        location = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return (int(location.x), int(location.y))

    # ---------- acting ----------
    def _bring_forward(self) -> None:
        """Keys and clicks go to the front app: if that is Jervis's own window, put the app being worked in first."""
        target = getattr(self, "_target", None)
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if target is None or front is None or (front.localizedName() or "").lower() not in OWN_APPS:
            return
        target.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        for _ in range(10):
            time.sleep(0.05)
            if AppKit.NSWorkspace.sharedWorkspace().frontmostApplication() == target:
                break

    def focus_moved(self) -> bool:
        target = getattr(self, "_target", None)
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if target is None or front is None or (front.localizedName() or "").lower() in OWN_APPS:
            return False
        return front.processIdentifier() != target.processIdentifier()

    def _has_focus(self, element: Element) -> bool:
        target = getattr(self, "_target", None)
        if target is None or element.handle is None:
            return False
        focused = _attr(AX.AXUIElementCreateApplication(target.processIdentifier()), "AXFocusedUIElement")
        if focused is None:
            return False
        if focused == element.handle or _attr(element.handle, "AXFocused") is True:
            return True
        parent = _attr(focused, "AXParent")   # a combo box's text part is a child of the combo box
        return parent is not None and parent == element.handle

    def focus_element(self, element: Element) -> str:
        self._bring_forward()
        if element.handle is not None:
            AX.AXUIElementSetAttributeValue(element.handle, "AXFocused", True)
            time.sleep(0.15)
            if self._has_focus(element):
                return ""
        self.click(element.center)   # some fields (toolbar boxes) only take the cursor from a real click
        time.sleep(0.3)
        if element.handle is None or self._has_focus(element):
            return ""
        return (f"I couldn't put the cursor in [{element.id}] {element.label()}, so nothing was typed. Try clicking "
                "it first, or pick another element.")

    def press_element(self, element: Element) -> str:
        if element.handle is not None and element.role in ("text field", "text area", "search field", "combo box"):
            if AX.AXUIElementSetAttributeValue(element.handle, "AXFocused", True) == 0:
                return ""
        if element.handle is not None and AX.AXUIElementPerformAction(element.handle, "AXPress") == 0:
            return ""
        return self.click(element.center)

    def _mouse(self, kind, point, button=Quartz.kCGMouseButtonLeft if Quartz else 0, clicks=1):
        event = Quartz.CGEventCreateMouseEvent(None, kind, point, button)
        Quartz.CGEventSetFlags(event, 0)   # a plain click, never a Cmd-click left over from a shortcut
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, clicks)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def click(self, point, button="left", double=False) -> str:
        self._bring_forward()
        point = (float(point[0]), float(point[1]))
        if button == "right":
            down, up, which = Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight
        else:
            down, up, which = Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft
        self._mouse(Quartz.kCGEventMouseMoved, point, which)
        time.sleep(0.05)
        for n in (1, 2) if double else (1,):
            self._mouse(down, point, which, n)
            self._mouse(up, point, which, n)
            time.sleep(0.06)
        return ""

    def type_text(self, text: str) -> str:
        self._bring_forward()
        for i in range(0, len(text), 8):   # macOS takes at most ~20 characters per event; small ones survive a busy app
            chunk = text[i:i + 8]
            for key_down in (True, False):
                event = Quartz.CGEventCreateKeyboardEvent(None, 0, key_down)
                Quartz.CGEventSetFlags(event, 0)   # never inherit a modifier from a shortcut pressed just before
                Quartz.CGEventKeyboardSetUnicodeString(event, len(chunk), chunk)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(0.03)
        return ""

    def press_keys(self, keys: list) -> str:
        flags = 0
        main = None
        for key in keys:
            key = {"win": "cmd", "super": "cmd", "return": "enter"}.get(key, key)
            if key in MODIFIERS:
                flags |= MODIFIERS[key]
            elif key in KEYCODES:
                main = KEYCODES[key]
            else:
                return f"Unknown key “{key}”."
        if main is None:
            return "No key to press."
        self._bring_forward()
        for key_down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, main, key_down)
            Quartz.CGEventSetFlags(event, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        return ""

    def scroll(self, amount: int, point=None) -> str:
        if point is not None:
            self._mouse(Quartz.kCGEventMouseMoved, (float(point[0]), float(point[1])))
        event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, int(amount))
        Quartz.CGEventSetFlags(event, 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        return ""

    def switch_window(self, title: str) -> str:
        wanted = title.split(":", 1)[0].strip().lower()
        for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
            if (app.localizedName() or "").lower() == wanted:
                app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
                return ""
        return f"No open app called “{title}”."
