"""discjockey/cdj.py: the CDJ rule (plan rekordbox stage D §1.4): every row both ways, the words, missing values."""
import pytest

from discjockey.cdj import REASONS, CdjProblem, cdj_problem
from discjockey.models import FileAudio


def problem(codec, rate=44100, bits=16, kbps=None, ext=".aiff"):
    return cdj_problem(FileAudio(codec, rate, bits, kbps), ext)


def reason(*args, **kw):
    found = problem(*args, **kw)
    return None if found is None else found.reason


def test_what_every_cdj_plays_is_not_flagged():
    assert problem("pcm_s16be") is None
    assert problem("pcm_s16le", ext=".wav") is None
    assert problem("pcm_s24be", bits=24) is None
    assert problem("pcm_s24le", 96000, 24, ext=".wav") is None
    assert problem("mp3", 44100, None, 320, ".mp3") is None
    assert problem("mp3", 48000, None, 128, ".mp3") is None
    assert problem("aac", 48000, None, 256, ".m4a") is None
    assert problem("flac", 96000, 24, ext=".flac") is None  # FLAC and ALAC play on the CDJ-3000 and the NXS2
    assert problem("flac", 88200, 24, ext=".flac") is None
    assert problem("alac", 44100, 16, ext=".m4a") is None


def test_format_codecs_no_cdj_plays():
    for codec in ("opus", "vorbis", "wmav2", "ac3", "wavpack", "ape", "dsd_lsbf"):
        assert reason(codec, 48000, None, 128, ".x") == "format", codec


def test_bitrate_321_is_flagged_and_320_is_not():
    assert reason("mp3", 44100, None, 321, ".mp3") == "bitrate"
    assert reason("aac", 44100, None, 400, ".m4a") == "bitrate"
    assert reason("mp3", 44100, None, 320, ".mp3") is None
    found = problem("mp3", 44100, None, 321, ".mp3")
    assert found.short == "MP3 321 kbps · CDJs stop at 320"
    assert found.words == ("MP3 at 321 kbps: CDJs play MP3 only up to 320 kbps, so it may not load or may stutter.")


def test_bit_depth_other_than_16_or_24_is_flagged():
    assert reason("pcm_f32le", 44100, 32, ext=".wav") == "bits"
    assert reason("pcm_s32le", 44100, 32, ext=".wav") == "bits"
    assert reason("pcm_u8", 44100, 8, ext=".wav") == "bits"
    assert reason("flac", 44100, 32, ext=".flac") == "bits"
    found = problem("pcm_f32le", 44100, 32, ext=".wav")
    assert found.short == "WAV 32-bit float · CDJs play 16/24-bit"
    assert found.words == "WAV 32-bit float: CDJs play only 16- and 24-bit files."
    assert problem("pcm_s32be", 44100, 32, ext=".aiff").short == "AIFF 32-bit · CDJs play 16/24-bit"


def test_a_rate_above_the_limit_is_flagged():
    assert reason("flac", 176400, 24, ext=".flac") == "rate_high"
    assert reason("pcm_s24le", 192000, 24, ext=".wav") == "rate_high"
    assert reason("flac", 96000, 24, ext=".flac") is None
    assert reason("mp3", 96000, None, 128, ".mp3") == "rate_high"  # lossy stops at 48 kHz
    assert reason("aac", 48000, None, 128, ".m4a") is None
    found = problem("flac", 176400, 24, ext=".flac")
    assert found.short == "FLAC 176.4 kHz · CDJs stop at 96 kHz"
    assert found.words == "FLAC at 176.4 kHz: CDJs play FLAC only up to 96 kHz."
    assert problem("mp3", 96000, None, 128, ".mp3").short == "MP3 96 kHz · CDJs stop at 48 kHz"


def test_a_lossless_rate_below_44_1_is_flagged():
    found = problem("pcm_s16le", 22050, 16, ext=".wav")
    assert found.reason == "rate_low"
    assert found.short == "WAV 22.05 kHz · CDJs need 44.1 kHz"
    assert found.words == "WAV at 22.05 kHz: CDJs play WAV from 44.1 kHz."
    assert reason("flac", 32000, 16, ext=".flac") == "rate_low"
    assert reason("mp3", 32000, None, 128, ".mp3") is None  # MP3 plays from 32 kHz


def test_the_format_words():
    found = problem("opus", 48000, None, 128, ".opus")
    assert found.short == "Opus · CDJs don't play it" and found.words == "CDJs don't play Opus files."
    assert problem("wmav2", 44100, None, 128, ".wma").words == "CDJs don't play WMA files."


def test_the_first_rule_that_matches_wins():
    # 24-bit/192 kHz would be rate_high; a 32-bit one is bits first; an MP3 over 320 at 96 kHz is bitrate first
    assert reason("pcm_f32le", 192000, 32, ext=".wav") == "bits"
    assert reason("mp3", 96000, None, 500, ".mp3") == "bitrate"
    assert reason("opus", 96000, None, 500, ".opus") == "format"


@pytest.mark.parametrize("audio", [FileAudio("mp3", None, None, None), FileAudio("aac", 44100, None, None),
                                   FileAudio("flac", None, None, None), FileAudio("pcm_s16be", 44100, None, None),
                                   FileAudio("mp3", None, None, 128)])
def test_a_missing_value_never_matches_its_rule(audio):
    assert cdj_problem(audio, ".x") is None


def test_every_reason_is_named_and_returned_as_a_frozen_record():
    assert REASONS == ("format", "bitrate", "bits", "rate_high", "rate_low")
    found = problem("opus", ext=".opus")
    assert isinstance(found, CdjProblem)
    with pytest.raises(AttributeError):
        found.reason = "x"
