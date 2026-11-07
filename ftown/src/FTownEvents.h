// FTownEvents.h - F-Town's events (docs/superpowers/plans/2026-11-04-ftown-events.md; docs/ftown-race-notes.md
// "Events"): the list FTownLoader offers after Free Roam, read from ftown-events.json beside the ini (built by
// tools/citymap/events.py). Included once by FTownLoader.cpp before FTownRace.h (which runs the events).
//
// The file is JSON: {"events": [{"id", "name" (the menu's text), "title" (the HUD's), "kind" (timeattack, sprint:
// checkpoints and a timed finish; drag: a timed finish and the trap speed; speedtrap: speed cameras, the score their
// sum), "icon" (a game texture hash, "0x..."), "best" (the event's section in FTownTimes.txt), "barriers" (its barrier
// file, or ""), "start" [x, y, z, heading], "gates" [{"type": checkpoint|camera|finish, "x", "y", "heading"}, ...]
// (the finish last), and fields FTownLoader skips ("route", "keys", ...)}]}. A small reader of our own (no library):
// strings without escapes but \" and \\, numbers, arrays, objects, true / false / null.

// ---------------------------------------------------------------- a small JSON reader

struct JNode
{
    char type;  // 'o' object, 'a' array, 's' string, 'n' number, 'b' true / false / null
    double num;
    const char* str;  // a string's text (not terminated), or an object member's key
    int len;
    const char* key;
    int keyLen;
    int child, next;  // first child, next sibling (-1: none)
};
static JNode* g_jn;
static int g_jnCount, g_jnMax;
static const char* g_jErr;

static void JSkip(const char*& p, const char* end)
{
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) p++;
}

static int JNew(char type)
{
    if (g_jnCount >= g_jnMax)
    {
        g_jErr = "too many values";
        return -1;
    }
    JNode& n = g_jn[g_jnCount];
    memset(&n, 0, sizeof(n));
    n.type = type;
    n.child = n.next = -1;
    return g_jnCount++;
}

static bool JString(const char*& p, const char* end, const char** s, int* len)
{
    if (p >= end || *p != '"')
        return false;
    *s = ++p;
    while (p < end && *p != '"')
    {
        if (*p == '\\')
            p++;
        p++;
    }
    if (p >= end)
        return false;
    *len = (int)(p - *s);
    p++;
    return true;
}

static int JValue(const char*& p, const char* end, int depth)
{
    JSkip(p, end);
    if (p >= end || depth > 16)
    {
        g_jErr = p >= end ? "the file ends inside a value" : "nested too deep";
        return -1;
    }
    if (*p == '{' || *p == '[')
    {
        bool obj = *p == '{';
        int me = JNew(obj ? 'o' : 'a');
        if (me < 0)
            return -1;
        p++;
        int last = -1;
        JSkip(p, end);
        if (p < end && *p == (obj ? '}' : ']'))
        {
            p++;
            return me;
        }
        for (;;)
        {
            const char* key = nullptr;
            int keyLen = 0;
            if (obj)
            {
                JSkip(p, end);
                if (!JString(p, end, &key, &keyLen))
                {
                    g_jErr = p >= end ? "the file ends inside a value" : "an object member without a quoted name";
                    return -1;
                }
                JSkip(p, end);
                if (p >= end || *p != ':')
                {
                    g_jErr = "a member name without ':'";
                    return -1;
                }
                p++;
            }
            int v = JValue(p, end, depth + 1);
            if (v < 0)
                return -1;
            g_jn[v].key = key;
            g_jn[v].keyLen = keyLen;
            if (last < 0)
                g_jn[me].child = v;
            else
                g_jn[last].next = v;
            last = v;
            JSkip(p, end);
            if (p < end && *p == ',')
            {
                p++;
                continue;
            }
            if (p < end && *p == (obj ? '}' : ']'))
            {
                p++;
                return me;
            }
            g_jErr = obj ? "an object not closed by '}'" : "an array not closed by ']'";
            return -1;
        }
    }
    if (*p == '"')
    {
        int me = JNew('s');
        if (me < 0 || !JString(p, end, &g_jn[me].str, &g_jn[me].len))
        {
            if (!g_jErr)
                g_jErr = "a string not closed";
            return -1;
        }
        return me;
    }
    if (*p == '-' || (*p >= '0' && *p <= '9'))
    {
        char buf[64];
        int k = 0;
        while (p < end && k < 63 && (strchr("+-.eE", *p) || (*p >= '0' && *p <= '9'))) buf[k++] = *p++;
        buf[k] = 0;
        int me = JNew('n');
        if (me < 0)
            return -1;
        g_jn[me].num = atof(buf);
        return me;
    }
    static const char* const words[] = {"true", "false", "null"};
    for (const char* w : words)
    {
        size_t n = strlen(w);
        if ((size_t)(end - p) >= n && !strncmp(p, w, n))
        {
            p += n;
            int me = JNew('b');
            if (me >= 0)
                g_jn[me].num = w[0] == 't';
            return me;
        }
    }
    g_jErr = "a value that is not JSON";
    return -1;
}

