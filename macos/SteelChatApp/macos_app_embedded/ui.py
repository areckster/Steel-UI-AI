"""UI components shared between the standalone macOS app and the embedded bundle."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Dict, List, Union

import httpx

from Cocoa import (
    NSAlert,
    NSAlertStyleInformational,
    NSAppearance,
    NSAppearanceNameVibrantDark,
    NSApp,
    NSApplication,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSMakeRect,
    NSLayoutConstraint,
    NSLayoutConstraintOrientationHorizontal,
    NSLayoutRelationEqual,
    NSMenu,
    NSMenuItem,
    NSOpenPanel,
    NSProgressIndicator,
    NSScrollView,
    NSSavePanel,
    NSSegmentedControl,
    NSSegmentedControlSegmentStyle,
    NSSegmentedCell,
    NSTextAlignmentRight,
    NSTextField,
    NSTextView,
    NSView,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMask,
)
from Foundation import NSBundle, NSObject, NSURL
from PyObjCTools import AppHelper
from WebKit import (
    WKUserContentController,
    WKUserScript,
    WKUserScriptInjectionTimeAtDocumentStart,
    WKWebView,
    WKWebViewConfiguration,
)


def main_thread(func):
    """Decorator to ensure UI updates are on the main thread."""

    def wrapper(*args, **kwargs):
        AppHelper.callAfter(func, *args, **kwargs)

    return wrapper


class ChatClient:
    """Thin async client for server endpoints, with thread helpers."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self._loop = asyncio.new_event_loop()
        self._thr = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thr.start()
        self._client = httpx.AsyncClient(http2=True, timeout=None)

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _post_stream(self, path: str, json_body: Dict[str, Any]):
        url = f"{self.base}{path}"
        async with self._client.stream("POST", url, json=json_body) as resp:
            async for chunk in resp.aiter_lines():
                if not chunk:
                    continue
                if not chunk.startswith("data:"):
                    continue
                payload = chunk[5:].strip()
                if not payload:
                    continue
                try:
                    evt = json.loads(payload)
                    yield evt
                except Exception:
                    continue

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        settings: Dict[str, Any],
        system: str,
        on_event,
    ):
        async def _run_stream():
            body = {"messages": messages, "settings": settings, "system": system}
            try:
                async for evt in self._post_stream("/api/chat/stream", body):
                    on_event(evt)
            except Exception as e:
                on_event({"type": "error", "message": f"{type(e).__name__}: {e}"})

        self._run(_run_stream())

    def models(self, on_result):
        async def _get():
            try:
                r = await self._client.get(f"{self.base}/api/models", timeout=10.0)
                on_result(r.json())
            except Exception as e:
                on_result({"error": str(e)})

        self._run(_get())

    def set_model(self, tag: str, on_result):
        async def _post():
            try:
                r = await self._client.post(
                    f"{self.base}/api/models/set", json={"model": tag}
                )
                on_result(r.json())
            except Exception as e:
                on_result({"error": str(e)})

        self._run(_post())

    def health(self, on_result):
        async def _get():
            try:
                r = await self._client.get(f"{self.base}/api/health", timeout=5.0)
                on_result(r.json())
            except Exception as e:
                on_result({"ok": False, "error": str(e)})

        self._run(_get())


