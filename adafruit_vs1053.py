# The MIT License (MIT)
#
# Copyright (c) 2017 Tony DiCola for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
`adafruit_vs1053`
====================================================

Driver for interacting and playing media files with the VS1053 audio codec over
a SPI connection.

* Author(s): Tony DiCola, Uri Shaked
"""
import digitalio
import time

from adafruit_bus_device.spi_device import SPIDevice


_COMMAND_BAUDRATE = const(250000)   # Speed for command transfers (MUST be slow)
_DATA_BAUDRATE    = const(8000000)  # Speed for data transfers (fast!)

_VS1053_SCI_READ   = const(0x03)
_VS1053_SCI_WRITE  = const(0x02)

_VS1053_REG_MODE        = const(0x00)
_VS1053_REG_STATUS      = const(0x01)
_VS1053_REG_BASS        = const(0x02)
_VS1053_REG_CLOCKF      = const(0x03)
_VS1053_REG_DECODETIME  = const(0x04)
_VS1053_REG_AUDATA      = const(0x05)
_VS1053_REG_WRAM        = const(0x06)
_VS1053_REG_WRAMADDR    = const(0x07)
_VS1053_REG_HDAT0       = const(0x08)
_VS1053_REG_HDAT1       = const(0x09)
_VS1053_REG_VOLUME      = const(0x0B)

_VS1053_GPIO_DDR        = const(0xC017)
_VS1053_GPIO_IDATA      = const(0xC018)
_VS1053_GPIO_ODATA      = const(0xC019)

_VS1053_INT_ENABLE          = const(0xC01A)

_VS1053_MODE_SM_DIFF        = const(0x0001)
_VS1053_MODE_SM_LAYER12     = const(0x0002)
_VS1053_MODE_SM_RESET       = const(0x0004)
_VS1053_MODE_SM_CANCEL      = const(0x0008)
_VS1053_MODE_SM_EARSPKLO    = const(0x0010)
_VS1053_MODE_SM_TESTS       = const(0x0020)
_VS1053_MODE_SM_STREAM      = const(0x0040)
_VS1053_MODE_SM_SDINEW      = const(0x0800)
_VS1053_MODE_SM_ADPCM       = const(0x1000)
_VS1053_MODE_SM_LINE1       = const(0x4000)
_VS1053_MODE_SM_CLKRANGE    = const(0x8000)


class VS1053:

    # Class-level buffer for read and write commands.
    # This is NOT thread/re-entrant safe (by design, for less memory hit).
    _SCI_SPI_BUFFER = bytearray(4)

    def __init__(self, spi, cs, xcs, xdcs, dreq, reset = None):
        # Create SPI device for VS1053
        self._cs = digitalio.DigitalInOut(cs) if cs else None
        self._vs1053_spi = SPIDevice(spi, self._cs, baudrate=_COMMAND_BAUDRATE, polarity=0, phase=0)
        # Setup control lines.
        self._xcs = digitalio.DigitalInOut(xcs)
        self._xcs.switch_to_output(value=True)
        self._xdcs = digitalio.DigitalInOut(xdcs)
        self._xdcs.switch_to_output(value=True)
        self._dreq = digitalio.DigitalInOut(dreq)
        self._dreq.switch_to_input()
        self._reset = None
        if reset:
            self._reset = digitalio.DigitalInOut(reset)
            self._reset.switch_to_output(value=False)
        # Reset chip.
        self.reset()
        # Check version is 4 (VS1053 ID).
        if self.version != 4:
            raise RuntimeError('Expected version 4 (VS1053) but got: {}  Check wiring!'.format(self.version))

    def _sci_write(self, address, value):
        # Write a 16-bit big-endian value to the provided 8-bit address.
        self._SCI_SPI_BUFFER[0] = _VS1053_SCI_WRITE
        self._SCI_SPI_BUFFER[1] = address & 0xFF
        self._SCI_SPI_BUFFER[2] = (value >> 8) & 0xFF
        self._SCI_SPI_BUFFER[3] = value & 0xFF
        self._xdcs.value = True
        self.wait_until_ready()
        self._xcs.value = False
        with self._vs1053_spi as spi:
            spi.configure(baudrate=_COMMAND_BAUDRATE)
            spi.write(self._SCI_SPI_BUFFER)
        self._xcs.value = True

    def _sci_read(self, address):
        # Read a 16-bit big-endian value from the provided 8-bit address.
        # Write a 16-bit big-endian value to the provided 8-bit address.
        self._SCI_SPI_BUFFER[0] = _VS1053_SCI_READ
        self._SCI_SPI_BUFFER[1] = address & 0xFF
        self._xdcs.value = True
        self.wait_until_ready()
        self._xcs.value = False
        with self._vs1053_spi as spi:
            spi.configure(baudrate=_COMMAND_BAUDRATE)
            spi.write(self._SCI_SPI_BUFFER, end=2)
            time.sleep(0.00001) # Delay 10 microseconds (at least)
            spi.readinto(self._SCI_SPI_BUFFER, end=2)
        self._xcs.value = True
        return (self._SCI_SPI_BUFFER[0] << 8) | self._SCI_SPI_BUFFER[1]

    def soft_reset(self):
        """Perform a quick soft reset of the VS1053."""
        self._sci_write(_VS1053_REG_MODE, _VS1053_MODE_SM_SDINEW | _VS1053_MODE_SM_RESET) # Newmode, Reset, No L1-2
        time.sleep(0.002)
        self.wait_until_ready()
        self._sci_write(_VS1053_REG_HDAT0, 0xABAD)
        self._sci_write(_VS1053_REG_HDAT1, 0x1DEA)
        time.sleep(0.1)
        self._sci_write(_VS1053_REG_CLOCKF,0xC000)   # Set the clock
        self._sci_write(_VS1053_REG_AUDATA,0xBB81)   # Sample rate 48k, stereo
        self._sci_write(_VS1053_REG_BASS, 0x0055)    # Set accent

    def reset(self):
        """Perform a longer full reset with clock and volume reset too."""
        if self._reset:
            self._reset.value = False
        time.sleep(0.002)
        self._xcs.value = True
        self._xdcs.value = True
        if self._reset:
            self._reset.value = True
        self.soft_reset()
        self._sci_write(_VS1053_REG_CLOCKF, 0x6000)
        self.set_volume(40, 40)

    def set_volume(self, left, right):
        """Set the volume of the left and right channels to the provided byte
        value (0-255), the lower the louder.
        """
        volume = ((left & 0xFF) << 8) | (right & 0xFF)
        self._sci_write(_VS1053_REG_VOLUME, volume)

    @property
    def ready_for_data(self):
        """Return True if the VS1053 is ready to accept data, false otherwise.
        """
        return self._dreq.value

    @property
    def version(self):
        """Return the status register version value."""
        return (self._sci_read(_VS1053_REG_STATUS) >> 4) & 0x0F

    @property
    def decode_time(self):
        """Return the decode time register value.  This is the amount of time
        the current file has been played back in seconds."""
        return self._sci_read(_VS1053_REG_DECODETIME)

    @decode_time.setter
    def decode_time(self, value):
        """Set the decode time register value."""
        # From datasheet, set twice to ensure it is correctly set (pg. 43)
        self._sci_write(_VS1053_REG_DECODETIME, value)

    @property
    def byte_rate(self):
        """Return the bit rate in bytes per second (computed each second).
        Useful to know if a song is being played and how fast it's happening.
        """
        self._sci_write(_VS1053_REG_WRAMADDR, 0x1e05)
        return self._sci_read(_VS1053_REG_WRAM)
        
    def wait_until_ready(self):
        while not self.ready_for_data:
            pass

    def start_playback(self):
        """Prepare for playback of a file.  After calling this check the
        ready_for_data property continually until true and then send in
        buffers of music data to the play_data function.
        """
        # Reset playback.
        self._sci_write(_VS1053_REG_MODE, _VS1053_MODE_SM_LINE1 | _VS1053_MODE_SM_SDINEW)
        # Resync.
        self._sci_write(_VS1053_REG_WRAMADDR, 0x1e29)
        self._sci_write(_VS1053_REG_WRAM, 0)
        # Set time to zero.
        self.decode_time = 0

    def stop_playback(self):
        """Stop any playback of audio."""
        self._sci_write(_VS1053_REG_MODE, _VS1053_MODE_SM_LINE1 | _VS1053_MODE_SM_SDINEW | _VS1053_MODE_SM_CANCEL)

    def play_data(self, data_buffer, start=0, end=None):
        """Send a buffer of file data to the VS1053 for playback.  Make sure
        the ready_for_data property is True before calling!
        """
        try:
            if end is None:
                end = len(data_buffer)
            self._xdcs.value = False
            self._xcs.value = True
            with self._vs1053_spi as spi:
                spi.configure(baudrate=_DATA_BAUDRATE)
                spi.write(data_buffer, start=start, end=end)
        finally:
            self._xdcs.value = True
            self._xcs.value = False

    def sine_test(self, n, seconds):
        """Play a sine wave for the specified number of seconds. Useful to
        test the VS1053 is working.
        """
        self.reset()
        mode = self._sci_read(_VS1053_REG_MODE)
        mode |= 0x0020
        self._sci_write(_VS1053_REG_MODE, mode)
        self.wait_until_ready()
        try:
            self._xdcs.value = False
            with self._vs1053_spi as spi:
                spi.configure(baudrate=_DATA_BAUDRATE)
                spi.write(bytes([0x53, 0xEF, 0x6E, n & 0xFF, 0x00, 0x00,
                                 0x00, 0x00]))
        finally:
            self._xdcs.value = True
        time.sleep(seconds)
        try:
            self._xdcs.value = False
            with self._vs1053_spi as spi:
                spi.configure(baudrate=_DATA_BAUDRATE)
                spi.write(bytes([0x45, 0x78, 0x69, 0x74, 0x00, 0x00, 0x00,
                                 0x00]))
        finally:
            self._xdcs.value = True