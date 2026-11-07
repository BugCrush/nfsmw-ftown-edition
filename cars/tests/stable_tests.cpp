// Native tests for cars/src/stable.h (no game, no Windows calls). Build and run: cars\tests\run-stable-tests.bat
#include <cstdio>
#include <cstring>
#include <vector>

#include "../src/stable.h"

static int g_failed = 0, g_passed = 0;
#define CHECK(c)                                                              \
    do {                                                                      \
        if (!(c)) {                                                           \
            std::printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);        \
            ok = false;                                                       \
        }                                                                     \
    } while (0)

// A blank stable image: every car, customisation and career slot free.
static std::vector<uint8_t> blank() {
    std::vector<uint8_t> img(cars::kStableSize, 0);
    cars::Stable s(img.data());
    for (int i = 0; i < cars::kMaxCars; i++) s.car(i)->handle = cars::kNoCar;
    for (int i = 0; i < cars::kMaxCustom; i++) s.custom_handle(i) = cars::kNoSmall;
    for (int i = 0; i < cars::kMaxCareer; i++) s.career_handle(i) = cars::kNoSmall;
    return img;
}

// Puts a car record in slot `slot` (handle = slot), as the game does.
static void put(std::vector<uint8_t>& img, int slot, uint32_t vkey, uint32_t bits, uint8_t custom = 0xFF,
                uint8_t career = 0xFF) {
    cars::Stable s(img.data());
    cars::CarRecord* r = s.car(slot);
    r->handle = (uint32_t)slot;
    r->fe_key = vkey ^ 0x5A5A5A5Au;
    r->vehicle_key = vkey;
    r->filter_bits = bits;
    r->customization = custom;
    r->career = career;
    if (custom != 0xFF) s.custom_handle(custom) = custom;
    if (career != 0xFF) s.career_handle(career) = career;
}

static const uint32_t STOCK = 1 | 0x10000, CAREER = 2 | 0x10000;
static const uint32_t DEFAULT_CAR = 0;

static bool same_set_changes_nothing() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xB, STOCK);
    auto loaded = def;
    uint32_t cur = 1, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.added == 0 && r.dropped == 0 && r.not_added_full == 0 && !r.reset_current && r.reset_quickrace == 0);
    CHECK(loaded == def);
    return ok;
}

static bool new_car_added_once() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xC, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    put(loaded, 1, 0xA, CAREER, 0, 0);  // a bought copy of A
    uint32_t cur = 1, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.added == 1);
    cars::Stable s(loaded.data());
    CHECK(s.car(2)->handle == 2 && s.car(2)->vehicle_key == 0xC && s.car(2)->filter_bits == STOCK);
    auto r2 = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r2.added == 0 && r2.dropped == 0);
    return ok;
}

static bool added_car_brings_its_customisation() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xD, 8 | 0x10000, 0);  // a bonus preset with customisation record 0
    cars::Stable(def.data()).custom_byte(0, 7) = 0x42;
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    put(loaded, 1, 0xA, CAREER, 0, 0);  // the user's car holds customisation 0
    uint32_t cur = 1, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    cars::Stable s(loaded.data());
    CHECK(r.added == 1);
    CHECK(s.car(2)->vehicle_key == 0xD && s.car(2)->customization == 1);
    CHECK(s.custom_handle(1) == 1 && s.custom_byte(1, 7) == 0x42);
    CHECK(s.custom_handle(0) == 0);  // the user's record untouched
    return ok;
}

static bool removed_car_dropped() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    put(loaded, 1, 0xE, STOCK);  // car E no longer exists
    uint32_t cur = 0, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.dropped == 1 && r.added == 0);
    CHECK(cars::Stable(loaded.data()).car(1)->handle == cars::kNoCar);
    return ok;
}

static bool removed_owned_car_dropped_with_refs() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    put(loaded, 4, 0xE, CAREER, 3, 2);  // bought E: customisation 3, career record 2
    uint32_t cur = 4, qr[11] = {};
    qr[5] = 4;
    qr[6] = 0;
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    cars::Stable s(loaded.data());
    CHECK(r.dropped == 1);
    CHECK(s.car(4)->handle == cars::kNoCar);
    CHECK(s.custom_handle(3) == cars::kNoSmall && s.career_handle(2) == cars::kNoSmall);
    CHECK(r.reset_current && cur == DEFAULT_CAR);
    CHECK(r.reset_quickrace == 1 && qr[5] == DEFAULT_CAR && qr[6] == 0);
    return ok;
}

static bool owned_stock_car_kept() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    put(loaded, 1, 0xA, CAREER, 0, 0);
    auto before = loaded;
    uint32_t cur = 1, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.added == 0 && r.dropped == 0 && cur == 1);
    CHECK(loaded == before);
    return ok;
}

