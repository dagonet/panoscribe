# e2e Whisper fixture

`quick_brown_fox.wav` — 16 kHz mono PCM WAV, ~3.3 s, 106 KB.

## Provenance

Synthetic speech generated entirely offline, no network access, no
third-party recording involved. There is no upstream copyright to
attribute: the audio is a novel, machine-generated rendering of a public-
domain pangram sentence, produced locally via the Windows SAPI text-to-
speech engine bundled with the OS.

Utterance: "The quick brown fox jumps over the lazy dog."

Generated with PowerShell + `System.Speech.Synthesis.SpeechSynthesizer`
using the built-in "Microsoft Zira Desktop" (en-US) voice:

```powershell
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Zira Desktop")
$synth.Rate = 0
$synth.SetOutputToWaveFile(
    "raw_speech_en.wav",
    (New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        22050,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono))
)
$synth.Speak("The quick brown fox jumps over the lazy dog.")
$synth.Dispose()
```

Then downsampled to the 16 kHz mono PCM format Whisper/faster-whisper
expects:

```bash
ffmpeg -y -i raw_speech_en.wav -ar 16000 -ac 1 -c:a pcm_s16le quick_brown_fox.wav
```

## License

No license restriction applies — this is locally synthesized audio, not a
derivative of any copyrighted recording. Treat it as public domain / CC0
for repository purposes.

## Usage

Used by `tests/test_e2e_whisper.py` (`@pytest.mark.slow`) to run a real
`faster-whisper` transcription end-to-end (CPU, `tiny` model) and assert on
model-nondeterminism-robust properties, not an exact transcript.
