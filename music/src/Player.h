// Plays one audio file through Windows: Media Foundation decodes it to PCM at the file's own sample
// rate, a WASAPI shared-mode stream opened at that same rate plays it. We never drop, repeat or
// re-time samples; Windows converts to the sound device's rate. Each song runs on its own worker
// thread, which cleans up after itself, so starting and stopping never make the caller wait.
#pragma once
#include <windows.h>

struct PlayerStats
{
    bool ready;                   // the file and the audio stream are open
    double durationSeconds;       // length the file reports (0 if unknown)
    double decodedSeconds;        // PCM decoded so far / sample rate
    double playedSeconds;         // the audio device's clock for this stream
    unsigned underruns;           // times the device buffer ran empty before the end (audible gaps)
    unsigned sampleRate, channels;
    HRESULT error;                // first failure, S_OK if none
};

class Player
{
public:
    Player();
    ~Player();

    // Opens the file and the audio stream and waits until they are ready, paused at the start.
    // False if the file can't be decoded or no audio device is available.
    bool Open(const wchar_t* path);
    // Opens and plays in the background; returns at once. A file that can't be played ends by
    // itself: Finished() becomes true and Stats().error says why.
    void Start(const wchar_t* path);
    void Play();                  // start, or resume after Pause
    void Pause();
    void Stop();                  // returns at once; the worker ends and frees everything itself
    void SetVolume(float volume); // 0..1, this stream only (not the process's mixer volume)

    bool Finished() const;        // nothing is playing: never started, stopped, ended, or failed
    PlayerStats Stats() const;    // of the current song; after Stop, only `error` of the last one

private:
    struct State;
    static DWORD WINAPI ThreadEntry(void* state);
    static void Run(State* s);
    static void ReleaseState(State* s);
    void Launch(const wchar_t* path, bool play);
    State* s_;
    LONG volumeMilli_;
    HRESULT lastError_;
};
