// GfxProbe: how a frame is built. A stage is a run of drawing into one target, from the moment the game
// switches to it until it switches away; a frame is a sequence of stages. Counters are added up per
// (target, nth visit of that target in the frame) and written every report; nothing is written per frame.
#include "probe.h"

enum { kMaxStages = 48, kMaxKeys = 96, kMaxLabels = 512, kMaxShapes = 32, kMaxCopies = 32, kTargetMask = 127 };

struct Stage
{
    int target;
    LONG draws, tris, clears, copies;
    LONGLONG inTicks, outTicks;
    unsigned short label[kMaxLabels];
};
struct Key
{
    int target, visit;
    LONG frames, timed;
    double order, draws, tris, clears, copies;
    LONGLONG inTicks, outTicks;
    LONG label[kMaxLabels];
};
struct Shape { char seq[200]; LONG frames; };
struct Copy { int src, dst; LONG count; };
struct Label { char fx[48]; char tech[40]; };

int g_curLabel, g_curPass;
bool g_timingFrame;
LONGLONG g_lastTick;
LONG g_timedCalls;
static LONGLONG g_looseIn, g_looseOut;
LONGLONG* g_tickIn = &g_looseIn;
LONGLONG* g_tickOut = &g_looseOut;

static Stage g_stages[kMaxStages];
static int g_stageCount;
static Stage* g_cur;
static int g_target = -1;
static bool g_began, g_presentPending;
static Key g_keys[kMaxKeys];
static int g_keyCount;
static Shape g_shapes[kMaxShapes];
static int g_shapeCount;
static Copy g_copies[kMaxCopies];
static int g_copyCount;
static Label g_labels[kMaxLabels] = { { "(none)", "-" } };
static int g_labelCount = 1;
static LONG g_frames, g_drivingFrames, g_timedFrames, g_overflow, g_frameNo, g_msaaOn, g_msaaOff;
// How often a table was full since the last report; a non-zero count means the report is incomplete.
static LONG g_labelOverflow, g_keyOverflow, g_shapeOverflow, g_copyOverflow;
static LONGLONG g_frameStart, g_frameTicks, g_presentTicks, g_looseInSum, g_looseOutSum;
static double g_clockNs;
static CRITICAL_SECTION g_liveLock;
static LiveData g_live;
static bool g_liveStarted;
static DWORD g_thread;

int LabelRegister(const char* fx, const char* tech)
{
    for (int i = 0; i < g_labelCount; ++i)
        if (!strcmp(g_labels[i].fx, fx) && !strcmp(g_labels[i].tech, tech))
            return i;
    if (g_labelCount == kMaxLabels)
    {
        ++g_labelOverflow; // such draws are counted under (none): the report says so
        return 0;
    }
    snprintf(g_labels[g_labelCount].fx, sizeof(g_labels[0].fx), "%s", fx);
    snprintf(g_labels[g_labelCount].tech, sizeof(g_labels[0].tech), "%s", tech);
    return g_labelCount++;
}
const char* LabelFx(int label) { return g_labels[label >= 0 && label < g_labelCount ? label : 0].fx; }
const char* LabelTech(int label) { return g_labels[label >= 0 && label < g_labelCount ? label : 0].tech; }

void FrameInit()
{
    InitializeCriticalSection(&g_liveLock);
    // What one clock read costs, so the report can say how much a timed frame is inflated.
    LONGLONG t0 = Ticks();
    for (int i = 0; i < 20000; ++i)
        Ticks();
    g_clockNs = TicksToMs(Ticks() - t0) * 1e6 / 20000;
}

static bool Active(const Stage* s) { return s->draws || s->clears || s->copies; }

static void Point()
{
    g_tickIn = g_cur ? &g_cur->inTicks : &g_looseIn;
    g_tickOut = g_cur ? &g_cur->outTicks : &g_looseOut;
}

// A stage in which nothing was drawn, cleared or copied is not a stage: its time goes to "loose".
static void DropIfIdle()
{
    if (g_cur && !Active(g_cur))
    {
        g_looseIn += g_cur->inTicks;
        g_looseOut += g_cur->outTicks;
        --g_stageCount;
        g_cur = g_stageCount ? &g_stages[g_stageCount - 1] : nullptr;
    }
}