static int JGet(int obj, const char* key)
{
    if (obj < 0 || g_jn[obj].type != 'o')
        return -1;
    int n = (int)strlen(key);
    for (int c = g_jn[obj].child; c >= 0; c = g_jn[c].next)
        if (g_jn[c].keyLen == n && !strncmp(g_jn[c].key, key, n))
            return c;
    return -1;
}

static bool JText(int v, char* out, int size)
{
    if (v < 0 || g_jn[v].type != 's' || g_jn[v].len >= size)
        return false;
    int k = 0;
    for (int i = 0; i < g_jn[v].len; i++)
    {
        char c = g_jn[v].str[i];
        if (c == '\\' && i + 1 < g_jn[v].len)
            c = g_jn[v].str[++i];
        out[k++] = c;
    }
    out[k] = 0;
    return true;
}

static bool JNums(int arr, float* out, int n)
{
    if (arr < 0 || g_jn[arr].type != 'a')
        return false;
    int k = 0;
    for (int c = g_jn[arr].child; c >= 0; c = g_jn[c].next, k++)
    {
        if (k >= n || g_jn[c].type != 'n')
            return false;
        out[k] = (float)g_jn[c].num;
    }
    return k == n;
}

static bool JNum(int v, float* out)
{
    if (v < 0 || g_jn[v].type != 'n')
        return false;
    *out = (float)g_jn[v].num;
    return true;
}

// ---------------------------------------------------------------- the events

enum EventKind
{
    EK_CHECKPOINTS,  // timeattack, sprint
    EK_DRAG,
    EK_SPEEDTRAP,
};
enum GateType
{
    GT_CHECKPOINT,
    GT_CAMERA,
    GT_FINISH,
};
static const int kMaxEvents = 8, kMaxGates = 17;
struct Event
{
    char id[16], name[48], title[32], best[24], barriers[MAX_PATH];
    int kind;
    DWORD icon;
    float start[4];  // render x, y, z, heading
    int gateCount;   // including the finish (the last)
    float gates[kMaxGates][3];  // render x, y, heading along the route
    int gateType[kMaxGates];
    int checkpoints, cameras;
    // Run J item 7: the course the minimap's line follows: the route's points (render x, y) and the course's part of
    // it (start_s .. finish_s metres along it); without a route the start and the gates in turn (0 .. the finish)
    int routeCount;
    float (*route)[2];
    float startS, finishS;
    // Run K item 3: the road the minimap draws across the route at each route point (centre x, y, half width; the
    // json's "band", tools/citymap/events.py course_band), the course line painted over it; null: WidthMetres wide
    float (*band)[3];
};
static Event g_events[kMaxEvents];
static int g_eventCount;
static char g_evName[MAX_PATH] = "ftown-events.json", g_evPath[MAX_PATH];
static bool g_mph;  // [Events] SpeedUnit = mph: speeds shown in mph (kept in km/h in FTownTimes.txt)
static MapSet g_bars[kMaxEvents];  // each event's race barriers (its own file, or none)

static void EventsSettings(const char* dir)
{
    GetPrivateProfileStringA("Events", "File", "ftown-events.json", g_evName, sizeof(g_evName), g_iniPath);
    snprintf(g_evPath, sizeof(g_evPath), "%s%s", dir, g_evName);
    char unit[16];
    GetPrivateProfileStringA("Events", "SpeedUnit", "km/h", unit, sizeof(unit), g_iniPath);
    g_mph = !_stricmp(unit, "mph");
    for (int k = 0; k < kMaxEvents; k++)
    {
        MapSet& m = g_bars[k];
        memset(&m, 0, sizeof(m));
        m.chunkName = "FTOWNBAR";
        m.prefix = "barriers: ";
    }
}