class NativeChatView(NSView):
    """Native chat UI: messages list, composer, telemetry, settings access."""

    def initWithClient_(self, client: ChatClient):
        self = super().init()
        if self is None:
            return None
        self.client = client
        self.history: List[Dict[str, str]] = []
        self.streaming = False
        self.settings: Dict[str, Any] = {
            "dynamic_ctx": True,
            "max_ctx": 40000,
            "num_ctx": 8192,
            "temperature": 0.9,
            "top_p": 0.9,
            "top_k": 100,
            "num_predict": "",
            "seed": "",
        }
        self.system = ""
        self.attachments: List[Dict[str, Any]] = []
        self._assistant_buf = ""
        self._started_at = 0.0
        self._first_byte = 0.0
        self._last_token_est = 0
        self._build()
        return self

    def _build(self):
        self.setTranslatesAutoresizingMaskIntoConstraints_(False)

        self.bg = NSVisualEffectView.alloc().init()
        self.bg.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.bg.setBlendingMode_(0)
        self.bg.setMaterial_(0)
        self.addSubview_(self.bg)

        self.scroll = NSScrollView.alloc().init()
        self.scroll.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.scroll.setHasVerticalScroller_(True)
        self.text = NSTextView.alloc().init()
        self.text.setEditable_(False)
        self.text.setRichText_(True)
        self.text.setDrawsBackground_(False)
        self.scroll.setDocumentView_(self.text)
        self.addSubview_(self.scroll)

        self.prompt = NSTextView.alloc().init()
        self.prompt.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.prompt.setRichText_(False)
        self.prompt.setFont_(self.text.font())
        self.prompt.setString_("")

        self.sendBtn = NSButton.alloc().init()
        self.sendBtn.setTitle_("Send")
        self.sendBtn.setBezelStyle_(NSBezelStyleRounded)
        self.sendBtn.setTarget_(self)
        self.sendBtn.setAction_(b"send:")

        self.attachBtn = NSButton.alloc().init()
        self.attachBtn.setTitle_("Attach…")
        self.attachBtn.setBezelStyle_(NSBezelStyleRounded)
        self.attachBtn.setTarget_(self)
        self.attachBtn.setAction_(b"attach:")

        self.telemetry = NSTextField.alloc().init()
        self.telemetry.setEditable_(False)
        self.telemetry.setBezeled_(False)
        self.telemetry.setDrawsBackground_(False)
        self.telemetry.setAlignment_(NSTextAlignmentRight)
        self.telemetry.setStringValue_("tkn: —/— • — ms")

        self.spinner = NSProgressIndicator.alloc().init()
        self.spinner.setStyle_(1)
        self.spinner.setDisplayedWhenStopped_(False)

        self.addSubview_(self.prompt)
        self.addSubview_(self.sendBtn)
        self.addSubview_(self.attachBtn)
        self.addSubview_(self.telemetry)
        self.addSubview_(self.spinner)

        for view in (
            self.bg,
            self.scroll,
            self.prompt,
            self.sendBtn,
            self.attachBtn,
            self.telemetry,
            self.spinner,
        ):
            view.setTranslatesAutoresizingMaskIntoConstraints_(False)

        def pin(a, attr_a, b, attr_b, constant=0.0):
            self.addConstraint_(
                NSLayoutConstraint.constraintWithItem_attribute_relatedBy_toItem_attribute_multiplier_constant_(
                    a, attr_a, 0, b, attr_b, 1.0, constant
                )
            )

        pin(self.bg, 0, self, 0, 0.0)
        pin(self.bg, 1, self, 1, 0.0)
        pin(self.bg, 2, self, 2, 0.0)
        pin(self.bg, 3, self, 3, 0.0)

        pad = 12.0
        pin(self.scroll, 0, self, 0, pad)
        pin(self.scroll, 1, self, 1, -120)
        pin(self.scroll, 2, self, 2, pad)
        pin(self.scroll, 3, self, 3, -pad)

        pin(self.prompt, 0, self.scroll, 1, 20.0)
        pin(self.prompt, 1, self, 1, -60)
        pin(self.prompt, 2, self, 2, pad)
        pin(self.prompt, 3, self, 3, -160)

        pin(self.sendBtn, 1, self, 1, -60)
        pin(self.sendBtn, 2, self, 2, -pad)
        pin(self.attachBtn, 1, self, 1, -60)
        pin(self.attachBtn, 2, self, 2, -100)

        pin(self.telemetry, 0, self.prompt, 0, -50)
        pin(self.telemetry, 2, self, 2, pad)
        pin(self.telemetry, 3, self, 3, -pad)

        pin(self.spinner, 1, self.prompt, 1, 0.0)
        pin(self.spinner, 2, self, 2, -pad)

        self.text.setAutomaticQuoteSubstitutionEnabled_(False)
        self.text.setAutomaticDashSubstitutionEnabled_(False)
        self.text.setAutomaticTextReplacementEnabled_(False)
        self.text.setAutomaticSpellingCorrectionEnabled_(False)
        self.prompt.setAutomaticQuoteSubstitutionEnabled_(False)
        self.prompt.setAutomaticDashSubstitutionEnabled_(False)
        self.prompt.setAutomaticTextReplacementEnabled_(False)
        self.prompt.setAutomaticSpellingCorrectionEnabled_(False)

        NSApp.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameVibrantDark))

    def _append_system(self, text: str):
        buf = self.text.string() or ""
        buf += f"\n\n🛠 {text}\n"
        self.text.setString_(buf)
        self.text.scrollToEndOfDocument_(None)

    def _append_user(self, content: str):
        from AppKit import NSAttributedString

        attr = NSAttributedString.alloc().initWithString_(
            f"\n\nYOU:\n{content}\n"
        )
        self.text.textStorage().appendAttributedString_(attr)
        self.text.scrollToEndOfDocument_(None)

    def _append_assistant_delta(self, delta: str):
        if not delta:
            return
        from AppKit import NSAttributedString

        attr = NSAttributedString.alloc().initWithString_(delta)
        self.text.textStorage().appendAttributedString_(attr)
        self.text.scrollToEndOfDocument_(None)
        self._last_token_est = max(self._last_token_est, int(len(delta) / 4))
        self._update_telemetry()

    def _append_assistant_done(self):
        from AppKit import NSAttributedString

        end = NSAttributedString.alloc().initWithString_("\n\n")
        self.text.textStorage().appendAttributedString_(end)
        self.text.scrollToEndOfDocument_(None)

    def _build_user_payload(self, prompt: str) -> str:
        user = prompt
        for att in self.attachments:
            if att.get("type") == "text" and att.get("text"):
                user += (
                    f"\n\n**File: {att.get('name','file')}**\n```\n{att['text']}\n```\n"
                )
            elif att.get("type") == "image" and att.get("url"):
                user += f"\n\n![{att.get('name', 'image')}]({att['url']})\n"
            else:
                user += f"\n\n(Attached file: {att.get('name', 'file')})\n"
        return user

    def send_(self, _):
        if self.streaming:
            # No cancel in this simple version
            return
        prompt = str(self.prompt.string()).strip()
        if not prompt and not self.attachments:
            return
        user_text = self._build_user_payload(prompt)
        self.history.append({"role": "user", "content": user_text})
        self._append_user(user_text)
        self.prompt.setString_("")
        self.streaming = True
        self.spinner.startAnimation_(None)
        import time

        self._started_at = time.perf_counter()
        self._first_byte = 0.0
        self._last_token_est = 0
        self._update_telemetry(in_tokens=int(len(user_text) / 4))
        self._assistant_buf = ""
        self._start_stream()

    def attach_(self, _):
        panel = NSOpenPanel.openPanel()
        panel.setAllowsMultipleSelection_(True)
        if panel.runModal():
            for url in panel.URLs():
                path = url.path()
                try:
                    name = os.path.basename(path)
                    with open(path, "rb") as handle:
                        data = handle.read()
                    # Heuristic: treat small files as text
                    try:
                        text = data.decode("utf-8")
                        self.attachments.append(
                            {"type": "text", "name": name, "text": text}
                        )
                    except Exception:
                        self.attachments.append(
                            {"type": "binary", "name": name}
                        )
                except Exception as exc:
                    self._append_system(f"Failed to attach: {exc}")

    def _on_event(self, evt: Dict[str, Any]):
        typ = evt.get("type")
        if typ == "delta":
            delta = evt.get("delta", "")
            if self._first_byte == 0.0:
                import time

                self._first_byte = time.perf_counter()
                self._update_telemetry()
            self._append_assistant_delta(delta)
            try:
                self._assistant_buf += delta
            except Exception:
                self._assistant_buf = delta
        elif typ == "tool_calls":
            self._append_system("[tools] running…")
        elif typ == "tool_result":
            name = evt.get("name")
            self._append_system(f"[tool:{name}] done")
        elif typ == "done":
            self._append_assistant_done()
            self.streaming = False
            self.spinner.stopAnimation_(None)
            if getattr(self, "_assistant_buf", ""):
                self.history.append(
                    {"role": "assistant", "content": self._assistant_buf}
                )
        elif typ == "error":
            self._append_system(f"Error: {evt.get('message')}")
            self.streaming = False
            self.spinner.stopAnimation_(None)

    def _start_stream(self):
        settings = dict(self.settings)
        system = self.system
        self.client.chat_stream(self.history, settings, system, self._on_event)

    def _update_telemetry(self, in_tokens: int | None = None):
        import time

        latency_ms = "—"
        if self._first_byte:
            latency_ms = f"{int(1000 * (self._first_byte - self._started_at))} ms"
        out = self._last_token_est or 0
        if in_tokens is None:
            in_tokens = 0
            if self.history:
                in_tokens = int(len(self.history[-1].get("content", "")) / 4)
        self.telemetry.setStringValue_(f"tkn: {in_tokens}/{out} • {latency_ms}")


