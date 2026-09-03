#!/usr/bin/env python3
"""시크릿을 사람에게서 받되, 대화창을 거치지 않는다.

왜 이것이 있는가
----------------
본부장은 터미널을 열지 않는다. 그렇다고 에이전트가 대화로
"Client Secret 을 알려주십시오" 라고 물으면 그 값이 대화 로그에 영구히 남는다.

그래서 값은 **별도 창**에서 받는다. 에이전트는 창을 띄우라고 시킬 뿐이고,
입력된 값은 이 프로세스 안에서 바로 키체인으로 들어간다. 에이전트가 보는 것은
마스킹된 결과뿐이다.

창을 띄우는 방법은 환경에 따라 네 단계로 물러난다.
    1. tkinter          — 표준 라이브러리. Windows/macOS 모두 있는 것이 정상
    2. osascript        — macOS 에서 tkinter 가 없을 때
    3. PowerShell       — Windows 에서 tkinter 가 없을 때
    4. TTY 프롬프트     — 사람이 직접 터미널을 쓰는 경우 (챔피언 세팅)
"""

from __future__ import annotations

import os
import subprocess
import sys


class PromptUnavailable(RuntimeError):
    """이 환경에서는 창을 띄울 수 없다."""


def _via_tkinter(fields: list[tuple[str, str, bool]], title: str) -> dict[str, str]:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                                   # pragma: no cover
        raise PromptUnavailable(f"tkinter 없음: {exc}") from exc

    result: dict[str, str] = {}
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=16)
    frame.grid()
    ttk.Label(
        frame,
        text="아래 값은 이 컴퓨터의 보안 저장소에만 저장됩니다.\n대화 기록에는 남지 않습니다.",
        justify="left",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

    entries: dict[str, tk.Entry] = {}
    for i, (key, label, secret) in enumerate(fields, start=1):
        ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", padx=(0, 10), pady=4)
        e = ttk.Entry(frame, width=46, show="*" if secret else "")
        e.grid(row=i, column=1, pady=4)
        entries[key] = e
    entries[fields[0][0]].focus_set()

    status = ttk.Label(frame, text="", foreground="#b00")
    status.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def submit(_event=None) -> None:
        missing = [lbl for k, lbl, _ in fields if not entries[k].get().strip()]
        if missing:
            status.config(text="빈 칸: " + ", ".join(missing))
            return
        for k, _, _ in fields:
            result[k] = entries[k].get().strip()
        root.destroy()

    def cancel(_event=None) -> None:
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(buttons, text="취소", command=cancel).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="저장", command=submit).grid(row=0, column=1)
    root.bind("<Return>", submit)
    root.bind("<Escape>", cancel)

    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 3
    root.geometry(f"+{x}+{y}")
    root.mainloop()

    if not result:
        raise KeyboardInterrupt("사용자가 입력을 취소했습니다")
    return result


def _via_osascript(fields: list[tuple[str, str, bool]], title: str) -> dict[str, str]:
    if sys.platform != "darwin":
        raise PromptUnavailable("macOS 아님")
    result: dict[str, str] = {}
    for key, label, secret in fields:
        script = (
            f'display dialog "{label}" default answer "" '
            f'with title "{title}"'
            + (" with hidden answer" if secret else "")
        )
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if proc.returncode != 0:
            raise KeyboardInterrupt("사용자가 입력을 취소했습니다")
        value = ""
        for part in proc.stdout.strip().split(", "):
            if part.startswith("text returned:"):
                value = part.split(":", 1)[1]
        if not value.strip():
            raise KeyboardInterrupt(f"{label} 이(가) 비어 있습니다")
        result[key] = value.strip()
    return result


_PS_FORM = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$f = New-Object Windows.Forms.Form
$f.Text = "{title}"
$f.Size = New-Object Drawing.Size(520, {height})
$f.StartPosition = "CenterScreen"
$f.TopMost = $true
$note = New-Object Windows.Forms.Label
$note.Text = "아래 값은 이 컴퓨터의 보안 저장소에만 저장됩니다."
$note.Location = New-Object Drawing.Point(14, 12)
$note.Size = New-Object Drawing.Size(470, 20)
$f.Controls.Add($note)
{controls}
$ok = New-Object Windows.Forms.Button
$ok.Text = "저장"
$ok.Location = New-Object Drawing.Point(300, {buttony})
$ok.DialogResult = [Windows.Forms.DialogResult]::OK
$f.Controls.Add($ok); $f.AcceptButton = $ok
$no = New-Object Windows.Forms.Button
$no.Text = "취소"
$no.Location = New-Object Drawing.Point(390, {buttony})
$no.DialogResult = [Windows.Forms.DialogResult]::Cancel
$f.Controls.Add($no); $f.CancelButton = $no
if ($f.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) {{ exit 1 }}
{outputs}
"""


def _via_powershell(fields: list[tuple[str, str, bool]], title: str) -> dict[str, str]:
    if os.name != "nt":
        raise PromptUnavailable("Windows 아님")
    controls, outputs = [], []
    y = 44
    for i, (key, label, secret) in enumerate(fields):
        controls.append(
            f'$l{i} = New-Object Windows.Forms.Label; $l{i}.Text = "{label}"; '
            f'$l{i}.Location = New-Object Drawing.Point(14, {y}); '
            f'$l{i}.Size = New-Object Drawing.Size(140, 20); $f.Controls.Add($l{i})'
        )
        controls.append(
            f'$t{i} = New-Object Windows.Forms.TextBox; '
            f'$t{i}.Location = New-Object Drawing.Point(160, {y - 3}); '
            f'$t{i}.Size = New-Object Drawing.Size(320, 22); '
            + (f'$t{i}.UseSystemPasswordChar = $true; ' if secret else "")
            + f'$f.Controls.Add($t{i})'
        )
        outputs.append(f'Write-Output ("{key}=" + $t{i}.Text)')
        y += 34
    script = _PS_FORM.format(
        title=title, height=y + 110, buttony=y + 10,
        controls="\n".join(controls), outputs="\n".join(outputs),
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise KeyboardInterrupt("사용자가 입력을 취소했습니다")
    result = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    for key, label, _ in fields:
        if not result.get(key):
            raise KeyboardInterrupt(f"{label} 이(가) 비어 있습니다")
    return result


def _via_tty(fields: list[tuple[str, str, bool]], title: str) -> dict[str, str]:
    if not sys.stdin.isatty():
        raise PromptUnavailable("TTY 없음 (에이전트가 실행 중)")
    import getpass
    print(f"\n{title}", file=sys.stderr)
    result = {}
    for key, label, secret in fields:
        value = (getpass.getpass(f"  {label}: ") if secret else input(f"  {label}: ")).strip()
        if not value:
            raise KeyboardInterrupt(f"{label} 이(가) 비어 있습니다")
        result[key] = value
    return result


def ask(fields: list[tuple[str, str, bool]], title: str = "설정") -> dict[str, str]:
    """(key, 라벨, 시크릿여부) 목록을 받아 값을 돌려준다.

    창을 띄우는 방법을 순서대로 시도한다. 전부 실패하면 PromptUnavailable.
    """
    errors = []
    for fn in (_via_tkinter, _via_osascript, _via_powershell, _via_tty):
        try:
            return fn(fields, title)
        except PromptUnavailable as exc:
            errors.append(f"{fn.__name__}: {exc}")
    raise PromptUnavailable(
        "입력 창을 띄울 수 없습니다.\n  " + "\n  ".join(errors)
    )