static void Open(int target)
{
    DropIfIdle();
    if (g_cur && g_cur->target == target)
    {
        Point();
        return;
    }
    if (g_stageCount == kMaxStages)
    {
        ++g_overflow; // the last stage absorbs the rest of the frame
        Point();
        return;
    }
    g_cur = &g_stages[g_stageCount++];
    memset(g_cur, 0, sizeof(*g_cur));
    g_cur->target = target;
    Point();
}

void FrameSetTarget(int target)
{
    g_target = target;
    if (!g_began || (g_cur && g_cur->target == target))
        return;
    Open(target);
}

void FrameDraw(D3DPRIMITIVETYPE type, UINT primitives)
{
    if (!g_cur)
        return;
    DWORD thread = GetCurrentThreadId();
    if (!g_thread)
        g_thread = thread;
    else if (thread != g_thread)
    {
        static bool said;
        if (!said)
            Log("WARNING draws come from two threads (%lu and %lu); the counters are approximate", g_thread, thread);
        said = true;
    }
    ++g_cur->draws;
    if (type >= D3DPT_TRIANGLELIST)
        g_cur->tris += primitives;
    ++g_cur->label[g_curLabel];
}

void FrameClear()
{
    if (g_cur)
        ++g_cur->clears;
}

void FrameCopy(int src, int dst)
{
    if (!g_cur)
        return;
    ++g_cur->copies;
    for (int i = 0; i < g_copyCount; ++i)
        if (g_copies[i].src == src && g_copies[i].dst == dst)
        {
            ++g_copies[i].count;
            return;
        }
    if (g_copyCount < kMaxCopies)
        g_copies[g_copyCount++] = { src, dst, 1 };
    else
        ++g_copyOverflow;
}

void FrameMsaa(DWORD value)
{
    ++(value ? g_msaaOn : g_msaaOff);
}

int FrameTarget() { return g_target; }
bool FrameStageActive() { return g_cur && Active(g_cur); }
int FrameStageNumber() { return g_stageCount; }

static Key* FindKey(int target, int visit)
{
    for (int i = 0; i < g_keyCount; ++i)
        if (g_keys[i].target == target && g_keys[i].visit == visit)
            return &g_keys[i];
    if (g_keyCount == kMaxKeys)
    {
        ++g_keyOverflow;
        return nullptr;
    }
    Key* k = &g_keys[g_keyCount++];
    memset(k, 0, sizeof(*k));
    k->target = target;
    k->visit = visit;
    return k;
}

// Which job a stage does, read off this game's frame: six-sided targets are the car's reflection, a
// texture with many draws is the shadow map, the back buffer before anything is drawn is the game's own
// work, its busy visit is the main view and its other visits the HUD; the rest are screen effects.
static int JobOf(const Stage& s)
{
    char kind = TargetKindCode(s.target);
    if (kind == 'c')
        return 1;
    if (kind == 'b')
        return s.draws == 0 ? 3 : s.draws > 300 ? 2 : 5;
    return s.draws > 100 ? 0 : 4;
}

// For the live panel: this frame per job, blended into the running values (a fifth new, four fifths old,
// so the numbers are readable). Times only move on timed frames.
static void LiveUpdate()
{
    float draws[kJobs] = {}, tris[kJobs] = {};
    LONGLONG ticks[kJobs] = {};
    for (int i = 0; i < g_stageCount; ++i)
    {
        const Stage& s = g_stages[i];
        int job = JobOf(s);
        draws[job] += s.draws;
        tris[job] += s.tris;
        ticks[job] += s.inTicks + s.outTicks;
    }
    ticks[3] += g_looseIn + g_looseOut;
    EnterCriticalSection(&g_liveLock);
    float keep = g_liveStarted ? 0.8f : 0.0f;
    for (int j = 0; j < kJobs; ++j)
    {
        g_live.draws[j] = g_live.draws[j] * keep + draws[j] * (1 - keep);
        g_live.tris[j] = g_live.tris[j] * keep + tris[j] * (1 - keep);
        if (g_timingFrame)
            g_live.ms[j] = g_live.ms[j] * keep + (float)TicksToMs(ticks[j]) * (1 - keep);
    }
    if (g_timingFrame)
        g_live.frameMs = g_live.frameMs * keep + (float)TicksToMs(g_lastTick - g_frameStart) * (1 - keep);
    g_liveStarted = true;
    static DWORD lastPoint;
    DWORD now = GetTickCount();
    if (now - lastPoint >= 100)
    {
        lastPoint = now;
        for (int k = 0; k < 3; ++k)
            g_live.history[g_live.historyNext][k] = g_live.draws[k];
        g_live.historyNext = (g_live.historyNext + 1) % kLiveHistory;
    }
    LeaveCriticalSection(&g_liveLock);
}