class SettingsPanel(NSWindow):
    """Settings window exposing model and runtime controls."""

    def initWithClient_native_(self, client: ChatClient, native: NativeChatView):
        style = NSWindowStyleMask.titled | NSWindowStyleMask.closable
        self = super().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 520, 560), style, NSBackingStoreBuffered, False
        )
        if self is None:
            return None

        self.setTitle_("Settings")
        self.client = client
        self.native = native

        root = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 520, 560))
        root.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.setContentView_(root)

        def label(text: str) -> NSTextField:
            field = NSTextField.alloc().init()
            field.setEditable_(False)
            field.setBezeled_(False)
            field.setDrawsBackground_(False)
            field.setStringValue_(text)
            return field

        def number_field(value: Any) -> NSTextField:
            field = NSTextField.alloc().init()
            field.setStringValue_(str(value))
            return field

        self.modelField = NSTextField.alloc().init()
        self.modelField.setStringValue_("")
        self.useBtn = NSButton.alloc().init()
        self.useBtn.setTitle_("Use Model")
        self.useBtn.setTarget_(self)
        self.useBtn.setAction_(b"applyModel:")

        self.refreshBtn = NSButton.alloc().init()
        self.refreshBtn.setTitle_("Installed…")
        self.refreshBtn.setTarget_(self)
        self.refreshBtn.setAction_(b"refreshModels:")

        self.modelsList = NSTextView.alloc().init()
        self.modelsList.setEditable_(False)

        self.systemField = NSTextView.alloc().init()
        self.systemField.setEditable_(True)

        self.dynamicField = NSButton.alloc().init()
        self.dynamicField.setTitle_("Dynamic Context")
        self.dynamicField.setButtonType_(3)
        self.dynamicField.setState_(1)

        self.maxCtxField = number_field(40000)
        self.numCtxField = number_field(8192)
        self.tempField = number_field(0.9)
        self.topPField = number_field(0.9)
        self.topKField = number_field(100)
        self.numPredictField = NSTextField.alloc().init()
        self.numPredictField.setStringValue_("")
        self.seedField = NSTextField.alloc().init()
        self.seedField.setStringValue_("")

        self.applySettingsBtn = NSButton.alloc().init()
        self.applySettingsBtn.setTitle_("Apply Settings")
        self.applySettingsBtn.setTarget_(self)
        self.applySettingsBtn.setAction_(b"applySettings:")

        self.healthField = NSTextField.alloc().init()
        self.healthField.setEditable_(False)
        self.healthField.setBezeled_(False)
        self.healthField.setDrawsBackground_(False)
        self.healthField.setStringValue_("Checking backend…")

        y = 520

        def add(view: NSView, height: float = 24, pad: float = 8) -> None:
            nonlocal y
            y -= height + pad
            view.setFrame_(NSMakeRect(16, y, 488, height))
            root.addSubview_(view)

        add(label("Model tag:"))
        add(self.modelField)

        row = NSView.alloc().initWithFrame_(NSMakeRect(16, y - 26, 488, 26))
        root.addSubview_(row)
        y -= 26 + 8

        self.useBtn.setFrame_(NSMakeRect(0, 0, 120, 26))
        row.addSubview_(self.useBtn)
        self.refreshBtn.setFrame_(NSMakeRect(128, 0, 120, 26))
        row.addSubview_(self.refreshBtn)

        add(label("Installed models:"))
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(16, y - 120, 488, 120))
        y -= 120 + 8
        scroll.setHasVerticalScroller_(True)
        scroll.setDocumentView_(self.modelsList)
        root.addSubview_(scroll)

        add(label("System prompt:"), height=18)
        system_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(16, y - 100, 488, 100))
        y -= 100 + 8
        system_scroll.setHasVerticalScroller_(True)
        system_scroll.setDocumentView_(self.systemField)
        root.addSubview_(system_scroll)

        add(self.dynamicField)
        add(label("Max Context"))
        add(self.maxCtxField)
        add(label("Static Context (num_ctx)"))
        add(self.numCtxField)
        add(label("Temperature"))
        add(self.tempField)
        add(label("top_p"))
        add(self.topPField)
        add(label("top_k"))
        add(self.topKField)
        add(label("num_predict (optional)"))
        add(self.numPredictField)
        add(label("seed (optional)"))
        add(self.seedField)
        add(self.applySettingsBtn)
        add(self.healthField)

        self._sync_from_native()
        self._check_health()

        return self

    def _sync_from_native(self) -> None:
        settings = self.native.settings
        self.dynamicField.setState_(1 if settings.get("dynamic_ctx") else 0)
        self.maxCtxField.setStringValue_(str(settings.get("max_ctx", 40000)))
        self.numCtxField.setStringValue_(str(settings.get("num_ctx", 8192)))
        self.tempField.setStringValue_(str(settings.get("temperature", 0.9)))
        self.topPField.setStringValue_(str(settings.get("top_p", 0.9)))
        self.topKField.setStringValue_(str(settings.get("top_k", 100)))
        self.numPredictField.setStringValue_(str(settings.get("num_predict", "")))
        self.seedField.setStringValue_(str(settings.get("seed", "")))
        self.systemField.setString_(self.native.system or "")

    def applySettings_(self, _sender) -> None:
        self.native.settings = {
            "dynamic_ctx": bool(self.dynamicField.state()),
            "max_ctx": int(self.maxCtxField.stringValue() or "40000"),
            "num_ctx": int(self.numCtxField.stringValue() or "8192"),
            "temperature": float(self.tempField.stringValue() or "0.9"),
            "top_p": float(self.topPField.stringValue() or "0.9"),
            "top_k": int(self.topKField.stringValue() or "100"),
            "num_predict": (self.numPredictField.stringValue() or "").strip(),
            "seed": (self.seedField.stringValue() or "").strip(),
        }
        self.native.system = str(self.systemField.string() or "")

    def refreshModels_(self, _sender) -> None:
        def on_result(obj: Dict[str, Any]) -> None:
            self.modelsList.setString_(json.dumps(obj, indent=2))

        self.client.models(on_result)

    def applyModel_(self, _sender) -> None:
        tag = self.modelField.stringValue()
        if not tag:
            return

        def on_result(obj: Dict[str, Any]) -> None:
            NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                "Model", "OK", None, None, json.dumps(obj)
            ).runModal()

        self.client.set_model(tag, on_result)

    def _check_health(self) -> None:
        def on_health(payload: Dict[str, Any]) -> None:
            if payload.get("ok"):
                self.healthField.setStringValue_(
                    f"Backend OK • model: {payload.get('model')}"
                )
            else:
                self.healthField.setStringValue_(
                    f"Backend DOWN: {payload.get('error', 'unknown')}"
                )

        self.client.health(on_health)


