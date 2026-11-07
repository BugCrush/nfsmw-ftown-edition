#include "Player.h"
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <string>
#include <vector>

#ifndef AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
#define AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM 0x80000000
#endif
#ifndef AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
#define AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY 0x08000000
#endif

static const DWORD kAudioStream = (DWORD)MF_SOURCE_READER_FIRST_AUDIO_STREAM;
static const REFERENCE_TIME kBufferTime = 2000000; // 200 ms, in 100 ns units

// One song being played. Shared by the Player that started it and its worker thread; whichever lets
// go last frees it, so Stop never has to wait for the worker.
struct Player::State
{
    std::wstring path;
    HANDLE opened = nullptr;
    volatile LONG refs = 2, wantPlay = 0, wantStop = 0, finished = 0;
    volatile LONG volumeMilli = 1000;
    CRITICAL_SECTION lock;
    PlayerStats stats = {};
};

void Player::ReleaseState(State* s)
{
    if (InterlockedDecrement(&s->refs) == 0)
    {
        CloseHandle(s->opened);
        DeleteCriticalSection(&s->lock);
        delete s;
    }
}

Player::Player() : s_(nullptr), volumeMilli_(1000), lastError_(S_OK) {}

Player::~Player()
{
    Stop();
}

void Player::Launch(const wchar_t* path, bool play)
{
    Stop();
    State* s = new State;
    InitializeCriticalSection(&s->lock);
    s->path = path;
    s->wantPlay = play;
    s->volumeMilli = volumeMilli_;
    s->opened = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    s_ = s;
    HANDLE thread = CreateThread(nullptr, 0, ThreadEntry, s, 0, nullptr);
    if (thread)
        CloseHandle(thread);
    else // no worker: it will never run, so report failure and drop its reference ourselves
    {
        s->stats.error = E_FAIL;
        s->finished = 1;
        SetEvent(s->opened);
        ReleaseState(s);
    }
}

bool Player::Open(const wchar_t* path)
{
    Launch(path, false);
    WaitForSingleObject(s_->opened, INFINITE);
    if (FAILED(Stats().error))
    {
        Stop();
        return false;
    }
    return true;
}

void Player::Start(const wchar_t* path)
{
    Launch(path, true);
}

void Player::Play()
{
    if (s_)
        InterlockedExchange(&s_->wantPlay, 1);
}

void Player::Pause()
{
    if (s_)
        InterlockedExchange(&s_->wantPlay, 0);
}

void Player::Stop()
{
    if (!s_)
        return;
    lastError_ = Stats().error;
    InterlockedExchange(&s_->wantStop, 1);
    ReleaseState(s_);
    s_ = nullptr;
}

void Player::SetVolume(float volume)
{
    if (volume < 0) volume = 0;
    if (volume > 1) volume = 1;
    volumeMilli_ = (LONG)(volume * 1000 + 0.5f);
    if (s_)
        InterlockedExchange(&s_->volumeMilli, volumeMilli_);
}

bool Player::Finished() const { return !s_ || s_->finished != 0; }

PlayerStats Player::Stats() const
{
    PlayerStats copy = {};
    copy.error = lastError_;
    if (!s_)
        return copy;
    EnterCriticalSection(&s_->lock);
    copy = s_->stats;
    LeaveCriticalSection(&s_->lock);
    return copy;
}

DWORD WINAPI Player::ThreadEntry(void* state)
{
    Run((State*)state);
    ReleaseState((State*)state);
    return 0;
}

template <class T> static void Release(T*& p)
{
    if (p)
    {
        p->Release();
        p = nullptr;
    }
}

