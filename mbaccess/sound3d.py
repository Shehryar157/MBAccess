"""3D sound with HRTF through OpenAL Soft (ctypes, no wrapper).

HRTF (head-related transfer function) filters a sound the way your head and outer
ears would if it came from a given direction, so on headphones you can hear front
from behind and diagonals between them, not just left/right panning.

The DLL comes with the PyOpenAL package (OpenAL Soft 1.18.2, built-in HRTF data).
We only use a few calls: open the device with HRTF switched on, upload sounds once
as buffers, and play them from sources fixed at angles around the listener's head.
"""
import ctypes
import math
import os

import numpy as np

ALC_HRTF_SOFT, ALC_HRTF_STATUS_SOFT = 0x1992, 0x1993
AL_SOURCE_RELATIVE, AL_POSITION, AL_GAIN, AL_BUFFER = 0x202, 0x1004, 0x100A, 0x1009
AL_PITCH, AL_LOOPING = 0x1003, 0x1007
AL_FORMAT_MONO16 = 0x1101
AL_NONE = 0
# ALC_HRTF_STATUS_SOFT values: 1 enabled, 3 required, 4 headphones detected
HRTF_ON = (1, 3, 4)


def _load_dll():
    import openal                   # pip install PyOpenAL: only for its bundled DLL
    return ctypes.CDLL(os.path.join(os.path.dirname(openal.__file__), "soft_oal_64.dll"))


class Sound3D:
    def __init__(self, rate=44100):
        al = self.al = _load_dll()
        al.alcOpenDevice.restype = ctypes.c_void_p
        al.alcCreateContext.restype = ctypes.c_void_p
        # without argtypes, ctypes passes ints as 32-bit: a 64-bit pointer overflows
        al.alBufferData.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.rate = rate
        self.device = al.alcOpenDevice(None)
        if not self.device:
            raise OSError("no OpenAL sound device")
        attrs = (ctypes.c_int * 3)(ALC_HRTF_SOFT, 1, 0)    # ask for HRTF even without headphones
        self.context = al.alcCreateContext(ctypes.c_void_p(self.device), attrs)
        al.alcMakeContextCurrent(ctypes.c_void_p(self.context))
        al.alDistanceModel(AL_NONE)     # no fading with distance: pitch tells distance
        status = ctypes.c_int()
        al.alcGetIntegerv(ctypes.c_void_p(self.device), ALC_HRTF_STATUS_SOFT, 1, ctypes.byref(status))
        self.hrtf = status.value in HRTF_ON

    def buffer(self, samples):
        """Upload a mono float array (-1..1) once; returns the buffer id."""
        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
        buf = ctypes.c_uint()
        self.al.alGenBuffers(1, ctypes.byref(buf))
        self.al.alBufferData(buf, AL_FORMAT_MONO16, pcm.ctypes.data, pcm.nbytes, self.rate)
        return buf.value

    def source(self, angle_degrees, gain=1.0):
        """A sound position fixed around the head: 0 = ahead, clockwise, 90 = right.
        Relative to the listener, so it stays put however the player turns."""
        src = ctypes.c_uint()
        self.al.alGenSources(1, ctypes.byref(src))
        a = math.radians(angle_degrees)
        # OpenAL axes: listener faces -z, +x is right, +y is up
        self.al.alSourcei(src, AL_SOURCE_RELATIVE, 1)
        self.al.alSource3f(src, AL_POSITION, ctypes.c_float(math.sin(a)), ctypes.c_float(0),
                           ctypes.c_float(-math.cos(a)))
        self.al.alSourcef(src, AL_GAIN, ctypes.c_float(gain))
        return src.value

    def play(self, source, buffer):
        self.al.alSourceStop(source)        # a source must stop before its buffer changes
        self.al.alSourcei(source, AL_BUFFER, buffer)
        self.al.alSourcePlay(source)

    def loop(self, source, buffer):
        """Play a buffer over and over until stop()."""
        self.al.alSourceStop(source)
        self.al.alSourcei(source, AL_BUFFER, buffer)
        self.al.alSourcei(source, AL_LOOPING, 1)
        self.al.alSourcePlay(source)

    def stop(self, source):
        self.al.alSourceStop(source)

    def set(self, source, gain=None, pitch=None):
        """Change a playing sound smoothly: pitch 1.0 = as recorded, 0.5 = an octave down."""
        if gain is not None:
            self.al.alSourcef(source, AL_GAIN, ctypes.c_float(gain))
        if pitch is not None:
            self.al.alSourcef(source, AL_PITCH, ctypes.c_float(pitch))