// One event from its JSON object; false (and *why) when a field is missing or wrong.
static bool EventFrom(int o, Event& e, const char** why)
{
    char kind[16], icon[24];
    if (!JText(JGet(o, "id"), e.id, sizeof(e.id)) || !JText(JGet(o, "name"), e.name, sizeof(e.name)) ||
        !JText(JGet(o, "title"), e.title, sizeof(e.title)) || !JText(JGet(o, "kind"), kind, sizeof(kind)) ||
        !JText(JGet(o, "best"), e.best, sizeof(e.best)) || !JText(JGet(o, "barriers"), e.barriers, sizeof(e.barriers)))
    {
        *why = "id, name, title, kind, best and barriers must be strings (of a sensible length)";
        return false;
    }
    if (strchr(e.name, '$') || strchr(e.title, '$'))
    {
        *why = "a '$' in the name or title (the front end's text would lose it)";
        return false;
    }
    if (!strcmp(kind, "timeattack") || !strcmp(kind, "sprint"))
        e.kind = EK_CHECKPOINTS;
    else if (!strcmp(kind, "drag"))
        e.kind = EK_DRAG;
    else if (!strcmp(kind, "speedtrap"))
        e.kind = EK_SPEEDTRAP;
    else
    {
        *why = "kind is not timeattack, sprint, drag or speedtrap";
        return false;
    }
    e.icon = JText(JGet(o, "icon"), icon, sizeof(icon)) ? (DWORD)strtoul(icon, nullptr, 0) : 0;
    if (!JNums(JGet(o, "start"), e.start, 4))
    {
        *why = "start is not [x, y, z, heading]";
        return false;
    }
    int gates = JGet(o, "gates");
    if (gates < 0 || g_jn[gates].type != 'a')
    {
        *why = "no gates";
        return false;
    }
    e.gateCount = e.checkpoints = e.cameras = 0;
    for (int g = g_jn[gates].child; g >= 0; g = g_jn[g].next)
    {
        char type[16];
        if (e.gateCount == kMaxGates)
        {
            *why = "more than 17 gates";
            return false;
        }
        float* v = e.gates[e.gateCount];
        if (!JText(JGet(g, "type"), type, sizeof(type)) || !JNum(JGet(g, "x"), &v[0]) || !JNum(JGet(g, "y"), &v[1]) ||
            !JNum(JGet(g, "heading"), &v[2]))
        {
            *why = "a gate without type, x, y and heading";
            return false;
        }
        int t = !strcmp(type, "checkpoint") ? GT_CHECKPOINT : !strcmp(type, "camera") ? GT_CAMERA
                : !strcmp(type, "finish") ? GT_FINISH : -1;
        if (t < 0)
        {
            *why = "a gate's type is not checkpoint, camera or finish";
            return false;
        }
        e.gateType[e.gateCount++] = t;
        e.checkpoints += t == GT_CHECKPOINT;
        e.cameras += t == GT_CAMERA;
    }
    for (int k = 0; k < e.gateCount; k++)
        if ((e.gateType[k] == GT_FINISH) != (k == e.gateCount - 1))
        {
            *why = "the finish is not the last gate (or there are two)";
            return false;
        }
    if (!e.gateCount)
    {
        *why = "no gates";
        return false;
    }
    // Run J item 7: the route (optional: a bad or missing one, the start and the gates)
    int route = JGet(o, "route"), n = 0;
    for (int c = route >= 0 && g_jn[route].type == 'a' ? g_jn[route].child : -1; c >= 0; c = g_jn[c].next) n++;
    float (*pts)[2] = n >= 2 && n <= 4096 ? (float (*)[2])malloc(sizeof(float) * 2 * n) : nullptr;
    int k = 0;
    for (int c = pts ? g_jn[route].child : -1; c >= 0 && JNums(c, pts[k], 2); c = g_jn[c].next) k++;
    float s0 = 0, s1 = 0;
    if (pts && k == n && JNum(JGet(o, "start_s"), &s0) && JNum(JGet(o, "finish_s"), &s1) && s1 > s0)
    {
        e.route = pts, e.routeCount = n, e.startS = s0, e.finishS = s1;
        // Run K item 3: the band (optional: one [x, y, half] per route point, each half 0..100 m; else none)
        int band = JGet(o, "band"), m = 0;
        for (int c = band >= 0 && g_jn[band].type == 'a' ? g_jn[band].child : -1; c >= 0; c = g_jn[c].next) m++;
        float (*bp)[3] = m == n ? (float (*)[3])malloc(sizeof(float) * 3 * n) : nullptr;
        int j = 0;
        for (int c = bp ? g_jn[band].child : -1; c >= 0 && JNums(c, bp[j], 3) && bp[j][2] >= 0 && bp[j][2] <= 100;
             c = g_jn[c].next)
            j++;
        if (bp && j == n)
            e.band = bp;
        else
        {
            free(bp);
            if (band >= 0)  // (the review: a json regenerated without its band, or a broken one, is visible in the log)
                Log("events: %s's band ignored (%d points for %d route points, or a half width outside 0..100 m): its "
                    "course line WidthMetres wide", e.id, m, n);
        }
        return true;
    }
    free(pts);
    e.routeCount = e.gateCount + 1;
    e.route = (float (*)[2])malloc(sizeof(float) * 2 * e.routeCount);
    if (!e.route)
    {
        e.routeCount = 0;
        return true;
    }
    e.route[0][0] = e.start[0], e.route[0][1] = e.start[1];
    float s = 0;
    for (int j = 0; j < e.gateCount; j++)
    {
        e.route[j + 1][0] = e.gates[j][0], e.route[j + 1][1] = e.gates[j][1];
        s += hypotf(e.route[j + 1][0] - e.route[j][0], e.route[j + 1][1] - e.route[j][1]);
    }
    e.startS = 0, e.finishS = s;
    return true;
}