static bool full_stable_adds_none_overwrites_none() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xB, STOCK);
    put(def, 2, 0xC, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    for (int i = 1; i < cars::kMaxCars; i++) put(loaded, i, 0xA, CAREER);
    auto before = loaded;
    uint32_t cur = 0, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.added == 0 && r.not_added_full == 2);
    CHECK(loaded == before);
    return ok;
}

// Review item 1: preset and bonus records use a name hash as their handle (CreateNewPresetCar: Handle =
// FEHashUpper(name)); the game finds them by it. An added one keeps it, unless a loaded record already uses it.
static bool preset_keeps_its_hash_handle() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xD, 8 | 0x10000);
    cars::Stable(def.data()).car(1)->handle = 0x38A3C42C;
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    uint32_t cur = 0, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    cars::Stable s(loaded.data());
    CHECK(r.added == 1 && s.car(1)->vehicle_key == 0xD && s.car(1)->handle == 0x38A3C42C);
    return ok;
}

static bool preset_hash_handle_taken_gets_the_slot() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xD, 8 | 0x10000);
    cars::Stable(def.data()).car(1)->handle = 0x38A3C42C;
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    cars::Stable(loaded.data()).car(0)->handle = 0x38A3C42C;  // already used in the loaded stable
    uint32_t cur = 0, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.added == 1 && cars::Stable(loaded.data()).car(1)->handle == 1);
    return ok;
}

// Review item 2: a load that would drop more cars than max_drop changes nothing and says so (a broken database must
// not wipe the user's cars).
static bool drop_guard_refuses_a_mass_removal() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    for (int i = 1; i <= 4; i++) put(loaded, i, 0xB0 + i, CAREER);
    auto before = loaded;
    uint32_t cur = 2, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR, 3);
    CHECK(r.guard_tripped && r.dropped == 0 && r.added == 0);
    CHECK(loaded == before && cur == 2);
    return ok;
}

// Review item 3: the cars that did not fit are named.
static bool not_added_cars_are_named() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    put(def, 1, 0xB, STOCK);
    put(def, 2, 0xC, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    for (int i = 1; i < cars::kMaxCars; i++) put(loaded, i, 0xA, CAREER);
    uint32_t cur = 0, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.not_added_keys.size() == 2 && r.not_added_keys[0] == 0xB && r.not_added_keys[1] == 0xC);
    return ok;
}

// Review item 4: when the current career car is removed, another car of the career (CAREER list) takes its place;
// the default car only if there is none.
static bool current_car_goes_to_another_career_car() {
    bool ok = true;
    auto def = blank();
    put(def, 0, 0xA, STOCK);
    auto loaded = blank();
    put(loaded, 0, 0xA, STOCK);
    put(loaded, 1, 0xA, CAREER, 0, 0);  // another bought car
    put(loaded, 2, 0xE, CAREER, 1, 1);  // the current car, removed
    uint32_t cur = 2, qr[11] = {};
    auto r = cars::reconcile(loaded.data(), def.data(), &cur, qr, DEFAULT_CAR);
    CHECK(r.dropped == 1 && r.reset_current && cur == 1);
    return ok;
}

static bool unknown_fingerprint_refused() {
    bool ok = true;
    std::vector<uint32_t> known = {0x0B28303D};
    CHECK(!cars::fingerprint_accepted(0x1, 0x2, known));
    CHECK(cars::fingerprint_accepted(0x0B28303D, 0x2, known));
    CHECK(cars::fingerprint_accepted(0x2, 0x2, {}));
    return ok;
}

int main() {
    struct {
        const char* name;
        bool (*fn)();
    } tests[] = {
        {"same_set_changes_nothing", same_set_changes_nothing},
        {"new_car_added_once", new_car_added_once},
        {"added_car_brings_its_customisation", added_car_brings_its_customisation},
        {"removed_car_dropped", removed_car_dropped},
        {"removed_owned_car_dropped_with_refs", removed_owned_car_dropped_with_refs},
        {"owned_stock_car_kept", owned_stock_car_kept},
        {"full_stable_adds_none_overwrites_none", full_stable_adds_none_overwrites_none},
        {"unknown_fingerprint_refused", unknown_fingerprint_refused},
        {"preset_keeps_its_hash_handle", preset_keeps_its_hash_handle},
        {"preset_hash_handle_taken_gets_the_slot", preset_hash_handle_taken_gets_the_slot},
        {"drop_guard_refuses_a_mass_removal", drop_guard_refuses_a_mass_removal},
        {"not_added_cars_are_named", not_added_cars_are_named},
        {"current_car_goes_to_another_career_car", current_car_goes_to_another_career_car},
    };
    for (auto& t : tests) {
        bool ok = t.fn();
        std::printf("%s %s\n", ok ? "PASS" : "FAIL", t.name);
        (ok ? g_passed : g_failed)++;
    }
    std::printf("%d/%d passed\n", g_passed, g_passed + g_failed);
    return g_failed ? 1 : 0;
}