void FrameLiveGet(LiveData* out)
{
    EnterCriticalSection(&g_liveLock);
    *out = g_live;
    LeaveCriticalSection(&g_liveLock);
}

// Called at the top of the Present hook: adds the finished frame to the totals.
void FrameEnd(bool driving)
{
    if (!g_began)
        return;
    DropIfIdle();
    int visits[kTargetMask + 1] = {};
    char seq[200];
    size_t len = 0;
    seq[0] = 0;
    for (int i = 0; i < g_stageCount; ++i)
    {
        const Stage& s = g_stages[i];
        Key* k = FindKey(s.target, ++visits[s.target & kTargetMask]);
        if (k)
        {
            ++k->frames;
            k->order += i + 1;
            k->draws += s.draws;
            k->tris += s.tris;
            k->clears += s.clears;
            k->copies += s.copies;
            if (g_timingFrame)
            {
                ++k->timed;
                k->inTicks += s.inTicks;
                k->outTicks += s.outTicks;
            }
            for (int l = 0; l < g_labelCount; ++l)
                k->label[l] += s.label[l];
        }
        if (len < sizeof(seq) - 12)
            len += snprintf(seq + len, sizeof(seq) - len, "%sT%d", i ? "," : "", s.target);
    }
    int shape = 0;
    while (shape < g_shapeCount && strcmp(g_shapes[shape].seq, seq))
        ++shape;
    if (shape == g_shapeCount && g_shapeCount < kMaxShapes)
    {
        strcpy(g_shapes[shape].seq, seq);
        g_shapes[shape].frames = 0;
        ++g_shapeCount;
    }
    if (shape < g_shapeCount)
        ++g_shapes[shape].frames;
    else
        ++g_shapeOverflow;
    if (g_cfg.panel)
        LiveUpdate();
    ++g_frames;
    if (driving)
        ++g_drivingFrames;
    if (g_timingFrame)
    {
        ++g_timedFrames;
        // Up to the clock read the Present hook made on entry (TimeEnter), not a fresh one: every tick of
        // the frame is then in exactly one stage or in "loose", and the parts add up to the frame.
        g_frameTicks += g_lastTick - g_frameStart;
        g_looseInSum += g_looseIn;
        g_looseOutSum += g_looseOut;
        g_presentPending = true;
    }
    g_timingFrame = false;
    g_stageCount = 0;
    g_cur = nullptr;
    Point();
}

void FramePresentDone(LONGLONG ticks)
{
    if (g_cfg.panel && g_presentPending)
        g_live.presentMs = g_live.presentMs * 0.8f + (float)TicksToMs(ticks) * 0.2f;
    if (g_presentPending)
        g_presentTicks += ticks;
    g_presentPending = false;
}

// Called at the bottom of the Present hook: the next frame starts on the target that is current now.
void FrameBegin(IDirect3DDevice9* dev, bool allowTiming)
{
    if (!g_began)
    {
        g_began = true;
        g_own = true;
        IDirect3DSurface9* current = nullptr;
        if (SUCCEEDED(dev->GetRenderTarget(0, &current)))
        {
            g_target = TargetId(dev, current);
            current->Release();
        }
        g_own = false;
    }
    g_looseIn = g_looseOut = 0;
    Open(g_target);
    // One frame in [Timing] EveryNFrames (1 = every frame). With a period above 1 prefer a prime such as
    // 61: it cannot stay in step with work the game does every 2nd, 4th or 8th frame.
    g_timingFrame = allowTiming && g_cfg.timing && (++g_frameNo % g_cfg.timingEvery) == 0;
    g_frameStart = g_lastTick = Ticks();
}