void Player::Run(State* s_)
{
    IMFSourceReader* reader = nullptr;
    IMFMediaType* want = nullptr, * got = nullptr;
    IMMDeviceEnumerator* devices = nullptr;
    IMMDevice* device = nullptr;
    IAudioClient* client = nullptr;
    IAudioRenderClient* render = nullptr;
    IAudioStreamVolume* streamVolume = nullptr;
    IAudioClock* clock = nullptr;
    UINT32 rate = 0, channels = 0, bits = 0, bufferFrames = 0;
    UINT64 clockFrequency = 0;
    bool mfStarted = false;

    HRESULT comInit = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    HRESULT hr = MFStartup(MF_VERSION, MFSTARTUP_LITE);
    mfStarted = SUCCEEDED(hr);

    // Decoder: ask for 16-bit PCM; the reader inserts the MP3 decoder and keeps the file's rate.
    if (SUCCEEDED(hr)) hr = MFCreateSourceReaderFromURL(s_->path.c_str(), nullptr, &reader);
    if (SUCCEEDED(hr)) hr = MFCreateMediaType(&want);
    if (SUCCEEDED(hr)) hr = want->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
    if (SUCCEEDED(hr)) hr = want->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM);
    if (SUCCEEDED(hr)) hr = want->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
    if (SUCCEEDED(hr)) hr = reader->SetCurrentMediaType(kAudioStream, nullptr, want);
    if (SUCCEEDED(hr)) hr = reader->GetCurrentMediaType(kAudioStream, &got);
    if (SUCCEEDED(hr)) hr = got->GetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, &rate);
    if (SUCCEEDED(hr)) hr = got->GetUINT32(MF_MT_AUDIO_NUM_CHANNELS, &channels);
    if (SUCCEEDED(hr)) hr = got->GetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, &bits);
    if (SUCCEEDED(hr) && (bits != 16 || !rate || !channels || channels > 2))
        hr = E_NOTIMPL; // a format we don't play (e.g. more than two channels)
    double duration = 0;
    if (SUCCEEDED(hr))
    {
        PROPVARIANT v;
        PropVariantInit(&v);
        if (SUCCEEDED(reader->GetPresentationAttribute((DWORD)MF_SOURCE_READER_MEDIASOURCE, MF_PD_DURATION, &v)) && v.vt == VT_UI8)
            duration = v.uhVal.QuadPart / 1e7;
        PropVariantClear(&v);
    }

    // Output: a shared-mode stream in the file's own format; Windows resamples if the device differs.
    WAVEFORMATEX format = {};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = (WORD)channels;
    format.nSamplesPerSec = rate;
    format.wBitsPerSample = 16;
    format.nBlockAlign = (WORD)(channels * 2);
    format.nAvgBytesPerSec = rate * format.nBlockAlign;
    if (SUCCEEDED(hr)) hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), (void**)&devices);
    if (SUCCEEDED(hr)) hr = devices->GetDefaultAudioEndpoint(eRender, eConsole, &device);
    if (SUCCEEDED(hr)) hr = device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&client);
    if (SUCCEEDED(hr)) hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
        kBufferTime, 0, &format, nullptr);
    if (SUCCEEDED(hr)) hr = client->GetBufferSize(&bufferFrames);
    if (SUCCEEDED(hr)) hr = client->GetService(__uuidof(IAudioRenderClient), (void**)&render);
    if (SUCCEEDED(hr)) hr = client->GetService(__uuidof(IAudioStreamVolume), (void**)&streamVolume);
    if (SUCCEEDED(hr)) hr = client->GetService(__uuidof(IAudioClock), (void**)&clock);
    if (SUCCEEDED(hr)) hr = clock->GetFrequency(&clockFrequency);

    EnterCriticalSection(&s_->lock);
    s_->stats.error = hr;
    s_->stats.ready = SUCCEEDED(hr);
    s_->stats.durationSeconds = duration;
    s_->stats.sampleRate = rate;
    s_->stats.channels = channels;
    LeaveCriticalSection(&s_->lock);
    SetEvent(s_->opened);

    std::vector<BYTE> pending;   // decoded PCM not yet handed to the device
    size_t pendingAt = 0;
    UINT64 framesDecoded = 0;
    bool endOfFile = false, running = false, everWrote = false;
    LONG appliedVolume = -1;

    while (SUCCEEDED(hr) && !s_->wantStop)
    {
        LONG volume = s_->volumeMilli;
        if (volume != appliedVolume)
        {
            float levels[2] = { volume / 1000.0f, volume / 1000.0f };
            streamVolume->SetAllVolumes(channels, levels);
            appliedVolume = volume;
        }

        // Keep the device buffer topped up, whether playing or paused.
        UINT32 padding = 0;
        hr = client->GetCurrentPadding(&padding);
        if (FAILED(hr))
            break;
        // An empty device buffer while we were already playing is a gap the listener hears.
        bool gap = running && everWrote && padding == 0 && !(endOfFile && pendingAt == pending.size());
        UINT32 room = bufferFrames - padding;
        while (room > 0 && SUCCEEDED(hr))
        {
            if (pendingAt == pending.size())
            {
                if (endOfFile)
                    break;
                DWORD flags = 0;
                IMFSample* sample = nullptr;
                hr = reader->ReadSample(kAudioStream, 0, nullptr, &flags, nullptr, &sample);
                if (FAILED(hr))
                    break;
                if (flags & MF_SOURCE_READERF_ENDOFSTREAM)
                    endOfFile = true;
                pending.clear();
                pendingAt = 0;
                if (sample)
                {
                    IMFMediaBuffer* buffer = nullptr;
                    BYTE* data = nullptr;
                    DWORD length = 0;
                    if (SUCCEEDED(sample->ConvertToContiguousBuffer(&buffer)) && SUCCEEDED(buffer->Lock(&data, nullptr, &length)))
                    {
                        pending.assign(data, data + length);
                        buffer->Unlock();
                        framesDecoded += length / format.nBlockAlign;
                    }
                    Release(buffer);
                    sample->Release();
                }
                continue;
            }
            UINT32 frames = (UINT32)((pending.size() - pendingAt) / format.nBlockAlign);
            if (frames > room)
                frames = room;
            BYTE* out = nullptr;
            hr = render->GetBuffer(frames, &out);
            if (FAILED(hr))
                break;
            memcpy(out, pending.data() + pendingAt, frames * format.nBlockAlign);
            hr = render->ReleaseBuffer(frames, 0);
            pendingAt += frames * format.nBlockAlign;
            room -= frames;
            everWrote = true;
        }
        if (FAILED(hr))
            break;

        bool wantPlay = s_->wantPlay != 0;
        if (wantPlay && !running)
            hr = client->Start();
        else if (!wantPlay && running)
            hr = client->Stop();
        running = wantPlay;

        UINT64 position = 0;
        clock->GetPosition(&position, nullptr);
        bool drained = endOfFile && pendingAt == pending.size() && padding == 0 && everWrote;
        EnterCriticalSection(&s_->lock);
        s_->stats.decodedSeconds = framesDecoded / (double)rate;
        s_->stats.playedSeconds = position / (double)clockFrequency;
        if (gap)
            ++s_->stats.underruns;
        LeaveCriticalSection(&s_->lock);
        if (drained || (endOfFile && !everWrote))
            break;
        Sleep(10);
    }

    if (FAILED(hr))
    {
        EnterCriticalSection(&s_->lock);
        if (SUCCEEDED(s_->stats.error))
            s_->stats.error = hr;
        LeaveCriticalSection(&s_->lock);
    }
    if (client)
        client->Stop();
    Release(clock);
    Release(streamVolume);
    Release(render);
    Release(client);
    Release(device);
    Release(devices);
    Release(got);
    Release(want);
    Release(reader);
    if (mfStarted)
        MFShutdown();
    if (SUCCEEDED(comInit))
        CoUninitialize();
    InterlockedExchange(&s_->finished, 1);
}
