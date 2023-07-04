import serial  # type: ignore
import time
from typing import List, Optional, Tuple


class TerminalException(Exception):
    pass


class Terminal:
    ESCAPE: bytes = b"\x1B"

    BOX_CHARSET: bytes = b"(0"
    NORMAL_CHARSET: bytes = b"(B"

    REQUEST_STATUS: bytes = b"[5n"
    STATUS_OKAY: bytes = b"[0n"

    REQUEST_CURSOR: bytes = b"[6n"

    MOVE_CURSOR_ORIGIN: bytes = b"[H"
    MOVE_CURSOR_UP: bytes = b"M"
    MOVE_CURSOR_DOWN: bytes = b"D"

    CLEAR_TO_ORIGIN: bytes = b"[1J"
    CLEAR_TO_END_OF_LINE: bytes = b"[0K"
    CLEAR_SCREEN: bytes = b"[2J"
    CLEAR_LINE: bytes = b"[2K"

    SET_132_COLUMNS: bytes = b"[?3h"
    SET_80_COLUMNS: bytes = b"[?3l"

    TURN_ON_REGION: bytes = b"[?6h"
    TURN_OFF_REGION: bytes = b"[?6l"

    TURN_ON_AUTOWRAP: bytes = b"[?7h"
    TURN_OFF_AUTOWRAP: bytes = b"[?7l"

    SET_BOLD: bytes = b"[1m"
    SET_NORMAL: bytes = b"[m"
    SET_REVERSE: bytes = b"[7m"

    SAVE_CURSOR: bytes = b"7"
    RESTORE_CURSOR: bytes = b"8"

    UP: bytes = b"[A"
    DOWN: bytes = b"[B"
    LEFT: bytes = b"[D"
    RIGHT: bytes = b"[C"
    BACKSPACE: bytes = b"\x08"
    DELETE: bytes = b"\x7F"

    CHECK_INTERVAL: float = 1.0
    MAX_FAILURES: int = 3

    def __init__(self, port: str, baud: int) -> None:
        self.serial = serial.Serial(port, baud, timeout=0.01)
        self.leftover = b""
        self.pending: List[bytes] = []
        self.responses: List[bytes] = []
        self.reversed = False
        self.bolded = False
        self.lastPolled = time.time()
        self.pollFailures = 0

        # First, connect and figure out what's going on.
        self.checkOk()

        # Reset terminal.
        self.columns: int = 80
        self.rows: int = 24
        self.cursor: Tuple[int, int] = (-1, -1)
        self.reset()

    def reset(self) -> None:
        self.sendCommand(self.SET_80_COLUMNS)
        self.sendCommand(self.TURN_OFF_REGION)
        self.sendCommand(self.CLEAR_SCREEN)
        self.sendCommand(self.MOVE_CURSOR_ORIGIN)
        self.sendCommand(self.SET_NORMAL)
        self.sendCommand(self.TURN_OFF_AUTOWRAP)

    def isOk(self) -> bool:
        self.sendCommand(self.REQUEST_STATUS)
        return self.recvResponse(1.0) == self.STATUS_OKAY

    def checkOk(self) -> None:
        if not self.isOk():
            raise TerminalException("Terminal did not respond okay!")

    def set132Columns(self) -> None:
        self.sendCommand(self.SET_132_COLUMNS)
        self.checkOk()

    def set80Columns(self) -> None:
        self.sendCommand(self.SET_80_COLUMNS)
        self.checkOk()

    def sendCommand(self, cmd: bytes) -> None:
        self.cursor = (-1, -1)
        self.serial.write(self.ESCAPE)

        if cmd == self.SET_NORMAL:
            self.reversed = False
            self.bolded = False
        elif cmd == self.SET_REVERSE:
            self.reversed = True
        elif cmd == self.SET_BOLD:
            self.bolded = True
        elif cmd == self.SET_132_COLUMNS:
            self.columns = 132
        elif cmd == self.SET_80_COLUMNS:
            self.columns = 80

        self.serial.write(cmd)

    def moveCursor(self, row: int, col: int) -> None:
        if row < 1 or row > self.rows:
            return
        if col < 1 or col > self.columns:
            return

        self.sendCommand(f"[{row};{col}H".encode("ascii"))
        self.cursor = (row, col)

    def fetchCursor(self) -> Tuple[int, int]:
        if self.cursor[0] != -1 and self.cursor[1] != -1:
            return self.cursor

        self.sendCommand(self.REQUEST_CURSOR)
        for _ in range(12):
            # We could be mid-page refresh, so give a wide berth.
            resp = self.recvResponse(0.25)
            if not resp:
                # Ran out of responses, try sending the command again.
                self.sendCommand(self.REQUEST_CURSOR)
            elif resp[:1] != b"[" or resp[-1:] != b"R":
                # Manual escape sequence sent by user? Swallow and read next.
                continue
            else:
                # Got a valid response!
                break
        else:
            raise TerminalException("Couldn't receive cursor position from terminal!")
        respstr = resp[1:-1].decode("ascii")
        row, col = respstr.split(";", 1)
        self.cursor = (int(row), int(col))
        return self.cursor

    def sendText(self, text: str) -> None:
        self.cursor = (-1, -1)
        inAlt = False

        def alt(char: bytes) -> bytes:
            nonlocal inAlt

            add = False
            if not inAlt:
                inAlt = True
                add = True

            return ((self.ESCAPE + self.BOX_CHARSET) if add else b"") + char

        def norm(char: bytes) -> bytes:
            nonlocal inAlt

            add = False
            if inAlt:
                inAlt = False
                add = True

            return ((self.ESCAPE + self.NORMAL_CHARSET) if add else b"") + char

        def fb(data: str) -> bytes:
            try:
                return norm(data.encode("ascii"))
            except UnicodeEncodeError:
                # Box drawing mappings to VT-100
                if data == "\u2500":
                    return alt(b"\x71")
                if data == "\u2502":
                    return alt(b"\x78")
                if data == "\u250c":
                    return alt(b"\x6C")
                if data == "\u2510":
                    return alt(b"\x6B")
                if data == "\u2514":
                    return alt(b"\x6D")
                if data == "\u2518":
                    return alt(b"\x6A")

                # Fill-drawing mapping hacks.
                if data == "\u2591":
                    if not self.bolded:
                        # We can just display.
                        return alt(b"\x6E")
                    else:
                        # We must un-bold for this special drawing character. Then, we must re-bold,
                        # and possibly re-reverse if that was what was going on.
                        return alt(
                            self.ESCAPE
                            + self.SET_NORMAL
                            + (
                                (self.ESCAPE + self.SET_REVERSE)
                                if self.reversed
                                else b""
                            )
                            + b"\x6E"
                            + self.ESCAPE
                            + self.SET_BOLD
                        )
                if data == "\u2592":
                    if not self.bolded:
                        # We can just display.
                        return alt(b"\x61")
                    else:
                        # We must un-bold for this special drawing character. Then, we must re-bold,
                        # and possibly re-reverse if that was what was going on.
                        return alt(
                            self.ESCAPE
                            + self.SET_NORMAL
                            + (
                                (self.ESCAPE + self.SET_REVERSE)
                                if self.reversed
                                else b""
                            )
                            + b"\x61"
                            + self.ESCAPE
                            + self.SET_BOLD
                        )
                if data == "\u2593":
                    if self.bolded:
                        return alt(b"\x61")
                    else:
                        return alt(
                            self.ESCAPE
                            + self.SET_BOLD
                            + b"\x61"
                            + self.ESCAPE
                            + self.SET_NORMAL
                            + (
                                (self.ESCAPE + self.SET_REVERSE)
                                if self.reversed
                                else b""
                            )
                        )
                if data == "\u2588":
                    return norm(
                        self.ESCAPE
                        + (self.SET_NORMAL if self.reversed else self.SET_REVERSE)
                        + b" "
                        + self.ESCAPE
                        + (self.SET_REVERSE if self.reversed else self.SET_NORMAL)
                        + ((self.ESCAPE + self.SET_BOLD) if self.bolded else b"")
                    )

                # +/- combined.
                if data == "\xb1":
                    return alt(b"\x67")
                # degrees
                if data == "\xb0":
                    return alt(b"\x66")

                # Unknown unicode.
                return alt(b"\x60")

        self.sendCommand(self.NORMAL_CHARSET)
        self.serial.write(b"".join(fb(s) for s in text))
        self.sendCommand(self.NORMAL_CHARSET)

    def setAutoWrap(self, value: bool = True) -> None:
        if value:
            self.sendCommand(self.TURN_ON_AUTOWRAP)
        else:
            self.sendCommand(self.TURN_OFF_AUTOWRAP)

    def clearAutoWrap(self) -> None:
        self.setAutoWrap(False)

    def setScrollRegion(self, top: int, bottom: int) -> None:
        self.sendCommand(f"[{top};{bottom}r".encode("ascii"))
        self.sendCommand(self.TURN_ON_REGION)

    def clearScrollRegion(self) -> None:
        self.sendCommand(self.TURN_OFF_REGION)

    def recvResponse(self, timeout: Optional[float] = None) -> bytes:
        # Fetch the last received response in the input loop, or if that is empty,
        # attempt to read the next response from the serial terminal.
        if self.responses:
            response = self.responses[0]
            self.responses = self.responses[1:]
        else:
            response = self._recvResponse(timeout)
        return response

    def _recvResponse(self, timeout: Optional[float]) -> bytes:
        # Attempt to read the next response from the serial terminal, handling escaped
        # arrowkeys as inputs as apposed to command responses.
        while True:
            oldInputLen = len(self.pending)
            resp = self._recvResponseImpl(timeout)
            if resp or len(self.pending) > oldInputLen:
                # We got a successful response of some type, reset our polling.
                self.lastPolled = time.time()
            if resp in {self.UP, self.DOWN, self.LEFT, self.RIGHT}:
                self.pending.append(resp)
            else:
                return resp

    def _recvResponseImpl(self, timeout: Optional[float]) -> bytes:
        # Attempt to read from serial until we have a valid escaped response. All non
        # escaped responses will be placed into the user input buffer.
        gotResponse: bool = False
        accum: bytes = b""

        start = time.time()
        while True:
            # Grab extra command bits from previous call to recvResponse first, then
            # grab characters from the device itself.
            if self.leftover:
                val = self.leftover[0:1]
                self.leftover = self.leftover[1:]
            else:
                val = self.serial.read()

            if not val:
                if gotResponse or (timeout and (time.time() - start) > timeout):
                    # Got a full command here.
                    while accum and (accum[0:1] != self.ESCAPE):
                        self.pending.append(accum[0:1])
                        accum = accum[1:]

                    if accum and accum[0:1] == self.ESCAPE:
                        # We could have some regular input after this. So parse the command a little.
                        accum = accum[1:]

                        for offs in range(len(accum)):
                            val = accum[offs : (offs + 1)]
                            if val not in {
                                b"0",
                                b"1",
                                b"2",
                                b"3",
                                b"4",
                                b"5",
                                b"6",
                                b"7",
                                b"8",
                                b"9",
                                b";",
                                b"?",
                                b"[",
                            }:
                                # This is the last character, so everything after is going to
                                # end up being the next response or some user input.
                                # Add the rest of the leftovers to be processed next time.
                                self.leftover += accum[offs + 1 :]
                                return accum[: (offs + 1)]

                        # This can happen if the user presses the "ESC" key which sends the escape
                        # sequence raw with nothing else available. Requeue this escape key and the
                        # rest of the accum and hope the user presses something else next.
                        self.leftover += self.ESCAPE + accum
                    else:
                        accum = b""
                        if timeout:
                            return b""
                        else:
                            gotResponse = False

                continue

            gotResponse = True
            accum += val

    def peekInput(self) -> Optional[bytes]:
        # Simply return the next input, or None if there is nothing pending.
        if self.pending:
            return self.pending[0]

        return None

    def recvInput(self) -> Optional[bytes]:
        # Pump response queue to grab input between any escaped values. Skip
        # that if we already have pending input since we don't need a round-trip.
        if not self.pending:
            response = self._recvResponse(timeout=0.01)
            if response:
                self.responses.append(response)

        # Also, occasionally check that the terminal is still alive.
        now = time.time()
        if now - self.lastPolled > self.CHECK_INTERVAL:
            self.lastPolled = now
            if self.isOk():
                self.pollFailures = 0
            else:
                self.pollFailures += 1
                if self.pollFailures > self.MAX_FAILURES:
                    # Do a hard check instead of soft.
                    self.checkOk()

        # See if we have anything pending.
        val: Optional[bytes] = None
        if self.pending:
            val = self.pending[0]
            self.pending = self.pending[1:]
        return val
