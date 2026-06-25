"""Malinche design system — tokens and AppKit factory helpers.

Phase 1 of the L4 UI redesign (see ``Docs/UI-REDESIGN-L4-PLAN.md``). One place
for spacing, type scale, accent, SF Symbols and vibrancy, so every window reads
as a deliberately designed macOS app instead of hand-placed dialog boxes.

Design decisions (locked):
- **Restrained colour.** Lean on system semantic colours and materials; a single
  brand accent (terracotta) for primary actions / active work / PRO. Jade marks
  "ready/done"; errors use the *system* red (the native, expected signal).
- **SF Symbols, not emoji.** Symbols are guaranteed present on macOS 12+, which
  also retires the missing-PNG/emoji-fallback problem in the menu bar.

Like ``theme.py``, this module is **AppKit-optional**: it imports cleanly with no
AppKit (the pure tokens/maps stay usable and unit-testable), and every helper
that builds an AppKit object returns ``None`` when AppKit is unavailable.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from src.app_status import AppStatus
from src.ui import theme

try:
    from AppKit import (
        NSColor,
        NSFont,
        NSImage,
        NSImageSymbolConfiguration,
        NSView,
        NSVisualEffectView,
    )

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised on non-mac CI
    NSColor = NSFont = NSImage = None  # type: ignore[assignment]
    NSImageSymbolConfiguration = NSView = NSVisualEffectView = None  # type: ignore[assignment]
    _APPKIT_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Spacing — an 8pt grid (with a 4pt half-step). Use these, never magic numbers.
# --------------------------------------------------------------------------- #

SPACE_HALF = 4
SPACE_TIGHT = 8
SPACE_CONTROL = 12
SPACE_GROUP = 16
SPACE_PADDING = 20

#: Ordered for tests / introspection.
SPACING: Tuple[int, ...] = (
    SPACE_HALF,
    SPACE_TIGHT,
    SPACE_CONTROL,
    SPACE_GROUP,
    SPACE_PADDING,
)


# --------------------------------------------------------------------------- #
# Type scale — (point size, weight name). System font everywhere; SF Mono for
# logs lives at the call site.
# --------------------------------------------------------------------------- #

TYPE_SCALE: Dict[str, Tuple[float, str]] = {
    "headline": (17.0, "bold"),
    "title": (15.0, "semibold"),
    "body": (13.0, "regular"),
    "caption": (11.0, "regular"),
}

#: Map weight names to NSFontWeight (CGFloat) values. Mirrors AppKit constants
#: so we do not depend on importing each ``NSFontWeight*`` symbol.
_FONT_WEIGHTS: Dict[str, float] = {
    "regular": 0.0,
    "medium": 0.23,
    "semibold": 0.3,
    "bold": 0.4,
}


# --------------------------------------------------------------------------- #
# Status → SF Symbol, and status → accent role. Both pure and exhaustively
# tested, so the menu bar and panel render from data, not scattered if-chains.
# --------------------------------------------------------------------------- #

STATUS_SYMBOLS: Dict[AppStatus, str] = {
    AppStatus.IDLE: "waveform",
    AppStatus.SCANNING: "magnifyingglass",
    AppStatus.TRANSCRIBING: "waveform.badge.mic",
    AppStatus.DOWNLOADING: "arrow.down.circle",
    AppStatus.MIGRATING: "arrow.triangle.2.circlepath",
    AppStatus.RECORDER_IDLE: "externaldrive",
    AppStatus.RECORDER_PENDING: "externaldrive.badge.plus",
    AppStatus.ERROR: "exclamationmark.triangle",
}

#: Semantic roles, deliberately only three. "ready" = jade, "active" = brand
#: accent (terracotta), "error" = system red. Keeps one brand colour in play.
STATUS_ROLES: Dict[AppStatus, str] = {
    AppStatus.IDLE: "ready",
    AppStatus.RECORDER_IDLE: "ready",
    AppStatus.SCANNING: "active",
    AppStatus.TRANSCRIBING: "active",
    AppStatus.DOWNLOADING: "active",
    AppStatus.MIGRATING: "active",
    AppStatus.RECORDER_PENDING: "active",
    AppStatus.ERROR: "error",
}


def symbol_name_for_status(status: AppStatus) -> str:
    """SF Symbol name for *status* (falls back to ``waveform``)."""
    return STATUS_SYMBOLS.get(status, "waveform")


def role_for_status(status: AppStatus) -> str:
    """Semantic accent role for *status*: ``ready`` | ``active`` | ``error``."""
    return STATUS_ROLES.get(status, "ready")


# --------------------------------------------------------------------------- #
# Colour.
# --------------------------------------------------------------------------- #


def accent_color():
    """The single brand accent (terracotta) — primary actions / active / PRO."""
    return theme.terracotta()


def color_for_role(role: str):
    """NSColor for a status role, or ``None`` without AppKit.

    ``ready`` → jade, ``active`` → terracotta (brand), ``error`` → system red.
    """
    if not _APPKIT_AVAILABLE:
        return None
    if role == "ready":
        return theme.jade()
    if role == "active":
        return theme.terracotta()
    if role == "error":
        return NSColor.systemRedColor()
    return NSColor.secondaryLabelColor()


def color_for_status(status: AppStatus):
    """Convenience: NSColor for *status* via its role."""
    return color_for_role(role_for_status(status))


# --------------------------------------------------------------------------- #
# AppKit factories (all return None without AppKit).
# --------------------------------------------------------------------------- #


def _weight_value(weight: str) -> float:
    return _FONT_WEIGHTS.get(weight, 0.0)


def system_font(style: str = "body"):
    """NSFont for a type-scale *style* (``headline``/``title``/``body``/``caption``)."""
    if not _APPKIT_AVAILABLE:
        return None
    size, weight = TYPE_SCALE.get(style, TYPE_SCALE["body"])
    return NSFont.systemFontOfSize_weight_(size, _weight_value(weight))


def sf_symbol(
    name: str,
    point: float = 15.0,
    weight: str = "regular",
    template: bool = True,
):
    """A configured SF Symbol ``NSImage``, or ``None`` if AppKit/symbol missing.

    Template images adopt the surrounding tint (correct for menu bar + buttons).
    """
    if not _APPKIT_AVAILABLE:
        return None
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if image is None:
        return None
    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        point, _weight_value(weight)
    )
    configured = image.imageWithSymbolConfiguration_(config) or image
    configured.setTemplate_(template)
    return configured


def status_symbol(status: AppStatus, point: float = 15.0, weight: str = "regular"):
    """SF Symbol ``NSImage`` for a status (template), or ``None`` without AppKit."""
    return sf_symbol(symbol_name_for_status(status), point=point, weight=weight)


def render_symbol_png(
    name: str,
    point: float = 15.0,
    weight: str = "regular",
    pixel_size: int = 36,
    dot: bool = False,
) -> Optional[bytes]:
    """Rasterise an SF Symbol to template PNG bytes (black glyph + alpha).

    The menu-bar status item in ``rumps`` takes a file path, not a live
    ``NSImage``. Rendering the symbol to a small template PNG lets us keep
    rumps' whole lifecycle while still showing real SF Symbols (and retiring the
    emoji fallback). Returns ``None`` if AppKit or the symbol is unavailable.

    The glyph is centred and aspect-fit into a ``pixel_size`` square so menu-bar
    icons render crisply at Retina without distortion.

    With ``dot=True`` the result is a **non-template** badged icon: the glyph is
    toned to a neutral grey that reads on both light and dark menu bars, and a
    bright gold dot is composited top-right — the ambient "an unseen insight is
    waiting" signal. The caller must set ``template = False`` for that variant so
    the gold survives (a template image would be recoloured to a single tint).
    """
    if not _APPKIT_AVAILABLE:
        return None
    symbol = sf_symbol(name, point=point, weight=weight, template=True)
    if symbol is None:
        return None
    from AppKit import (
        NSBitmapImageFileTypePNG,
        NSColor,
        NSCompositingOperationSourceAtop,
        NSCompositingOperationSourceOver,
        NSGraphicsContext,
    )
    from Foundation import NSMakeRect, NSMakeSize

    size = symbol.size()
    scale = (
        min(pixel_size / size.width, pixel_size / size.height)
        if (size.width and size.height)
        else 1.0
    )
    draw_w, draw_h = size.width * scale, size.height * scale
    origin_x = (pixel_size - draw_w) / 2.0
    origin_y = (pixel_size - draw_h) / 2.0

    canvas = NSImage.alloc().initWithSize_(NSMakeSize(pixel_size, pixel_size))
    canvas.lockFocus()
    NSGraphicsContext.currentContext().setShouldAntialias_(True)
    symbol.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(origin_x, origin_y, draw_w, draw_h),
        NSMakeRect(0, 0, 0, 0),
        NSCompositingOperationSourceOver,
        1.0,
    )
    if dot:
        from AppKit import NSBezierPath, NSRectFillUsingOperation

        # Tone the (template-black) glyph to a menu-bar-readable grey.
        NSColor.colorWithRed_green_blue_alpha_(0.62, 0.6, 0.56, 1.0).set()
        NSRectFillUsingOperation(
            NSMakeRect(0, 0, pixel_size, pixel_size),
            NSCompositingOperationSourceAtop,
        )
        # Bright gold dot, top-right (image coords: origin bottom-left).
        r = pixel_size * 0.19
        cx = pixel_size - r - pixel_size * 0.02
        cy = pixel_size - r - pixel_size * 0.02
        NSColor.colorWithRed_green_blue_alpha_(0.84, 0.69, 0.20, 1.0).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(cx - r, cy - r, 2 * r, 2 * r)
        ).fill()
        NSColor.colorWithRed_green_blue_alpha_(0.96, 0.87, 0.56, 1.0).setFill()
        ir = r * 0.5
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(cx - ir, cy - ir, 2 * ir, 2 * ir)
        ).fill()
    canvas.unlockFocus()

    from AppKit import NSBitmapImageRep

    rep = NSBitmapImageRep.imageRepWithData_(canvas.TIFFRepresentation())
    if rep is None:
        return None
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    return bytes(png) if png is not None else None


#: Vibrancy materials by role. Resolved lazily so the module imports without
#: AppKit; unknown names fall back to the popover material.
_MATERIAL_NAMES = {
    "popover": "NSVisualEffectMaterialPopover",
    "sidebar": "NSVisualEffectMaterialSidebar",
    "menu": "NSVisualEffectMaterialMenu",
    "window": "NSVisualEffectMaterialWindowBackground",
    "hud": "NSVisualEffectMaterialHUDWindow",
}


def vibrant_view(frame=None, material: str = "popover"):
    """A configured ``NSVisualEffectView`` (active, within-window), or ``None``."""
    if not _APPKIT_AVAILABLE:
        return None
    import AppKit

    view = (
        NSVisualEffectView.alloc().initWithFrame_(frame)
        if frame is not None
        else NSVisualEffectView.alloc().init()
    )
    const = _MATERIAL_NAMES.get(material, _MATERIAL_NAMES["popover"])
    material_value = getattr(AppKit, const, getattr(AppKit, _MATERIAL_NAMES["popover"]))
    view.setMaterial_(material_value)
    view.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
    view.setState_(AppKit.NSVisualEffectStateActive)
    return view


def make_label(text: str, style: str = "body", secondary: bool = False):
    """A non-editable, transparent ``NSTextField`` label, or ``None``.

    Uses the type scale and system label colours — the building block that keeps
    typography consistent across windows.
    """
    if not _APPKIT_AVAILABLE:
        return None
    from AppKit import NSTextField

    label = NSTextField.labelWithString_(text)
    label.setFont_(system_font(style))
    label.setTextColor_(
        NSColor.secondaryLabelColor() if secondary else NSColor.labelColor()
    )
    return label


def make_primary_button(title: str, target=None, action=None):
    """A prominent push button tinted with the brand accent, or ``None``."""
    if not _APPKIT_AVAILABLE:
        return None
    from AppKit import NSButton

    button = NSButton.buttonWithTitle_target_action_(title, target, action)
    # macOS 11+: prominent style + accent tint reads as the primary action.
    try:
        import AppKit

        button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        button.setControlSize_(AppKit.NSControlSizeLarge)
        button.setBezelColor_(accent_color())
    except Exception:  # pragma: no cover - cosmetic only
        pass
    return button