def _fetch_patch_script(base: str) -> str:
    return f"""
    (function() {{
        const BASE = {json.dumps(base)};
        const originalFetch = window.fetch.bind(window);
        window.fetch = function(resource, init) {{
            if (typeof resource === 'string' && resource.startsWith('/')) {{
                resource = BASE + resource;
            }} else if (resource instanceof Request && resource.url && resource.url.startsWith('/')) {{
                resource = new Request(BASE + resource.url, resource);
            }}
            return originalFetch(resource, init);
        }};
    }})();
    """


def build_web_chat_view(port_or_base: Union[int, str]) -> WKWebView:
    """Create a WKWebView configured to load the packaged index.html and point it at the backend."""

    if isinstance(port_or_base, int):
        base_url = f"http://127.0.0.1:{port_or_base}"
    else:
        base_url = str(port_or_base).rstrip("/")
    config = WKWebViewConfiguration.alloc().init()
    controller = WKUserContentController.alloc().init()
    script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        _fetch_patch_script(base_url),
        WKUserScriptInjectionTimeAtDocumentStart,
        True,
    )
    controller.addUserScript_(script)
    port_script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        f"window.STEELCHAT_BACKEND = '{base_url}';",
        WKUserScriptInjectionTimeAtDocumentStart,
        True,
    )
    controller.addUserScript_(port_script)
    config.setUserContentController_(controller)
    web = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 900, 640), config)

    bundle = NSBundle.mainBundle()
    html_path = bundle.pathForResource_ofType_inDirectory_("index", "html", "web")
    if html_path is not None:
        url = NSURL.fileURLWithPath_(html_path)
        root = url.URLByDeletingLastPathComponent()
        web.loadFileURL_allowingReadAccessToURL_(url, root)

    return web


__all__ = [
    "ChatClient",
    "NativeChatView",
    "SettingsPanel",
    "build_web_chat_view",
    "main_thread",
]