// "7 checkpoints and the finish", "4 cameras and the finish", "the finish"
static void GatesText(const Event& e, char* out, size_t n)
{
    char a[32] = "", b[32] = "";
    if (e.checkpoints)
        snprintf(a, sizeof(a), "%d checkpoints and ", e.checkpoints);
    if (e.cameras)
        snprintf(b, sizeof(b), "%d cameras and ", e.cameras);
    snprintf(out, n, "%s%sthe finish", a, b);
}

// At start: the file read and checked; each good event kept (a bad one is left out, logged). false: no events.
static bool EventsRead()
{
    g_eventCount = 0;
    HANDLE f = CreateFileA(g_evPath, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE)
    {
        Log("events off: %s cannot be opened (error %lu)", g_evName, (unsigned long)GetLastError());
        return false;
    }
    DWORD size = GetFileSize(f, nullptr), got = 0;
    char* text = size && size < (4u << 20) ? (char*)malloc(size) : nullptr;
    bool read = text && ReadFile(f, text, size, &got, nullptr) && got == size;
    CloseHandle(f);
    if (!read)
    {
        Log("events off: %s cannot be read (%lu bytes; at most 4 MB)", g_evName, (unsigned long)size);
        free(text);
        return false;
    }
    g_jnMax = size / 2 + 16;
    g_jn = (JNode*)malloc(sizeof(JNode) * g_jnMax);
    g_jnCount = 0;
    g_jErr = nullptr;
    const char* p = text;
    int root = g_jn ? JValue(p, text + size, 0) : -1;
    if (root >= 0)
    {
        JSkip(p, text + size);
        if (p != text + size)
            root = -1, g_jErr = "text after the end of the JSON";
    }
    int list = JGet(root, "events");
    if (root < 0 || list < 0 || g_jn[list].type != 'a')
    {
        Log("events off: %s is not an events file (%s)", g_evName, g_jErr ? g_jErr : "no \"events\" list");
        free(g_jn);
        g_jn = nullptr;
        free(text);
        return false;
    }
    int n = 0;
    for (int o = g_jn[list].child; o >= 0; o = g_jn[o].next, n++)
    {
        if (g_eventCount == kMaxEvents)
        {
            Log("events: more than %d events in %s; the rest left out", kMaxEvents, g_evName);
            break;
        }
        Event& e = g_events[g_eventCount];
        memset(&e, 0, sizeof(e));
        const char* why = "";
        if (!EventFrom(o, e, &why))
        {
            Log("events: event %d of %s left out: %s", n + 1, g_evName, why);
            continue;
        }
        char gates[64];
        GatesText(e, gates, sizeof(gates));
        Log("events: %d %s (%s): start render (%.2f, %.2f, %.2f) heading %.1f, %s; barriers %s; best in [%s]",
            g_eventCount + 1, e.name, e.id, e.start[0], e.start[1], e.start[2], e.start[3], gates,
            e.barriers[0] ? e.barriers : "none", e.best);
        g_eventCount++;
    }
    free(g_jn);
    g_jn = nullptr;
    free(text);
    if (!g_eventCount)
        Log("events off: %s has no usable event", g_evName);
    return g_eventCount > 0;
}
