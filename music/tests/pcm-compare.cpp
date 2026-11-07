// Checks that a trimmed song is the original minus its start: decodes both files with Windows'
// decoder (the one the player uses) and compares the audio sample by sample.
// Build (from music\tests):
//   zig c++ -target x86-windows-gnu -w -municode pcm-compare.cpp -o pcm-compare.exe -lmfplat -lmfreadwrite -lmfuuid -lole32
// Run: pcm-compare.exe <original> <trimmed> <seconds removed>      (exit code 0 = same audio)
#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <stdio.h>
#include <stdlib.h>
#include <vector>

static const DWORD kAudio = (DWORD)MF_SOURCE_READER_FIRST_AUDIO_STREAM;

static bool Decode(const wchar_t* path, std::vector<short>* pcm, UINT32* rate, UINT32* channels)
{
    IMFSourceReader* reader = nullptr;
    IMFMediaType* want = nullptr, * got = nullptr;
    HRESULT hr = MFCreateSourceReaderFromURL(path, nullptr, &reader);
    if (SUCCEEDED(hr)) hr = MFCreateMediaType(&want);
    if (SUCCEEDED(hr)) hr = want->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
    if (SUCCEEDED(hr)) hr = want->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM);
    if (SUCCEEDED(hr)) hr = want->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
    if (SUCCEEDED(hr)) hr = reader->SetCurrentMediaType(kAudio, nullptr, want);
    if (SUCCEEDED(hr)) hr = reader->GetCurrentMediaType(kAudio, &got);
    if (SUCCEEDED(hr)) hr = got->GetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, rate);
    if (SUCCEEDED(hr)) hr = got->GetUINT32(MF_MT_AUDIO_NUM_CHANNELS, channels);
    while (SUCCEEDED(hr))
    {
        DWORD flags = 0;
        IMFSample* sample = nullptr;
        hr = reader->ReadSample(kAudio, 0, nullptr, &flags, nullptr, &sample);
        if (FAILED(hr) || (flags & MF_SOURCE_READERF_ENDOFSTREAM))
        {
            if (sample)
                sample->Release();
            break;
        }
        if (!sample)
            continue;
        IMFMediaBuffer* buffer = nullptr;
        BYTE* data = nullptr;
        DWORD length = 0;
        if (SUCCEEDED(sample->ConvertToContiguousBuffer(&buffer)) && SUCCEEDED(buffer->Lock(&data, nullptr, &length)))
        {
            pcm->insert(pcm->end(), (short*)data, (short*)data + length / 2);
            buffer->Unlock();
        }
        if (buffer)
            buffer->Release();
        sample->Release();
    }
    return SUCCEEDED(hr) && !pcm->empty();
}

int wmain(int argc, wchar_t** argv)
{
    if (argc < 4)
    {
        printf("usage: pcm-compare <original> <trimmed> <seconds removed>\n");
        return 2;
    }
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    MFStartup(MF_VERSION, MFSTARTUP_LITE);
    std::vector<short> a, b;
    UINT32 rateA = 0, chA = 0, rateB = 0, chB = 0;
    if (!Decode(argv[1], &a, &rateA, &chA) || !Decode(argv[2], &b, &rateB, &chB) || rateA != rateB || chA != chB)
    {
        printf("FAIL: could not decode both files to the same format\n");
        return 1;
    }
    double removed = _wtof(argv[3]);
    long long expected = (long long)(removed * rateA + 0.5) * chA; // in samples (all channels)
    printf("original %.3f s, trimmed %.3f s, difference %.3f s (asked: %.3f s)\n", a.size() / (double)(rateA * chA),
        b.size() / (double)(rateB * chB), (a.size() - (double)b.size()) / (rateA * chA), removed);

    // The decoder may place the trimmed file a few samples differently; find the exact shift.
    long long window = (long long)rateA * chA * 2, from = (long long)rateA * chA; // 2 s, starting 1 s in
    long long best = 0, bestSum = -1;
    for (long long shift = -4000LL * chA; shift <= 4000LL * chA; shift += chA)
    {
        long long sum = 0;
        for (long long i = 0; i < window; i += 7)
        {
            long long ia = expected + shift + from + i;
            if (ia < 0 || ia >= (long long)a.size() || from + i >= (long long)b.size())
            {
                sum = -1;
                break;
            }
            sum += llabs(a[ia] - b[from + i]);
        }
        if (sum >= 0 && (bestSum < 0 || sum < bestSum))
        {
            bestSum = sum;
            best = shift;
        }
    }
    long long offset = expected + best;
    printf("the trimmed file's audio starts %.4f s into the original\n", offset / (double)(rateA * chA));

    // Compare everything after the first 0.2 s (the first frames after a cut can borrow data from
    // frames that are gone, so the decoder may mute or alter a few milliseconds there).
    long long skip = (long long)(0.2 * rateA) * chA, compared = 0, differing = 0, maxDiff = 0;
    for (long long i = skip; i < (long long)b.size() && offset + i < (long long)a.size(); ++i)
    {
        long long d = llabs(a[offset + i] - b[i]);
        ++compared;
        differing += d != 0;
        if (d > maxDiff)
            maxDiff = d;
    }
    long long startDiffer = 0;
    for (long long i = 0; i < skip && i < (long long)b.size(); ++i)
        startDiffer += a[offset + i] != b[i];
    printf("after the first 0.2 s: %lld samples compared, %lld differ, largest difference %lld (of 32767)\n", compared, differing, maxDiff);
    printf("in the first 0.2 s: %lld of %lld samples differ\n", startDiffer, skip);
    bool same = compared > 0 && differing == 0;
    printf("%s\n", same ? "SAME AUDIO" : "DIFFERENT");
    return same ? 0 : 1;
}