void FrameReport()
{
    if (!g_frames)
        return;
    Log("FRAMEMAP frames=%ld driving=%.2f stages=%d overflow=%ld", g_frames, g_drivingFrames / (double)g_frames, g_keyCount,
        g_overflow);
    int order[kMaxKeys];
    for (int i = 0; i < g_keyCount; ++i)
    {
        int j = i;
        for (; j > 0 && g_keys[order[j - 1]].order / g_keys[order[j - 1]].frames > g_keys[i].order / g_keys[i].frames; --j)
            order[j] = order[j - 1];
        order[j] = i;
    }
    for (int n = 0; n < g_keyCount; ++n)
    {
        const Key& k = g_keys[order[n]];
        char what[96];
        TargetDescribe(k.target, what, sizeof(what));
        double f = k.frames;
        Log("STAGE order=%.2f target=T%d visit=%d %s seen=%.1f draws=%.2f tris=%.2f clears=%.2f copies=%.2f timed=%ld in_ms=%.4f out_ms=%.4f",
            k.order / f, k.target, k.visit, what, k.frames * 100.0 / g_frames, k.draws / f, k.tris / f, k.clears / f,
            k.copies / f, k.timed, k.timed ? TicksToMs(k.inTicks) / k.timed : 0.0, k.timed ? TicksToMs(k.outTicks) / k.timed : 0.0);
        for (int l = 0; l < g_labelCount; ++l)
            if (k.label[l])
                Log("LABEL target=T%d visit=%d fx=%s tech=%s draws=%.2f", k.target, k.visit, g_labels[l].fx, g_labels[l].tech,
                    k.label[l] / f);
    }
    for (int shown = 0; shown < 5; ++shown) // the five most common frame shapes
    {
        int best = -1;
        for (int i = 0; i < g_shapeCount; ++i)
            if (g_shapes[i].frames > 0 && (best < 0 || g_shapes[i].frames > g_shapes[best].frames))
                best = i;
        if (best < 0)
            break;
        Log("SHAPE share=%.1f seq=%s", g_shapes[best].frames * 100.0 / g_frames, g_shapes[best].seq);
        g_shapes[best].frames = 0;
    }
    for (int i = 0; i < g_copyCount; ++i)
        Log("COPY src=T%d dst=T%d per_frame=%.2f", g_copies[i].src, g_copies[i].dst, g_copies[i].count / (double)g_frames);
    if (g_timedFrames)
        Log("TIME timed_frames=%ld frame_ms=%.4f present_ms=%.4f loose_in_ms=%.4f loose_out_ms=%.4f calls=%.1f clock_ns=%.0f",
            g_timedFrames, TicksToMs(g_frameTicks) / g_timedFrames, TicksToMs(g_presentTicks) / g_timedFrames,
            TicksToMs(g_looseInSum) / g_timedFrames, TicksToMs(g_looseOutSum) / g_timedFrames,
            g_timedCalls / (double)g_timedFrames, g_clockNs);
    if (g_msaaOn || g_msaaOff)
        Log("MSAA on=%ld off=%ld", g_msaaOn, g_msaaOff);
    if (g_labelOverflow || g_keyOverflow || g_shapeOverflow || g_copyOverflow || g_overflow)
        Log("OVERFLOW labels=%ld keys=%ld shapes=%ld copies=%ld stages=%ld", g_labelOverflow, g_keyOverflow, g_shapeOverflow,
            g_copyOverflow, g_overflow);
    g_labelOverflow = g_keyOverflow = g_shapeOverflow = g_copyOverflow = 0;
    g_keyCount = g_shapeCount = g_copyCount = 0;
    g_frames = g_drivingFrames = g_timedFrames = g_overflow = g_timedCalls = g_msaaOn = g_msaaOff = 0;
    g_frameTicks = g_presentTicks = g_looseInSum = g_looseOutSum = 0;
}
