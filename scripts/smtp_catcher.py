#!/usr/bin/env python3
"""Minimal SMTP catcher used to prove the mail path end to end.

Listens on a local port, accepts one message, writes it to disk and prints
the envelope.  Used by the mail test; in Docker Compose this role is played
by MailHog.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    writer.write(b"220 localhost ESMTP wiseq-test\r\n")
    await writer.drain()
    data_lines: list[str] = []
    in_data = False
    while True:
        line = await reader.readline()
        if not line:
            break
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if in_data:
            if text == ".":
                in_data = False
                writer.write(b"250 OK: queued\r\n")
                await writer.drain()
                continue
            data_lines.append(text)
            continue
        cmd = text.split(" ")[0].upper()
        if cmd in ("HELO", "EHLO"):
            writer.write(b"250-localhost\r\n250 SIZE 10485760\r\n")
        elif cmd == "MAIL":
            writer.write(b"250 OK\r\n")
        elif cmd == "RCPT":
            writer.write(b"250 OK\r\n")
        elif cmd == "DATA":
            writer.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            in_data = True
        elif cmd == "QUIT":
            writer.write(b"221 Bye\r\n")
            await writer.drain()
            break
        elif cmd == "RSET":
            writer.write(b"250 OK\r\n")
        else:
            writer.write(b"250 OK\r\n")
        await writer.drain()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/smtp_capture.txt")
    out.write_text("\n".join(data_lines), encoding="utf-8")
    writer.close()


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1025
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
