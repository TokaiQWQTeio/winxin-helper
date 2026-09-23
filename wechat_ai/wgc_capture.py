"""Capture one WeChat window frame in a fresh process without UIA/COM imports."""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hwnd", type=int)
    parser.add_argument("output")
    args = parser.parse_args()

    from windows_capture import WindowsCapture, Frame, InternalCaptureControl

    capture = WindowsCapture(
        cursor_capture=False, draw_border=False, window_hwnd=args.hwnd,
    )

    @capture.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl) -> None:
        frame.save_as_image(args.output)
        control.stop()

    @capture.event
    def on_closed() -> None:
        pass

    capture.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
